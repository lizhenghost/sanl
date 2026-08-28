"""
CF 优选中心核心引擎（三合一改造）
- harvest_domains: 优选域名批量 DNS 解析 → 优选 IP 入端点库（一个域名常含几十个任播 IP）
- find_cf_templates: 自动发现节点池中走 CF CDN 的中转节点作为模板（vless/vmess+ws, Host 为域名）
- endpoints_to_nodes: 优质优选端点 × 模板 → 节点变体（server=优选IP, Host/SNI=原域名）
  → fingerprint 去重入节点池, 参加统一测速排名, 可直接订阅使用（不只是加速素材）
"""
import asyncio
import logging
from typing import List, Dict, Set

from ..schema import repository

logger = logging.getLogger(__name__)

# CF CDN 常见 HTTPS 端口（Cloudflare 官方支持回源的 TLS 端口）
CF_TLS_PORTS = {443, 2053, 2083, 2087, 2096, 8443}

# 解析并发与超时
RESOLVE_CONCURRENCY = 20
RESOLVE_TIMEOUT = 6.0


async def _resolve_host(host: str) -> List[str]:
    """解析单个域名到 IP 列表（A/AAAA），失败返回空"""
    import socket
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
            ), timeout=RESOLVE_TIMEOUT)
        ips, seen = [], set()
        for fam, *_rest, sockaddr in infos:
            ip = sockaddr[0]
            if ip not in seen:
                seen.add(ip)
                ips.append(ip)
        return ips
    except Exception as e:
        logger.debug(f"[harvest] 解析失败 {host}: {e}")
        return []


