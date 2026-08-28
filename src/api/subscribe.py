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
            if n.country_code:
                p["country_code"] = n.country_code
            proxies.append(p)
        except Exception as e:
            continue

    # libyaml CSafeDumper：5000 节点序列化 650ms→133ms（约 5 倍）；无 libyaml 时回退纯 Python
    _dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
    return yaml.dump(_clash_full_config(proxies), Dumper=_dumper,
                     default_flow_style=False, allow_unicode=True, sort_keys=False)


def _clash_full_config(proxies: list) -> dict:
    """补全 Clash 配置：proxies + proxy-groups + rules + dns。
    增强：DNS 防污染(fake-ip) + AI 解锁 + 流媒体分流 + 广告拦截 + 国内直连。"""

    names, seen = [], set()
    for p in proxies:
        nm = p.get("name", "")
        if nm and nm not in seen:
            seen.add(nm)
            names.append(nm)
    if not names:
        return {"proxies": proxies}

    # ---- 按国家分组 ----
    groups_by_country = {}
    for p in proxies:
        c = _country_label((p.get("country") or "其他节点").strip(), p.get("country_code"))
        groups_by_country.setdefault(c, []).append(p["name"])
    country_names = list(groups_by_country.keys())

    # ---- 策略组 ----
    proxy_groups = [
        {"name": "🚀 节点选择", "type": "select",
         "proxies": ["🚀 自动选择", "🤖 AI 解锁", "🎬 流媒体", "♻️ 故障转移"] + country_names + ["DIRECT"]},
        {"name": "🚀 自动选择", "type": "url-test",
         "url": "http://www.gstatic.com/generate_204", "interval": 300, "tolerance": 50, "proxies": names},
        {"name": "♻️ 故障转移", "type": "fallback",
         "url": "http://www.gstatic.com/generate_204", "interval": 300, "proxies": names},
        {"name": "🤖 AI 解锁", "type": "select",
         "proxies": ["🚀 自动选择"] + [g for g in country_names if g in ("美国","日本","新加坡","英国","德国")] + names[:20]},
        {"name": "🎬 流媒体", "type": "select",
         "proxies": ["🚀 自动选择"] + country_names + names[:20]},
    ]
    for cname, nodelist in groups_by_country.items():
        proxy_groups.append({"name": cname, "type": "select", "proxies": ["🚀 自动选择","DIRECT"] + nodelist})

    # ---- 规则集（从上到下，先匹配先生效）----
    rules = [
        # 广告拦截
        "DOMAIN-SUFFIX,adnxs.com,REJECT","DOMAIN-SUFFIX,doubleclick.net,REJECT",
        "DOMAIN-SUFFIX,googlesyndication.com,REJECT","DOMAIN-SUFFIX,google-analytics.com,REJECT",
        "DOMAIN-SUFFIX,googletagmanager.com,REJECT","DOMAIN-KEYWORD,adsense,REJECT",
        # 本地/局域网
        "DOMAIN-SUFFIX,local,DIRECT","IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
        "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve","IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
        "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve","IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
        # AI 平台
        "DOMAIN-SUFFIX,openai.com,🤖 AI 解锁","DOMAIN-SUFFIX,chatgpt.com,🤖 AI 解锁",
        "DOMAIN-SUFFIX,oaistatic.com,🤖 AI 解锁","DOMAIN-SUFFIX,oaiusercontent.com,🤖 AI 解锁",
        "DOMAIN-SUFFIX,anthropic.com,🤖 AI 解锁","DOMAIN-SUFFIX,claude.ai,🤖 AI 解锁",
        "DOMAIN-SUFFIX,gemini.google.com,🤖 AI 解锁","DOMAIN-SUFFIX,bard.google.com,🤖 AI 解锁",
        "DOMAIN-SUFFIX,copilot.microsoft.com,🤖 AI 解锁","DOMAIN-SUFFIX,perplexity.ai,🤖 AI 解锁",
        "DOMAIN-SUFFIX,huggingface.co,🤖 AI 解锁","DOMAIN-SUFFIX,midjourney.com,🤖 AI 解锁",
        "DOMAIN-SUFFIX,stability.ai,🤖 AI 解锁","DOMAIN-KEYWORD,openai,🤖 AI 解锁",
        # 流媒体
        "DOMAIN-SUFFIX,netflix.com,🎬 流媒体","DOMAIN-SUFFIX,nflxvideo.net,🎬 流媒体",
        "DOMAIN-KEYWORD,netflix,🎬 流媒体","DOMAIN-SUFFIX,youtube.com,🎬 流媒体",
        "DOMAIN-SUFFIX,googlevideo.com,🎬 流媒体","DOMAIN-SUFFIX,ytimg.com,🎬 流媒体",
        "DOMAIN-SUFFIX,disneyplus.com,🎬 流媒体","DOMAIN-KEYWORD,disney,🎬 流媒体",
        "DOMAIN-SUFFIX,hbomax.com,🎬 流媒体","DOMAIN-SUFFIX,primevideo.com,🎬 流媒体",
        "DOMAIN-SUFFIX,spotify.com,🎬 流媒体","DOMAIN-KEYWORD,tiktok,🎬 流媒体",
        "DOMAIN-SUFFIX,bilibili.tv,🎬 流媒体",
        # 国内直连
        "DOMAIN-SUFFIX,cn,DIRECT","DOMAIN-SUFFIX,qq.com,DIRECT",
        "DOMAIN-SUFFIX,weixin.com,DIRECT","DOMAIN-SUFFIX,taobao.com,DIRECT",
        "DOMAIN-SUFFIX,jd.com,DIRECT","DOMAIN-SUFFIX,baidu.com,DIRECT",
        "DOMAIN-SUFFIX,bilibili.com,DIRECT","DOMAIN-SUFFIX,douyin.com,DIRECT",
        "DOMAIN-SUFFIX,163.com,DIRECT","DOMAIN-SUFFIX,alipay.com,DIRECT",
        "DOMAIN-SUFFIX,aliyun.com,DIRECT","DOMAIN-SUFFIX,alicdn.com,DIRECT",
        "DOMAIN-SUFFIX,weibo.com,DIRECT","DOMAIN-SUFFIX,zhihu.com,DIRECT",
        "DOMAIN-SUFFIX,xiaomi.com,DIRECT","DOMAIN-SUFFIX,myqcloud.com,DIRECT",
        "GEOIP,CN,DIRECT",
        # 常被墙服务
        "DOMAIN-SUFFIX,google.com,🚀 节点选择","DOMAIN-SUFFIX,googleapis.com,🚀 节点选择",
        "DOMAIN-SUFFIX,telegram.org,🚀 节点选择","DOMAIN-SUFFIX,t.me,🚀 节点选择",
        "DOMAIN-KEYWORD,telegram,🚀 节点选择",
        "DOMAIN-SUFFIX,github.com,🚀 节点选择","DOMAIN-SUFFIX,githubusercontent.com,🚀 节点选择",
        "DOMAIN-SUFFIX,wikipedia.org,🚀 节点选择","DOMAIN-SUFFIX,reddit.com,🚀 节点选择",
        "DOMAIN-SUFFIX,x.com,🚀 节点选择","DOMAIN-SUFFIX,twimg.com,🚀 节点选择",
        "DOMAIN-SUFFIX,facebook.com,🚀 节点选择","DOMAIN-SUFFIX,instagram.com,🚀 节点选择",
        "DOMAIN-SUFFIX,whatsapp.com,🚀 节点选择",
        # 兜底
        "MATCH,🚀 节点选择",
    ]

    # ---- DNS 防污染（fake-ip 模式，国内外分流）----
    dns_config = {
        "enable": True, "listen": "0.0.0.0:1053",
        "enhanced-mode": "fake-ip", "fake-ip-range": "198.18.0.1/16",
        "fake-ip-filter": ["*.lan","*.local","localhost.ptlogin2.qq.com","+.msftconnecttest.com","+.msftncsi.com","*.cn"],
        "nameserver": ["https://223.5.5.5/dns-query","https://1.12.12.12/dns-query","119.29.29.29"],
        "fallback": ["https://1.1.1.1/dns-query","https://8.8.8.8/dns-query","tls://8.8.8.8:853"],
        "fallback-filter": {"geoip": True, "geoip-code": "CN", "ipcidr": ["240.0.0.0/4"],
            "domain": ["+.google.com","+.youtube.com","+.facebook.com","+.github.com"]},
    }

    return {"proxies": proxies, "proxy-groups": proxy_groups, "rules": rules, "dns": dns_config}


