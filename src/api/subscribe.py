"""
多格式订阅生成器
支持 Clash / V2Ray(sub) / Sing-box / Base64 / Txt 五种格式
协议覆盖：ss / ssr / vmess / vless / trojan / hysteria2 / hysteria / tuic /
         socks5 / http / snell / wireguard
"""
import base64
import json
import yaml
from typing import List
from urllib.parse import quote

from ..schema.models import Node


def _nd(n: Node) -> dict:
    try:
        return json.loads(n.node_data) if isinstance(n.node_data, str) else dict(n.node_data or {})
    except Exception:
        return {}


def _cipher_of(nd, default="auto"):
    return nd.get("cipher") or nd.get("method") or default


# ============ Clash ============

def generate_clash(nodes: List[Node]) -> str:
    proxies = []
    for n in nodes:
        try:
            nd = _nd(n)
            p = {
                "name": n.node_name or f"node_{n.id}",
                "type": _clash_type(n.node_type),
                "server": nd.get("server", ""),
                "port": int(nd.get("port", 443)),
            }
            t = p["type"]

            if t in ("ss", "ssr"):
                p["cipher"] = _cipher_of(nd, "aes-128-gcm")
                p["password"] = nd.get("password", "")
                p["udp"] = bool(nd.get("udp", True))
                if t == "ssr":
                    p["obfs"] = nd.get("obfs", "plain")
                    p["protocol"] = nd.get("protocol", "origin")
                    p["obfs-param"] = nd.get("obfs-param", "")
                    p["protocol-param"] = nd.get("protocol-param", "")
                    if nd.get("group"): p["group"] = nd["group"]
            elif t == "vmess":
                p["uuid"] = nd.get("uuid", "")
                p["alterId"] = int(nd.get("alterId", 0) or 0)
                p["cipher"] = "auto"
                _clash_transport(nd, p)
                if nd.get("udp") is not False: p["udp"] = True
            elif t == "vless":
                p["uuid"] = nd.get("uuid", "")
                p["flow"] = nd.get("flow", "")
                p["udp"] = True
                _clash_transport(nd, p)
            elif t == "trojan":
                p["password"] = nd.get("password", "")
                p["udp"] = True
                if nd.get("sni") or nd.get("servername"):
                    p["sni"] = nd.get("sni") or nd.get("servername")
                _clash_transport(nd, p)
            elif t in ("hysteria2",):
                p["password"] = nd.get("password", "")
                if nd.get("obfs"): p["obfs"] = nd["obfs"]
                if nd.get("obfs-password"): p["obfs-password"] = nd["obfs-password"]
                if nd.get("up-speed"): p["up"] = str(nd["up-speed"])
                if nd.get("down-speed"): p["down"] = str(nd["down-speed"])
            elif t == "hysteria":
                p["auth-str"] = nd.get("auth-str", nd.get("password", ""))
                if nd.get("up-speed"): p["up"] = str(nd["up-speed"])
                if nd.get("down-speed"): p["down"] = str(nd["down-speed"])
                if nd.get("obfs"): p["obfs"] = nd["obfs"]
                if nd.get("alpn"): p["alpn"] = nd["alpn"]
            elif t == "tuic":
                p["uuid"] = nd.get("uuid", "")
                p["password"] = nd.get("password", "")
                if nd.get("congestion-controller"): p["congestion-controller"] = nd["congestion-controller"]
                if nd.get("alpn"): p["alpn"] = nd["alpn"]
                p["reduce-rtt"] = bool(nd.get("reduce-rtt", False))
            elif t == "socks5":
                if nd.get("username"): p["username"] = nd["username"]
                if nd.get("password"): p["password"] = nd["password"]
                p["udp"] = bool(nd.get("udp", True))
            elif t == "http":
                if nd.get("username"): p["username"] = nd["username"]
                if nd.get("password"): p["password"] = nd["password"]
                if nd.get("tls"): p["tls"] = True
            elif t == "snell":
                p["psk"] = nd.get("psk", nd.get("password", ""))
                p["obfs"] = nd.get("obfs", "plain")
                if nd.get("version"): p["version"] = nd["version"]
            elif t == "wireguard":
                p["private-key"] = nd.get("private-key", "")
                p["ip"] = nd.get("ip", "")
                if nd.get("dns"): p["dns"] = nd["dns"]
                if nd.get("mtu"): p["mtu"] = nd["mtu"]
                p["udp"] = True

            _clash_tls(nd, p)
            if n.country:
                p["country"] = n.country
            proxies.append(p)
        except Exception as e:
            continue

    return yaml.dump({"proxies": proxies}, default_flow_style=False, allow_unicode=True)


