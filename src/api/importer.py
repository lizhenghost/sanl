"""
手动导入解析器：把各种格式的节点信息解析为统一的 node_data dict
支持：
  - 单节点链接: ss:// vmess:// vless:// trojan:// hysteria2:// hy2:// tuic://
  - 多行混合粘贴（逐行解析）
  - Clash YAML 片段（proxies: [...]）
  - 整段 Base64 订阅内容
"""
import base64
import json
import logging
import re
from typing import List, Tuple
from urllib.parse import urlparse, parse_qs, unquote

import yaml

logger = logging.getLogger(__name__)

SUPPORTED_PREFIXES = (
    "ss://", "vmess://", "vless://", "trojan://", "hysteria2://",
    "hy2://", "tuic://", "socks5://", "socks://", "snell://",
    "ssr://", "hysteria://", "wireguard://",
)


def _b64decode(s: str) -> bytes:
    """容错 base64 解码（自动补齐 padding / 处理 urlsafe）"""
    s = s.strip().replace("-", "+").replace("_", "/")
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.b64decode(s)


def _safe_name(fragment: str, fallback: str) -> str:
    name = unquote(fragment).strip() if fragment else ""
    return name or fallback


# ---------- 各协议解析 ----------

def parse_ss(uri: str) -> Tuple[str, dict, str]:
    """ss:// SIP002 + legacy"""
    body = uri[5:]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    # query (plugin 等，暂存)
    query = {}
    if "?" in body:
        body, qs = body.split("?", 1)
        query = parse_qs(qs)

    if "@" not in body:
        # legacy: 整段 base64(method:password@host:port[#fragment]) —— fragment 可能被一起编码
        decoded = _b64decode(body).decode()
        if "#" in decoded:
            decoded, frag2 = decoded.split("#", 1)
            frag = frag or frag2
        method, rest = decoded.split(":", 1)
        password, hostport = rest.rsplit("@", 1)
    else:
        userinfo, hostport = body.rsplit("@", 1)
        if ":" not in unquote(userinfo):  # userinfo 是 base64(method:password)
            userinfo = _b64decode(userinfo).decode()
        method, password = userinfo.split(":", 1)

    hostport = hostport.strip()  # 尾部换行/空白防御

    host, port = hostport.rsplit(":", 1)
    data = {
        "server": host.strip("[]"), "port": int(port),
        "cipher": method.strip(), "password": unquote(password),
        "udp": True,
    }
    if query.get("plugin"):
        data["plugin"] = query["plugin"][0]
    return "ss", data, _safe_name(frag, f"SS-{host}")


def parse_vmess(uri: str) -> Tuple[str, dict, str]:
    """vmess://base64(json)"""
    obj = json.loads(_b64decode(uri[8:]).decode())
    data = {
        "server": str(obj.get("add", "")), "port": int(obj.get("port", 443)),
        "uuid": obj.get("id", ""), "alterId": int(obj.get("aid", 0) or 0),
        "cipher": obj.get("scy", "auto"),
        "network": obj.get("net", "tcp"), "tls": str(obj.get("tls", "")).lower() == "tls",
    }
    if obj.get("host"): data["servername"] = obj["host"]
    if obj.get("sni"): data["sni"] = obj["sni"]
    if obj.get("path"): data["ws-path"] = obj["path"]
    name = obj.get("ps") or f"VMess-{data['server']}"
    return "vmess", data, name