# 常见国旗 emoji → 中文国家名（订阅分组名若要可读，避免客户端显示 □□）
_FLAG_NAMES = {
    '🇳🇱':'荷兰','🇺🇸':'美国','🇷🇴':'罗马尼亚','🇩🇪':'德国','🇫🇷':'法国','🇨🇦':'加拿大',
    '🇬🇧':'英国','🇫🇮':'芬兰','🇵🇱':'波兰','🇧🇷':'巴西','🇦🇺':'澳大利亚','🇯🇵':'日本',
    '🇸🇬':'新加坡','🇭🇰':'香港','🇹🇼':'台湾','🇰🇷':'韩国','🇮🇳':'印度','🇹🇷':'土耳其',
    '🇷🇺':'俄罗斯','🇦🇪':'阿联酋','🇪🇪':'爱沙尼亚','🇴🇲':'阿曼','🇪🇸':'西班牙','🇿🇦':'南非',
    '🇹🇭':'泰国','🇷🇸':'塞尔维亚','🇨🇭':'瑞士','🇸🇪':'瑞典','🇦🇹':'奥地利','🇻🇳':'越南',
    '🇧🇬':'保加利亚','🇮🇹':'意大利','🇮🇷':'伊朗','🇨🇳':'中国','🇵🇦':'巴拿马','🇳🇴':'挪威',
    '🇱🇻':'拉脱维亚','🇬🇷':'希腊','🇧🇪':'比利时','🇲🇽':'墨西哥','🇭🇺':'匈牙利','🇨🇴':'哥伦比亚',
    '🇩🇰':'丹麦','🇰🇿':'哈萨克斯坦','🇲🇴':'澳门','🇨🇾':'塞浦路斯','🇨🇿':'捷克','🇦🇲':'亚美尼亚',
    '🇵🇹':'葡萄牙','🇱🇹':'立陶宛','🇲🇩':'摩尔多瓦','🇮🇪':'爱尔兰','🇲🇾':'马来西亚','🇨🇱':'智利',
    '🇦🇷':'阿根廷','🇿🇦':'南非','🇳🇿':'新西兰','🇺🇦':'乌克兰','🇮🇩':'印尼','🇸🇦':'沙特',
}
def _country_label(country: str, code=None) -> str:
    """把 country（可能是 emoji flag / 中文名 / 未知）转成可读的 [旗帜]中文名 标签。"""
    raw = (country or "").strip()
    if not raw or raw in ("", "其他节点", "None", "unknown"):
        if code:
            return code.upper()
        return "其他节点"
    # 若已是带中文的名字（如 "美国"）直接返回；若是纯 emoji flag 则映射为中文名
    if any('\u4e00' <= ch <= '\u9fa5' for ch in raw):
        return raw
    if raw in _FLAG_NAMES:
        return _FLAG_NAMES[raw]
    # 形如 flag+文字 的组合，取文字部分
    for ch in raw:
        if '\u4e00' <= ch <= '\u9fa5':
            return raw
    return raw or "其他节点"


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
# ============ Surge / Loon / Quantumult X ============

