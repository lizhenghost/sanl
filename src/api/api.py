"""
FastAPI 主应用
"""
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request, BackgroundTasks, UploadFile, File, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, Response
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

from ..config import get_app_config, get_scheduler_config
from ..schema import repository, models
from .cache import cached, invalidate_all, cache_stats
from ..scheduler.scheduler import Scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global scheduler
    
    # 启动时初始化
    logger.info("Initializing Sanl...")
    repository.init_db()
    
    scheduler = Scheduler()
    scheduler.start()
    
    yield
    
    # 关闭时清理
    if scheduler:
        scheduler.shutdown()
    logger.info("Sanl stopped")


def create_app() -> FastAPI:
    app_config = get_app_config()
    
    app = FastAPI(
        title=app_config.get("name", "Sanl"),
        version=app_config.get("version", "1.0.0"),
        description="免费节点池聚合平台",
        lifespan=lifespan,
        # 本地化 API 文档（默认 swagger-ui 引用 jsdelivr CDN，国内被墙白屏 → 自建零依赖 /docs 页）
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # 挂载本地化 API 文档页
    from .local_docs import register_local_docs
    register_local_docs(app)
    
    # 挂载静态文件
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    vendor_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "vendor")
    os.makedirs(static_dir, exist_ok=True)
    os.makedirs(vendor_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.mount("/vendor", StaticFiles(directory=vendor_dir), name="vendor")
    
    # 主页
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    # PWA 根路径文件：sw.js 必须在根 scope 才能控制全站缓存
    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(os.path.join(static_dir, "sw.js"),
                            media_type="application/javascript",
                            headers={"Cache-Control": "no-cache",
                                     "Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def webmanifest():
        return FileResponse(os.path.join(static_dir, "manifest.webmanifest"),
                            media_type="application/manifest+json",
                            headers={"Cache-Control": "no-cache"})
    
    # 包含路由
    app.include_router(api_router, prefix="/api")
    from .converter import router as convert_router
    app.include_router(convert_router, prefix="/api", tags=["converter"])
    app.include_router(sub_router, prefix="/sub", tags=["subscription"])

    # 缓存失效：任何非只读请求（POST/PUT/DELETE）完成后清空读缓存。
    # 写操作频率远低于读（每小时抓取/测速），清空可保正确且命中率高。
    @app.middleware("http")
    async def invalidate_on_write(request: Request, call_next):
        response = await call_next(request)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            try:
                invalidate_all()
            except Exception:
                pass
        return response

    # SPA 路由 fallback：前端是单页 tab 切换，地址栏直接输入 /nodes、/dashboard 等
    # 路径（或刷新、收藏）时，凡未匹配 /api、/sub、/static、/vendor 等前缀的 GET，
    # 一律返回单页 index.html，由前端 JS 接管渲染，避免空白 404。
    # 放在所有 mount/router、中间件之后，仅兜底未命中路径。
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        lower = full_path.lower()
        for prefix in ("api/", "sub/", "static/", "vendor/", "openapi.json",
                       "docs", "redoc", "sw.js", "manifest.webmanifest", "favicon.ico"):
            if lower == prefix.rstrip('/') or lower.startswith(prefix):
                raise HTTPException(status_code=404)
        return FileResponse(os.path.join(static_dir, "index.html"))
    
    return app


api_router = APIRouter()
sub_router = APIRouter()


# ===== 数据源接口 =====

class SourceCreate(BaseModel):
    name: str
    url: str
    source_type: str = "unknown"


@api_router.post("/sources")
async def create_source(source: SourceCreate):
    """添加数据源"""
    try:
        s = repository.add_source(source.name, source.url, source.source_type)
        if s is None:
            raise HTTPException(status_code=500, detail="Failed to create source")
        return s
    except HTTPException:
        raise
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=400, detail="Source URL already exists")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/sources", response_model=List[models.Source])
@cached(ttl=3)
async def list_sources(enabled: bool = True):
    """获取数据源列表"""
    return repository.list_sources(enabled_only=enabled)


@api_router.put("/sources/{source_id}/enable")
async def toggle_source(source_id: int, enabled: bool = True):
    """启用/禁用数据源"""
    repository.enable_source(source_id, 1 if enabled else 0)
    return {"status": "ok"}


@api_router.put("/sources/{source_id}/speed-test")
async def toggle_source_speed_test(source_id: int, speed_test: bool = True):
    """切换数据源是否参与测速（1=参加延迟/测速, 0=不参加）"""
    repository.set_source_speed_test(source_id, 1 if speed_test else 0)
    return {"status": "ok"}


@api_router.delete("/sources/{source_id}")
async def delete_source(source_id: int):
    """删除数据源"""
    repository.enable_source(source_id, 0)  # 软删除
    return {"status": "ok"}


# ===== 手动导入（订阅链接/节点链接/单节点表单）=====

class NodeImportRequest(BaseModel):
    content: str  # 多行 ss/vmess/vless/trojan/hy2/tuic 链接、Clash YAML 或 Base64 订阅
    label: str = "手动导入"


class SingleNodeForm(BaseModel):
    type: str  # ss / vmess / vless / trojan / hysteria2 / tuic
    server: str
    port: int
    password: Optional[str] = None
    uuid: Optional[str] = None
    cipher: Optional[str] = None
    sni: Optional[str] = None
    name: Optional[str] = None
    skip_cert_verify: bool = False


@api_router.post("/nodes/import")
async def import_nodes(req: NodeImportRequest):
    """批量手动导入节点：支持多行协议链接 / Clash YAML / sing-box JSON / Base64 订阅内容"""
    from .importer import parse_content
    from ..schema.repository import node_fingerprint, get_connection
    result = parse_content(req.content)
    if not result["nodes"]:
        raise HTTPException(status_code=400, detail="；".join(result["errors"]) or "无可识别的节点")

    src = repository.get_or_create_manual_source(req.label)
    imported, skipped = 0, 0
    for ntype, data, name in result["nodes"]:
        try:
            # 指纹去重（同类型+服务器+端口+凭据视为同一节点）
            fp = node_fingerprint(ntype, data)
            with get_connection() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM nodes WHERE fingerprint = ?", (fp,)
                ).fetchone()
            if exists:
                skipped += 1
                continue
            repository.add_node(
                subscribe_url=f"manual://{req.label}", source_id=src.id,
                node_name=name, node_type=ntype, node_data=data,
                status="active"
            )
            imported += 1
        except Exception as e:
            result["errors"].append(f"{name}: {e}")

    return {"imported": imported, "skipped": skipped, "errors": result["errors"][:10],
            "total_parsed": len(result["nodes"])}


@api_router.post("/nodes/import/single")
async def import_single_node(form: SingleNodeForm):
    """表单式导入单个节点"""
    from .importer import build_from_form
    try:
        ntype, data, name = build_from_form(form.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    src = repository.get_or_create_manual_source("手动导入")
    repository.add_node(
        subscribe_url="manual://form", source_id=src.id,
        node_name=name, node_type=ntype, node_data=data,
        status="active"
    )
    return {"status": "ok", "name": name, "type": ntype}


@api_router.post("/nodes/import/upload")
async def import_nodes_upload(file: UploadFile = File(...), label: str = Query("文件上传")):
    """本地文件上传导入（大纲 4.1 社区提交）：txt/yaml/conf/json 均可，自动识别格式"""
    from .importer import parse_content
    from ..schema.repository import node_fingerprint, get_connection
    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 5MB 上限")
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1", errors="ignore")
    result = parse_content(content)
    if not result["nodes"]:
        raise HTTPException(status_code=400, detail="；".join(result["errors"]) or "文件中无可识别的节点")

    safe_label = (label or "文件上传")[:50]
    src = repository.get_or_create_manual_source(f"上传:{file.filename or safe_label}")
    imported, skipped = 0, 0
    for ntype, data, name in result["nodes"]:
        try:
            fp = node_fingerprint(ntype, data)
            with get_connection() as conn:
                exists = conn.execute("SELECT 1 FROM nodes WHERE fingerprint = ?", (fp,)).fetchone()
            if exists:
                skipped += 1
                continue
            repository.add_node(
                subscribe_url=f"manual://upload-{src.id}", source_id=src.id,
                node_name=name, node_type=ntype, node_data=data, status="active")
            imported += 1
        except Exception as e:
            result["errors"].append(f"{name}: {e}")
    return {"imported": imported, "skipped": skipped, "errors": result["errors"][:10],
            "total_parsed": len(result["nodes"])}


@api_router.post("/nodes/{node_id}/ban")
async def ban_node(node_id: int):
    """手动封禁节点（大纲 H.3）：标记 banned，订阅与测速均排除"""
    ok = repository.set_node_banned(node_id, True)
    if not ok:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"status": "ok", "id": node_id, "banned": True}


@api_router.post("/nodes/{node_id}/unban")
async def unban_node(node_id: int):
    """解除封禁：恢复为 unknown（等待下一轮测速重判）"""
    ok = repository.set_node_banned(node_id, False)
    if not ok:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"status": "ok", "id": node_id, "banned": False}