def _parse_vlike_tls(query: dict, data: dict):
    """vless/trojan/hy2/tuic 共用的 query → node_data 字段"""
    q = {k: v[0] for k, v in query.items() if v}
    security = q.get("security", "")
    if security == "tls" or q.get("sni"):
        data["tls"] = True
        if q.get("sni"): data["sni"] = q["sni"]
        if q.get("host"): data["servername"] = q["host"]
    elif security == "reality":
        data["tls"] = True
        data["reality-opts"] = {k: q[k] for k in ("pbk", "sid") if k in q}
        if q.get("sni"): data["sni"] = q["sni"]
    if q.get("flow"): data["flow"] = q["flow"]
    if q.get("type") == "ws":
        data["network"] = "ws"
        if q.get("path"): data["ws-path"] = q["path"]
        if q.get("host"): data["ws-opts"] = {"headers": {"Host": q["host"]}}
    if q.get("type") == "grpc" and q.get("serviceName"):
        data["network"] = "grpc"
        data["grpc-service-name"] = q["serviceName"]
    if q.get("obfs"):
        data["obfs"] = q["obfs"]
        if q.get("obfs-password"): data["obfs-password"] = q["obfs-password"]
    if q.get("congestion_control"):
        data["congestion-controller"] = q["congestion_control"]
    if q.get("alpn"): data["alpn"] = q["alpn"].split(",")
    if q.get("fp"): data["client-fingerprint"] = q["fp"]
    data["skip-cert-verify"] = q.get("allowInsecure", "0") in ("1", "true")
    return data


def parse_vless(uri: str) -> Tuple[str, dict, str]:
    """vless://uuid@host:port?params#name"""
    body = uri[8:]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    qs = ""
    if "?" in body:
        body, qs = body.split("?", 1)
    userinfo, hostport = body.rsplit("@", 1)
    host, port = hostport.rsplit(":", 1)
    data = {
        "server": host.strip("[]"), "port": int(port),
        "uuid": unquote(userinfo), "udp": True,
    }
    _parse_vlike_tls(parse_qs(qs), data)
    return "vless", data, _safe_name(frag, f"VLESS-{host}")


def parse_trojan(uri: str) -> Tuple[str, dict, str]:
    """trojan://password@host:port?params#name"""
    body = uri[9:]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    qs = ""
    if "?" in body:
        body, qs = body.split("?", 1)
    userinfo, hostport = body.rsplit("@", 1)
    host, port = hostport.rsplit(":", 1)
    data = {
        "server": host.strip("[]"), "port": int(port),
        "password": unquote(userinfo), "udp": True,
    }
    _parse_vlike_tls(parse_qs(qs), data)
    return "trojan", data, _safe_name(frag, f"Trojan-{host}")


def parse_hysteria2(uri: str) -> Tuple[str, dict, str]:
    """hysteria2://auth@host:port?params#name"""
    body = uri.split("://", 1)[1]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    qs = ""
    if "?" in body:
        body, qs = body.split("?", 1)
    userinfo, hostport = body.rsplit("@", 1)
    host, port = hostport.rsplit(":", 1)
    data = {
        "server": host.strip("[]"), "port": int(port),
        "password": unquote(userinfo),
    }
    _parse_vlike_tls(parse_qs(qs), data)
    return "hysteria2", data, _safe_name(frag, f"Hy2-{host}")


def parse_tuic(uri: str) -> Tuple[str, dict, str]:
    """tuic://uuid:password@host:port?params#name"""
    body = uri[7:]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    qs = ""
    if "?" in body:
        body, qs = body.split("?", 1)
    userinfo, hostport = body.rsplit("@", 1)
    uuid, _, password = userinfo.partition(":")
    host, port = hostport.rsplit(":", 1)
    data = {
        "server": host.strip("[]"), "port": int(port),
        "uuid": unquote(uuid), "password": unquote(password),
    }
    _parse_vlike_tls(parse_qs(qs), data)
    return "tuic", data, _safe_name(frag, f"TUIC-{host}")


def parse_socks5(uri: str) -> Tuple[str, dict, str]:
    """socks5://[user:pass@]host:port#name"""
    body = uri.split("://", 1)[1]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    userinfo, hostport = (body.rsplit("@", 1) if "@" in body else (None, body))
    host, port = hostport.rsplit(":", 1)
    data = {"server": host.strip("[]"), "port": int(port), "udp": True}
    if userinfo:
        u, _, p = userinfo.partition(":")
        if u: data["username"] = unquote(u)
        if p: data["password"] = unquote(p)
    return "socks5", data, _safe_name(frag, f"SOCKS5-{host}")


