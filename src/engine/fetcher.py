"""订阅并发拉取器：多 URL 并发、超时、UA 伪装、失败重试。"""
import asyncio
import logging
from typing import List, Tuple, Optional, Callable

import httpx

logger = logging.getLogger(__name__)

_UA = "clash.meta/v1.19.0 (sanl-engine; self-developed) like ClashVerge/1.5.0"
_DEFAULT_TIMEOUT = 20.0
_MAX_CHARS = 12 * 1024 * 1024  # 单源字符上限，防异常大文件


async def fetch_one(client: httpx.AsyncClient, url: str, retries: int = 1) -> Tuple[str, str]:
    """拉取单个订阅，返回 (url, content)；失败返回 (url, '')"""
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.text[:_MAX_CHARS]
            if content.strip():
                return url, content
            return url, ""
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(0.8)
            else:
                logger.warning(f"[engine] 拉取失败 {url[:80]}: {type(e).__name__}: {e}")
    return url, ""


async def fetch_many(urls: List[str], concurrency: int = 10,
                     timeout: float = _DEFAULT_TIMEOUT,
                     progress_cb: Optional[Callable[[int, int], None]] = None
                     ) -> List[Tuple[str, str]]:
    """并发拉取全部订阅。progress_cb(done, total) 可选。"""
    sem = asyncio.Semaphore(max(1, concurrency))
    counter = {"done": 0}
    total = len(urls)

    async with httpx.AsyncClient(timeout=timeout,
                                 headers={"User-Agent": _UA},
                                 follow_redirects=True) as client:

        async def guarded(u: str) -> Tuple[str, str]:
            async with sem:
                r = await fetch_one(client, u)
                counter["done"] += 1
                if progress_cb:
                    try:
                        progress_cb(counter["done"], total)
                    except Exception:
                        pass
                return r

        results = await asyncio.gather(*[guarded(u) for u in urls], return_exceptions=True)
    return list(results)