@api_router.post("/sources/discover")
async def discover_sources(min_stars: int = Query(100, ge=0), per_page: int = Query(15, ge=1, le=50),
                           auto_add: bool = Query(False, description="自动入库新发现的源")):
    """GitHub 仓库自动发现（大纲 附录A#10/G.1）：搜索免费节点订阅仓库并给出候选订阅文件"""
    from ..scraper.scraper import Scraper
    sc = Scraper()
    try:
        candidates = await sc.discover_github_sources(min_stars=min_stars, per_page=per_page)
    finally:
        await sc.close()
    # 排除已存在的源 URL
    existing = {s.url for s in repository.list_sources()}
    new_items = [c for c in candidates if c["url"] not in existing]
    added = 0
    if auto_add:
        for c in new_items[:10]:
            if repository.add_source(name=f"[discover] {c['repo']}", url=c["url"], source_type="github"):
                added += 1
    return {"candidates": len(candidates), "new": len(new_items),
            "added": added, "items": new_items[:30]}


# ===== 全源池导入 / CF 优选端点 =====

@api_router.post("/sources/import-all")
async def import_all_sources():
    """手动触发全量池导入：抓取所有启用源 → 解析 → 指纹去重入库（后台异步执行）"""
    import asyncio
    from ..scheduler.pool_importer import run_pool_import

    async def _job():
        try:
            summary = await run_pool_import()
            logger.info(f"手动全量导入完成: {summary}")
        except Exception as e:
            logger.error(f"手动全量导入失败: {e}")

    asyncio.create_task(_job())
    return {"status": "started", "message": "全量导入已在后台启动，稍后刷新页面查看各源节点数"}


@api_router.post("/sources/{source_id}/reimport")
async def reimport_single_source(source_id: int):
    """单源重新导入（同步执行，返回导入统计）"""
    from ..scheduler.pool_importer import run_pool_import
    source = repository.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    summary = await run_pool_import(source_id=source_id)
    return {"status": "ok", "source": source.name, **summary}


@api_router.get("/cf/endpoints")
async def list_cf_endpoints(
    limit: int = Query(2000, le=20000),
    isp: Optional[str] = Query(None, pattern="^(telecom|mobile|unicom|all|any)$",
                               description="运营商筛选：telecom电信/mobile移动/unicom联通/all三网通用/any全部"),
    sort: str = Query("id", pattern="^(latency|id)$", description="latency=按IP版本分组+TCP延迟升序"),
    only_alive: bool = Query(False, description="仅返回延迟检测存活的端点"),
    ip_version: Optional[int] = Query(None, ge=0, le=6,
                                      description="IP版本筛选：4=IPv4 / 6=IPv6 / 0=域名 / 不传=全部")
):
    """CF 优选 IP/域名端点列表，支持运营商、IP版本筛选与延迟排序"""
    items = repository.get_cf_endpoints(limit=limit, isp=isp, sort=sort,
                                        only_alive=only_alive, ip_version=ip_version)
    return {"total": repository.count_cf_endpoints(),
            "by_isp": repository.cf_isp_stats(),
            "by_ip_version": repository.cf_ip_version_stats(),
            "endpoints": items}


