"""轻量 GeoIP 批查：为引擎存活节点补国家码（ip-api batch，免费额度内节流使用）。"""
import asyncio
import logging
from typing import List

import httpx

logger = logging.getLogger(__name__)

_BATCH = "http://ip-api.com/batch?fields=status,countryCode,query"
# 免费限制 45 req/min；batch 每次最多 100 IP。保守节流。
_sem = asyncio.Semaphore(2)


async def fill_country_codes(cands) -> int:
    """给 Candidate 列表补 country_code（仅缺省的）。返回补全数量。"""
    need = [c for c in cands if not getattr(c, "country_code", "")
            and c.proxy.get("server")]
    if not need:
        return 0
    filled = 0
    async with httpx.AsyncClient(timeout=8.0) as client:
        for i in range(0, len(need), 100):
            batch = need[i:i + 100]
            payload = [str(c.proxy["server"]) for c in batch]
            try:
                async with _sem:
                    r = await client.post(_BATCH, json=payload)
                r.raise_for_status()
                for c, item in zip(batch, r.json()):
                    cc = (item or {}).get("countryCode") or ""
                    if len(cc) == 2:
                        c.country_code = cc
                        filled += 1
            except Exception as e:
                logger.debug(f"[geoip] batch 失败: {e}")
            if i + 100 < len(need):
                await asyncio.sleep(1.6)  # 45/min 节流
    logger.info(f"[engine] GeoIP 补全 {filled}/{len(need)}")
    return filled
