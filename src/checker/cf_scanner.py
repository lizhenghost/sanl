"""
CF 官方/自定义网段扫描器（参考 CFData-WEB 思路）
流程: 网段展开(/24精简采样) → TCPing 扫描 → 合格延迟过滤 → Host伪装下载测速 → 数据中心(colo)识别 → TOP-N 入库
"""
import asyncio
import ipaddress
import json
import logging
import os
import random
import socket
import ssl
import time
from typing import List

from ..schema import repository

logger = logging.getLogger(__name__)

# 内置测速网址（Host 伪装下载用；auto=自动选择）
SPEED_URLS = [
    {"key": "auto", "name": "自动选择", "url": ""},
    {"key": "cachefly", "name": "CacheFly (美)", "url": "http://cachefly.cachefly.net/10mb.test"},
    {"key": "cf", "name": "Cloudflare 官方", "url": "https://speed.cloudflare.com/__down?bytes=20000000"},
    {"key": "ovh", "name": "OVH (欧)", "url": "https://proof.ovh.net/files/10Mb.dat"},
    {"key": "tele2", "name": "Tele2 (欧)", "url": "http://speedtest.tele2.net/10MB.zip"},
    {"key": "tb", "name": "ThinkBroadband (英)", "url": "http://ipv4.download.thinkbroadband.com/10MB.zip"},
]

# CF 支持的 HTTPS 明文可选端口（截图「测试端口」下拉）
SCAN_PORTS = [443, 2053, 2083, 2087, 2096, 8443, 80, 8080, 8880, 2052, 2082, 2086, 2095]

IPS_CACHE = os.path.join("data", "cf_ips_cache.json")
CACHE_TTL = 3600

# 运行态（内存）：前端轮询
STATE = {
    "running": False,
    "phase": "",
    "scanned": 0,
    "total": 0,
    "found": 0,
    "started_at": None,
    "log": [],
}


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    STATE["log"].append(f"[{ts}] {msg}")
    STATE["log"] = STATE["log"][-60:]
    logger.info(f"[cf-scan] {msg}")


async def get_official_ranges(ip_type: int = 4) -> List[str]:
    """CF 官方 IP 段（本地缓存 1 小时）"""
    if os.path.exists(IPS_CACHE):
        try:
            cache = json.load(open(IPS_CACHE))
            if time.time() - cache.get("ts", 0) < CACHE_TTL and cache.get(str(ip_type)):
                return cache[str(ip_type)]
        except Exception:
            pass
    url = f"https://www.cloudflare.com/ips-v{ip_type}"
    txt = await asyncio.to_thread(_http_get_sync, url, 15)
    ranges = [l.strip() for l in txt.splitlines() if l.strip() and "/" in l]
    try:
        cache = json.load(open(IPS_CACHE)) if os.path.exists(IPS_CACHE) else {}
    except Exception:
        cache = {}
    cache.update({str(ip_type): ranges, "ts": time.time()})
    os.makedirs("data", exist_ok=True)
    json.dump(cache, open(IPS_CACHE, "w"))
    return ranges