def parse_http_proxy(uri: str) -> Tuple[str, dict, str]:
    """http://[user:pass@]host:port#name（HTTP 代理节点，host 必须是 IP 以避免误判订阅 URL）"""
    from urllib.parse import urlsplit
    u = urlsplit(uri)
    host = u.hostname or ""
    if not _is_ipv4(host):
        raise ValueError("http 代理节点 host 必须为 IP（域名型请用表单或 Clash 导入）")
    port = u.port or 80
    data = {"server": host, "port": port, "udp": False}
    if u.username: data["username"] = unquote(u.username)
    if u.password: data["password"] = unquote(u.password)
    frag = uri.split("#", 1)[1] if "#" in uri else ""
    return "http", data, _safe_name(frag, f"HTTP-{host}")


def parse_snell(uri: str) -> Tuple[str, dict, str]:
    """snell://password@host:port?psk=xxx&obfs=http#name"""
    body = uri[8:]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    qs = ""
    if "?" in body:
        body, qs = body.split("?", 1)
    userinfo, hostport = body.rsplit("@", 1)
    host, port = hostport.rsplit(":", 1)
    data = {
        "server": host.strip("[]"), "port": int(port),
        "password": unquote(userinfo), "udp": True,
    }
    q = {k: v[0] for k, v in parse_qs(qs).items() if v}
    if q.get("psk"): data["psk"] = q["psk"]
    if q.get("obfs"): data["obfs"] = q["obfs"]
    return "snell", data, _safe_name(frag, f"Snell-{host}")


def parse_ssr(uri: str) -> Tuple[str, dict, str]:
    """ssr://base64(host:port:proto:method:obfs:base64pass/?params)#name"""
    body = uri[6:]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    decoded = _b64decode(body).decode("utf-8", "ignore")
    m = re.match(r'^([^:]+):(\d+):([^:]+):([^:]+):([^:]+):([^:]+?)(?:/\?(.*))?$', decoded)
    if not m:
        raise ValueError("ssr 链接格式错误")
    host, port, proto, method, obfs, pwd_b64, param_s = m.groups()
    try:
        password = _b64decode(pwd_b64).decode("utf-8", "ignore")
    except Exception:
        password = pwd_b64
    data = {
        "server": host.strip("[]"), "port": int(port),
        "protocol": proto, "cipher": method, "obfs": obfs,
        "password": password, "udp": True,
    }
    if param_s:
        q = {k: v[0] for k, v in parse_qs(param_s).items() if v}
        if q.get("obfsparam"):
            data["obfs-param"] = _b64decode(q["obfsparam"]).decode("utf-8", "ignore")
        if q.get("protoparam"):
            data["protocol-param"] = _b64decode(q["protoparam"]).decode("utf-8", "ignore")
        if q.get("remarks"):
            frag = _b64decode(q["remarks"]).decode("utf-8", "ignore")
        if q.get("group"):
            data["group"] = _b64decode(q["group"]).decode("utf-8", "ignore")
    return "ssr", data, _safe_name(frag, f"SSR-{host}")


def parse_hysteria(uri: str) -> Tuple[str, dict, str]:
    """hysteria://host:port?protocol=udp&auth=xxx&upmbps=10&downmbps=50&insecure=1#name（Hy v1）"""
    body = uri.split("://", 1)[1]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    qs = ""
    if "?" in body:
        body, qs = body.split("?", 1)
    host, port = body.rsplit(":", 1)
    data = {"server": host.strip("[]"), "port": int(port), "udp": True}
    q = {k: v[0] for k, v in parse_qs(qs).items() if v}
    if q.get("auth"): data["auth-str"] = q["auth"]
    if q.get("upmbps"): data["up-speed"] = int(q["upmbps"])
    if q.get("downmbps"): data["down-speed"] = int(q["downmbps"])
    if q.get("protocol"): data["protocol"] = q["protocol"]
    if q.get("insecure") in ("1", "true", "yes"): data["skip-cert-verify"] = True
    if q.get("sni"): data["sni"] = q["sni"]
    return "hysteria", data, _safe_name(frag, f"Hy-{host}")


