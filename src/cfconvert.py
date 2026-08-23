"""C4：CF 优选端点 → 可用代理节点转换器（优选订阅转换的数据底座）。

原理（行业通行做法，实现自主）：
- 「优选」的本质：vless/vmess+ws(+tls) 流量经 Cloudflare CDN 中转，回源由 Host/SNI 头决定，
  因此把节点的连接地址(server)替换为测速更优的 CF 优选 IP/域名，其余参数保持模板原样，
  即得到一个「同后端、更快入口」的新节点。
- 模板来源：池内评分最高的 ws 节点（自动），或用户指定节点（template_id）。
- 产物入库 source_type='cf-convert'，随后参与统一测速管线（C2），合格者进入优选订阅（C3）。
"""
import json
import logging
from typing import List, Optional

from .schema import repository

logger = logging.getLogger(__name__)

# CF CDN 支持的标准 TLS 端口（优选替换时端口保持模板端口，仅当模板端口非 CF 端口时用 443）
_CF_TLS_PORTS = {443, 2053, 2083, 2087, 2096, 8443}


def find_ws_template(template_id: Optional[int] = None) -> Optional[dict]:
    """挑选 ws+tls 模板节点：优先指定 id，否则取评分最高的 vless/vmess+ws 节点。

    返回 {node_id, node_type, node_data(dict), name}
    """
    with repository.get_connection() as conn:
        if template_id:
            row = conn.execute(
                "SELECT id, node_type, node_data, node_name FROM nodes WHERE id = ?",
                (template_id,)).fetchone()
        else:
            row = conn.execute(
                """SELECT id, node_type, node_data, node_name FROM nodes
                   WHERE node_type IN ('vless','vmess')
                     AND (node_data LIKE '%"network": "ws"%' OR node_data LIKE '%"network":"ws"%')
                     AND status = 'active'
                   ORDER BY score DESC, latency IS NULL, latency ASC LIMIT 1""").fetchone()
            if not row:  # 池内暂无 active ws 节点时放宽
                row = conn.execute(
                    """SELECT id, node_type, node_data, node_name FROM nodes
                       WHERE node_type IN ('vless','vmess')
                         AND (node_data LIKE '%"network": "ws"%' OR node_data LIKE '%"network":"ws"%')
                       ORDER BY score DESC LIMIT 1""").fetchone()
        if not row:
            return None
        return {"node_id": row["id"], "node_type": row["node_type"],
                "node_data": json.loads(row["node_data"]), "name": row["node_name"]}


def build_from_template(tpl: dict, endpoints: List[dict], *,
                        rename_prefix: str = "CF") -> List[dict]:
    """把优选端点套进 ws 模板生成新节点（upsert_nodes_bulk 的 item 格式）。"""
    base = tpl["node_data"]
    tpl_type = tpl["node_type"]
    ws_opts = base.get("ws-opts") or {}
    host = (ws_opts.get("headers") or {}).get("Host") or base.get("servername") or base.get("sni") or base["server"]
    sni = base.get("servername") or base.get("sni") or host
    path = ws_opts.get("path", "/")
    port = int(base.get("port", 443))
    if port not in _CF_TLS_PORTS:
        port = 443
    tls = bool(base.get("tls", True))

    items = []
    for ep in endpoints:
        ehost = str(ep.get("host") or "").strip()
        if not ehost:
            continue
        nd = {
            "server": ehost,
            "port": port,
            "network": "ws",
            "tls": tls,
            "servername": sni,
            "ws-opts": {"path": path, "headers": {"Host": host}},
            "skip-cert-verify": bool(base.get("skip-cert-verify", False)),
        }
        if tpl_type == "vmess":
            nd["uuid"] = base.get("uuid", "")
            nd["alterId"] = int(base.get("alterId", 0) or 0)
            nd["cipher"] = base.get("cipher", "auto")
        else:  # vless
            nd["uuid"] = base.get("uuid", "")
            if base.get("flow"):
                nd["flow"] = base["flow"]
        latency = ep.get("latency_ms")
        tag = f"{latency}ms" if latency else "opt"
        items.append({
            "subscribe_url": f"cf-convert://{tpl['node_id']}",
            "source_id": None,
            "node_name": f"{rename_prefix}_{ehost}|{tag}",
            "node_type": tpl_type,
            "node_data": nd,
        })
    return items


def convert(count: int = 50, isp: Optional[str] = None,
            template_id: Optional[int] = None) -> dict:
    """主入口：模板 + 优质端点 → 批量入库。返回统计。"""
    tpl = find_ws_template(template_id)
    if not tpl:
        return {"ok": False, "error": "池内未找到可用的 vless/vmess+ws 模板节点"}

    endpoints = repository.get_cf_endpoints(limit=max(1, min(count, 2000)),
                                            isp=isp, sort="latency", only_alive=True)
    if not endpoints:
        return {"ok": False, "error": "cf_endpoints 无已测速的优选端点（先执行 CF 扫描/测速）"}

    items = build_from_template(tpl, endpoints)
    stat = repository.upsert_nodes_bulk(items)
    logger.info(f"[cf-convert] 模板#{tpl['node_id']}({tpl['node_type']}) × {len(items)} 端点 → {stat}")
    return {"ok": True, "template": {"id": tpl["node_id"], "type": tpl["node_type"],
                                     "name": tpl["name"]},
            "generated": len(items), **stat}
