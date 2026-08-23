"""sanl-engine 管线编排：拉取 → 解析 → 去重 → L1 TCP → L2 链路 → L3 测速 → 命名输出。

三级漏斗设计（自研）：
  L1 纯 asyncio TCP 握手（万级节点秒级筛除大部分死节点，零外部依赖）
  L2 mihomo 内核真实链路 204 探测（仅 TCP 最优 Top-N 候选参与）
  L3 经节点出口限流量下载测速（min-speed 合格线过滤）
"""
import hashlib
import logging
import time
from typing import Callable, Dict, List, Optional

from ..api.importer import parse_content
from .fetcher import fetch_many
from .kernel import KernelManager
from .models import Candidate, EngineResult, StageStats
from .namer import rename_alive
from .prober import probe_candidates
from .tcplayer import batch_probe

logger = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[str, int, int, str], None]]


def _fingerprint(p: dict) -> str:
    """节点指纹：server:port:密码类字段:sni:network —— 跨源去重的稳定键。"""
    pw = str(p.get("password") or p.get("uuid") or "")
    sni = str(p.get("servername") or p.get("sni") or "")
    net = str(p.get("network") or "")
    return hashlib.sha1(
        f"{p.get('server')}:{p.get('port')}:{pw}:{sni}:{net}".encode()
    ).hexdigest()[:20]


def _parse_all(contents) -> List[Candidate]:
    """全部订阅内容 → 去重后的候选列表。"""
    cands: Dict[str, Candidate] = {}
    dup = 0
    for url, content in contents:
        if not content:
            continue
        try:
            parsed = parse_content(content, cf_as_nodes=False)
        except Exception as e:
            logger.warning(f"[engine] 解析失败 {url[:70]}: {e}")
            continue
        for ptype, data, name in parsed.get("nodes", []):
            proxy = {"name": str(name), "type": str(ptype), **data}
            fp = _fingerprint(proxy)
            if fp in cands:
                dup += 1
                continue
            cands[fp] = Candidate(proxy=proxy, fingerprint=fp)
    logger.info(f"[engine] 解析 {sum(1 for _, c in contents if c)} 源 → "
                f"{len(cands)} 候选（去重 {dup}）")
    return list(cands.values())


