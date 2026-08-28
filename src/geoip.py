"""
GeoIP 出口识别模块
使用 ip-api.com 免费接口（batch 100/请求, 15 req/min）识别节点真实出口位置
结果缓存到 nodes.country / nodes.country_code
"""
import asyncio
import ipaddress
import logging
import socket
import time
from typing import List, Dict

import httpx

from .schema import repository

logger = logging.getLogger(__name__)

IPAPI_BATCH_URL = "http://ip-api.com/batch"
# 免费版字段限制内可用的字段
FIELDS = "status,country,countryCode,lat,lon,city"

# 内存缓存: server -> (ts, result)，避免重复查询
_geo_cache: Dict[str, tuple] = {}
CACHE_TTL = 24 * 3600  # 24h


def _is_ipv4(s: str) -> bool:
    try:
        return ipaddress.ip_address(s).version == 4
    except ValueError:
        return False


def _is_ipv6(s: str) -> bool:
    try:
        return ipaddress.ip_address(s).version == 6
    except ValueError:
        return False


def _is_private_ip(ip: str) -> bool:
    """内网/保留地址不送公网 GeoIP 查询（如 127.0.0.1、10.x、CF 内网误配）"""
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback or a.is_reserved or a.is_link_local
    except ValueError:
        return True


def _emoji_flag(country_code: str) -> str:
    """国家代码 → emoji 国旗"""
    if not country_code or len(country_code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in country_code.upper())


async def lookup_servers(servers: List[str], batch_size: int = 100) -> Dict[str, dict]:
    """
    批量查询 server（IP 或域名）的出口地理位置
    返回 {server: {country, country_code, lat, lon}}（键 = 传入的原始字符串）

    说明：ip-api 免费端点只接受 IP，不接受域名；
    域名会先在本地做 DNS 解析（loop.run_in_executor 并发），再用解析出的 IP 查询，
    结果按「原始 server 字符串」为键返回——此前用响应里的 query(IP) 做键，
    导致域名节点的 GeoIP 全部匹配失败（updated=0 的根因）。
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

    # ---- 域名 → IP 预解析（免费 ip-api 不支持域名入参）----
    loop = asyncio.get_running_loop()

    def _resolve(host: str):
        try:
            return socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)[0][4][0]
        except Exception:
            return None

    resolve_map: Dict[str, str] = {}   # domain -> ip
    uniq_domains = [s for s in dict.fromkeys(pending)
                    if not _is_ipv4(s) and not _is_ipv6(s)]
    if uniq_domains:
        tasks = [loop.run_in_executor(None, _resolve, d) for d in uniq_domains]
        resolved = await asyncio.gather(*tasks, return_exceptions=True)
        for d, ip in zip(uniq_domains, resolved):
            if isinstance(ip, Exception):
                continue
            if ip and not _is_private_ip(ip):
                resolve_map[d] = ip

    # 待查询 IP 列表（域名已替换为解析后的 IP；未解析成功的跳过）
    ip_targets: List[str] = []
    target_owner: Dict[str, List[str]] = {}   # ip -> [原始server...]
    for s in pending:
        ip = s if (_is_ipv4(s) or _is_ipv6(s)) else resolve_map.get(s)
        if not ip:
            continue
        if ip not in target_owner:
            target_owner[ip] = []
            ip_targets.append(ip)
        target_owner[ip].append(s)

    # 分批查询，批间隔 4.5s（15 req/min 安全线内）
    async with httpx.AsyncClient(timeout=15) as client:
        for i in range(0, len(ip_targets), batch_size):
            batch = ip_targets[i:i + batch_size]
            try:
                resp = await client.post(
                    f"{IPAPI_BATCH_URL}?fields={FIELDS}",
                    json=batch
                )
                if resp.status_code == 200:
                    # batch 响应与请求顺序一一对应，按下标配对（响应 query 是
                    # 解析后的 IP，不能当键用——域名节点会因此全部 miss）
                    items = resp.json()
                    for orig_ip, item in zip(batch, items):
                        if item.get("status") != "success":
                            continue
                        info = {
                            "country": item.get("country", ""),
                            "country_code": item.get("countryCode", ""),
                            "lat": item.get("lat", 0),
                            "lon": item.get("lon", 0),
                            "city": item.get("city", ""),
                        }
                        # 回写到所有指向该 IP 的原始 server（含域名）
                        for owner in target_owner.get(orig_ip, [orig_ip]):
                            results[owner] = info
                            _geo_cache[owner] = (now, info)
                else:
                    logger.warning(f"ip-api batch HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"ip-api batch failed: {e}")
            if i + batch_size < len(ip_targets):
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
    刷新节点 GeoIP：优先补「国家/国家码缺失」的 active 节点（已正确的节点跳过，避免无效查询）
    更新 nodes.country（emoji 国旗）/ country_code
    """
    # 优先补缺失；若缺失的很少，则返回后无需查询已正确节点（日志因此不再出现 0/300）
    missing = repository.list_nodes_missing_geo(limit=limit, status="active")
    if missing:
        nodes = missing
    else:
        nodes = []  # 全部已有国家，无需查询

    if not nodes:
        logger.info("GeoIP refresh: 所有 active 节点已具备出口信息，无待补项")
        return {"updated": 0, "looked_up": 0, "total": 0}

    # 去重收集 server
    servers = list({s for s in (_node_server(n) for n in nodes) if s})
    if not servers:
        return {"updated": 0, "looked_up": 0, "total": len(nodes)}

    geo = await lookup_servers(servers)
    updated = 0
    for n in nodes:
        info = geo.get(_node_server(n))
        if not info:
            continue
        code = info["country_code"]
        flag = _emoji_flag(code)
        city = info.get("city", "")
        # country 相同但 country_code 未写入时也要更新；city 缺失也补
        if flag and (n.country != flag or getattr(n, "country_code", None) != code or not getattr(n, "city", None)):
            repository.update_node_geo(n.id, flag, code, city)
            updated += 1

    logger.info(f"GeoIP refreshed: {updated}/{len(nodes)} nodes updated ({len(servers)} servers looked up)")
    return {"updated": updated, "looked_up": len(servers), "total": len(nodes)}
