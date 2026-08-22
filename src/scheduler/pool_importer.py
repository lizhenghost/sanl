"""
全源节点池导入器
遍历 DB 启用源 → 抓取（GitHub 镜像回退）→ 统一解析（13 协议/Clash/sing-box/Base64）
→ 指纹去重 Upsert 入库（status=unknown，等测速回填）
CF 优选 host:port 列表 → cf_endpoints 表（独立于代理节点）
"""
import asyncio
import logging
import time
from typing import Optional

from ..schema import repository
from ..scraper.scraper import Scraper
from ..api.importer import parse_content

logger = logging.getLogger(__name__)

# 单次全量导入的源并发数
FETCH_CONCURRENCY = 4


def detect_isp(*texts) -> str:
    """从 URL/名称/备注推断运营商：telecom(电信)/mobile(移动)/unicom(联通)/all(三网通用)"""
    import re
    joined = " ".join(t for t in texts if t).lower()
    if any(k in joined for k in ("cmcc", "移动")):
        return "mobile"
    if any(k in joined for k in ("unicom", "联通")) or re.search(r'(^|[^a-z])cu([^a-z]|$)', joined):
        return "unicom"
    if any(k in joined for k in ("telecom", "电信")) or re.search(r'(^|[^a-z])ct([^a-z]|$)', joined):
        return "telecom"
    return ""


async def run_pool_import(scraper: Optional[Scraper] = None, source_id: Optional[int] = None) -> dict:
    """
    执行全源导入。返回摘要 dict。
    source_id 指定时只导入该源（单源刷新）。
    """
    own = scraper is None
    sc = scraper or Scraper()
    started = time.time()
    summary = {"sources_total": 0, "sources_ok": 0, "sources_failed": 0,
               "parsed": 0, "inserted": 0, "updated": 0, "cf_endpoints": 0, "errors": []}
    try:
        sources = repository.list_sources(enabled_only=True)
        if source_id:
            sources = [s for s in sources if s.id == source_id]
        # 手动导入源不参与自动池导入（内容已在导入时入库）
        sources = [s for s in sources if s.source_type != "manual"]
        summary["sources_total"] = len(sources)

        sem = asyncio.Semaphore(FETCH_CONCURRENCY)

        async def _one(src):
            async with sem:
                return await _import_one(sc, src, summary)

        await asyncio.gather(*[_one(s) for s in sources])
        summary["elapsed_sec"] = round(time.time() - started, 1)
        logger.info(f"池导入完成: {summary}")
        return summary
    finally:
        if own:
            await sc.close()


async def _import_one(sc: Scraper, src, summary: dict):
    try:
        r = await sc.fetch_source(src.url, src.source_type)
        if not r or not r.raw_content or r.error:
            err = (r.error if r else "无返回")[:120]
            summary["sources_failed"] += 1
            summary["errors"].append(f"{src.name}: {err}")
            try:
                repository.record_source_failure(src.id)
            except Exception:
                pass
            return
        content = r.raw_content
        # Base64 订阅在 parse_content 内部自动识别
        parsed = parse_content(content, cf_as_nodes=False)
        nodes = parsed.get("nodes", [])
        cf_eps = parsed.get("cf_endpoints", [])

        if nodes:
            items = [{
                "subscribe_url": src.url,
                "source_id": src.id,
                "node_name": name,
                "node_type": ntype,
                "node_data": data,
            } for (ntype, data, name) in nodes]
            res = repository.upsert_nodes_bulk(items)
            summary["parsed"] += len(items)
            summary["inserted"] += res["inserted"]
            summary["updated"] += res["updated"]

        if cf_eps:
            src_isp = detect_isp(src.url, src.name) or "all"
            for ep in cf_eps:
                # 行级备注命中运营商优先（如「CF 电信优选」），否则用来源级（如 /cmcc 路径）
                ep["isp"] = detect_isp(ep.get("remark", "")) or src_isp
            n = repository.upsert_cf_endpoints(cf_eps, source_id=src.id, default_isp=src_isp)
            summary["cf_endpoints"] += n

        node_count = len(nodes)
        repository.update_source_status(src.id, 1, node_count)
        try:
            repository.record_source_success(src.id)
        except Exception:
            pass
        summary["sources_ok"] += 1
        logger.info(f"源[{src.name}] 解析 {node_count} 节点 + {len(cf_eps)} CF端点")
    except Exception as e:
        summary["sources_failed"] += 1
        summary["errors"].append(f"{src.name}: {str(e)[:120]}")
        try:
            repository.record_source_failure(src.id)
        except Exception:
            pass