def generate_surge(nodes: List[Node]) -> str:
    """Surge 配置（[Proxy] 段）。支持 ss/trojan/vmess(Surge5+)/http/socks5，其余跳过。"""
    lines = ["#!PROFILES-OFFSET:0", "[Proxy]"]
    count = 0
    for n in nodes:
        try:
            nd = _nd(n)
            name = (n.node_name or f"node_{n.id}").replace(",", " ").strip()
            server, port = nd.get("server", ""), int(nd.get("port", 443))
            t = n.node_type.lower()
            sni = nd.get("sni") or nd.get("servername") or ""
            if t == "ss":
                lines.append(f"{name} = ss, {server}, {port}, encrypt-method={_cipher_of(nd)}, password={nd.get('password','')}, udp-relay=true")
            elif t == "trojan":
                extra = f", sni={sni}" if sni else ""
                if nd.get("skip-cert-verify"): extra += ", skip-cert-verify=true"
                ws = ""
                if nd.get("network") == "ws":
                    ws = ", ws=true"
                    if nd.get("ws-path") or nd.get("path"): ws += f", ws-path={nd.get('ws-path') or nd.get('path')}"
                    host = nd.get("servername") or nd.get("host")
                    if host: ws += f", ws-headers=Host:{host}"
                lines.append(f"{name} = trojan, {server}, {port}, password={nd.get('password','')}{extra}{ws}")
            elif t == "vmess":
                extra = []
                if nd.get("tls"): extra.append("tls=true")
                if sni: extra.append(f"sni={sni}")
                if nd.get("network") == "ws":
                    extra.append("ws=true")
                    if nd.get("ws-path") or nd.get("path"): extra.append(f"ws-path={nd.get('ws-path') or nd.get('path')}")
                    host = nd.get("servername") or nd.get("host") or nd.get("ws-host")
                    if host: extra.append(f"ws-headers=Host:{host}")
                es = ("," + ",".join(extra)) if extra else ""
                lines.append(f"{name} = vmess, {server}, {port}, username={nd.get('uuid','')}{es}")
            elif t == "http":
                user, pwd = nd.get("username", ""), nd.get("password", "")
                auth = f", {user}, {pwd}" if user else ""
                tl = ", tls=true" if nd.get("tls") else ""
                lines.append(f"{name} = http, {server}, {port}{auth}{tl}")
            elif t in ("socks5", "socks"):
                user, pwd = nd.get("username", ""), nd.get("password", "")
                auth = f", {user}, {pwd}" if user else ""
                lines.append(f"{name} = socks5, {server}, {port}{auth}, udp-relay=true")
            else:
                continue
            count += 1
        except Exception:
            continue
    if not count:
        return "\n".join(lines + ["# (无兼容节点)"])
    lines += ["", "[Proxy Group]", "Proxy = select, Auto, DIRECT, " + ", ".join(
        _surge_escape(n.node_name) for n in nodes[:500] if n.node_name), "",
        "[Rule]", "FINAL,Proxy"]
    return "\n".join(lines)


