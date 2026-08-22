"""
CF 优选端点 TCP 延迟检测（tcping）
异步批量 socket connect 测 RTT，结果写回 cf_endpoints.latency_ms
"""
import asyncio
import logging
import time
from typing import List

from ..schema import repository
from ..utils.net import tcping as _tcping_shared

logger = logging.getLogger(__name__)

# 并发与超时：4200+ 端点场景下 ~30 秒内完成一轮
PING_CONCURRENCY = 300
PING_TIMEOUT = 1.5  # 秒


async def _worker(queue: asyncio.Queue, sem: asyncio.Semaphore, out: list):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        host, port, idx = item
        async with sem:
            out[idx] = {"host": host, "port": port,
                        "latency_ms": await _tcping_shared(host, port, PING_TIMEOUT)}
        queue.task_done()


async def ping_all(limit: int = 5000, isp: str = "any") -> dict:
    """对全部（或指定运营商）CF 端点做一轮 tcping，返回统计"""
    endpoints = repository.get_cf_endpoints(limit=limit, isp=isp)
    if not endpoints:
        return {"total": 0, "alive": 0}

    t0 = time.time()
    queue: asyncio.Queue = asyncio.Queue()
    results: List[dict] = [None] * len(endpoints)
    for i, ep in enumerate(endpoints):
        queue.put_nowait((ep["host"], int(ep["port"] or 443), i))

    sem = asyncio.Semaphore(PING_CONCURRENCY)
    workers = [asyncio.create_task(_worker(queue, sem, results))
               for _ in range(min(PING_CONCURRENCY, len(endpoints)))]
    for _ in workers:
        queue.put_nowait(None)
    await asyncio.gather(*workers)

    results = [r for r in results if r]
    n = repository.save_cf_latencies(results)
    latencies = [r["latency_ms"] for r in results if r["latency_ms"] is not None]
    stats = {
        "total": len(results),
        "alive": len(latencies),
        "avg_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "min_ms": min(latencies) if latencies else None,
        "elapsed_s": round(time.time() - t0, 1),
    }
    logger.info(f"CF tcping 完成: {stats}")
    return stats


async def ping_sample(host: str, port: int, count: int = 3) -> dict:
    """单端点多次采样取最小值"""
    rtts = []
    for _ in range(max(1, count)):
        rtt = await _tcping_shared(host, port, PING_TIMEOUT)
        if rtt is not None:
            rtts.append(rtt)
        await asyncio.sleep(0.05)
    return {"host": host, "port": port,
            "latency_ms": min(rtts) if rtts else None, "samples": len(rtts)}