def parse_wireguard(uri: str) -> Tuple[str, dict, str]:
    """wireguard://publickey@host:port?privatekey=xxx&ip=10.0.0.2&mtu=1420#name"""
    body = uri.split("://", 1)[1]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    qs = ""
    if "?" in body:
        body, qs = body.split("?", 1)
    userinfo, hostport = (body.rsplit("@", 1) if "@" in body else ("", body))
    host, port = hostport.rsplit(":", 1)
    data = {
        "server": host.strip("[]"), "port": int(port),
        "public-key": unquote(userinfo), "udp": True,
    }
    q = {k: v[0] for k, v in parse_qs(qs).items() if v}
    if q.get("privatekey"): data["private-key"] = q["privatekey"]
    if q.get("ip"): data["ip"] = q["ip"]
    if q.get("dns"): data["dns"] = q["dns"]
    if q.get("mtu"): data["mtu"] = int(q["mtu"])
    if q.get("reserved"): data["reserved"] = q["reserved"]
    return "wireguard", data, _safe_name(frag, f"WG-{host}")


PARSERS = {
    "ss://": parse_ss, "vmess://": parse_vmess, "vless://": parse_vless,
    "trojan://": parse_trojan, "hysteria2://": parse_hysteria2,
    "hy2://": parse_hysteria2, "tuic://": parse_tuic,
    "socks5://": parse_socks5, "socks://": parse_socks5,
    "snell://": parse_snell, "ssr://": parse_ssr,
    "hysteria://": parse_hysteria, "wireguard://": parse_wireguard,
}


def _random_password(n=16):
    import secrets, string
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


def _is_ipv4(s: str) -> bool:
    import socket
    try:
        socket.inet_pton(socket.AF_INET, s)
        return True
    except OSError:
        return False


def _is_domain(s: str) -> bool:
    return bool(re.match(r'^[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(\\.[A-Za-z]{2,})+$', s))


def parse_host_port(line: str) -> Tuple[str, dict, str]:
    """解析 host:port#remark 或 host#remark（无协议前缀的 CF 优选格式）"""
    remark = ""
    if "#" in line:
        line, remark = line.split("#", 1)
    line = line.strip()
    remark = remark.strip() or f"优选-{line}"

    # 防御：URL / 协议保留字符直接拒绝
    if not line or "://" in line or "/" in line or "?" in line or " " in line:
        raise ValueError("host[:port] 格式无效")

    # host:port 或 host
    if ":" in line:
        host, port_s = line.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            host, port = line, 443
    else:
        host, port = line, 443

    if not (host and 0 < port < 65536 and _is_valid_endpoint_host(host)):
        raise ValueError("host/port 无效")

    # 构造为 trojan://random@host:port?security=tls#remark
    password = _random_password(18)
    uri = f"trojan://{password}@{host}:{port}?security=tls#{remark}"
    return parse_trojan(uri)


_DOMAIN_RE = re.compile(r'^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$', re.IGNORECASE)


import ipaddress

from ..utils.net import detect_isp as _detect_isp_shared, detect_ip_version as _detect_ipv_shared


def _is_ipv6(host: str) -> bool:
    """裸 IPv6 或 [方括号] 形式"""
    h = (host or "").strip().strip("[]")
    if ":" not in h:
        return False
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def detect_ip_version(host: str) -> int:
    """兼容别名：共享工具"""
    return _detect_ipv_shared(host)


def _is_valid_endpoint_host(host: str) -> bool:
    """CF 优选端点 host 必须是合法域名 / IPv4 / IPv6（拒绝 cf- 这类残片）"""
    if _is_ipv6(host):
        return True
    return bool(_is_ipv4(host) or _DOMAIN_RE.match(host))


# ---------- Clash YAML ----------

def _from_clash_proxies(proxies: list) -> List[Tuple[str, dict, str]]:
    """Clash proxies 列表 → 统一元组（node_data 保持 Clash 原字段）"""
    out = []
    for p in proxies or []:
        if not isinstance(p, dict) or not p.get("server"):
            continue
        ptype = str(p.get("type", "")).lower()
        name = p.pop("name", None) or f"{ptype}-{p['server']}"
        out.append((ptype, p, str(name)))
    return out