def _surge_escape(s: str) -> str:
    return str(s).replace(",", " ").strip() or "node"


def generate_loon(nodes: List[Node]) -> str:
    """Loon 插件格式（[Proxy] 段）。支持 ss/trojan/vmess/vless/hysteria2/http/socks5。"""
    lines = ["[Proxy]"]
    count = 0
    for n in nodes:
        try:
            nd = _nd(n)
            name = (n.node_name or f"node_{n.id}").replace(",", " ").strip()
            server, port = nd.get("server", ""), int(nd.get("port", 443))
            t = n.node_type.lower()
            sni = nd.get("sni") or nd.get("servername") or ""
            if t == "ss":
                lines.append(f"{name} = Shadowsocks, {server}, {port}, encrypt-method={_cipher_of(nd)}, password={nd.get('password','')}, udp=true")
            elif t == "trojan":
                extra = f", sni={sni}" if sni else ""
                if nd.get("skip-cert-verify"): extra += ", skip-cert-verify=true"
                lines.append(f"{name} = Trojan, {server}, {port}, password={nd.get('password','')}{extra}, udp=true")
            elif t == "vmess":
                extra = []
                if nd.get("network") == "ws":
                    extra.append("ws=true")
                    if nd.get("ws-path") or nd.get("path"): extra.append(f"ws-path={nd.get('ws-path') or nd.get('path')}")
                    host = nd.get("servername") or nd.get("host")
                    if host: extra.append(f"ws-headers=Host:{host}")
                if nd.get("tls"):
                    extra.append("tls=true")
                    if sni: extra.append(f"sni={sni}")
                es = (", " + ", ".join(extra)) if extra else ""
                lines.append(f"{name} = VMess, {server}, {port}, username={nd.get('uuid','')}{es}")
            elif t == "vless":
                extra = [f"uuid={nd.get('uuid','')}"]
                if sni: extra.append(f"sni={sni}")
                if nd.get("flow"): extra.append(f"flow={nd['flow']}")
                if nd.get("network") == "ws":
                    extra.append("transport=ws")
                    if nd.get("ws-path") or nd.get("path"): extra.append(f"path={nd.get('ws-path') or nd.get('path')}")
                es = (", " + ", ".join(extra)) if extra else ""
                lines.append(f"{name} = VLESS, {server}, {port}{es}")
            elif t in ("hysteria2", "hy2"):
                extra = f", sni={sni}" if sni else ""
                if nd.get("skip-cert-verify"): extra += ", skip-cert-verify=true"
                lines.append(f"{name} = Hysteria2, {server}, {port}, password={nd.get('password','')}{extra}")
            elif t == "http":
                user, pwd = nd.get("username", ""), nd.get("password", "")
                auth = f", {user}, {pwd}" if user else ""
                lines.append(f"{name} = HTTP, {server}, {port}{auth}")
            elif t in ("socks5", "socks"):
                user, pwd = nd.get("username", ""), nd.get("password", "")
                auth = f", {user}, {pwd}" if user else ""
                lines.append(f"{name} = SOCKS5, {server}, {port}{auth}")
            else:
                continue
            count += 1
        except Exception:
            continue
    if not count:
        lines.append("# (无兼容节点)")
    return "\n".join(lines)


