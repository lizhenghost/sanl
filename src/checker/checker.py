"""
subs-check 测速引擎
通过子进程调用 subs-check 二进制进行测速
支持前台(手动)/后台(定时)测速 + 实时进度跟踪
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import time
from collections import deque
from typing import Dict, List, Optional

import httpx

from ..config import get_subs_check_config, get_app_config, get_scheduler_config, get_app_config
from ..schema import repository

logger = logging.getLogger(__name__)

# subs-check 日志关键行（剥 ANSI 后匹配）
_RE_SUBS = re.compile(r'订阅链接数量.*?总计[=:]\s*(\d+)')
_RE_FOUND = re.compile(r'获取节点数量[=:]\s*(\d+)')
_RE_DEDUP = re.compile(r'去重后节点数量[=:]\s*(\d+)')
_RE_ALIVE = re.compile(r'存活节点数量[=:]\s*(\d+)')
_RE_USABLE = re.compile(r'可用节点数量[=:]\s*(\d+)')
_RE_TRAFFIC = re.compile(r'测试总消耗流量[=:]\s*([\d.]+\s*[KMG]B)')
_RE_ANSI = re.compile(r'\x1b\[[0-9;]*m')

# 阶段定义（前端步骤条）
PHASES = ["拉取订阅", "解析去重", "连通性测活", "入库完成"]

# 测速模式：控制测试维度（subs-check 无独立测速开关，通过参数组合实现）
#   latency — 仅测活+延迟：跳过流媒体检测/IP重命名/速度测试(download压到1s)
#   speed   — 延迟+下载速度：跳过流媒体检测（默认，性价比最高）
#   full    — 全部维度：延迟+速度+流媒体解锁+IP风险
CHECK_MODES = {
    "latency": {
        "label": "仅延迟",
        "media-check": False,
        "rename-node": False,       # IP 地理查询是耗时项，仅延迟模式直接跳过
        "download-timeout": 1,
        "download-mb": 1,
        "min-speed": 0,
    },
    "speed": {
        "label": "延迟+速度",
        "media-check": False,
        "rename-node": True,
        "download-timeout": 6,
        "download-mb": 1,
        "min-speed": 128,   # 256→128：存活但中速的节点也算可用（免费池本就稀缺，128KB/s 可满足基础代理）
    },
    "full": {
        "label": "全量(含流媒体)",
        "media-check": True,
        "rename-node": True,
        "download-timeout": 6,
        "download-mb": 1,
        "min-speed": 128,
    },
}
# 允许通过 API 覆盖的 subs-check 参数白名单
OVERRIDABLE_KEYS = {"concurrent", "timeout", "min-speed", "download-mb",
                    "download-timeout", "speed-concurrent", "speed-test-url",
                    "alive-test-url", "media-concurrent"}


async def _safe_wait(task) -> None:
    """等待日志泵任务结束（吞异常，最多等 10s）"""
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=10)
    except Exception:
        task.cancel()


class Checker:
    def __init__(self):
        self.config = get_subs_check_config()
        self.binary_path = self.config.get("binary_path", "./subs-check")
        self.config_path = self.config.get("config_path", "./config/subs-check.yaml")
        self.output_dir = self.config.get("output_dir", "./output")
        self.api_port = 8199
        self.api_base = f"http://127.0.0.1:{self.api_port}"
        # 当前/最近一次任务进度（前台手动 / 后台定时 共用同一状态管道）
        self.current_job: Optional[Dict] = None

    # ---------- 进度跟踪 ----------
    def _job_init(self, job_id: int, trigger: str, mode: str = "speed"):
        self.current_job = {
            "job_id": job_id,
            "source": "manual" if trigger == "manual" else "scheduled",  # manual=前台 scheduled=后台
            "mode": mode if mode in CHECK_MODES else "speed",
            "started_at": time.time(),
            "finished_at": None,
            "status": "running",
            "phase_idx": 0,
            "subs_total": None,      # 订阅数
            "nodes_found": None,     # 获取节点
            "nodes_deduped": None,   # 去重后
            "nodes_alive": None,     # 存活
            "traffic": "",
            "log": deque(maxlen=200),
        }

    def _job_log(self, line: str):
        """处理子进程一行输出：记录 + 解析指标 + 推进阶段"""
        clean = _RE_ANSI.sub("", line).strip()
        if not clean:
            return
        job = self.current_job
        if not job:
            return
        job["log"].append(clean)

        m = _RE_SUBS.search(clean)
        if m:
            job["subs_total"] = int(m.group(1))
        m = _RE_FOUND.search(clean)
        if m and job["phase_idx"] < 1:
            job["nodes_found"] = int(m.group(1))
            job["phase_idx"] = 1          # 进入 解析去重
        m = _RE_DEDUP.search(clean)
        if m:
            job["nodes_deduped"] = int(m.group(1))
        if "开始检测节点" in clean or "启动流水线" in clean:
            job["phase_idx"] = max(job["phase_idx"], 2)   # 进入 连通性测活
        m = _RE_ALIVE.search(clean)
        if m:
            v = int(m.group(1))
            if job["nodes_alive"] != v:
                job["nodes_alive"] = v
                job["phase_idx"] = max(job["phase_idx"], 3)  # 存活出炉→入库完成阶段
        m = _RE_USABLE.search(clean)
        if m:
            job["nodes_alive"] = int(m.group(1))
        m = _RE_TRAFFIC.search(clean)
        if m:
            job["traffic"] = m.group(1)
        if "检测完成" in clean or "保存本地成功" in clean:
            job["phase_idx"] = 3

    async def get_progress(self) -> Dict:
        """进度快照：优先内存中的当前/最近任务；无则回退 DB 最近一条"""
        job = self.current_job
        if not job:
            with repository.get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM check_jobs ORDER BY created_at DESC LIMIT 1").fetchone()
            if row:
                r = dict(row)
                return {
                    "job_id": r.get("id"), "source": "scheduled", "status": r.get("status"),
                    "phase_idx": None, "phases": PHASES, "elapsed": None,
                    "subs_total": None, "nodes_found": None, "nodes_deduped": None,
                    "nodes_alive": None, "traffic": "", "log": [],
                    "finished_at": r.get("finished_at"),
                    "error_message": r.get("error_message"),
                }
            return {"status": "idle", "phases": PHASES}

        elapsed = (job["finished_at"] or time.time()) - job["started_at"]
        return {
            "job_id": job["job_id"], "source": job["source"],
            "mode": job.get("mode", "speed"),
            "status": job["status"], "phase_idx": job["phase_idx"],
            "phases": PHASES, "elapsed": round(elapsed),
            "subs_total": job["subs_total"], "nodes_found": job["nodes_found"],
            "nodes_deduped": job["nodes_deduped"], "nodes_alive": job["nodes_alive"],
            "traffic": job["traffic"],
            "log": list(job["log"])[-80:],
            "finished_at": job["finished_at"],
            "error_message": job.get("error"),
        }

    async def _pump_stream(self, stream, logfile) -> None:
        """逐行读取子进程输出：写文件日志 + 更新内存进度"""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", "ignore").rstrip()
                try:
                    with open(logfile, "a") as f:
                        f.write(text + "\n")
                except OSError:
                    pass
                self._job_log(text)
        except Exception as e:
            logger.debug(f"log pump ended: {e}")


    async def run_check(self, trigger: str = "manual", mode: str = "speed",
                        overrides: Optional[Dict] = None) -> Dict:
        """运行一次完整的测速检查
        trigger: manual=前台(用户手动触发) / scheduled=后台(定时调度)
        mode: latency=仅延迟 / speed=延迟+速度 / full=全量(含流媒体)
        overrides: 覆盖 subs-check 参数（仅白名单键生效）"""
        mode = mode if mode in CHECK_MODES else "speed"
        job_id = repository.add_check_job("full_check")
        repository.update_check_job(getattr(job_id, "id", job_id), "running")  # pending→running，修 history/progress 分歧
        self._job_init(getattr(job_id, "id", job_id), trigger, mode)
        job = self.current_job

        from ..utils.taskmgr import task_manager
        TASK_ID = "check"
        task_manager.start(TASK_ID, f"⚡ {CHECK_MODES[mode]['label']}测速")
        try:
            all_sources = repository.list_sources(enabled_only=True)
            # 源级测速参与开关：只测 speed_test=1 的源（用户可指定哪些源参加/不参加）
            sources = [s for s in all_sources if int(getattr(s, 'speed_test', 1) or 1)]
            # 自定义参与源数量（max_sources）：按节点数/健康度排序取前 N，提速增效
            max_sources = int((overrides or {}).get("max_sources", 0) or 0)
            if max_sources and max_sources > 0:
                sources = sorted(sources, key=lambda s: int(getattr(s, 'node_count', 0) or 0), reverse=True)[:max_sources]
            if not sources:
                logger.warning("No enabled sources (or none opted-in to speed test)")
                repository.update_check_job(job_id.id, "failed", error="No enabled sources")
                job.update({"status": "failed", "finished_at": time.time(), "error": "No enabled sources"})
                return {"status": "no_sources", "job_id": job_id}

            task_manager.update(TASK_ID, phase="running",
                                detail=f"准备 {len(sources)} 个源订阅（{CHECK_MODES[mode]['label']}）"
                                       + (f"，限前 {max_sources} 个源" if max_sources else ""))

            import time as _t
            job_start_ts = int(_t.time())

            # 测速后端可切换：sanl-engine（自研）/ subs-check（外部二进制桥接）
            backend = str(get_scheduler_config().get("check_backend", "engine")).lower()
            if backend == "engine":
                logger.info(f"Starting sanl-engine with {len(sources)} sources ({trigger})")
                result = await self._run_engine(sources, mode=mode, overrides=overrides)
            else:
                await self._update_subs_check_config(sources, mode=mode, overrides=overrides)
                logger.info(f"Starting subs-check with {len(sources)} sources ({trigger})")
                task_manager.update(TASK_ID, detail="subs-check 测试中（拉取/解析/连通性/延迟速度）…")
                result = await self._run_subs_check()
            task_manager.update(TASK_ID, done=1, total=2, detail="入库与评分计算中…")

            if result.get("success"):
                await self._parse_and_store_results(result)
                # 重新计算评分
                from ..schema.repository import update_node_scores
                scored = update_node_scores()
                logger.info(f"Updated scores for {scored} nodes")
                repository.update_check_job(job_id.id, "completed", result=json.dumps(result))
                job.update({"status": "completed", "finished_at": time.time()})
                task_manager.finish(TASK_ID)
                # 健康历史快照（近 7 天趋势数据源，附录：优化 #4）
                try:
                    snap = repository.record_health_snapshot(job_start_ts)
                    logger.info(f"Health history snapshot: {snap} records")
                except Exception as he:
                    logger.warning(f"health snapshot failed: {he}")
                # 合格延迟判定：超过阈值的存活节点标记 inactive（默认订阅不输出）
                try:
                    threshold = get_scheduler_config().get("qualified_latency_ms", 200)
                    marked = repository.apply_qualified_latency(int(threshold))
                    logger.info(f"Qualified-latency check (>{threshold}ms): {marked} nodes marked inactive")
                except Exception as qe:
                    logger.warning(f"apply qualified latency failed: {qe}")
                # 测速后异步刷新 GeoIP 出口识别（不阻塞返回；外层捕获避免 Future exception 泄漏）
                import asyncio
                from ..geoip import refresh_node_geo

                async def _safe_geo():
                    try:
                        await refresh_node_geo(limit=300)
                    except Exception as ge:
                        logger.warning(f"GeoIP refresh failed: {ge}")

                _t = asyncio.create_task(_safe_geo())
                _t.add_done_callback(lambda fut: None)  # 消费异常，避免 asyncio 报 unretrieved
            else:
                err = result.get("error", "Unknown error")
                repository.update_check_job(job_id.id, "failed", error=err)
                job.update({"status": "failed", "finished_at": time.time(), "error": err})

            return result

        except Exception as e:
            task_manager.finish(TASK_ID, error=str(e)[:120])
            logger.error(f"Check failed: {e}")
            repository.update_check_job(job_id.id, "failed", error=str(e))
            job.update({"status": "failed", "finished_at": time.time(), "error": str(e)})
            return {"status": "error", "job_id": job_id, "error": str(e)}

    async def _run_engine(self, sources: List, mode: str = "speed",
                          overrides: Optional[Dict] = None) -> Dict:
        """自研引擎后端：sanl-engine 三级漏斗管线。

        输出与 subs-check 后端同构的 result dict（result_path 指向 clash proxies yaml），
        复用既有 _parse_and_store_results 回填管道，绝不删库。
        """
        import yaml as _yaml
        from ..engine.pipeline import run_pipeline

        # 与 _update_subs_check_config 相同的源筛选：只喂真实代理订阅
        urls = [
            s.url for s in sources
            if not s.url.startswith('manual://')
            and not s.url.startswith('data:')
            and (getattr(s, 'source_type', '') or '').lower() not in ('cf-list', 'static')
        ]
        try:
            manual_count = repository.count_nodes_by_source_type('manual')
        except Exception:
            manual_count = 0
        if manual_count > 0:
            local_port = get_app_config().get('port', 8899)
            urls.append(f"http://127.0.0.1:{local_port}/sub/internal/manual")

        ov = {k: v for k, v in (overrides or {}).items() if k != "max_sources"}
        # 注意：不继承 subs-check 的 concurrent——两者并发语义完全不同
        # （subs-check 是其内部 goroutine 数；sanl-engine 的 concurrent 是 mihomo 探测通道数，
        #   实测标定 16×8s 最优，灌入 30+ 会因内核过载误杀 ~30% 存活节点）
        ov.setdefault("min-speed", CHECK_MODES.get(mode, CHECK_MODES["speed"]).get("min-speed", 128))

        job = self.current_job
        TASK_ID = "check"
        from ..utils.taskmgr import task_manager

        def on_progress(phase: str, done: int, total: int, detail: str):
            # 映射到前端四阶段：拉取订阅→解析去重→连通性测活→入库完成
            if phase == "fetch":
                job["phase_idx"] = 0
                job["subs_total"] = total
            elif phase == "parse":
                job["nodes_found"] = job["nodes_deduped"] = total
                job["phase_idx"] = max(job["phase_idx"], 1)
            elif phase in ("l1", "probe"):
                job["phase_idx"] = 2
            elif phase == "done":
                job["phase_idx"] = 3
            line = f"[{phase}] {done}/{total} {detail}".strip()
            job["log"].append(line)
            task_manager.update(TASK_ID, phase="running", detail=line)

        result = await run_pipeline(
            urls, mode=mode, overrides=ov,
            progress_cb=on_progress,
            workdir=str(get_app_config().get("engine_workdir", "./output/engine")))

        if not result.ok:
            return {"success": False, "error": result.error}

        st = result.stats.as_dict()
        job.update({
            "subs_total": st["fetched_sources"],
            "nodes_found": st["parsed_nodes"],
            "nodes_deduped": st["deduped_nodes"],
            "nodes_alive": len(result.alive_proxies),
        })

        out_dir = get_app_config().get("engine_workdir", "./output/engine")
        os.makedirs(out_dir, exist_ok=True)
        result_path = os.path.join(out_dir, "all.yaml")
        with open(result_path, "w", encoding="utf-8") as f:
            _yaml.safe_dump({"proxies": result.alive_proxies}, f, allow_unicode=True, sort_keys=False)

        logger.info(f"sanl-engine 完成: 候选 {st['deduped_nodes']} → "
                    f"L1 {st['l1_alive']} → L2 {st['l2_alive']} → 合格 {st['l3_passed']} "
                    f"耗时 {result.elapsed}s")
        return {
            "success": True,
            "backend": "sanl-engine",
            "result_path": result_path,
            "total_nodes": st["deduped_nodes"],
            "alive": len(result.alive_proxies),
            "elapsed": result.elapsed,
        }

    async def _update_subs_check_config(self, sources: List, mode: str = "speed",
                                        overrides: Optional[Dict] = None):
        """动态更新 subs-check 配置文件中的订阅源（保留其他设置）
        mode: 测速维度模式（latency/speed/full）；overrides: 参数覆盖（白名单）"""
        import yaml

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f) or {}

        # subs-check 只吃真实代理订阅：
        # - manual:// 手动导入节点 → 通过本机内部端点 /sub/internal/manual 聚合输出，同样参与测速
        # - data:/static 与 cf-list 类型是 CF 优选 host:port 列表，不是代理节点，喂进去只会浪费时间
        remote_urls = [
            src.url for src in sources
            if not src.url.startswith('manual://')
            and not src.url.startswith('data:')
            and (getattr(src, 'source_type', '') or '').lower() not in ('cf-list', 'static')
        ]
        try:
            manual_count = repository.count_nodes_by_source_type('manual')
        except Exception:
            manual_count = 0
        if manual_count > 0:
            local_port = get_app_config().get('port', 8899)
            remote_urls.append(f"http://127.0.0.1:{local_port}/sub/internal/manual")
            logger.info(f"Including {manual_count} manual nodes via internal endpoint")
        config['sub-urls'] = remote_urls

        # 按模式应用测试维度参数，再叠加用户覆盖项（白名单校验）
        for k, v in CHECK_MODES.get(mode, CHECK_MODES["speed"]).items():
            if k != "label":
                config[k] = v
        for k, v in (overrides or {}).items():
            if k == "max_sources":   # 顶层逻辑参数，不写入 subs-check yaml
                continue
            if k in OVERRIDABLE_KEYS:
                config[k] = v
            else:
                logger.warning(f"Ignored non-overridable key: {k}")

        logger.info(f"Updated subs-check config: {len(remote_urls)} sources, "
                    f"mode={mode} ({CHECK_MODES.get(mode, {}).get('label')}), "
                    f"media-check={config.get('media-check')}, "
                    f"concurrent={config.get('concurrent')}")

        with open(self.config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

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

            # 启动 subs-check（独立进程组，便于整组清理）；stdout/stderr 走管道逐行解析实时进度
            logfile = "/tmp/subs-check.log"
            with open(logfile, "a") as f:
                f.write(f"\n===== Sanl 任务启动 ({self.current_job['source']}) "
                        f"{time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            process = await asyncio.create_subprocess_exec(
                self.binary_path,
                "-f", self.config_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.dirname(os.path.abspath(self.binary_path)),
                start_new_session=True,
            )
            pump = asyncio.create_task(self._pump_stream(process.stdout, logfile))

            max_wait = 5400  # 90 分钟
            waited = 0
            poll_interval = 3
            stable_ticks = 0      # 结果文件连续无增长的检测轮数
            last_size = -1

            while waited < max_wait:
                await asyncio.sleep(poll_interval)
                waited += poll_interval

                if process.returncode is not None:
                    break

                # 只认本轮启动之后新写入的结果文件（mtime > start_ts）
                if (os.path.exists(result_file) and os.path.getsize(result_file) > 0
                        and os.path.getmtime(result_file) > start_ts):
                    # 动态等写入完成：文件大小连续 5 轮(约15s)不再增长即视为写完
                    # （替代旧版固定 sleep(60)，平均可省 40~55 秒）
                    size = os.path.getsize(result_file)
                    stable_ticks = stable_ticks + 1 if size == last_size else 0
                    last_size = size
                    if stable_ticks >= 5:
                        self._terminate(process)
                        await _safe_wait(pump)
                        return await self._read_results()

            self._terminate(process)
            await _safe_wait(pump)
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
            # 流媒体解锁标记（大纲 附录B check-streaming）：从 subs-check 节点名/字段提取
            stream_flags = set()
            for kw in ('Netflix', 'Disney', 'Hulu', 'HBO', 'YouTube', 'ChatGPT', 'TikTok', 'Prime'):
                if kw.lower() in name.lower() or kw.lower() in json.dumps(node_data, ensure_ascii=False).lower():
                    stream_flags.add(kw)
            results.append({
                "node_type": ptype,
                "node_data": node_data,
                "node_name": name,
                "download_speed": download_speed,
                "latency": latency,
                "country": country,
                "stream_flags": "|".join(sorted(stream_flags)) or None,
            })

        from ..schema.repository import apply_check_results, get_ranking_stats
        from ..api.cache import invalidate_all
        stats = apply_check_results(results)
        logger.info(f"测速结果回填完成: 存活 {stats['alive']}，未命中转 inactive {stats['marked_inactive']}")
        invalidate_all()  # 数据变更后清空读缓存，保证下一批读快照新鲜
        # 将存活/总数/均分并入 result，供趋势接口读取（原只存 total_nodes 导致 trend 全 0）
        try:
            result["alive"] = int(stats.get("alive", 0))
            result["total"] = int(result.get("total_nodes", 0) or 0)
            result["avg_score"] = round(float(get_ranking_stats().get("avg_score", 0) or 0), 1)
        except Exception as se:
            logger.warning(f"merge alive into result failed: {se}")

    async def get_api_status(self) -> Dict:
        """获取 subs-check API 状态"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api_base}/api/status")
                return resp.json()
        except Exception as e:
            return {"error": str(e)}