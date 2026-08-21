"""
多格式订阅生成器
支持 Clash / V2Ray / Sing-box / Base64 四种格式
"""
import base64
import json
import yaml
from typing import List
from ..schema.models import Node


def generate_clash(nodes: List[Node]) -> str:
    """生成 Clash YAML 订阅"""
    proxies = []
    for n in nodes:
        try:
            nd = json.loads(n.node_data) if isinstance(n.node_data, str) else n.node_data
        except:
            nd = {}

        p = {
            "name": n.node_name or f"node_{n.id}",
            "type": _clash_type(n.node_type),
            "server": nd.get("server", ""),
            "port": int(nd.get("port", 443)),
        }

        t = _clash_type(n.node_type)
        if t == "ss":
            p["cipher"] = nd.get("cipher", "aes-128-gcm")
            p["password"] = nd.get("password", "")
            p["udp"] = nd.get("udp", True)
        elif t == "vmess":
            p["uuid"] = nd.get("uuid", "")
            p["alterId"] = nd.get("alterId", 0)
            p["cipher"] = "auto"
            if nd.get("servername"):
                p["servername"] = nd["servername"]
        elif t == "trojan":
            p["password"] = nd.get("password", "")
            if nd.get("sni"):
                p["sni"] = nd["sni"]
            p["udp"] = True
        elif t == "hysteria2" or t == "hy2":
            p["password"] = nd.get("password", "")
            p["obfs"] = nd.get("obfs", "")
            p["obfs-password"] = nd.get("obfs-password", "")
        elif t == "vless":
            p["uuid"] = nd.get("uuid", "")
            p["flow"] = nd.get("flow", "")

        if nd.get("skip-cert-verify"):
            p["skip-cert-verify"] = True
        if nd.get("servername"):
            p["servername"] = nd["servername"]
        if n.country:
            p["country"] = n.country

        proxies.append(p)

    return yaml.dump({"proxies": proxies}, default_flow_style=False, allow_unicode=True)


def generate_v2ray(nodes: List[Node]) -> str:
    """生成 V2Ray 订阅（base64 编码的 JSON）"""
    lines = []
    for n in nodes:
        try:
            nd = json.loads(n.node_data) if isinstance(n.node_data, str) else n.node_data
        except:
            nd = {}

        server = nd.get("server", "")
        port = nd.get("port", 443)
        ptype = n.node_type.lower()

        if ptype in ("ss", "shadowsocks"):
            # ss://BASE64(method:password)@server:port#name
            method = nd.get("cipher", "aes-128-gcm")
            pwd = nd.get("password", "")
            auth = base64.b64encode(f"{method}:{pwd}".encode()).decode().strip("=")
            link = f"ss://{auth}@{server}:{port}#{n.node_name or ''}"
        elif ptype == "vmess":
            v = {
                "v": "2",
                "ps": n.node_name or "",
                "add": server,
                "port": str(port),
                "id": nd.get("uuid", ""),
                "aid": nd.get("alterId", 0),
                "net": nd.get("network", "tcp"),
                "type": nd.get("header_type", "none"),
                "host": nd.get("host", ""),
                "path": nd.get("path", ""),
                "tls": nd.get("tls", ""),
            }
            link = f"vmess://{base64.b64encode(json.dumps(v, separators=(',', ':')).encode()).decode()}"
        elif ptype == "trojan":
            pwd = nd.get("password", "")
            host = nd.get("servername", server)
            link = f"trojan://{pwd}@{server}:{port}?sni={host}#{n.node_name or ''}"
        elif ptype in ("vless",):
            uuid = nd.get("uuid", "")
            link = f"vless://{uuid}@{server}:{port}?type=tcp&security=none#{n.node_name or ''}"
        else:
            continue

        lines.append(link)

    raw = "\n".join(lines)
    return base64.b64encode(raw.encode()).decode()


def generate_singbox(nodes: List[Node]) -> str:
    """生成 Sing-box JSON 配置"""
    outbounds = []
    for n in nodes:
        try:
            nd = json.loads(n.node_data) if isinstance(n.node_data, str) else n.node_data
        except:
            nd = {}

        server = nd.get("server", "")
        port = int(nd.get("port", 443))
        ptype = n.node_type.lower()

        tag = n.node_name or f"node_{n.id}"

        if ptype in ("ss", "shadowsocks"):
            outbounds.append({
                "type": "shadowsocks",
                "tag": tag,
                "server": server,
                "server_port": port,
                "method": nd.get("cipher", "aes-128-gcm"),
                "password": nd.get("password", ""),
            })
        elif ptype == "vmess":
            outbounds.append({
                "type": "vmess",
                "tag": tag,
                "server": server,
                "server_port": port,
                "uuid": nd.get("uuid", ""),
                "security": "auto",
                "alter_id": nd.get("alterId", 0),
            })
        elif ptype == "trojan":
            outbounds.append({
                "type": "trojan",
                "tag": tag,
                "server": server,
                "server_port": port,
                "password": nd.get("password", ""),
                "tls": {"enabled": True, "server_name": nd.get("servername", server)},
            })
        elif ptype == "vless":
            outbounds.append({
                "type": "vless",
                "tag": tag,
                "server": server,
                "server_port": port,
                "uuid": nd.get("uuid", ""),
            })

    config = {
        "log": {"level": "info"},
        "outbounds": outbounds,
    }
    return json.dumps(config, indent=2, ensure_ascii=False)


def generate_base64(nodes: List[Node]) -> str:
    """生成 Base64 编码的通用订阅（多行 proxy link）"""
    lines = []
    for n in nodes:
        try:
            nd = json.loads(n.node_data) if isinstance(n.node_data, str) else n.node_data
        except:
            nd = {}

        server = nd.get("server", "")
        port = nd.get("port", 443)
        ptype = n.node_type.lower()

        if ptype in ("ss", "shadowsocks"):
            method = nd.get("cipher", "aes-128-gcm")
            pwd = nd.get("password", "")
            auth = base64.b64encode(f"{method}:{pwd}".encode()).decode().strip("=")
            link = f"ss://{auth}@{server}:{port}"
        elif ptype == "vmess":
            v = {
                "v": "2", "ps": n.node_name or "", "add": server,
                "port": str(port), "id": nd.get("uuid", ""),
                "aid": nd.get("alterId", 0), "net": "tcp",
            }
            link = f"vmess://{base64.b64encode(json.dumps(v, separators=(',', ':')).encode()).decode()}"
        elif ptype == "trojan":
            pwd = nd.get("password", "")
            host = nd.get("servername", server)
            link = f"trojan://{pwd}@{server}:{port}?sni={host}"
        elif ptype == "vless":
            uuid = nd.get("uuid", "")
            link = f"vless://{uuid}@{server}:{port}?type=tcp"
        else:
            continue

        lines.append(link)

    raw = "\n".join(lines)
    return base64.b64encode(raw.encode()).decode()


def _clash_type(node_type: str) -> str:
    """映射节点类型到 Clash 类型"""
    t = node_type.lower()
    if t in ("ss", "shadowsocks"):
        return "ss"
    if t in ("vmess",):
        return "vmess"
    if t in ("trojan",):
        return "trojan"
    if t in ("vless",):
        return "vless"
    if t in ("hysteria2", "hy2"):
        return "hysteria2"
    return "ss"