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
from ..utils.net import detect_isp
from ..scraper.scraper import Scraper
from ..api.importer import parse_content

logger = logging.getLogger(__name__)

# 单次全量导入的源并发数
FETCH_CONCURRENCY = 4




async def run_pool_import(scraper: Optional[Scraper] = None, source_id: Optional[int] = None) -> dict:
    """
    执行全源导入。返回摘要 dict。
    source_id 指定时只导入该源（单源刷新）。
    全程向 task_manager 汇报进度（前端进度条）。
    """
    own = scraper is None
    sc = scraper or Scraper()
    started = time.time()
    summary = {"sources_total": 0, "sources_ok": 0, "sources_failed": 0,
               "parsed": 0, "inserted": 0, "updated": 0, "cf_endpoints": 0, "errors": []}
    from ..utils.taskmgr import task_manager
    tid = "fetch"
    task_manager.start(tid, "📥 全量抓取源")
    try:
        sources = repository.list_sources(enabled_only=True)
        if source_id:
            sources = [s for s in sources if s.id == source_id]
        # 手动导入源不参与自动池导入（内容已在导入时入库）
        sources = [s for s in sources if s.source_type != "manual"]
        summary["sources_total"] = len(sources)
        task_manager.update(tid, total=len(sources), detail=f"共 {len(sources)} 个源")

        sem = asyncio.Semaphore(FETCH_CONCURRENCY)

        done_counter = {"n": 0}

        async def _one(src):
            async with sem:
                task_manager.update(tid, detail=f"抓取: {src.name[:40]}")
                r = await _import_one(sc, src, summary)
                done_counter["n"] += 1
                task_manager.update(tid, done=done_counter["n"],
                                    detail=f"完成 {done_counter['n']}/{len(sources)} · 成功{summary['sources_ok']} 失败{summary['sources_failed']}")
                return r

        await asyncio.gather(*[_one(s) for s in sources])
        summary["elapsed_sec"] = round(time.time() - started, 1)
        task_manager.finish(tid)
        logger.info(f"池导入完成: {summary}")
        return summary
    except Exception as e:
        task_manager.finish(tid, error=str(e)[:120])
        raise
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

            # ⭐ 优选域名 → 自动解析全部 IP 入库（新加优选域名源即自动生效）
            domains = [ep["host"] for ep in cf_eps if not _is_ip(ep.get("host", ""))]
            if domains:
                try:
                    from ..engine.cf_hub import harvest_domains
                    hr = await harvest_domains(domains, port=int(cf_eps[0].get("port", 443) or 443))
                    summary["cf_resolved_ips"] = summary.get("cf_resolved_ips", 0) + hr.get("new_ips", 0)
                    logger.info(f"[pool] 源 {src.name}: {len(domains)} 优选域名自动解析 → 新增 {hr.get('new_ips', 0)} IP")
                except Exception as e:
                    logger.warning(f"[pool] 源 {src.name} 优选域名解析失败: {e}")

        node_count = len(nodes)
        repository.update_source_status(src.id, 1, node_count)
        try:
            repository.record_source_success(src.id)
        except Exception:
            pass
        summary["sources_ok"] += 1
        try:
            from ..api.cache import invalidate_all
            invalidate_all()  # 抓取入库后清空读缓存
        except Exception:
            pass
        logger.info(f"源[{src.name}] 解析 {node_count} 节点 + {len(cf_eps)} CF端点")
    except Exception as e:
        summary["sources_failed"] += 1
        summary["errors"].append(f"{src.name}: {str(e)[:120]}")
        try:
            repository.record_source_failure(src.id)
        except Exception:
            pass


def _is_ip(s: str) -> bool:
    """host 是否已是 IP（域名/IPv6 判断用）"""
    import ipaddress
    try:
        ipaddress.ip_address(str(s).strip("[]"))
        return True
    except (ValueError, TypeError):
        return False