def _clash_transport(nd: dict, p: dict):
    """vmess/vless/trojan 的传输层（ws/grpc/h2/tcp）"""
    net = nd.get("network", "tcp")
    p["network"] = net
    if net == "ws":
        wso = {}
        if nd.get("ws-path") or nd.get("path"):
            wso["path"] = nd.get("ws-path") or nd.get("path")
        host = nd.get("servername") or nd.get("host") or nd.get("ws-host")
        if host:
            wso["headers"] = {"Host": host}
        if wso:
            p["ws-opts"] = wso
    elif net == "grpc":
        g = {}
        if nd.get("grpc-service-name"):
            g["grpc-service-name"] = nd["grpc-service-name"]
        if g:
            p["grpc-opts"] = g
    elif net == "h2":
        h2 = {}
        if nd.get("ws-path") or nd.get("path"):
            h2["path"] = nd.get("ws-path") or nd.get("path")
        host = nd.get("servername") or nd.get("host")
        if host:
            h2["host"] = [host]
        if h2:
            p["h2-opts"] = h2
    elif net == "http" and nd.get("path"):
        p["http-opts"] = {"path": [nd["path"]]}


def _clash_tls(nd: dict, p: dict):
    """TLS / REALITY / SNI 通用字段"""
    tls = nd.get("tls") or nd.get("security") == "tls" or nd.get("security") == "reality" or nd.get("servername") or nd.get("sni")
    if tls or p.get("type") in ("trojan", "hysteria2", "hysteria", "tuic"):
        p["tls"] = True
    if nd.get("sni"):
        p["servername"] = nd["sni"]
    elif nd.get("servername"):
        p["servername"] = nd["servername"]
    if nd.get("skip-cert-verify"):
        p["skip-cert-verify"] = True
    if nd.get("alpn"):
        p["alpn"] = nd["alpn"] if isinstance(nd["alpn"], list) else [nd["alpn"]]
    if nd.get("client-fingerprint"):
        p["client-fingerprint"] = nd["client-fingerprint"]
    if nd.get("reality-opts"):
        p["reality-opts"] = nd["reality-opts"]


# ============ Links（v2ray/base64/txt 共用） ============

def generate_links(nodes: List[Node]) -> str:
    """生成多行标准 URI"""
    lines = []
    for n in nodes:
        try:
            link = _to_link(n)
            if link:
                name = n.node_name or ""
                lines.append(f"{link}#{quote(name)}" if name else link)
        except Exception:
            continue
    return "\n".join(lines)