def generate_qx(nodes: List[Node]) -> str:
    """Quantumult X 格式（filter/proxy 行）。支持 ss/trojan/vmess/http/socks5。"""
    lines = ["# Quantumult X 节点列表：粘贴到 [server_local] 段"]
    count = 0
    for n in nodes:
        try:
            nd = _nd(n)
            name = (n.node_name or f"node_{n.id}").replace(",", " ").strip()
            server, port = nd.get("server", ""), int(nd.get("port", 443))
            t = n.node_type.lower()
            sni = nd.get("sni") or nd.get("servername") or ""
            if t == "ss":
                lines.append(f"{name} = ss, {server}, {port}, encrypt-method={_cipher_of(nd)}, password={nd.get('password','')}, udp-relay=true")
            elif t == "trojan":
                extra = []
                if sni: extra.append(f"sni={sni}")
                if nd.get("skip-cert-verify"): extra.append("tls-verification=false")
                es = (", " + ", ".join(extra)) if extra else ""
                lines.append(f"{name} = trojan, {server}, {port}, password={nd.get('password','')}{es}, over-tls=true")
            elif t == "vmess":
                opts = []
                if nd.get("network") == "ws":
                    opts.append("network=ws")
                    if nd.get("ws-path") or nd.get("path"): opts.append(f"ws-path={nd.get('ws-path') or nd.get('path')}")
                    host = nd.get("servername") or nd.get("host")
                    if host: opts.append(f"ws-headers=Host:{host}")
                if nd.get("tls"):
                    opts.append("over-tls=true")
                    if sni: opts.append(f"tls-host={sni}")
                os_ = (', "' + '", "'.join(opts) + '"') if opts else ""
                lines.append(f"{name} = vmess, {server}, {port}, {nd.get('uuid','')}{os_}")
            elif t in ("http",):
                user, pwd = nd.get("username", ""), nd.get("password", "")
                auth = f", {user}, {pwd}" if user else ""
                prefix = "https" if nd.get("tls") else "http"
                lines.append(f"{name} = {prefix}, {server}, {port}{auth}")
            elif t in ("socks5", "socks"):
                user, pwd = nd.get("username", ""), nd.get("password", "")
                auth = f", {user}, {pwd}" if user else ""
                lines.append(f"{name} = socks5, {server}, {port}{auth}, over-tls=false")
            else:
                continue
            count += 1
        except Exception:
            continue
    if not count:
        lines.append("# (无兼容节点)")
    return "\n".join(lines)