async def run_pipeline(source_urls: List[str], *,
                       mode: str = "speed",
                       overrides: Optional[Dict] = None,
                       progress_cb: ProgressCb = None,
                       workdir: str = "./output/engine") -> EngineResult:
    """执行一轮完整管线。progress_cb(phase, done, total, detail)。

    overrides 支持键：timeout / concurrent(L2通道数) / min-speed /
    download-mb / download-timeout / speed-test-url / l1-concurrency / l2-max
    """
    t0 = time.monotonic()
    ov = {k.lower(): v for k, v in (overrides or {}).items()}
    stats = StageStats()
    result = EngineResult(stats=stats)

    def prog(phase, done, total, detail=""):
        if progress_cb:
            try:
                progress_cb(phase, done, total, detail)
            except Exception:
                pass

    try:
        # ---------- 1. 拉取 ----------
        prog("fetch", 0, len(source_urls), f"拉取 {len(source_urls)} 个订阅")
        contents = await fetch_many(
            source_urls,
            concurrency=int(ov.get("sub-urls-concurrent", 12)),
            timeout=float(ov.get("sub-timeout", 20)),
            progress_cb=lambda d, t: prog("fetch", d, t))
        stats.fetched_sources = sum(1 for _, c in contents if c)
        empty = len(source_urls) - stats.fetched_sources
        if not stats.fetched_sources:
            raise RuntimeError("所有订阅拉取失败")
        prog("fetch", len(source_urls), len(source_urls),
             f"成功 {stats.fetched_sources}" + (f"（失败 {empty}）" if empty else ""))

        # ---------- 2. 解析+去重 ----------
        candidates = _parse_all(contents)
        stats.parsed_nodes = len(candidates)
        stats.deduped_nodes = len(candidates)
        if not candidates:
            raise RuntimeError("解析得到 0 个候选节点")
        prog("parse", len(candidates), len(candidates),
             f"候选 {len(candidates)}（来自 {stats.fetched_sources} 源）")

        # ---------- 3. L1 TCP ----------
        # overrides.timeout 单位沿用 ms（subs-check 参数惯例）；L1 握手上限 2s
        timeout_ms = float(ov.get("timeout", 2000))
        l1c = int(ov.get("l1-concurrency", 500))
        prog("l1", 0, len(candidates), "TCP 批量测活")
        await batch_probe(candidates, concurrency=l1c,
                          timeout=min(2.0, timeout_ms / 1000),
                          progress_cb=lambda d, t: prog("l1", d, t))
        alive_l1 = sorted([c for c in candidates if c.tcp_rtt is not None],
                          key=lambda c: c.tcp_rtt)
        stats.l1_alive = len(alive_l1)
        prog("l1", len(candidates), len(candidates), f"TCP 存活 {len(alive_l1)}")
        logger.info(f"[engine] L1 漏斗: 候选 {len(candidates)} → TCP 存活 {len(alive_l1)} "
                    f"({len(alive_l1)/max(1,len(candidates))*100:.1f}%) 超时 {timeout_ms/1000}s")

        # ---------- 4. L2/L3 内核探测 ----------
        # 实测标定：30通道×5s 会把 30% 的活节点挤死（并发过载+超时不足，
        # 重测实验 60 判死节点低并发长超时救回 18 个，含 135ms 优质节点）。
        # 默认改为 16 通道 × 8s；L2 上限 2500 防止 TCP 较慢的好节点被截断。
        l2_max = int(ov.get("l2-max", 2500))
        pool = alive_l1[:max(1, l2_max)]
        do_speed = mode in ("speed", "full")
        channels = max(2, int(ov.get("concurrent", 16)))
        speed_url = str(ov.get("speed-test-url") or
                        "http://cachefly.cachefly.net/1mb.test")
        min_speed = int(ov.get("min-speed", 128))

        km = KernelManager([c.proxy for c in pool], workdir=workdir,
                           channels=channels,
                           base_port=int(ov.get("probe-base-port", 7891)),
                           api_port=int(ov.get("probe-api-port", 9095)))
        prog("probe", 0, len(pool),
             f"L2 链路探测 {len(pool)} 候选 × {channels} 通道"
             + (" + L3 测速" if do_speed else ""))
        try:
            await km.start()
            await probe_candidates(
                km, pool,
                do_speed=do_speed, speed_url=speed_url, min_speed=min_speed,
                download_mb=float(ov.get("download-mb", 1)),
                download_timeout=float(ov.get("download-timeout", 6)),
                alive_timeout=max(8.0, timeout_ms / 1000),
                progress_cb=lambda d, t: prog("probe", d, t))
        finally:
            await km.stop()

        alive_l2 = [c for c in pool if c.alive]
        stats.l2_alive = len(alive_l2)
        logger.info(f"[engine] L2 漏斗: {len(pool)} 候选 × {channels} 通道 → 存活 {len(alive_l2)} "
                    f"({len(alive_l2)/max(1,len(pool))*100:.1f}%) 超时 {alive_timeout if 'alive_timeout' in dir() else 8}s")

        # ---------- 5. GeoIP + 合格筛选 + 命名 ----------
        passed = [c for c in alive_l2
                  if (not do_speed)
                  or (c.download_speed is not None and c.download_speed >= min_speed)]
        stats.l3_passed = len(passed)
        # 补国家码（名字猜不出时查 GeoIP），失败不影响主流程
        try:
            from .geoip import fill_country_codes
            await fill_country_codes(passed)
        except Exception as ge:
            logger.warning(f"[engine] GeoIP 跳过: {ge}")
        # 低延迟优先排序后命名输出
        passed.sort(key=lambda c: (c.latency if c.latency is not None else 9999))
        result.alive_proxies = rename_alive(passed)
        prog("done", 1, 1,
             f"存活 {len(alive_l2)} / 合格 {len(passed)}"
             + ("" if do_speed else "（latency 模式不测速）"))

        result.ok = True
    except Exception as e:
        logger.exception("[engine] 管线失败")
        result.ok = False
        result.error = f"{type(e).__name__}: {e}"
    finally:
        result.elapsed = round(time.monotonic() - t0, 1)

    return result