def _is_ip(s: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(s.strip("[]"))
        return True
    except ValueError:
        return False


async def harvest_domains(domains: List[str], port: int = 443,
                          keep_domain: bool = True) -> dict:
    """
    批量解析优选域名 → IP 全部入 cf_endpoints。
    - 每个解析出的 IP 记为 `ip:port#原域名`
    - 域名本身也保留一条（ip_version=0），保持优选工具兼容
    返回 {domains, resolved_domains, new_ips, total_endpoints}
    """
    domains = [d.strip().rstrip(".") for d in domains if d.strip()]
    if not domains:
        return {"domains": 0, "resolved_domains": 0, "new_ips": 0,
                "total_endpoints": repository.count_cf_endpoints()}

    before = repository.count_cf_endpoints()
    sem = asyncio.Semaphore(RESOLVE_CONCURRENCY)

    async def _one(d: str):
        async with sem:
            return d, await _resolve_host(d)

    results = await asyncio.gather(*[_one(d) for d in domains], return_exceptions=True)

    items = []
    resolved = 0
    for r in results:
        if isinstance(r, Exception):
            continue
        domain, ips = r
        if not ips and not _is_ip(domain):
            continue
        if _is_ip(domain):          # 本身就是 IP：直接当端点
            items.append({"host": domain.strip("[]"), "port": port,
                          "remark": "手动IP", "ip_version": _ip_ver(domain)})
            resolved += 1
            continue
        resolved += 1
        for ip in ips:
            items.append({"host": ip, "port": port,
                          "remark": domain, "ip_version": _ip_ver(ip)})
        if keep_domain:
            items.append({"host": domain, "port": port,
                          "remark": "优选域名", "ip_version": 0})

    added = repository.upsert_cf_endpoints(items)
    total = repository.count_cf_endpoints()
    logger.info(f"[harvest] {len(domains)} 域名 → 解析成功 {resolved} → "
                f"{len(items)} 条端点写入 (新增 {total - before})")
    return {"domains": len(domains), "resolved_domains": resolved,
            "new_ips": max(0, total - before), "total_endpoints": total}


def _ip_ver(s: str) -> int:
    return 6 if ":" in s else 4


# ---------- CF 中转模板识别 ----------

def _ws_host(data: dict) -> str:
    ws = data.get("ws-opts") or {}
    headers = ws.get("headers") or {}
    host = headers.get("Host") or headers.get("host") or ""
    return str(host).split(":")[0]


def is_cf_relay(node_type: str, data: dict) -> bool:
    """
    判断节点是否走 Cloudflare CDN 中转：
    vless/vmess(+tls) + ws 传输 + Host/SNI 为域名 + 端口属于 CF TLS 端口集。
    这类节点把 server 替换为优选 IP 后仍可连通（CDN 按 SNI/Host 回源）。
    """
    t = (node_type or "").lower()
    if t not in ("vless", "vmess"):
        return False
    net = str(data.get("network") or data.get("net") or "tcp").lower()
    if net != "ws":
        return False
    host = _ws_host(data)
    sni = str(data.get("servername") or data.get("sni") or host)
    if not host or _is_ip(host):
        return False
    try:
        port = int(data.get("port", 0) or 0)
    except (TypeError, ValueError):
        return False
    if port not in CF_TLS_PORTS:
        return False
    # tls 可选（ws+tls 最常见; 无 tls 的 80/8080 端口不在 CF_TLS_PORTS 里）
    return bool(data.get("tls") in (True, "true", 1) or sni)


def find_cf_templates(limit_per_name: int = 5) -> List[dict]:
    """
    从节点池找出 CF 中转模板。按 (uuid/password, Host, port, 传输参数) 分组去重，
    每组取最多 limit_per_name 个代表 —— 同一机场同一入口只需少量模板。
    返回 [{id, node_name, node_type, node_data}]
    """
    with repository.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, node_name, node_type, node_data FROM nodes
               WHERE node_type IN ('vless','vmess') AND status IN ('active','unknown')
               ORDER BY COALESCE(score,0) DESC, id ASC LIMIT 4000""").fetchall()
    groups: Dict[str, dict] = {}
    counts: Dict[str, int] = {}
    for r in rows:
        data = repository._parse_node_data(r["node_data"]) or {}
        if not is_cf_relay(r["node_type"], data):
            continue
        cred = (data.get("uuid") or data.get("password") or "")
        host = _ws_host(data)
        path = str(((data.get("ws-opts") or {}).get("path")) or "")
        key = f"{r['node_type']}|{cred[:64]}|{host}|{data.get('port')}|{path[:120]}"
        counts[key] = counts.get(key, 0) + 1
        if counts[key] <= limit_per_name and key not in groups:
            groups[key] = {"id": r["id"], "node_name": r["node_name"],
                           "node_type": r["node_type"], "node_data": data}
    templates = list(groups.values())
    logger.info(f"[cf-hub] 发现 {len(templates)} 组 CF 中转模板 "
                f"(候选 {sum(counts.values())} 节点)")
    return templates


def endpoints_to_nodes(top_n: int = 50, max_per_template: int = 10,
                       isp: str = "any") -> dict:
    """
    优质优选端点 × CF 模板 → 节点变体入池。
    - 端点来源：cf_endpoints 中已检测且延迟合格(latency_ms 非空升序)，按 ISP 筛选
    - 每个模板配 top_n 个最优端点（每端点最多用于 max_per_template 个模板防刷量）
    - 变体命名：`⚡{国家码}{序号}|{模板名截断}`
    返回 {templates, variants_created, inserted}
    """
    eps = repository.get_cf_endpoints(limit=top_n * 4, isp=isp,
                                      only_alive=True, sort="latency")
    eps = [e for e in eps if e.get("latency_ms") is not None][:top_n]
    if not eps:
        return {"templates": 0, "variants_created": 0, "inserted": 0,
                "message": "无已检测存活的优选端点——请先执行统一检测"}

    templates = find_cf_templates()
    if not templates:
        return {"templates": 0, "variants_created": 0, "inserted": 0,
                "message": "节点池中没有可用的 CF 中转模板节点(vless/vmess+ws+tls)"}

    use_count: Dict[str, int] = {}
    items = []
    for tpl in templates:
        made = 0
        for e in eps:
            if made >= max_per_template:
                break
            ep_key = f"{e['host']}:{e['port']}"
            if use_count.get(ep_key, 0) >= max_per_template:
                continue
            use_count[ep_key] = use_count.get(ep_key, 0) + 1
            nd = dict(tpl["node_data"])
            old_server = str(nd.get("server", ""))
            nd["server"] = e["host"]
            nd["port"] = int(e["port"])
            name = f"⚡{e['host']}|{tpl['node_name'][:24]}"
            items.append({"subscribe_url": "", "source_id": None,
                          "node_name": name, "node_type": tpl["node_type"],
                          "node_data": nd})
            made += 1
            _ = old_server

    stats = repository.upsert_nodes_bulk(items)
    return {"templates": len(templates), "variants_created": len(items),
            "inserted": stats.get("inserted", 0),
            "updated": stats.get("updated", 0)}