# ---------- Sing-box JSON ----------

_SBOX_TYPE_MAP = {
    "shadowsocks": "ss", "shadowsocksr": "ssr", "vmess": "vmess",
    "vless": "vless", "trojan": "trojan", "hysteria2": "hysteria2",
    "hysteria": "hysteria", "tuic": "tuic", "socks": "socks5", "http": "http",
}
_SBOX_SKIP_TYPES = {"direct", "block", "dns", "selector", "urltest", "ssh", ""}


def _from_singbox_outbounds(outbounds: list) -> List[Tuple[str, dict, str]]:
    """sing-box outbounds 列表 → 统一元组（node_data 转为 Clash 风格内部格式）"""
    out = []
    for ob in outbounds or []:
        if not isinstance(ob, dict):
            continue
        stype = str(ob.get("type", "")).lower()
        if stype in _SBOX_SKIP_TYPES or not ob.get("server"):
            continue
        ntype = _SBOX_TYPE_MAP.get(stype)
        if not ntype:
            continue
        data = {
            "server": str(ob.get("server", "")),
            "port": int(ob.get("server_port", 443) or 443),
            "udp": True,
        }
        if ntype in ("ss", "ssr"):
            data["cipher"] = ob.get("method", "aes-128-gcm")
            data["password"] = ob.get("password", "")
            if ntype == "ssr":
                data["protocol"] = ob.get("protocol", "origin")
                data["obfs"] = ob.get("obfs", "plain")
                if ob.get("obfs_param"): data["obfs-param"] = ob["obfs_param"]
                if ob.get("protocol_param"): data["protocol-param"] = ob["protocol_param"]
        elif ntype == "vmess":
            data["uuid"] = ob.get("uuid", "")
            data["alterId"] = int(ob.get("alter_id", 0) or 0)
            data["cipher"] = ob.get("security", "auto")
        elif ntype == "vless":
            data["uuid"] = ob.get("uuid", "")
            if ob.get("flow"): data["flow"] = ob["flow"]
        elif ntype in ("trojan", "hysteria2"):
            data["password"] = ob.get("password", "")
        elif ntype == "hysteria":
            data["auth-str"] = ob.get("auth_str", ob.get("password", ""))
            if ob.get("up_mbps"): data["up-speed"] = ob["up_mbps"]
            if ob.get("down_mbps"): data["down-speed"] = ob["down_mbps"]
        elif ntype == "tuic":
            data["uuid"] = ob.get("uuid", "")
            data["password"] = ob.get("password", "")
        elif ntype in ("socks5", "http"):
            if ob.get("username"): data["username"] = ob["username"]
            if ob.get("password"): data["password"] = ob["password"]
        # TLS
        tls = ob.get("tls") or {}
        if isinstance(tls, dict):
            if tls.get("enabled"):
                data["tls"] = True
            if tls.get("server_name"): data["sni"] = tls["server_name"]
            if tls.get("alpn"): data["alpn"] = tls["alpn"]
            if tls.get("insecure"): data["skip-cert-verify"] = True
            reality = tls.get("reality") or {}
            if isinstance(reality, dict) and reality.get("enabled"):
                data["reality-opts"] = {k: reality[k] for k in ("public_key", "short_id") if k in reality}
                if reality.get("public_key"):
                    data["reality-opts"]["pbk"] = reality["public_key"]
                if reality.get("short_id"):
                    data["reality-opts"]["sid"] = reality["short_id"]
        # 传输层
        tr = ob.get("transport") or {}
        if isinstance(tr, dict) and tr.get("type"):
            net = str(tr["type"]).lower()
            if net in ("ws", "http"):
                data["network"] = "ws" if net == "ws" else "h2"
                if tr.get("path"): data["ws-path"] = tr["path"]
                host = (tr.get("headers") or {}).get("Host") or tr.get("host")
                if host:
                    data["servername"] = host if isinstance(host, str) else host[0]
            elif net == "grpc":
                data["network"] = "grpc"
                if tr.get("service_name"): data["grpc-service-name"] = tr["service_name"]
        name = str(ob.get("tag", "") or f"{ntype.upper()}-{data['server']}")
        out.append((ntype, data, name))
    return out