def _to_link(n: Node) -> str:
    nd = _nd(n)
    server = nd.get("server", "")
    port = nd.get("port", 443)
    ptype = n.node_type.lower()
    name = n.node_name or ""

    if ptype in ("ss", "shadowsocks"):
        auth = base64.b64encode(f"{_cipher_of(nd, 'aes-128-gcm')}:{nd.get('password','')}".encode()).decode().strip("=")
        return f"ss://{auth}@{server}:{port}"
    if ptype == "ssr":
        pwd_b64 = base64.b64encode(nd.get("password", "").encode()).decode().strip("=")
        core = f"{server}:{port}:{nd.get('protocol','origin')}:{_cipher_of(nd,'aes-256-cfb')}:{nd.get('obfs','plain')}:{pwd_b64}"
        params = []
        if nd.get("obfs-param"):
            params.append(f"obfsparam={base64.b64encode(nd['obfs-param'].encode()).decode()}")
        if nd.get("protocol-param"):
            params.append(f"protoparam={base64.b64encode(nd['protocol-param'].encode()).decode()}")
        if name:
            params.append(f"remarks={base64.b64encode(name.encode()).decode()}")
        if params:
            core += "/?" + "&".join(params)
        return f"ssr://{base64.b64encode(core.encode()).decode().strip('=')}"
    if ptype == "vmess":
        v = {
            "v": "2", "ps": name, "add": server, "port": str(port),
            "id": nd.get("uuid", ""), "aid": int(nd.get("alterId", 0) or 0),
            "net": nd.get("network", "tcp"),
            "type": "none", "host": "", "path": "",
        }
        tls = nd.get("tls") or nd.get("security") == "tls"
        v["tls"] = "tls" if tls else ""
        if nd.get("ws-path") or nd.get("path"):
            v["path"] = nd.get("ws-path") or nd.get("path")
        if nd.get("servername") or nd.get("host"):
            v["host"] = nd.get("servername") or nd.get("host")
        if nd.get("sni"):
            v["sni"] = nd["sni"]
        return f"vmess://{base64.b64encode(json.dumps(v, separators=(',', ':')).encode()).decode()}"
    if ptype == "vless":
        qs = {}
        if nd.get("network"): qs["type"] = nd["network"]
        qs["security"] = "reality" if nd.get("reality-opts") else ("tls" if nd.get("tls") or nd.get("servername") else "none")
        if nd.get("sni"): qs["sni"] = nd["sni"]
        if nd.get("servername") and "sni" not in qs: qs["sni"] = nd["servername"]
        if nd.get("flow"): qs["flow"] = nd["flow"]
        if nd.get("ws-path") or nd.get("path"): qs["path"] = nd.get("ws-path") or nd.get("path")
        if nd.get("host"): qs["host"] = nd["host"]
        if nd.get("grpc-service-name"): qs["serviceName"] = nd["grpc-service-name"]
        if nd.get("reality-opts"):
            for k in ("pbk", "sid"):
                if k in nd["reality-opts"]: qs[k] = nd["reality-opts"][k]
        if nd.get("alpn"): qs["alpn"] = ",".join(nd["alpn"]) if isinstance(nd["alpn"], list) else nd["alpn"]
        q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
        return f"vless://{nd.get('uuid','')}@{server}:{port}?{q}" if q else f"vless://{nd.get('uuid','')}@{server}:{port}"
    if ptype == "trojan":
        qs = {}
        if nd.get("sni"): qs["sni"] = nd["sni"]
        elif nd.get("servername"): qs["sni"] = nd["servername"]
        if nd.get("network") == "ws":
            qs["type"] = "ws"
            if nd.get("ws-path") or nd.get("path"): qs["path"] = nd.get("ws-path") or nd.get("path")
            if nd.get("servername") or nd.get("host"): qs["host"] = nd.get("servername") or nd.get("host")
        if nd.get("skip-cert-verify"): qs["allowInsecure"] = "1"
        q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
        return f"trojan://{nd.get('password','')}@{server}:{port}" + (f"?{q}" if q else "")
    if ptype in ("hysteria2", "hy2"):
        qs = {"security": "tls", "sni": nd.get("sni") or nd.get("servername") or server}
        if nd.get("obfs"): qs["obfs"] = nd["obfs"]
        if nd.get("obfs-password"): qs["obfs-password"] = nd["obfs-password"]
        if nd.get("up-speed"): qs["upmbps"] = nd["up-speed"]
        if nd.get("down-speed"): qs["downmbps"] = nd["down-speed"]
        if nd.get("skip-cert-verify"): qs["insecure"] = "1"
        q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
        return f"hysteria2://{nd.get('password','')}@{server}:{port}?{q}"
    if ptype == "hysteria":
        qs = {"protocol": nd.get("protocol", "udp"), "auth": nd.get("auth-str", nd.get("password", ""))}
        if nd.get("up-speed"): qs["upmbps"] = nd["up-speed"]
        if nd.get("down-speed"): qs["downmbps"] = nd["down-speed"]
        if nd.get("sni"): qs["sni"] = nd["sni"]
        if nd.get("skip-cert-verify"): qs["insecure"] = "1"
        q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
        return f"hysteria://{server}:{port}?{q}"
    if ptype == "tuic":
        qs = {}
        if nd.get("sni"): qs["sni"] = nd["sni"]
        elif nd.get("servername"): qs["sni"] = nd["servername"]
        if nd.get("congestion-controller"): qs["congestion_control"] = nd["congestion-controller"]
        if nd.get("alpn"):
            alpn = nd["alpn"] if isinstance(nd["alpn"], list) else [nd["alpn"]]
            qs["alpn"] = ",".join(alpn)
        q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
        return f"tuic://{nd.get('uuid','')}:{nd.get('password','')}@{server}:{port}" + (f"?{q}" if q else "")
    if ptype in ("socks5", "socks"):
        userinfo = ""
        if nd.get("username"):
            userinfo = f"{quote(nd['username'])}:{quote(nd.get('password',''))}@" if nd.get("password") else f"{quote(nd['username'])}@"
        return f"socks5://{userinfo}{server}:{port}"
    if ptype == "http":
        userinfo = ""
        if nd.get("username"):
            userinfo = f"{quote(nd['username'])}:{quote(nd.get('password',''))}@"
        return f"http://{userinfo}{server}:{port}"
    if ptype == "snell":
        qs = {}
        if nd.get("psk"): qs["psk"] = nd["psk"]
        elif nd.get("password"): qs["psk"] = nd["password"]
        if nd.get("obfs"): qs["obfs"] = nd["obfs"]
        q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
        return f"snell://{nd.get('password', nd.get('psk',''))}@{server}:{port}" + (f"?{q}" if q else "")
    if ptype == "wireguard":
        qs = {}
        if nd.get("private-key"): qs["privateKey"] = nd["private-key"]
        if nd.get("ip"): qs["ip"] = nd["ip"]
        if nd.get("dns"): qs["dns"] = nd["dns"]
        if nd.get("mtu"): qs["mtu"] = nd["mtu"]
        q = "&".join(f"{k}={v}" for k, v in qs.items() if v)
        return f"wireguard://{nd.get('public-key','')}@{server}:{port}" + (f"?{q}" if q else "")
    return ""


