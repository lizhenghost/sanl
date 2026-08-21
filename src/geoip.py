"""
GeoIP 出口识别模块
使用 ip-api.com 免费接口（batch 100/请求, 15 req/min）识别节点真实出口位置
结果缓存到 nodes.country / nodes.country_code
"""
import asyncio
import logging
import time
from typing import List, Dict

import httpx

from .schema import repository

logger = logging.getLogger(__name__)

IPAPI_BATCH_URL = "http://ip-api.com/batch"
# 免费版字段限制内可用的字段
FIELDS = "status,country,countryCode,lat,lon,query"

# 内存缓存: server -> (ts, result)，避免重复查询
_geo_cache: Dict[str, tuple] = {}
CACHE_TTL = 24 * 3600  # 24h


def _emoji_flag(country_code: str) -> str:
    """国家代码 → emoji 国旗"""
    if not country_code or len(country_code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in country_code.upper())


async def lookup_servers(servers: List[str], batch_size: int = 100) -> Dict[str, dict]:
    """
    批量查询 server（IP 或域名）的出口地理位置
    返回 {server: {country, country_code, lat, lon}}
    """
    now = time.time()
    results = {}
    pending = []

    for s in servers:
        if not s:
            continue
        cached = _geo_cache.get(s)
        if cached and now - cached[0] < CACHE_TTL:
            results[s] = cached[1]
        else:
            pending.append(s)

    if not pending:
        return results

    # 分批查询，批间隔 4.5s（15 req/min 安全线内）
    async with httpx.AsyncClient(timeout=15) as client:
        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]
            try:
                resp = await client.post(
                    f"{IPAPI_BATCH_URL}?fields={FIELDS}",
                    json=batch
                )
                if resp.status_code == 200:
                    for item in resp.json():
                        q = item.get("query")
                        if item.get("status") == "success" and q:
                            info = {
                                "country": item.get("country", ""),
                                "country_code": item.get("countryCode", ""),
                                "lat": item.get("lat", 0),
                                "lon": item.get("lon", 0),
                            }
                            results[q] = info
                            _geo_cache[q] = (now, info)
                else:
                    logger.warning(f"ip-api batch HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"ip-api batch failed: {e}")
            if i + batch_size < len(pending):
                await asyncio.sleep(4.5)  # 免费限流保护

    return results


def _node_server(node) -> str:
    """从 node_data JSON 中提取 server 地址"""
    try:
        import json as _json
        data = _json.loads(node.node_data) if isinstance(node.node_data, str) else (node.node_data or {})
        return data.get("server") or ""
    except Exception:
        return ""


async def refresh_node_geo(limit: int = 300) -> dict:
    """
    刷新节点 GeoIP：取 active 节点的 server 地址查询出口位置
    更新 nodes.country（emoji 国旗）/ country_code
    """
    nodes = repository.list_nodes(status="active", limit=limit)
    # 去重收集 server
    servers = list({s for s in (_node_server(n) for n in nodes) if s})
    if not servers:
        return {"updated": 0, "looked_up": 0}

    geo = await lookup_servers(servers)
    updated = 0
    for n in nodes:
        info = geo.get(_node_server(n))
        if not info:
            continue
        code = info["country_code"]
        flag = _emoji_flag(code)
        # country 相同但 country_code 未写入时也要更新
        if flag and (n.country != flag or getattr(n, "country_code", None) != code):
            repository.update_node_geo(n.id, flag, code)
            updated += 1

    logger.info(f"GeoIP refreshed: {updated}/{len(nodes)} nodes updated ({len(servers)} servers looked up)")
    return {"updated": updated, "looked_up": len(servers), "total": len(nodes)}