def generate_mixed(nodes: List[Node]) -> str:
    return generate_txt(nodes)


def generate_clash_meta(nodes: List[Node]) -> str:
    """Clash.Meta 兼容（与 clash 同构；Meta 内核字段超集）"""
    return generate_clash(nodes)


FORMAT_GENERATORS = {
    "clash": generate_clash,
    "clash-meta": generate_clash_meta,
    "singbox": generate_singbox,
    "v2ray": generate_v2ray,
    "base64": generate_base64,
    "txt": generate_txt,
    "mixed": generate_mixed,
    "surge": generate_surge,
    "loon": generate_loon,
    "qx": generate_qx,
    # 单协议明文链接（兼容 NekoBox/OneClick 等客户端按协议筛选）
    "ss": lambda ns: generate_links(_filter_nodes(ns, "ss")),
    "ssr": lambda ns: generate_links(_filter_nodes(ns, "ssr")),
    "vmess": lambda ns: generate_links(_filter_nodes(ns, "vmess")),
    "vless": lambda ns: generate_links(_filter_nodes(ns, "vless")),
    "trojan": lambda ns: generate_links(_filter_nodes(ns, "trojan")),
    "hysteria2": lambda ns: generate_links(_filter_nodes(ns, "hysteria2")),
    "hysteria": lambda ns: generate_links(_filter_nodes(ns, "hysteria")),
    "tuic": lambda ns: generate_links(_filter_nodes(ns, "tuic")),
    "http": lambda ns: generate_links(_filter_nodes(ns, "http")),
    "socks5": lambda ns: generate_links(_filter_nodes(ns, "socks5")),
    "socks": lambda ns: generate_links(_filter_nodes(ns, "socks5")),
}

# 单协议过滤（大小写不敏感，兼容 node_type 变体）
def _filter_nodes(nodes: List[Node], ptype: str) -> List[Node]:
    target = ptype.lower()
    out = []
    for n in nodes:
        t = (n.node_type or "").lower()
        if t == target or t.endswith(f"-{target}") or t.endswith(f"_{target}"):
            out.append(n)
    return out


def generate_by_format(fmt: str, nodes: List[Node]) -> str:
    key = (fmt or "").strip().lower()
    if not key:
        raise ValueError("格式为空")
    gen = FORMAT_GENERATORS.get(key)
    if not gen:
        raise ValueError(f"未知导出格式: {fmt}（支持: {', '.join(sorted(FORMAT_GENERATORS.keys()))}）")
    return gen(nodes)


EXPORT_CONTENT_TYPES = {
    "clash": "text/yaml; charset=utf-8",
    "clash-meta": "text/yaml; charset=utf-8",
    "singbox": "application/json; charset=utf-8",
    "v2ray": "text/plain; charset=utf-8",
    "base64": "text/plain; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "mixed": "text/plain; charset=utf-8",
    "surge": "text/plain; charset=utf-8",
    "loon": "text/plain; charset=utf-8",
    "qx": "text/plain; charset=utf-8",
    # 单协议明文链接
    "ss": "text/plain; charset=utf-8",
    "ssr": "text/plain; charset=utf-8",
    "vmess": "text/plain; charset=utf-8",
    "vless": "text/plain; charset=utf-8",
    "trojan": "text/plain; charset=utf-8",
    "hysteria2": "text/plain; charset=utf-8",
    "hysteria": "text/plain; charset=utf-8",
    "tuic": "text/plain; charset=utf-8",
    "http": "text/plain; charset=utf-8",
    "socks5": "text/plain; charset=utf-8",
    "socks": "text/plain; charset=utf-8",
}
