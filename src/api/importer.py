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

SUPPORTED_PREFIXES = ("ss://", "vmess://", "vless://", "trojan://", "hysteria2://", "hy2://", "tuic://")


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
        # legacy: 整段 base64(method:password@host:port)
        decoded = _b64decode(body).decode()
        method, rest = decoded.split(":", 1)
        password, hostport = rest.rsplit("@", 1)
    else:
        userinfo, hostport = body.rsplit("@", 1)
        if ":" not in unquote(userinfo):  # userinfo 是 base64(method:password)
            userinfo = _b64decode(userinfo).decode()
        method, password = userinfo.split(":", 1)

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


PARSERS = {
    "ss://": parse_ss, "vmess://": parse_vmess, "vless://": parse_vless,
    "trojan://": parse_trojan, "hysteria2://": parse_hysteria2,
    "hy2://": parse_hysteria2, "tuic://": parse_tuic,
}


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


# ---------- 总入口 ----------

def parse_content(content: str) -> dict:
    """
    解析任意粘贴内容，返回 {nodes: [(type, data, name)], errors: [str]}
    自动识别：多行链接 / Clash YAML / 整段 Base64 订阅
    """
    content = (content or "").strip()
    if not content:
        return {"nodes": [], "errors": ["内容为空"]}

    results, errors = [], []

    # 1) Clash YAML（含 proxies 键）
    if "proxies:" in content:
        try:
            doc = yaml.safe_load(content)
            if isinstance(doc, dict) and doc.get("proxies"):
                got = _from_clash_proxies(doc["proxies"])
                if got:
                    return {"nodes": got, "errors": errors}
        except Exception as e:
            errors.append(f"YAML 解析失败: {e}")

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

    if parsed_any:
        return {"nodes": results, "errors": errors}

    # 3) 整段 Base64 订阅
    try:
        decoded = _b64decode(content).decode("utf-8", "ignore")
        if any(decoded.strip().lower().startswith(p) for p in SUPPORTED_PREFIXES):
            inner = parse_content(decoded)
            return {"nodes": inner["nodes"], "errors": errors + inner["errors"]}
    except Exception:
        pass

    if not results:
        errors.append("无法识别内容格式（支持 ss/vmess/vless/trojan/hysteria2/tuic 链接、Clash YAML、Base64 订阅）")
    return {"nodes": results, "errors": errors}


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
    elif ntype in ("trojan", "hysteria2", "hy2"):
        data["password"] = form.get("password") or ""
    elif ntype == "tuic":
        data["uuid"] = form.get("uuid") or ""
        data["password"] = form.get("password") or ""
    else:
        raise ValueError(f"暂不支持类型: {ntype}")

    return ntype, data, name