# ---------- 总入口 ----------

def parse_content(content: str, cf_as_nodes: bool = True) -> dict:
    """
    解析任意粘贴内容，返回 {nodes: [(type, data, name)], cf_endpoints: [{host,port,remark}], errors: [str]}
    自动识别：多行链接 / Clash YAML / sing-box JSON / 整段 Base64 订阅 / host:port CF优选列表
    cf_as_nodes=False 时，CF 优选行不伪装成 trojan 节点，而是进入 cf_endpoints（池导入用）
    """
    content = (content or "").strip()
    if not content:
        return {"nodes": [], "cf_endpoints": [], "errors": ["内容为空"]}

    results, errors, cf_list = [], [], []

    # 0.5) sing-box JSON
    stripped = content.strip()
    if stripped.startswith("{") and '"outbounds"' in stripped:
        try:
            doc = json.loads(stripped)
            got = _from_singbox_outbounds(doc.get("outbounds"))
            if got:
                return {"nodes": got, "cf_endpoints": [], "errors": errors}
        except Exception as e:
            errors.append(f"sing-box JSON 解析失败: {e}")

    # 1) Clash YAML（含 proxies 键）    if "proxies:" in content:
        try:
            doc = yaml.safe_load(content)
            if isinstance(doc, dict) and doc.get("proxies"):
                got = _from_clash_proxies(doc["proxies"])
                if got:
                    return {"nodes": got, "cf_endpoints": [], "errors": errors}
        except Exception as e:
            errors.append(f"YAML 解析失败: {e}")

    # 1.1) JSON 数组（含 type+server 的对象数组）
    stripped = content.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            arr = json.loads(stripped)
            if isinstance(arr, list) and arr and all(isinstance(x, dict) and x.get("server") for x in arr):
                got = _from_clash_proxies(arr)
                if got:
                    return {"nodes": got, "cf_endpoints": [], "errors": errors}
        except Exception as e:
            errors.append(f"JSON 解析失败: {e}")

    # 2) 逐行解析
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    parsed_any = False
    for line in lines:
        low = line.lower()
        parser = next((PARSERS[p] for p in PARSERS if low.startswith(p)), None)
        if parser:
            try:
                results.append(parser(line))
                parsed_any = True
            except Exception as e:
                errors.append(f"行解析失败: {line[:40]}... ({e})")
            continue
        # 2.1) http:// 开头：IP 型视为 HTTP 代理节点，否则视为订阅 URL 跳过
        if low.startswith("http://"):
            try:
                results.append(parse_http_proxy(line))
                parsed_any = True
                continue
            except Exception:
                pass
            continue

        # 2.2) https://（整段订阅 URL）、注释、协议相对链接 → 跳过
        if low.startswith(("https://", "#", "//")):
            continue

        # 2.3) 无协议前缀的 host:port#remark / host#remark（CF 优选格式，兼容 [IPv6]:port）
        try:
            _body = line.split("#", 1)[0].strip()
            _remark = line.split("#", 1)[1].strip() if "#" in line else ""
            if _body.startswith("[") and "]" in _body:
                # [2606:4700::1111]:443 → host=2606:4700::1111
                _host = _body[1:_body.index("]")].strip()
                _rest = _body[_body.index("]") + 1:]
                _port = int(_rest.lstrip(":")) if _rest.lstrip(":").isdigit() else 443
            elif ":" in _body:
                _host, _p = _body.rsplit(":", 1)
                _port = int(_p) if _p.isdigit() else 443
            else:
                _host, _port = _body, 443
            if _is_valid_endpoint_host(_host) and 0 < _port < 65536:
                if cf_as_nodes:
                    results.append(parse_host_port(line))
                else:
                    cf_list.append({"host": _host.strip("[]"), "port": _port,
                                    "ip_version": detect_ip_version(_host),
                                    "remark": _remark or f"优选-{_host}"})
            else:
                raise ValueError("host/port 无效")
            parsed_any = True
            continue
        except Exception as e:
            errors.append(f"行解析失败: {line[:40]}... ({e})")

    if parsed_any:
        return {"nodes": results, "cf_endpoints": cf_list, "errors": errors}

    # 3) 整段 Base64 订阅
    try:
        decoded = _b64decode(content).decode("utf-8", "ignore")
        if any(decoded.strip().lower().startswith(p) for p in SUPPORTED_PREFIXES):
            inner = parse_content(decoded)
            merged_cf = cf_list + (inner.get("cf_endpoints") or [])
            return {"nodes": inner["nodes"], "cf_endpoints": merged_cf, "errors": errors + inner["errors"]}
    except Exception:
        pass

    if not results:
        if not cf_list:
            errors.append("无法识别内容格式（支持 ss/vmess/vless/trojan/hysteria2/tuic 链接、Clash/sing-box 订阅、Base64、host:port 列表）")
    return {"nodes": results, "cf_endpoints": cf_list, "errors": errors}


