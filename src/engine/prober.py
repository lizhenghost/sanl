"""L2/L3 探测器：经内核通道对候选节点做真实链路探测与限流量测速。

L2 存活+延迟：经节点出口请求 204 端点，成功即存活，总耗时即应用层延迟。
L3 下载测速：经节点出口流式下载测速文件，限字节/限时，计算 B/s。
"""
import asyncio
import logging
import time
from typing import List, Optional

import httpx

from .kernel import KernelManager
from .models import Candidate

logger = logging.getLogger(__name__)

# 204 探测端点（多备选，逐个尝试）
_ALIVE_URLS = [
    "http://www.gstatic.com/generate_204",
    "http://cp.cloudflare.com/generate_204",
    "http://connectivitycheck.platform.hicloud.com/generate_204",
]


async def _http_probe(proxy_url: str, timeout: float) -> Optional[int]:
    """经 proxy_url 发 204 探测，返回应用层延迟 ms；全失败返回 None。"""
    last_err = None
    async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout) as c:
        for url in _ALIVE_URLS[:2]:
            t0 = time.monotonic()
            try:
                r = await c.get(url)
                if r.status_code in (200, 204):
                    return int((time.monotonic() - t0) * 1000)
                last_err = f"status={r.status_code}"
            except Exception as e:
                last_err = type(e).__name__
    logger.debug(f"[probe] alive 失败 {proxy_url}: {last_err}")
    return None


async def _speed_probe(proxy_url: str, speed_url: str,
                       max_bytes: int, max_seconds: float,
                       timeout: float) -> Optional[int]:
    """流式下载测速，返回 B/s（整数）；失败返回 None。"""
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout) as c:
            t0 = time.monotonic()
            total = 0
            async with c.stream("GET", speed_url) as resp:
                if resp.status_code != 200:
                    return None
                async for chunk in resp.aiter_bytes(65536):
                    total += len(chunk)
                    elapsed = time.monotonic() - t0
                    if total >= max_bytes or elapsed >= max_seconds:
                        break
            elapsed = max(time.monotonic() - t0, 0.05)
            return int(total / elapsed)
    except Exception:
        return None


async def probe_candidates(km: KernelManager, candidates: List[Candidate],
                           *, do_speed: bool,
                           speed_url: str,
                           min_speed: int,
                           download_mb: float = 1.0,
                           download_timeout: float = 6.0,
                           alive_timeout: float = 5.0,
                           progress_cb=None) -> None:
    """多通道并发探测候选：写回 candidate.latency / download_speed / alive。"""
    channels = km.channels
    queue: asyncio.Queue = asyncio.Queue()
    for c in candidates:
        queue.put_nowait(c)

    counter = {"done": 0}
    total = len(candidates)
    max_bytes = int(download_mb * 1024 * 1024)

    async def worker(ch: int):
        while True:
            try:
                cand = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await km.select(ch, cand.name)
                await asyncio.sleep(0.05)  # 切换缓冲
                lat = await _http_probe(km.endpoint(ch), alive_timeout)
                if lat is None:
                    cand.alive = False
                else:
                    cand.alive = True
                    cand.latency = lat
                    if do_speed:
                        speed = await _speed_probe(
                            km.endpoint(ch), speed_url,
                            max_bytes=max_bytes, max_seconds=download_timeout,
                            timeout=download_timeout + 3)
                        cand.download_speed = speed
                        if speed is not None and speed < min_speed:
                            # 速度不达标：存活但不可用（与 subs-check min-speed 语义一致）
                            cand.download_speed = speed  # 保留实测值供评分
            finally:
                counter["done"] += 1
                if progress_cb and counter["done"] % 10 == 0:
                    try:
                        progress_cb(counter["done"], total)
                    except Exception:
                        pass
                queue.task_done()

    workers = [asyncio.create_task(worker(i)) for i in range(channels)]
    await asyncio.gather(*workers)