# ============ V2Ray / Base64 / Txt ============

def generate_v2ray(nodes: List[Node]) -> str:
    return base64.b64encode(generate_links(nodes).encode()).decode()


def generate_base64(nodes: List[Node]) -> str:
    return base64.b64encode(generate_links(nodes).encode()).decode()


def generate_txt(nodes: List[Node]) -> str:
    return generate_links(nodes)


# ============ Sing-box ============

def generate_singbox(nodes: List[Node]) -> str:
    outbounds = []
    for n in nodes:
        try:
            nd = _nd(n)
            server = nd.get("server", "")
            port = int(nd.get("port", 443))
            ptype = n.node_type.lower()
            tag = n.node_name or f"node_{n.id}"

            if ptype in ("ss", "shadowsocks"):
                outbounds.append({
                    "type": "shadowsocks", "tag": tag, "server": server,
                    "server_port": port, "method": _cipher_of(nd, "aes-128-gcm"),
                    "password": nd.get("password", ""),
                })
            elif ptype == "ssr":
                ob = {
                    "type": "shadowsocksr", "tag": tag, "server": server,
                    "server_port": port, "method": _cipher_of(nd, "aes-256-cfb"),
                    "password": nd.get("password", ""),
                }
                if nd.get("obfs"): ob["obfs"] = nd["obfs"]
                if nd.get("protocol"): ob["protocol"] = nd["protocol"]
                if nd.get("obfs-param"): ob["obfs_param"] = nd["obfs-param"]
                if nd.get("protocol-param"): ob["protocol_param"] = nd["protocol-param"]
                outbounds.append(ob)
            elif ptype == "vmess":
                ob = {
                    "type": "vmess", "tag": tag, "server": server,
                    "server_port": port, "uuid": nd.get("uuid", ""),
                    "security": "auto", "alter_id": int(nd.get("alterId", 0) or 0),
                }
                _sbox_transport(nd, ob)
                outbounds.append(ob)
            elif ptype == "vless":
                ob = {
                    "type": "vless", "tag": tag, "server": server,
                    "server_port": port, "uuid": nd.get("uuid", ""),
                }
                _sbox_transport(nd, ob)
                _sbox_tls(nd, ob)
                outbounds.append(ob)
            elif ptype == "trojan":
                ob = {
                    "type": "trojan", "tag": tag, "server": server,
                    "server_port": port, "password": nd.get("password", ""),
                }
                _sbox_transport(nd, ob)
                _sbox_tls(nd, ob)
                outbounds.append(ob)
            elif ptype in ("hysteria2", "hy2"):
                ob = {
                    "type": "hysteria2", "tag": tag, "server": server,
                    "server_port": port, "password": nd.get("password", ""),
                }
                if nd.get("obfs"): ob["obfs"] = {"type": nd["obfs"], "password": nd.get("obfs-password", "")}
                _sbox_tls(nd, ob)
                outbounds.append(ob)
            elif ptype == "hysteria":
                ob = {
                    "type": "hysteria", "tag": tag, "server": server,
                    "server_port": port, "up_mbps": int(nd.get("up-speed", 0) or 0),
                    "down_mbps": int(nd.get("down-speed", 0) or 0),
                    "auth_str": nd.get("auth-str", nd.get("password", "")),
                }
                _sbox_tls(nd, ob)
                outbounds.append(ob)
            elif ptype == "tuic":
                ob = {
                    "type": "tuic", "tag": tag, "server": server,
                    "server_port": port, "uuid": nd.get("uuid", ""),
                    "password": nd.get("password", ""),
                }
                _sbox_tls(nd, ob)
                outbounds.append(ob)
            elif ptype in ("socks5", "socks"):
                ob = {"type": "socks", "tag": tag, "server": server, "server_port": port}
                if nd.get("username"):
                    ob["username"] = nd["username"]
                    ob["password"] = nd.get("password", "")
                outbounds.append(ob)
            elif ptype == "http":
                ob = {"type": "http", "tag": tag, "server": server, "server_port": port}
                if nd.get("username"):
                    ob["username"] = nd["username"]
                    ob["password"] = nd.get("password", "")
                _sbox_tls(nd, ob)
                outbounds.append(ob)
            elif ptype == "wireguard":
                ob = {
                    "type": "wireguard", "tag": tag, "server": server,
                    "server_port": port, "local_address": [nd.get("ip", "")],
                    "private_key": nd.get("private-key", ""),
                    "peer_public_key": nd.get("public-key", ""),
                }
                if nd.get("mtu"): ob["mtu"] = nd["mtu"]
                outbounds.append(ob)
        except Exception:
            continue

    return json.dumps({
        "log": {"level": "info"},
        "outbounds": outbounds,
    }, indent=2, ensure_ascii=False)


