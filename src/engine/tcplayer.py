"""L1 TCP 测活层：纯 asyncio 批量 TCP 握手测 RTT（完全自主实现，无外部依赖）。

万级节点在秒级完成初筛，把昂贵的真实链路探测（L2/L3）留给少数候选。
内置两级优化：
- 域名解析缓存（同域名多节点只解析一次）
- DNS 解析限流（getaddrinfo 默认线程池仅 ~32 线程，无节流时大量协程排队导致假超时）
"""
import asyncio
import ipaddress
import logging
import socket
import time
from typing import List, Tuple, Optional

from .models import Candidate

logger = logging.getLogger(__name__)

# ---- DNS 解析缓存与限流 ----
_dns_cache: dict = {}            # host -> (ip or None, expire_ts)
_dns_sem = asyncio.Semaphore(48)
_DNS_TTL = 600.0


async def resolve_host(host: str, timeout: float = 3.0) -> Optional[str]:
    """带缓存/限流的 A 记录解析；IP 直返，失败短缓存防雪崩。"""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    hit = _dns_cache.get(host)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    async with _dns_sem:
        hit = _dns_cache.get(host)  # 双检：等锁期间可能已被并发协程解析
        if hit and hit[1] > time.monotonic():
            return hit[0]
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, None, family=socket.AF_INET,
                                 type=socket.SOCK_STREAM), timeout=timeout)
            ip = infos[0][4][0]
            _dns_cache[host] = (ip, time.monotonic() + _DNS_TTL)
            return ip
        except Exception:
            _dns_cache[host] = (None, time.monotonic() + 60.0)
            return None


def dns_stats() -> dict:
    total = len(_dns_cache)
    ok = sum(1 for v in _dns_cache.values() if v[0])
    return {"domains": total, "resolved": ok}


async def probe_tcp_timed(host: str, port: int, timeout: float = 2.0) -> Optional[float]:
    """TCP 握手并测量耗时（毫秒，含必要时的 DNS），失败返回 None。"""
    t0 = time.monotonic()
    target = await resolve_host(str(host))
    if target is None:
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    writer = None
    try:
        fut = asyncio.open_connection(target, port)
        _, writer = await asyncio.wait_for(fut, timeout=max(0.05, timeout))
        return (time.monotonic() - t0) * 1000.0
    except Exception:
        return None
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def batch_probe(candidates: List[Candidate], concurrency: int = 500,
                      timeout: float = 2.0,
                      progress_cb=None) -> None:
    """批量 L1 测活：结果写回 candidate.tcp_rtt（None=不通）。"""
    sem = asyncio.Semaphore(max(10, concurrency))
    counter = {"done": 0}
    total = len(candidates)

    async def work(c: Candidate):
        async with sem:
            p = c.proxy
            c.tcp_rtt = await probe_tcp_timed(p.get("server"), p.get("port"),
                                              timeout=timeout)
        counter["done"] += 1
        if progress_cb and counter["done"] % 50 == 0:
            try:
                progress_cb(counter["done"], total)
            except Exception:
                pass

    await asyncio.gather(*[work(c) for c in candidates])
    logger.info(f"[engine] L1 完成 {dns_stats()}")