def _http_get_sync(url: str, timeout: int = 10) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "NodePool/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def build_candidates(ip_type: int, ranges: List[str], slim: bool,
                     per_subnet: int = 8, v6_per_range: int = 256) -> List[str]:
    """网段 → 候选 IP 列表。slim=True 时 v4 按 /24 抽样、v6 每段随机生成"""
    out = []
    for r in ranges or []:
        try:
            net = ipaddress.ip_network(r, strict=False)
        except ValueError:
            continue
        if net.version != ip_type:
            continue
        if ip_type == 6:
            # v6: 在网段内随机取固定数量（v6 地址空间天文数字，只能抽样）
            base = int(net.network_address)
            prefix = net.prefixlen
            host_bits = min(128 - prefix, 64)
            space = 1 << host_bits
            seen = set()
            for _ in range(min(v6_per_range, max(space, 1))):
                ip = ipaddress.IPv6Address(base + random.getrandbits(host_bits))
                s = str(ip)
                if s not in seen:
                    seen.add(s); out.append(s)
            continue
        # v4
        if slim and net.prefixlen <= 24:
            sub_base = int(net.network_address) & ~0xFF  # /24 基址
            picked = {sub_base + 1, sub_base + 254}
            while len(picked) < per_subnet:
                picked.add(sub_base + random.randint(2, 253))
            out.extend(str(ipaddress.IPv4Address(a)) for a in sorted(picked))
        elif net.prefixlen < 32:
            n = min(net.num_addresses, 4096)
            step = max(1, net.num_addresses // n)
            start = int(net.network_address)
            out.extend(str(ipaddress.IPv4Address(start + i * step)) for i in range(n))
        else:
            out.append(str(net.network_address))
    # 去重保序
    return list(dict.fromkeys(out))


async def _tcping(host: str, port: int, timeout: float = 1.0) -> float | None:
    loop = asyncio.get_event_loop()
    start = loop.time()
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        rtt = (loop.time() - start) * 1000
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return round(rtt)
    except Exception:
        return None


async def _trace_colo(ip: str, port: int, is_tls: bool, timeout: float = 2.5) -> str:
    """GET /cdn-cgi/trace 提取 colo（数据中心）"""
    raw = await _fetch_via_ip(ip, port, is_tls, "speed.cloudflare.com",
                              "/cdn-cgi/trace", max_bytes=2048, timeout=timeout)
    if raw:
        for line in raw.decode("utf-8", "ignore").splitlines():
            if line.startswith("colo="):
                return line.split("=", 1)[1].strip()
    return ""


async def _fetch_via_ip(ip: str, port: int, is_tls: bool, host_header: str,
                        path: str, max_bytes: int, timeout: float,
                        measure_speed: bool = False) -> bytes | None:
    """连指定 IP，Host/SNI 伪装成域名取内容；measure_speed=True 时返回 (data, mbps)"""
    def _do():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            t0 = time.time()
            sock.connect((ip, port))
            conn_ms = (time.time() - t0) * 1000
            if is_tls:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                sock = ctx.wrap_socket(sock, server_hostname=host_header)
            req = (f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\n"
                   f"User-Agent: NodePool/2.0\r\nAccept: */*\r\nConnection: close\r\n\r\n")
            sock.sendall(req.encode())
            buf, total = b"", 0
            t_dl = time.time()
            while total < max_bytes:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk; total += len(chunk)
            elapsed = max(time.time() - t_dl, 0.001)
            # 剥响应头
            body = buf.split(b"\r\n\r\n", 1)[-1] if b"\r\n\r\n" in buf else buf
            if measure_speed:
                # 净速度按 (头+体)/耗时 近似（大文件时误差可忽略）
                return body, round(total / elapsed / 1024 / 1024, 2), conn_ms
            return body
        except Exception:
            return (None, 0, None) if measure_speed else None
        finally:
            try:
                sock.close()
            except Exception:
                pass
    return await asyncio.to_thread(_do)


async def _download_speed_test(ip: str, port: int, url: str, seconds_cap: float = 5.0):
    """Host 伪装下载测速 → (mbps, colo)；url 为空返回 (None, '')"""
    from urllib.parse import urlparse
    p = urlparse(url if "://" in url else "https://" + url)
    is_tls = p.scheme == "https"
    host_header = p.hostname or "speed.cloudflare.com"
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    cap = int(8 * 1024 * 1024)  # 最多读 8MB
    res = await _fetch_via_ip(ip, port, is_tls, host_header, path, cap, seconds_cap,
                              measure_speed=True)
    body, mbps, conn_ms = res if isinstance(res, tuple) else (None, 0, None)
    colo = ""
    if body and b"colo=" in body:
        for line in body.decode("utf-8", "ignore").splitlines():
            if line.startswith("colo="):
                colo = line.split("=", 1)[1].strip()
    return (mbps if mbps else None), colo


async def run_scan(params: dict) -> dict:
    """
    params: ip_type, port, concurrency, max_latency, min_speed, top_n,
            scan_mode(tcping/http), speed_key/speed_url, slim, custom_ranges
    """
    if STATE["running"]:
        return {"status": "busy", "message": "已有扫描在进行中"}

    ip_type = int(params.get("ip_type", 4))
    port = int(params.get("port", 443))
    concurrency = max(10, min(int(params.get("concurrency", 100)), 1000))
    max_latency = int(params.get("max_latency", 500))
    min_speed = float(params.get("min_speed", 0) or 0)
    top_n = max(1, min(int(params.get("top_n", 20)), 500))
    scan_mode = params.get("scan_mode", "tcping")
    slim = bool(params.get("slim", True))
    speed_url = (params.get("speed_url") or "").strip()
    if not speed_url:
        key = params.get("speed_key", "auto")
        speed_url = next((u["url"] for u in SPEED_URLS if u["key"] == key and u["url"]), "")
        if not speed_url and min_speed > 0:
            speed_url = random.choice([u["url"] for u in SPEED_URLS if u["url"]])

    STATE.update({"running": True, "phase": "获取网段", "scanned": 0, "total": 0,
                  "found": 0, "started_at": time.time(), "log": []})
    t0 = time.time()
    try:
        custom = params.get("custom_ranges") or []
        if custom:
            ranges = [r.strip() for r in custom if r.strip()]
            _log(f"非标优选：使用自定义网段 {len(ranges)} 个")
        else:
            ranges = await get_official_ranges(ip_type)
            _log(f"官方优选：获取 CF IPv{ip_type} 网段 {len(ranges)} 个")

        STATE["phase"] = "生成候选"
        cands = build_candidates(ip_type, ranges, slim)
        random.shuffle(cands)
        STATE["total"] = len(cands)
        _log(f"候选 IP {len(cands)} 个（{'精简' if slim else '完整'}采样），端口 {port}，并发 {concurrency}")

        # ---- 第一阶段：TCP 扫描 ----
        STATE["phase"] = f"TCP扫描({scan_mode})"
        sem = asyncio.Semaphore(concurrency)
        alive = []

        async def _probe(ip):
            async with sem:
                if scan_mode == "http":
                    body = await _fetch_via_ip(ip, port, port in (443, 2053, 2083, 2087, 2096, 8443),
                                               "speed.cloudflare.com", "/cdn-cgi/trace", 1024, 2.5)
                    ok = bool(body and b"colo=" in body)
                    lat = None
                else:
                    lat = await _tcping(ip, port)
                    ok = lat is not None and lat <= max_latency
                STATE["scanned"] += 1
                if ok:
                    alive.append({"ip": ip, "latency_ms": lat})
            await asyncio.sleep(0)  # 让出事件循环

        await asyncio.gather(*[_probe(ip) for ip in cands])
        _log(f"TCP 阶段完成：存活 {len(alive)} 个")

        # 过滤延迟阈值 + 排序
        alive = [a for a in alive if a["latency_ms"] is None or a["latency_ms"] <= max_latency]
        alive.sort(key=lambda x: x["latency_ms"] if x["latency_ms"] is not None else 9999)

        # ---- 第二阶段：下载测速 + colo ----
        shortlist = alive[:max(top_n * 4, 30)]
        results = []
        if shortlist and (min_speed > 0 or True):
            need_speed = min_speed > 0 and speed_url
            STATE["phase"] = "下载测速" if need_speed else "识别数据中心"
            if speed_url:
                _log(f"{'测速网址' if need_speed else 'trace探测'}: {speed_url or '(trace)'}")
            sem2 = asyncio.Semaphore(max(4, concurrency // 20))

            async def _detail(item):
                async with sem2:
                    mbps, colo = None, ""
                    if speed_url and (need_speed or scan_mode == "tcping"):
                        mbps, colo = await _download_speed_test(
                            item["ip"], port, speed_url,
                            seconds_cap=6.0 if need_speed else 3.0)
                    elif scan_mode == "http":
                        colo = ""  # http 模式第一阶段已带 colo，简化不重复
                    if need_speed and (mbps is None or mbps < min_speed):
                        return  # 不合格
                    results.append({"ip": item["ip"], "port": port,
                                    "latency_ms": item["latency_ms"],
                                    "speed_mbps": mbps, "colo": colo})
                    STATE["found"] += 1

            await asyncio.gather(*[_detail(x) for x in shortlist])

        results.sort(key=lambda r: (r["latency_ms"] if r["latency_ms"] is not None else 9999,
                                    -(r["speed_mbps"] or 0)))
        results = results[:top_n]
        repository.save_scan_results(results)
        STATE["phase"] = "done"
        _log(f"✅ 完成：合格 {len(results)} 个（延迟≤{max_latency}ms"
             f"{f'、速度≥{min_speed}MB/s' if min_speed > 0 else ''}），耗时 {round(time.time()-t0,1)}s")
        return {"status": "done", "found": len(results)}
    except Exception as e:
        STATE["phase"] = "error"
        _log(f"❌ 扫描失败: {e}")
        logger.exception("cf scan failed")
        return {"status": "error", "message": str(e)}
    finally:
        STATE["running"] = False