def _sbox_transport(nd: dict, ob: dict):
    net = nd.get("network", "tcp")
    sno = {"type": net}
    if net in ("ws", "http"):
        if nd.get("ws-path") or nd.get("path"):
            sno["path"] = nd.get("ws-path") or nd.get("path")
        host = nd.get("servername") or nd.get("host")
        if host:
            sno["headers"] = {"Host": host}
    elif net == "grpc":
        if nd.get("grpc-service-name"):
            sno["service_name"] = nd["grpc-service-name"]
    ob["transport"] = sno


def _sbox_tls(nd: dict, ob: dict):
    tls = nd.get("tls") or nd.get("security") in ("tls", "reality") or nd.get("servername") or nd.get("sni") or otype_tls(ob.get("type"))
    if tls:
        to = {}
        if nd.get("sni"): to["server_name"] = nd["sni"]
        elif nd.get("servername"): to["server_name"] = nd["servername"]
        if nd.get("alpn"): to["alpn"] = nd["alpn"] if isinstance(nd["alpn"], list) else [nd["alpn"]]
        if nd.get("skip-cert-verify"): to["insecure"] = True
        if nd.get("reality-opts"):
            to["reality"] = {"enabled": True, "public_key": nd["reality-opts"].get("pbk", ""), "short_id": nd["reality-opts"].get("sid", "")}
        ob["tls"] = to


def otype_tls(t: str) -> bool:
    return t in ("trojan", "hysteria2", "hysteria", "tuic", "http", "vless")


# ============ 类型映射 ============

def _clash_type(node_type: str) -> str:
    t = node_type.lower()
    if t in ("ss", "shadowsocks"): return "ss"
    if t in ("ssr", "shadowsocksr"): return "ssr"
    if t == "vmess": return "vmess"
    if t == "vless": return "vless"
    if t == "trojan": return "trojan"
    if t in ("hysteria2", "hy2"): return "hysteria2"
    if t == "hysteria": return "hysteria"
    if t == "tuic": return "tuic"
    if t in ("socks5", "socks"): return "socks5"
    if t == "http": return "http"
    if t == "snell": return "snell"
    if t == "wireguard": return "wireguard"
    return "ss"