# ---------- 单节点表单 → URI/数据 ----------

def build_from_form(form: dict) -> Tuple[str, dict, str]:
    """
    表单式单节点导入
    form: {type, server, port, password?, uuid?, cipher?, sni?, name?}
    """
    ntype = str(form.get("type", "")).lower().strip()
    server = str(form.get("server", "")).strip()
    port = int(form.get("port") or 0)
    if not server or not (0 < port < 65536):
        raise ValueError("server/port 无效")
    name = form.get("name") or f"{ntype.upper()}-{server}"

    data = {"server": server, "port": port, "udp": True}
    if form.get("sni"): data["sni"] = form["sni"]
    if form.get("skip_cert_verify"): data["skip-cert-verify"] = True

    if ntype == "ss":
        data["cipher"] = form.get("cipher") or "aes-128-gcm"
        data["password"] = form.get("password") or ""
    elif ntype == "vmess":
        data["uuid"] = form.get("uuid") or ""
        data["alterId"] = int(form.get("alterId") or 0)
        data["cipher"] = "auto"
    elif ntype in ("vless",):
        data["uuid"] = form.get("uuid") or ""
    elif ntype in ("trojan", "hysteria2", "hy2", "hysteria"):
        data["password"] = form.get("password") or ""
        if ntype == "hysteria":
            data["auth-str"] = form.get("password") or ""
    elif ntype == "tuic":
        data["uuid"] = form.get("uuid") or ""
        data["password"] = form.get("password") or ""
    elif ntype in ("socks5", "socks"):
        if form.get("username"): data["username"] = form["username"]
        if form.get("password"): data["password"] = form["password"]
        return "socks5", data, name
    elif ntype in ("http", "https"):
        if form.get("username"): data["username"] = form["username"]
        if form.get("password"): data["password"] = form["password"]
        return "http", data, name
    elif ntype == "snell":
        data["password"] = form.get("password") or ""
        data["psk"] = form.get("psk") or form.get("password") or ""
        if form.get("obfs"): data["obfs"] = form["obfs"]
    elif ntype == "ssr":
        data["protocol"] = form.get("protocol") or "origin"
        data["cipher"] = form.get("cipher") or "aes-256-cfb"
        data["obfs"] = form.get("obfs") or "plain"
        data["password"] = form.get("password") or ""
        data["obfs-param"] = form.get("obfs_param") or ""
        data["protocol-param"] = form.get("protocol_param") or ""
    elif ntype == "wireguard":
        data["public-key"] = form.get("public_key") or ""
        data["private-key"] = form.get("private_key") or ""
        if form.get("ip"): data["ip"] = form["ip"]
        if form.get("mtu"): data["mtu"] = int(form["mtu"])
    else:
        raise ValueError(f"暂不支持类型: {ntype}")

    return ntype, data, name
