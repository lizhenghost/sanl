"""共享网络工具：TCP ping、IP 版本识别、运营商识别（cf_ping / cf_scanner / importer 共用）"""
import asyncio
import ipaddress
import re
from typing import Optional


async def tcping(host: str, port: int, timeout: float = 1.0) -> Optional[float]:
    """单次 TCP 握手延迟（毫秒），失败返回 None"""
    loop = asyncio.get_event_loop()
    start = loop.time()
    try:
        _, w = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout)
        rtt_ms = (loop.time() - start) * 1000
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return round(rtt_ms)
    except Exception:
        return None


def detect_ip_version(host: str) -> int:
    """IP 版本：4=IPv4 / 6=IPv6 / 0=域名"""
    h = (host or "").strip().strip("[]")
    if ":" in h:
        try:
            return ipaddress.ip_address(h).version
        except ValueError:
            return 0
    try:
        return ipaddress.ip_address(h).version
    except ValueError:
        return 0


def detect_isp(*texts) -> str:
    """从 URL/名称/备注推断运营商：telecom(电信)/mobile(移动)/unicom(联通)/''(未知→三网)"""
    joined = " ".join(t for t in texts if t).lower()
    if any(k in joined for k in ("cmcc", "移动")):
        return "mobile"
    if any(k in joined for k in ("unicom", "联通")) or re.search(r'(^|[^a-z])cu([^a-z]|$)', joined):
        return "unicom"
    if any(k in joined for k in ("telecom", "电信")) or re.search(r'(^|[^a-z])ct([^a-z]|$)', joined):
        return "telecom"
    return ""