@api_router.post("/cf/ping")
async def ping_cf_endpoints(
    background_tasks: BackgroundTasks,
    isp: str = Query("any", pattern="^(telecom|mobile|unicom|all|any)$"),
    limit: int = Query(5000, le=20000)
):
    """对 CF 优选端点发起一轮 TCP 延迟检测（后台执行，前端轮询列表看结果）"""
    from ..checker import cf_ping

    async def _run():
        await cf_ping.ping_all(isp=isp, limit=limit)

    background_tasks.add_task(_run)
    return {"status": "started",
            "message": f"延迟检测已启动（{isp}，最多 {limit} 个端点），约 30-60 秒后刷新查看"}


# ---------- CF 网段扫描器（参考 CFData-WEB v1.7.8） ----------
from ..checker import cf_scanner


@api_router.get("/cf/scan/meta")
async def cf_scan_meta():
    """扫描器元信息：可选端口、内置测速网址"""
    return {"ports": cf_scanner.SCAN_PORTS,
            "speed_urls": [{"key": u["key"], "name": u["name"]} for u in cf_scanner.SPEED_URLS]}


@api_router.get("/cf/scan/status")
async def cf_scan_status():
    return {k: (list(v) if k == "log" else v) for k, v in cf_scanner.STATE.items()}


@api_router.post("/cf/scan")
async def cf_scan_start(
    background_tasks: BackgroundTasks,
    ip_type: int = Query(4, ge=4, le=6),
    port: int = Query(443),
    concurrency: int = Query(100, ge=10, le=1000),
    max_latency: int = Query(500, ge=20, le=3000, description="扫描合格延迟 ms"),
    min_speed: float = Query(0, ge=0, le=100, description="测试合格速度 MB/s，0=跳过测速"),
    top_n: int = Query(20, ge=1, le=500, description="测速结果数量 TOP N"),
    scan_mode: str = Query("tcping", pattern="^(tcping|http)$"),
    speed_key: str = Query("auto", description="测速网址 key，auto=自动选择"),
    speed_url: str = Query("", description="自定义测速网址（优先于 speed_key）"),
    slim: bool = Query(True, description="精简地址库：按 /24 子网抽样探测"),
    custom_ranges: str = Query("", description="非标优选：自定义网段，逗号分隔，如 103.22.200.0/24,2606:4700::/32")
):
    """启动一轮 CF 网段扫描（官方优选=CF官方段；非标优选=自定义网段）"""
    ranges = [r.strip() for r in (custom_ranges or "").split(",") if r.strip()]
    params = dict(ip_type=ip_type, port=port, concurrency=concurrency,
                  max_latency=max_latency, min_speed=min_speed, top_n=top_n,
                  scan_mode=scan_mode, speed_key=speed_key, speed_url=speed_url,
                  slim=slim, custom_ranges=ranges)

    async def _run():
        await cf_scanner.run_scan(params)

    if cf_scanner.STATE["running"]:
        raise HTTPException(status_code=409, detail="已有扫描在进行中")
    background_tasks.add_task(_run)
    return {"status": "started", "params": params}


@api_router.get("/cf/scan/results")
async def cf_scan_results(limit: int = Query(500, le=2000)):
    items = repository.get_scan_results(limit=limit)
    return {"total": len(items), "results": items}


@api_router.delete("/cf/scan/results")
async def cf_scan_results_clear():
    n = repository.clear_scan_results()
    return {"cleared": n}


@api_router.get("/cf/endpoints/export")
async def export_cf_endpoints(
    isp: str = Query("any", pattern="^(telecom|mobile|unicom|all|any)$"),
    limit: int = Query(5000, le=20000)
):
    """导出 CF 优选端点为 host:port#备注 文本（可直接粘进优选工具）"""
    items = repository.get_cf_endpoints(limit=limit, isp=isp)
    lines = [f"{it['host']}:{it['port']}#{it['remark'] or it['isp']}" for it in items]
    return Response(
        content="\n".join(lines),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache"}
    )


# ===== 节点接口 =====

@api_router.get("/nodes", response_model=List[models.Node])
@cached(ttl=3)
async def list_nodes(
    status: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    node_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    min_score: float = Query(0, ge=0, le=100),
    min_speed: Optional[float] = Query(None, ge=0, description="最低速度 KB/s"),
    max_latency: Optional[int] = Query(None, ge=0, description="最大延迟 ms"),
    sort: str = Query("latency", pattern="^(latency|speed|score|created|name|country)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    source_type: Optional[str] = Query(None, description="manual=手动导入, auto=系统抓取")
):
    """获取节点列表（筛选/排序/分页，方案 v2.1 Phase 4）"""
    nodes = repository.list_nodes(
        status=status, country=country, node_type=node_type, limit=limit,
        offset=offset, min_score=min_score, min_speed=min_speed,
        max_latency=max_latency, sort=sort, order=order, source_type=source_type
    )
    result = []
    for n in nodes:
        d = {
            "id": n.id, "node_name": n.node_name, "node_type": n.node_type,
            "status": n.status, "country": n.country, "country_code": getattr(n, "country_code", None),
            "latency": n.latency, "download_speed": n.download_speed, "score": n.score,
            "last_checked_at": n.last_checked_at, "fail_count": getattr(n, "fail_count", 0),
            "stream_flags": getattr(n, "stream_flags", None),  # 流媒体解锁标记（Netflix/Disney/YouTube 等）
        }
        d.update(repository.score_grade(n.score or 0))
        result.append(d)
    return result


@api_router.get("/nodes/stats")
@cached(ttl=5)
async def node_stats():
    """获取节点统计"""
    total = repository.count_nodes()
    active = repository.count_nodes(status=models.NodeStatus.ACTIVE.value)
    inactive = repository.count_nodes(status=models.NodeStatus.INACTIVE.value)
    unknown = repository.count_nodes(status=models.NodeStatus.UNKNOWN.value)
    
    # 按国家统计
    countries = {}
    with repository.get_connection() as conn:
        rows = conn.execute(
            "SELECT country, COUNT(*) as cnt FROM nodes WHERE status = ? GROUP BY country ORDER BY cnt DESC LIMIT 20",
            (models.NodeStatus.ACTIVE.value,)
        ).fetchall()
        for r in rows:
            if r[0]:
                countries[r[0]] = r[1]
    
    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "unknown": unknown,
        "countries": countries
    }


