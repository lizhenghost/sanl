"""L1.5 TLS 预检查 —— 对 tls:true 的 vless/vmess/trojan 节点先做 TCP+TLS hello 探测。

解决的核心问题：免费源大量 TLS 节点中服务器实际挂了或不说 TLS，
直接进 mihomo 会占满通道后全部失败。L1.5 在进内核前快速过滤。

原理：
  1. TCP 连接 server:port
  2. 发送 TLS ClientHello（带 SNI）
  3. 接收 ServerHello + 证书（不验证链）
  4. 成功=服务器接受 TLS；失败=死节点/非 TLS 端口/SNI 不匹配

与 L1 TCP 握手的区别：L1 只验证 TCP 可达，不验证 TLS 层。
"""
import asyncio
import logging
import ssl
from typing import Optional

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 200  # TLS 预检查并发


class TLSPreCheckResult:
    __slots__ = ("ok", "error")
    def __init__(self, ok: bool, error: str = ""):
        self.ok = ok
        self.error = error


async def tls_precheck(server: str, port: int, sni: Optional[str],
                       timeout: float = 3.0) -> TLSPreCheckResult:
    """对单个节点做 TLS hello 预检查。"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # 只关心能否握手，不验证链
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port, ssl=ctx, server_hostname=sni or server),
            timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return TLSPreCheckResult(ok=True)
    except ssl.SSLError as e:
        return TLSPreCheckResult(ok=False, error=f"tls:{e}")
    except (ConnectionRefusedError, ConnectionResetError) as e:
        return TLSPreCheckResult(ok=False, error=f"conn:{type(e).__name__}")
    except OSError as e:
        return TLSPreCheckResult(ok=False, error=f"os:{e}")
    except asyncio.TimeoutError:
        return TLSPreCheckResult(ok=False, error="timeout")
    except Exception as e:
        return TLSPreCheckResult(ok=False, error=f"other:{type(e).__name__}")


async def tls_precheck_batch(nodes: list,
                             timeout: float = 3.0,
                             progress_cb=None) -> list:
    """批量 TLS 预检查。nodes = [(server, port, sni), ...]。
    返回 [(server, port, sni, result), ...]，result.ok 表示通过。
    """
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    results = [None] * len(nodes)

    async def _check(idx, node):
        async with sem:
            server, port, sni = node
            r = await tls_precheck(server, port, sni, timeout)
            results[idx] = (server, port, sni, r)
            if progress_cb:
                progress_cb(idx + 1, len(nodes))

    tasks = [asyncio.create_task(_check(i, n)) for i, n in enumerate(nodes)]
    await asyncio.gather(*tasks, return_exceptions=True)

    passed = []
    for r in results:
        if r and r[3].ok:
            passed.append(r[:3])
    return passed