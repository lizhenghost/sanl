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

        # subs-check 只吃真实代理订阅：
        # - manual:// 手动导入源不支持
        # - data:/static 与 cf-list 类型是 CF 优选 host:port 列表，不是代理节点，喂进去只会浪费时间
        remote_urls = [
            src.url for src in sources
            if not src.url.startswith('manual://')
            and not src.url.startswith('data:')
            and (getattr(src, 'source_type', '') or '').lower() not in ('cf-list', 'static')
        ]
        config['sub-urls'] = remote_urls

        with open(self.config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Updated subs-check config with {len(remote_urls)} remote sources")

    def _kill_stale_processes(self):
        """清理上一轮残留的 subs-check 孤儿进程（后端重启会遗留进程占用 API 端口）"""
        try:
            subprocess.run(["pkill", "-f", "subs-check"], capture_output=True, timeout=5)
            time.sleep(1.0)
        except Exception as e:
            logger.warning(f"pkill subs-check failed: {e}")

    async def _run_subs_check(self) -> Dict:
        """运行 subs-check（后台运行，轮询输出文件，因为 subs-check 作为守护进程不会自动退出）"""
        process = None
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            self._kill_stale_processes()

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

            # 启动 subs-check（独立进程组，便于整组清理），日志重定向到文件
            process = await asyncio.create_subprocess_exec(
                self.binary_path,
                "-f", self.config_path,
                stdout=open("/tmp/subs-check.log", "a"),
                stderr=open("/tmp/subs-check.log", "a"),
                cwd=os.path.dirname(os.path.abspath(self.binary_path)),
                start_new_session=True,
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
                    self._terminate(process)
                    return await self._read_results()

            self._terminate(process)
            return {"success": False, "error": f"Timeout after {max_wait}s"}

        except FileNotFoundError:
            return {"success": False, "error": f"subs-check binary not found: {self.binary_path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if process is not None and process.returncode is None:
                self._terminate(process)

    @staticmethod
    def _terminate(process):
        """杀掉子进程及其整个进程组（start_new_session 的子进程用 killpg 才能全灭）"""
        try:
            os.killpg(os.getpgid(process.pid), 15)
        except (ProcessLookupError, PermissionError):
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        except Exception:
            pass

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
        """解析结果并回填数据库（指纹匹配 upsert，绝不删库；手动导入节点永不受影响）"""
        import yaml
        import re

        result_path = result.get("result_path", "")
        if not os.path.exists(result_path):
            return

        with open(result_path, 'r') as f:
            data = yaml.safe_load(f) or {}

        proxies = data.get('proxies', [])
        logger.info(f"Parsing {len(proxies)} alive proxies (upsert mode, no wipe)")

        results = []
        for proxy in proxies:
            name = str(proxy.get('name', ''))
            ptype = str(proxy.get('type', 'unknown')).lower()
            if not proxy.get('server'):
                continue

            # subs-check 命名格式: 国家|速度|延迟|名称 —— 提取测速指标
            download_speed, latency, country = None, None, None
            if '|' in name:
                parts = [p.strip() for p in name.split('|')]
                emoji_match = re.search(r'[\U0001F1E6-\U0001F1FF]{2}', parts[0])
                if emoji_match:
                    country = emoji_match.group(0)
                for p in parts[1:3]:
                    if p.endswith('KB/s'):
                        try:
                            download_speed = int(float(p[:-4]) * 1024)
                            break
                        except ValueError:
                            pass
                    elif p.endswith('MB/s'):
                        try:
                            download_speed = int(float(p[:-4]) * 1024 * 1024)
                            break
                        except ValueError:
                            pass
                for p in parts[1:4]:
                    digits = p.replace('ms', '').strip()
                    if digits.isdigit():
                        latency = int(digits)
                        break
                    if download_speed and latency:
                        break

            node_data = dict(proxy)  # clash 原字段即内部存储格式
            node_data.pop('name', None)
            results.append({
                "node_type": ptype,
                "node_data": node_data,
                "node_name": name,
                "download_speed": download_speed,
                "latency": latency,
                "country": country,
            })

        from ..schema.repository import apply_check_results
        stats = apply_check_results(results)
        logger.info(f"测速结果回填完成: 存活 {stats['alive']}，未命中转 inactive {stats['marked_inactive']}")

    async def get_api_status(self) -> Dict:
        """获取 subs-check API 状态"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api_base}/api/status")
                return resp.json()
        except Exception as e:
            return {"error": str(e)}