@api_router.get("/nodes/subscribe")
async def get_subscribe(
    fmt: str = Query("clash", pattern="^(clash|clash-meta|singbox|v2ray|base64|txt|mixed|surge|loon|qx)$"),
    limit: int = Query(5000, le=20000),
    min_score: float = Query(0, ge=0, le=100),
    min_speed: Optional[float] = Query(None, ge=0, description="最低速度 KB/s"),
    max_latency: Optional[int] = Query(None, ge=0, description="最大延迟 ms"),
    country: Optional[str] = Query(None),
    src: Optional[str] = Query(None, pattern="^(manual|auto)$", description="来源筛选"),
    proto: Optional[str] = Query(None, description="协议过滤：ss/vmess/vless/trojan/hysteria2/tuic/..."),
    status: str = Query("active", pattern="^(active|all|unknown)$", description="导出范围：active=仅可用，all=全池"),
    category: Optional[str] = Query(None, description="订阅分类：free/airport/premium/cf（大纲 4.3）")
):
    """获取多格式订阅链接（10 种格式 × 协议/状态/速度/延迟/分类多维筛选）"""
    from .subscribe import generate_by_format, EXPORT_CONTENT_TYPES

    if status == "all":
        # 全池导出（含 unknown/inactive），按评分降序、未测节点殿后
        nodes = repository.list_nodes(
            limit=limit, country=country, node_type=proto,
            sort="score", order="desc", source_type=src, category=category
        )
    else:
        # 活跃节点按评分降序
        nodes = repository.get_ranking(
            limit=limit, country=country, min_score=min_score,
            node_type=proto, source_type=src, category=category
        )

    # 内存过滤 min_speed / max_latency
    if min_speed is not None:
        nodes = [n for n in nodes if (n.download_speed or 0) >= min_speed * 1024]
    if max_latency is not None:
        nodes = [n for n in nodes if n.latency and n.latency <= max_latency]

    if not nodes:
        raise HTTPException(status_code=404, detail="No nodes available")

    content = generate_by_format(fmt, nodes)

    return Response(
        content=content,
        media_type=EXPORT_CONTENT_TYPES.get(fmt, "text/plain; charset=utf-8"),
        headers={"Cache-Control": "no-cache"}
    )


@api_router.post("/token/{token_id}/traffic-limit")
async def set_token_limit(token_id: int, limit_mb: float = Query(0, ge=0, le=1024*1024,
                          description="流量限额 MB，0=不限流（大纲 J.2）")):
    """设置 Token 流量限额；订阅访问累计超限时该 token 返回 429"""
    ok = repository.set_token_traffic_limit(token_id, limit_mb)
    if not ok:
        raise HTTPException(status_code=404, detail="Token 不存在")
    quota = repository.check_token_traffic_quota(token_id)
    return {"status": "ok", "id": token_id, "limit_mb": limit_mb, **quota}


@api_router.get("/token/{token_id}/quota")
async def get_token_quota(token_id: int):
    """查询 Token 当前流量用量与配额"""
    return {"status": "ok", **repository.check_token_traffic_quota(token_id)}


# ===== 排名接口 =====


@sub_router.get("/internal/manual", include_in_schema=False)
async def subscribe_internal_manual():
    """内部端点：手动导入节点聚合订阅（供 subs-check 每轮测速使用，不对外）"""
    from .subscribe import generate_by_format
    nodes = repository.list_nodes(
        limit=10000, sort="score", order="desc", source_type="manual"
    )
    if not nodes:
        return Response(content="", media_type="text/plain; charset=utf-8")
    content = generate_by_format("base64", nodes)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache"}
    )


@api_router.get("/settings/check-threshold")
async def get_check_threshold():
    """获取节点合格延迟阈值（ms）"""
    return {"status": "ok", "qualified_latency_ms": get_scheduler_config().get("qualified_latency_ms", 200)}


@api_router.post("/settings/check-threshold")
async def set_check_threshold(value: int = Query(..., ge=50, le=5000, description="合格延迟 ms")):
    """设置节点合格延迟阈值：测速后超过阈值的存活节点标记为 inactive（不出现在默认订阅）"""
    import yaml as _yaml
    path = os.path.join("config", "app.yaml")
    try:
        with open(path) as f:
            cfg = _yaml.safe_load(f) or {}
        cfg.setdefault("scheduler", {})["qualified_latency_ms"] = value
        with open(path, "w") as f:
            _yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {e}")
    return {"status": "ok", "qualified_latency_ms": value}


@api_router.post("/admin/apply-qualified-latency")
async def apply_qualified_latency():
    """按当前阈值立即重判现有 active 节点（无需等下轮测速）"""
    threshold = get_scheduler_config().get("qualified_latency_ms", 200)
    changed = repository.apply_qualified_latency(threshold)
    return {"status": "ok", "threshold_ms": threshold, "marked_inactive": changed}

# ===== 订阅短链路由 /sub/{token}/{format}（方案核心 API 设计）=====

