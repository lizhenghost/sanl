"""
subs-check 测速引擎
通过子进程调用 subs-check 二进制进行测速
"""
import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Dict, List, Optional

import httpx

from ..config import get_subs_check_config
from ..schema import repository

logger = logging.getLogger(__name__)


class Checker:
    def __init__(self):
        self.config = get_subs_check_config()
        self.binary_path = self.config.get("binary_path", "./subs-check")
        self.config_path = self.config.get("config_path", "./config/subs-check.yaml")
        self.output_dir = self.config.get("output_dir", "./output")
        self.api_port = 8199
        self.api_base = f"http://127.0.0.1:{self.api_port}"

    async def run_check(self) -> Dict:
        """运行一次完整的测速检查"""
        job_id = repository.add_check_job("full_check")

        try:
            sources = repository.list_sources(enabled_only=True)
            if not sources:
                logger.warning("No enabled sources found")
                repository.update_check_job(job_id.id, "failed", error="No enabled sources")
                return {"status": "no_sources", "job_id": job_id.id}

            await self._update_subs_check_config(sources)

            logger.info(f"Starting subs-check with {len(sources)} sources")
            result = await self._run_subs_check()

            if result.get("success"):
                await self._parse_and_store_results(result)
                # 重新计算评分
                from ..schema.repository import update_node_scores
                scored = update_node_scores()
                logger.info(f"Updated scores for {scored} nodes")
                repository.update_check_job(job_id.id, "completed", result=json.dumps(result))
                # 测速后异步刷新 GeoIP 出口识别（不阻塞返回）
                import asyncio
                from ..geoip import refresh_node_geo
                asyncio.create_task(refresh_node_geo(limit=300))
            else:
                repository.update_check_job(job_id.id, "failed", error=result.get("error", "Unknown error"))

            return result

        except Exception as e:
            logger.error(f"Check failed: {e}")
            repository.update_check_job(job_id.id, "failed", error=str(e))
            return {"status": "error", "job_id": job_id.id, "error": str(e)}

    async def _update_subs_check_config(self, sources: List):
        """动态更新 subs-check 配置文件中的订阅源（保留其他设置）"""
        import yaml

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f) or {}

        # 过滤掉 manual:// 协议源（subs-check 不支持该协议，会重试3次报错浪费时间）
        config['sub-urls'] = [src.url for src in sources if not src.url.startswith('manual://')]

        with open(self.config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Updated subs-check config with {len(config['sub-urls'])} remote sources")

    async def _run_subs_check(self) -> Dict:
        """运行 subs-check（后台运行，轮询输出文件，因为 subs-check 作为守护进程不会自动退出）"""
        try:
            os.makedirs(self.output_dir, exist_ok=True)

            # 关键：删除上一轮的旧结果文件，否则轮询会立即误判"已完成"并读旧数据
            result_file = os.path.join(self.output_dir, "all.yaml")
            for stale in (result_file, os.path.join(self.output_dir, "result", "all.yaml")):
                try:
                    if os.path.exists(stale):
                        os.remove(stale)
                        logger.info(f"Removed stale result file: {stale}")
                except OSError:
                    pass
            start_ts = time.time()

            # 启动 subs-check，日志重定向到文件
            process = await asyncio.create_subprocess_exec(
                self.binary_path,
                "-f", self.config_path,
                stdout=open("/tmp/subs-check.log", "a"),
                stderr=open("/tmp/subs-check.log", "a"),
                cwd=os.path.dirname(os.path.abspath(self.binary_path))
            )

            max_wait = 5400  # 90 分钟
            waited = 0
            poll_interval = 30

            while waited < max_wait:
                await asyncio.sleep(poll_interval)
                waited += poll_interval

                if process.returncode is not None:
                    break

                # 只认本轮启动之后新写入的结果文件（mtime > start_ts）
                if (os.path.exists(result_file) and os.path.getsize(result_file) > 0
                        and os.path.getmtime(result_file) > start_ts):
                    # 等 60 秒确保写入完成
                    await asyncio.sleep(60)
                    process.kill()
                    await process.wait()
                    return await self._read_results()

            process.kill()
            await process.wait()
            return {"success": False, "error": f"Timeout after {max_wait}s"}

        except FileNotFoundError:
            return {"success": False, "error": f"subs-check binary not found: {self.binary_path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _read_results(self) -> Dict:
        """读取 subs-check 输出结果"""
        try:
            possible_paths = [
                os.path.join(self.output_dir, "all.yaml"),
                os.path.join(self.output_dir, "result", "all.yaml"),
                os.path.join(self.output_dir, "output", "all.yaml"),
            ]

            result_path = None
            for path in possible_paths:
                if path and os.path.exists(path):
                    result_path = path
                    break

            if not result_path:
                for root, dirs, files in os.walk(self.output_dir):
                    for f in files:
                        if f == "all.yaml":
                            result_path = os.path.join(root, f)
                            break
                    if result_path:
                        break

            if not result_path or not os.path.exists(result_path):
                return {"success": False, "error": "Result file not found"}

            import yaml
            with open(result_path, 'r') as f:
                data = yaml.safe_load(f)

            proxies = data.get('proxies', []) if isinstance(data, dict) else []

            return {
                "success": True,
                "total_nodes": len(proxies),
                "result_path": result_path
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to read results: {e}"}

    async def _parse_and_store_results(self, result: Dict):
        """解析结果并存储到数据库"""
        import yaml
        import re

        result_path = result.get("result_path", "")
        if not os.path.exists(result_path):
            return

        with open(result_path, 'r') as f:
            data = yaml.safe_load(f)

        proxies = data.get('proxies', [])
        logger.info(f"Parsing {len(proxies)} proxies from result")

        sources = repository.list_sources(enabled_only=True)
        source_url = sources[0].url if sources else ''
        source_id = sources[0].id if sources else None

        from src.schema.repository import get_connection
        with get_connection() as conn:
            conn.execute("DELETE FROM nodes")

        added = 0
        for proxy in proxies:
            name = proxy.get('name', '')
            ptype = proxy.get('type', 'unknown')

            country = None
            if '|' in name:
                country_part = name.split('|')[0]
                emoji_match = re.search(r'[\U0001F1E6-\U0001F1FF]{2}', country_part)
                if emoji_match:
                    country = emoji_match.group(0)

            latency = None
            download_speed = None
            if '|' in name:
                parts = name.split('|')
                if len(parts) >= 2:
                    speed_str = parts[1].strip()
                    if 'KB/s' in speed_str:
                        try:
                            download_speed = int(float(speed_str.replace('KB/s', '').strip()) * 1024)
                        except:
                            pass
                    elif 'MB/s' in speed_str:
                        try:
                            download_speed = int(float(speed_str.replace('MB/s', '').strip()) * 1024 * 1024)
                        except:
                            pass

            status = 'active' if download_speed and download_speed > 0 else 'inactive'

            node_data = {
                'name': name,
                'type': ptype,
                'server': proxy.get('server', ''),
                'port': proxy.get('port', 0),
                'cipher': proxy.get('cipher', ''),
                'password': proxy.get('password', ''),
                'uuid': proxy.get('uuid', ''),
                'alterId': proxy.get('alterId', 0),
                'udp': proxy.get('udp', False),
            }

            now = int(time.time())
            with get_connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO nodes (subscribe_url, source_id, node_name, node_type, node_data,
                       status, country, download_speed, last_checked_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source_url, source_id, name, ptype, json.dumps(node_data),
                     status, country, download_speed, now, now, now)
                )
                _ = cursor.lastrowid

            added += 1

        logger.info(f"Stored {added} nodes with status info")

    async def get_api_status(self) -> Dict:
        """获取 subs-check API 状态"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api_base}/api/status")
                return resp.json()
        except Exception as e:
            return {"error": str(e)}