@sub_router.get("/{token}/{fmt}")
async def subscribe_by_token(
    request: Request,
    token: str,
    fmt: str,
    limit: int = Query(5000, le=20000),
    min_score: float = Query(0, ge=0, le=100),
    min_speed: Optional[float] = Query(None, ge=0),
    max_latency: Optional[int] = Query(None, ge=0),
    country: Optional[str] = Query(None),
    src: Optional[str] = Query(None, pattern="^(manual|auto)$"),
    proto: Optional[str] = Query(None, description="协议过滤"),
    status: str = Query("active", pattern="^(active|all|unknown)$"),
    category: Optional[str] = Query(None, description="订阅分类：free/airport/premium/cf（按来源 category 过滤，大纲 4.3）")
):
    """Token 鉴权订阅输出：/sub/{token}/{clash|clash-meta|singbox|v2ray|base64|txt|mixed|surge|loon|qx}"""
    from .subscribe import generate_by_format, EXPORT_CONTENT_TYPES

    # Token 校验（无效/禁用/过期 → 401）
    info = repository.validate_token(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # 流量限额检查（大纲 J.2 按流量限制）：超限返回 429
    quota = repository.check_token_traffic_quota(info.get("id"))
    if not quota.get("allowed", True):
        raise HTTPException(status_code=429,
                            detail=f"Token 流量配额已用尽 ({quota['used_mb']:.1f}/{quota['limit_mb']:.0f} MB)")

    if status == "all":
        nodes = repository.list_nodes(
            limit=limit, country=country, node_type=proto,
            sort="score", order="desc", source_type=src, category=category
        )
    else:
        nodes = repository.get_ranking(
            limit=limit, country=country, min_score=min_score,
            node_type=proto, source_type=src, category=category
        )
    if min_speed is not None:
        nodes = [n for n in nodes if (n.download_speed or 0) >= min_speed * 1024]
    if max_latency is not None:
        nodes = [n for n in nodes if n.latency and n.latency <= max_latency]

    if not nodes:
        raise HTTPException(status_code=404, detail="No nodes available")

    try:
        content = generate_by_format(fmt, nodes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 访问统计（token 维度，附录：优化 #3）——失败不影响输出
    try:
        repository.log_sub_access(info.get("id"), f"/sub/{token[:8]}.../{fmt}",
                                  request.headers.get("user-agent", ""), len(content.encode()), len(nodes))
    except Exception:
        pass

    return Response(
        content=content,
        media_type=EXPORT_CONTENT_TYPES.get(fmt, "text/plain; charset=utf-8"),
        headers={"Cache-Control": "no-cache", "profile-update-interval": "6"}
    )


@api_router.post("/nodes/{node_id}/favorite")
async def toggle_node_favorite(node_id: int):
    """切换节点收藏（星标）；收藏节点在订阅输出中置顶"""
    try:
        fav = repository.toggle_favorite(node_id)
        return {"status": "ok", "id": node_id, "favorite": fav}
    except ValueError:
        raise HTTPException(status_code=404, detail="Node not found")


@api_router.get("/nodes/{node_id}/history")
async def get_node_history(node_id: int, days: int = Query(7, ge=1, le=30)):
    """单节点近 N 天健康趋势（延迟/速度/存活）"""
    return {"status": "ok", "node_id": node_id, "days": days,
            "points": repository.node_health_trend(node_id, days)}


@api_router.get("/tokens/stats")
async def get_token_stats():
    """订阅分发统计：按 token 汇总访问次数/流量/最近UA"""
    return {"status": "ok", "items": repository.token_access_stats()}


@api_router.get("/ranking")
@cached(ttl=3)
async def get_ranking(
    limit: int = Query(50, le=200),
    country: Optional[str] = Query(None),
    node_type: Optional[str] = Query(None),
    min_score: float = Query(0, ge=0, le=100),
    offset: int = Query(0, ge=0)
):
    """获取节点排名（按评分降序）"""
    nodes = repository.get_ranking(
        limit=limit,
        country=country,
        node_type=node_type,
        min_score=min_score,
        offset=offset
    )
    # 附带质量等级标签（附录 H.2）
    enriched = []
    for n in nodes:
        d = dict(n.__dict__) if hasattr(n, "__dict__") else dict(n)
        d.update(repository.score_grade(d.get("score") or 0))
        enriched.append(d)
    stats = repository.get_ranking_stats()
    return {
        "nodes": enriched,
        "stats": stats,
        "limit": limit,
        "offset": offset
    }


@api_router.post("/ranking/refresh")
async def refresh_ranking():
    """重新计算所有节点评分"""
    from ..schema.repository import update_node_scores
    count = update_node_scores()
    return {"status": "ok", "updated": count}


# ===== 检查任务接口 =====

@api_router.post("/check/run")
async def run_check(
    trigger: str = "manual",
    mode: str = Query("speed", description="测速维度: latency=仅延迟 / speed=延迟+速度 / full=全量含流媒体"),
    overrides: Optional[Dict] = Body(None, description="可选参数覆盖: concurrent/timeout/min-speed/download-mb/download-timeout/speed-concurrent 等"),
):
    """触发一次测速：manual=前台(页面实时进度) / scheduled=后台(定时调度同款)
    mode 可选测试维度；overrides 仅接受白名单键"""
    if trigger not in ("manual", "scheduled"):
        raise HTTPException(status_code=400, detail="trigger must be manual|scheduled")
    if mode not in ("latency", "speed", "full"):
        raise HTTPException(status_code=400, detail="mode must be latency|speed|full")
    ck = scheduler.checker
    if ck.current_job and ck.current_job.get("status") == "running":
        return {"status": "already_running", "job_id": ck.current_job["job_id"],
                "source": ck.current_job["source"]}
    import asyncio
    asyncio.create_task(ck.run_check(trigger=trigger, mode=mode,
                                     overrides=overrides if isinstance(overrides, dict) else None))
    return {"status": "started", "trigger": trigger, "mode": mode}


@api_router.get("/check/progress")
async def check_progress():
    """当前/最近一次测速任务的实时进度（前台手动与后台定时共用）"""
    return await scheduler.checker.get_progress()


@api_router.get("/check/history")
@cached(ttl=3)
async def check_history(limit: int = 10):
    """获取检查历史"""
    with repository.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM check_jobs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@api_router.get("/check/jobs/{job_id}")
async def check_job_detail(job_id: int):
    """获取单个测速任务详情/进度（方案核心 API：GET /api/speedtest/{job}）"""
    job = repository.get_check_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@api_router.get("/version")
async def get_version():
    """版本信息（前端 logo 动态展示）"""
    cfg = get_app_config()
    return {"name": cfg.get("name", "Sanl"),
            "version": cfg.get("version", "1.0.0")}


@api_router.get("/stats/trend")
@cached(ttl=5)
async def stats_trend(limit: int = Query(30, le=100)):
    """测速历史趋势（方案 Phase 3：定时全量测速 + 历史趋势）"""
    return repository.get_score_trend(limit)


@api_router.post("/sources/{source_id}/fetch")
async def fetch_single_source(source_id: int, trigger_check: bool = False):
    """手动触发单源抓取+导入（指纹去重入库）；trigger_check=true 时同时触发全量测速"""
    source = repository.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if not source.enabled:
        raise HTTPException(status_code=400, detail="Source is disabled")

    from ..scheduler.pool_importer import run_pool_import
    try:
        summary = await run_pool_import(source_id=source_id)
        if summary["sources_ok"] > 0:
            result = {"status": "ok", "parsed": summary["parsed"],
                      "inserted": summary["inserted"], "updated": summary["updated"],
                      "cf_endpoints": summary["cf_endpoints"]}
        else:
            result = {"status": "failed",
                      "error": (summary["errors"][0] if summary["errors"] else "unknown")}
    except Exception as e:
        result = {"status": "failed", "error": str(e)[:200]}

    if trigger_check and result.get("status") == "ok":
        import asyncio
        asyncio.create_task(scheduler.checker.run_check())
        result["check_triggered"] = True
    return result


@api_router.post("/geoip/refresh")
async def geoip_refresh(limit: int = Query(300, le=1000)):
    """刷新节点 GeoIP 出口识别（ip-api.com 免费接口，方案 Phase 3 / 附录 I）"""
    from ..geoip import refresh_node_geo
    result = await refresh_node_geo(limit=limit)
    return result


# ===== Phase 2: Token 鉴权系统 =====

class TokenCreate(BaseModel):
    name: str = "default"
    permissions: str = "read"
    user_id: Optional[int] = None
    expired_at: Optional[int] = None  # Unix 时间戳，None=永久（附录 J 过期机制）


@api_router.post("/tokens")
async def create_new_token(token_data: TokenCreate):
    """创建新 Token（支持过期时间）"""
    token_str = "np_" + __import__('secrets').token_hex(32)
    t = repository.create_token(
        user_id=token_data.user_id,
        token_str=token_str,
        name=token_data.name,
        permissions=token_data.permissions,
        expired_at=token_data.expired_at
    )
    if not t:
        raise HTTPException(status_code=500, detail="Failed to create token")
    return {"id": t.id, "token": t.token, "name": t.name, "permissions": t.permissions, "expired_at": t.expired_at}


class TokenRefreshRequest(BaseModel):
    token: str
    renew_days: Optional[int] = Field(None, ge=1, le=3650, description="强制续期时间（天）：从当前时间起算，覆盖原过期时间")


@api_router.post("/token/refresh")
async def refresh_token(req: TokenRefreshRequest):
    """轮换 Token：旧 token 立即失效，生成同权限新 token（附录 J.2 刷新接口）。
    传 renew_days 时强制续期（新过期时间 = now + N 天）；不传则沿用原过期时间。"""
    import secrets as _secrets
    old = repository.get_token_by_value(req.token)
    if not old or not old.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive token")
    new_token = "np_" + _secrets.token_hex(32)
    # 强制续期：renew_days 从当前时间重新起算；否则沿用旧 expired_at
    new_expired = (int(__import__('time').time()) + req.renew_days * 86400) if req.renew_days else old.expired_at
    t = repository.create_token(
        user_id=old.user_id, token_str=new_token, name=old.name,
        permissions=old.permissions, expired_at=new_expired
    )
    repository.delete_token(old.id)
    return {"token": new_token, "name": old.name, "permissions": old.permissions, "expired_at": new_expired}


@api_router.get("/tokens")
async def list_all_tokens():
    """获取所有 Token"""
    tokens = repository.list_tokens()
    # 隐藏完整 token，只显示前 8 位
    for t in tokens:
        if len(t["token"]) > 8:
            t["token_preview"] = t["token"][:8] + "..." + t["token"][-4:]
    return tokens


@api_router.put("/tokens/{token_id}/toggle")
async def toggle_token(token_id: int, is_active: bool = True):
    """启用/禁用 Token"""
    repository.toggle_token_active(token_id, 1 if is_active else 0)
    return {"status": "ok"}


@api_router.delete("/tokens/{token_id}")
async def delete_token(token_id: int):
    """删除 Token"""
    repository.delete_token(token_id)
    return {"status": "ok"}


@api_router.get("/tokens/validate")
async def validate_token(request: Request):
    """验证当前请求携带的 Token"""
    from ..auth import get_current_user
    auth_info = await get_current_user(request)
    if auth_info["authenticated"]:
        return {"valid": True, "method": auth_info["method"], "token": auth_info["token"]}
    return {"valid": False}


# ===== 世界地图数据 =====

@api_router.get("/cache/status")
async def cache_status():
    """缓存命中率（管理面板用，用于验证缓存是否生效、命中率高低）"""
    return cache_stats()


@api_router.get("/map")
@cached(ttl=5)
async def get_map_data():
    """获取世界地图可视化数据"""
    from ..mapdata import get_map_data
    nodes = repository.list_nodes(status="active", limit=1000)
    nodes_list = []
    for n in nodes:
        nodes_list.append({
            "id": n.id,
            "node_name": n.node_name,
            "country": n.country,
            "score": n.score,
            "download_speed": n.download_speed,
            "latency": n.latency
        })
    return get_map_data(nodes_list)


@api_router.get("/map/countries")
async def get_country_list():
    """获取国家列表（含坐标）"""
    from ..mapdata import COUNTRY_COORDS
    return COUNTRY_COORDS


# ===== Phase 2: 增强数据源管理 =====

# 预置免费节点源
PRESET_SOURCES = [
    {"name": "Pawdroid/Free-servers", "url": "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/clash.yml", "type": "github"},
    {"name": "mahdibland/V2RayAggregator", "url": "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge_base64.txt", "type": "github"},
    {"name": "free-nodes/clashfree", "url": "https://raw.githubusercontent.com/free-nodes/clashfree/main/clash.yml", "type": "github"},
    {"name": "snakem982/proxypool", "url": "https://raw.githubusercontent.com/snakem982/proxypool/main/source/freenode", "type": "github"},
    {"name": "mermeroo/V2RAY-CLASH-BASE64", "url": "https://raw.githubusercontent.com/mermeroo/V2RAY-CLASH-BASE64/main/sub.txt", "type": "github"},
    {"name": "xiaoji235/airport-free", "url": "https://raw.githubusercontent.com/xiaoji235/airport-free/main/sub.txt", "type": "github"},
    {"name": "paidki/FreeNodes", "url": "https://raw.githubusercontent.com/paidki/FreeNodes/main/sub.txt", "type": "github"},
    {"name": "pepslsub/free", "url": "https://raw.githubusercontent.com/pepslsub/free/main/sub", "type": "github"},
    {"name": "Alvin9999/pac2", "url": "https://raw.githubusercontent.com/Alvin9999/pac2/master/clash.meta.yaml", "type": "github"},
    {"name": "ripaojiedian/freenode", "url": "https://raw.githubusercontent.com/ripaojiedian/freenode/main/clash.yaml", "type": "github"},
    {"name": "chengdoudou/free-node", "url": "https://raw.githubusercontent.com/chengdoudou/free-node/main/clash.txt", "type": "github"},
    {"name": "RUNBLACK/clashnode", "url": "https://raw.githubusercontent.com/RUNBLACK/clashnode/main/clashnode.yml", "type": "github"},
    {"name": "zlccccc/ProxyPool", "url": "https://raw.githubusercontent.com/zlccccc/ProxyPool/main/sub/sub_merge.txt", "type": "github"},
    {"name": "aiboboxx/clashfree", "url": "https://raw.githubusercontent.com/aiboboxx/clashfree/main/clash.yml", "type": "github"},
    {"name": "huyz2023/free-proxy", "url": "https://raw.githubusercontent.com/huyz2023/free-proxy/main/sub.txt", "type": "github"},
    {"name": "LancelotRar/best-cf-ipv4", "url": "https://raw.githubusercontent.com/LancelotRar/best-cf-ips/main/best-cf-ipv4.txt", "type": "github"},
    {"name": "LancelotRar/best-cf-domain", "url": "https://raw.githubusercontent.com/LancelotRar/best-cf-ips/main/best-cf-domain.txt", "type": "github"},
    {"name": "BestCF-CMCC", "url": "https://090227.pages.dev/bestcf?isp=cmcc&ips=100", "type": "http"},
    {"name": "BestCF-US", "url": "https://bestcf.pages.dev/random-region/US/all.txt", "type": "http"},
    {"name": "BestCF-JP", "url": "https://bestcf.pages.dev/random-region/JP/all.txt", "type": "http"},
    {"name": "BestCF-TW", "url": "https://bestcf.pages.dev/random-region/TW/all.txt", "type": "http"},
    {"name": "BestCF-HK", "url": "https://bestcf.pages.dev/random-region/HK/all.txt", "type": "http"},
    {"name": "BestCF-MO", "url": "https://bestcf.pages.dev/random-region/MO/all.txt", "type": "http"},
    {"name": "BestCF-RU", "url": "https://bestcf.pages.dev/random-region/RU/all.txt", "type": "http"},
    {"name": "CF-090227-8ips", "url": "https://cf.090227.xyz/cmcc?ips=8", "type": "http"},
    {"name": "static-youxuan", "url": "data:static/youxuan.txt", "type": "static"},
    {"name": "static-visa", "url": "data:static/visa.txt", "type": "static"},
    {"name": "static-shopify", "url": "data:static/shopify.txt", "type": "static"},
    {"name": "static-ubi", "url": "data:static/ubi.txt", "type": "static"},
    {"name": "static-nexusmods", "url": "data:static/nexusmods.txt", "type": "static"},
    {"name": "static-timeis", "url": "data:static/timeis.txt", "type": "static"},
    {"name": "static-icook", "url": "data:static/icook.txt", "type": "static"},
    {"name": "static-bestcf-mingyu", "url": "data:static/bestcf_mingyu.txt", "type": "static"},
    {"name": "static-cdn-2020111", "url": "data:static/cdn_2020111.txt", "type": "static"},
    {"name": "static-cfip-1323123", "url": "data:static/cfip_1323123.txt", "type": "static"},
    {"name": "static-cfip-cfcdn", "url": "data:static/cfip_cfcdn.txt", "type": "static"},
    {"name": "static-cloudflare-182682", "url": "data:static/cloudflare_182682.txt", "type": "static"},
    {"name": "static-cloudflare-dl", "url": "data:static/cloudflare_dl.txt", "type": "static"},
    {"name": "static-cloudflare-ip", "url": "data:static/cloudflare_ip.txt", "type": "static"},
    {"name": "static-fn-130519", "url": "data:static/fn_130519.txt", "type": "static"},
    {"name": "static-freeyx", "url": "data:static/freeyx.txt", "type": "static"},
    {"name": "static-nrt", "url": "data:static/nrt.txt", "type": "static"},
    {"name": "static-nrtcfdns", "url": "data:static/nrtcfdns.txt", "type": "static"},
    {"name": "static-saas", "url": "data:static/saas.txt", "type": "static"},
    {"name": "static-tencentapp", "url": "data:static/tencentapp.txt", "type": "static"},
    {"name": "static-cf3666888", "url": "data:static/cf_3666888.txt", "type": "static"},
    {"name": "static-blogluo", "url": "data:static/blogluo.txt", "type": "static"},
    {"name": "static-eteaf", "url": "data:static/eteaf.txt", "type": "static"},
    {"name": "static-1cf", "url": "data:static/1cf.txt", "type": "static"},
    {"name": "static-cf1s", "url": "data:static/cf1s.txt", "type": "static"},
    {"name": "static-avido", "url": "data:static/avido.txt", "type": "static"},
    {"name": "static-cdncf", "url": "data:static/cdncf.txt", "type": "static"},
    {"name": "static-youxuan2", "url": "data:static/youxuan2.txt", "type": "static"},
    {"name": "static-uac", "url": "data:static/uac.txt", "type": "static"},
    {"name": "static-mfyx", "url": "data:static/mfyx.txt", "type": "static"},
    {"name": "static-cdn7zz", "url": "data:static/cdn7zz.txt", "type": "static"},
    {"name": "static-cdn204910", "url": "data:static/cdn204910.txt", "type": "static"},
    {"name": "static-qocu", "url": "data:static/qocu.txt", "type": "static"},
    {"name": "static-cf123", "url": "data:static/cf123.txt", "type": "static"},
    {"name": "static-cfvip", "url": "data:static/cfvip.txt", "type": "static"},
    {"name": "static-4cf", "url": "data:static/4cf.txt", "type": "static"},
    {"name": "static-777ai", "url": "data:static/777ai.txt", "type": "static"},
]


class BatchImportSources(BaseModel):
    source_ids: List[int]  # 预置源索引


@api_router.get("/sources/presets")
async def list_preset_sources():
    """获取预置免费节点源列表"""
    # 标记已存在的源
    existing = repository.list_sources(enabled_only=False)
    existing_urls = {s.url for s in existing}
    result = []
    for i, src in enumerate(PRESET_SOURCES):
        result.append({
            "index": i,
            "name": src["name"],
            "url": src["url"],
            "type": src["type"],
            "already_added": src["url"] in existing_urls
        })
    return result


@api_router.post("/sources/batch-import")
async def batch_import_sources(import_data: BatchImportSources):
    """批量导入预置数据源"""
    imported = []
    skipped = []
    errors = []
    for idx in import_data.source_ids:
        if idx < 0 or idx >= len(PRESET_SOURCES):
            errors.append({"index": idx, "error": "Invalid index"})
            continue
        src = PRESET_SOURCES[idx]
        try:
            s = repository.add_source(src["name"], src["url"], src["type"])
            if s:
                imported.append({"name": src["name"], "id": s.id})
            else:
                skipped.append({"name": src["name"], "reason": "Already exists"})
        except Exception as e:
            errors.append({"name": src["name"], "error": str(e)})
    return {"imported": imported, "skipped": skipped, "errors": errors}


class RawImportSource(BaseModel):
    name: str
    content: str  # Base64 编码的订阅内容
    source_type: str = "raw"


@api_router.post("/sources/raw-import")
async def raw_import_source(raw_data: RawImportSource):
    """通过粘贴内容导入数据源"""
    import base64
    try:
        # 解码 Base64 内容
        decoded = base64.b64decode(raw_data.content).decode("utf-8")
        # 保存到临时文件
        import tempfile
        import hashlib
        content_hash = hashlib.md5(raw_data.content.encode()).hexdigest()[:8]
        tmp_path = os.path.join(os.path.dirname(repository.DB_PATH), "..", "data", f"raw_{content_hash}.txt")
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "w") as f:
            f.write(decoded)
        # 添加为数据源
        s = repository.add_source(raw_data.name, f"file://{tmp_path}", raw_data.source_type)
        if s:
            return {"status": "ok", "source": {"id": s.id, "name": s.name}}
        return {"status": "error", "error": "Failed to create source"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to import: {str(e)}")


@api_router.get("/sources/health")
@cached(ttl=5)
async def get_sources_health():
    """获取数据源健康度报告
    状态语义（修复：原逻辑把 last_status==0 未抓取当健康必要条件，导致正常源全标红）：
    - last_status=0 → pending 待抓取（新源尚未轮到调度，中性状态）
    - last_status=1 且启用 → healthy 健康（最近一次抓取成功）
    - 启用但 fail_count>=3 或禁用 → unhealthy 异常
    """
    sources = repository.list_sources(enabled_only=False)
    health = []
    for s in sources:
        if s.enabled == 1 and s.last_status == 1:
            state = "healthy"
        elif s.last_status == 0 and (s.fail_count or 0) < 3:
            state = "pending"
        else:
            state = "unhealthy"
        health.append({
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "enabled": bool(s.enabled),
            "node_count": s.node_count,
            "last_status": s.last_status,
            "last_fetched_at": s.last_fetched_at,
            "fail_count": s.fail_count,
            "state": state,
            "healthy": state == "healthy"
        })
    return health


@api_router.get("/tasks")
async def get_tasks():
    """全局任务进度（抓取/测速等后台任务统一视图，前端进度条数据源）"""
    from ..utils.taskmgr import task_manager
    return {"active": task_manager.get_active(), "recent": task_manager.get_recent(3)}


@api_router.post("/sources/fetch-all")
async def fetch_all_sources_now(background: BackgroundTasks):
    """立即触发全量源抓取（不等每6h定时；新导入的源马上验证可用性）"""
    from ..scheduler.pool_importer import run_pool_import
    from ..scraper.scraper import Scraper

    async def _job():
        sc = Scraper()
        try:
            summary = await run_pool_import(sc)
            logger.info(f"Manual fetch-all done: {summary.get('sources_ok', 0)} ok / {summary.get('sources_failed', 0)} failed")
        finally:
            await sc.close()
    background.add_task(_job)
    return {"status": "ok", "message": "全量抓取已启动，稍后刷新查看各源节点数"}


# ===== 源站 API 代理 =====

@api_router.get("/subs-check/{path:path}")
async def proxy_to_subs_check(path: str):
    """代理到 subs-check API"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://127.0.0.1:8199/{path}", follow_redirects=True)
        return JSONResponse(content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text, 
                          status_code=resp.status_code)