"""
FastAPI 主应用
"""
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, Response
from fastapi.routing import APIRouter
from pydantic import BaseModel
from typing import List, Optional

from ..config import get_app_config
from ..schema import repository, models
from ..scheduler.scheduler import Scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global scheduler
    
    # 启动时初始化
    logger.info("Initializing NodePool...")
    repository.init_db()
    
    scheduler = Scheduler()
    scheduler.start()
    
    yield
    
    # 关闭时清理
    if scheduler:
        scheduler.shutdown()
    logger.info("NodePool stopped")


def create_app() -> FastAPI:
    app_config = get_app_config()
    
    app = FastAPI(
        title=app_config.get("name", "NodePool"),
        version=app_config.get("version", "1.0.0"),
        description="免费节点池聚合平台",
        lifespan=lifespan
    )
    
    # 挂载静态文件
    static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # 主页
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return FileResponse(os.path.join(static_dir, "index.html"))
    
    # 包含路由
    app.include_router(api_router, prefix="/api")
    app.include_router(sub_router, prefix="/sub", tags=["subscription"])
    
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
async def list_sources(enabled: bool = True):
    """获取数据源列表"""
    return repository.list_sources(enabled_only=enabled)


@api_router.put("/sources/{source_id}/enable")
async def toggle_source(source_id: int, enabled: bool = True):
    """启用/禁用数据源"""
    repository.enable_source(source_id, 1 if enabled else 0)
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
    """批量手动导入节点：支持多行协议链接 / Clash YAML / Base64 订阅内容"""
    from .importer import parse_content
    result = parse_content(req.content)
    if not result["nodes"]:
        raise HTTPException(status_code=400, detail="；".join(result["errors"]) or "无可识别的节点")

    src = repository.get_or_create_manual_source(req.label)
    imported, skipped = 0, 0
    for ntype, data, name in result["nodes"]:
        try:
            # 同源同名同地址去重
            existing = repository.list_nodes(source_type="manual", limit=5000)
            if any(n.node_name == name and (n.node_data or {}).get("server") == data.get("server")
                   for n in existing):
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


# ===== 节点接口 =====

@api_router.get("/nodes", response_model=List[models.Node])
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
        }
        d.update(repository.score_grade(n.score or 0))
        result.append(d)
    return result


@api_router.get("/nodes/stats")
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
    fmt: str = Query("clash", pattern="^(clash|singbox|v2ray|base64)$"),
    limit: int = Query(200, le=2000),
    min_score: float = Query(0, ge=0, le=100),
    min_speed: Optional[float] = Query(None, ge=0, description="最低速度 KB/s"),
    max_latency: Optional[int] = Query(None, ge=0, description="最大延迟 ms"),
    country: Optional[str] = Query(None),
    src: Optional[str] = Query(None, pattern="^(manual|auto)$", description="来源筛选")
):
    """获取多格式订阅链接（支持 min_speed/max_latency 筛选，方案 4.3 节）"""
    from .subscribe import generate_clash, generate_v2ray, generate_singbox, generate_base64

    # 获取活跃节点，按评分降序（src: manual=手动导入, auto=系统抓取, None=聚合全部）
    nodes = repository.get_ranking(
        limit=limit,
        country=country,
        min_score=min_score,
        source_type=src
    )

    # 内存过滤 min_speed / max_latency（ranking 不支持的维度）
    if min_speed is not None:
        nodes = [n for n in nodes if (n.download_speed or 0) >= min_speed * 1024]
    if max_latency is not None:
        nodes = [n for n in nodes if n.latency and n.latency <= max_latency]

    if not nodes:
        raise HTTPException(status_code=404, detail="No nodes available")

    generators = {
        "clash": generate_clash,
        "v2ray": generate_v2ray,
        "singbox": generate_singbox,
        "base64": generate_base64,
    }

    content = generators[fmt](nodes)

    media_types = {
        "clash": "text/plain; charset=utf-8",
        "v2ray": "text/plain; charset=utf-8",
        "singbox": "application/json; charset=utf-8",
        "base64": "text/plain; charset=utf-8",
    }

    return Response(
        content=content,
        media_type=media_types.get(fmt, "text/plain"),
        headers={"Cache-Control": "no-cache"}
    )


# ===== 排名接口 =====

# ===== 订阅短链路由 /sub/{token}/{format}（方案核心 API 设计）=====

@sub_router.get("/{token}/{fmt}")
async def subscribe_by_token(
    token: str,
    fmt: str,
    limit: int = Query(200, le=2000),
    min_score: float = Query(0, ge=0, le=100),
    min_speed: Optional[float] = Query(None, ge=0),
    max_latency: Optional[int] = Query(None, ge=0),
    country: Optional[str] = Query(None),
    src: Optional[str] = Query(None, pattern="^(manual|auto)$")
):
    """Token 鉴权订阅输出：/sub/np_xxx/clash?v2ray|singbox|base64
    支持筛选参数 min_speed/max_latency/src（聚合手动+系统全部节点）"""
    from .subscribe import generate_clash, generate_v2ray, generate_singbox, generate_base64

    # Token 校验（无效/禁用/过期 → 401）
    info = repository.validate_token(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    nodes = repository.get_ranking(limit=limit, country=country, min_score=min_score, source_type=src)
    if min_speed is not None:
        nodes = [n for n in nodes if (n.download_speed or 0) >= min_speed * 1024]
    if max_latency is not None:
        nodes = [n for n in nodes if n.latency and n.latency <= max_latency]

    if not nodes:
        raise HTTPException(status_code=404, detail="No nodes available")

    generators = {"clash": generate_clash, "v2ray": generate_v2ray,
                  "singbox": generate_singbox, "base64": generate_base64}
    if fmt not in generators:
        raise HTTPException(status_code=400, detail="fmt must be clash|v2ray|singbox|base64")

    return Response(
        content=generators[fmt](nodes),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "profile-update-interval": "6"}
    )


@api_router.get("/ranking")
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
async def run_check():
    """手动触发一次检查（后台异步执行，立即返回）"""
    import asyncio
    task = asyncio.create_task(scheduler.checker.run_check())
    return {"status": "started", "task_id": str(task.get_coro().__name__) if hasattr(task, 'get_coro') else "async"}


@api_router.get("/check/history")
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


@api_router.get("/stats/trend")
async def stats_trend(limit: int = Query(30, le=100)):
    """测速历史趋势（方案 Phase 3：定时全量测速 + 历史趋势）"""
    return repository.get_score_trend(limit)


@api_router.post("/sources/{source_id}/fetch")
async def fetch_single_source(source_id: int, trigger_check: bool = False):
    """手动触发单源抓取验证（方案核心 API：POST /api/sources/{id}/fetch）
    验证源可达性并更新健康度；trigger_check=true 时同时触发全量测速拉取新源节点"""
    source = repository.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if not source.enabled:
        raise HTTPException(status_code=400, detail="Source is disabled")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(source.url, headers={"User-Agent": "Mozilla/5.0 NodePool/2.0"})
        ok = resp.status_code == 200 and len(resp.text) > 50
        if ok:
            repository.record_source_success(source_id)
            repository.update_source_status(source_id, 0)
            result = {"status": "ok", "http": resp.status_code, "size": len(resp.text)}
        else:
            repository.record_source_failure(source_id)
            result = {"status": "unhealthy", "http": resp.status_code}
    except Exception as e:
        repository.record_source_failure(source_id)
        result = {"status": "failed", "error": str(e)[:200]}

    if trigger_check and result["status"] == "ok":
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


@api_router.post("/token/refresh")
async def refresh_token(req: TokenRefreshRequest):
    """轮换 Token：旧 token 立即失效，生成同权限新 token（附录 J.2 刷新接口）"""
    import secrets as _secrets
    old = repository.get_token_by_value(req.token)
    if not old or not old.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive token")
    new_token = "np_" + _secrets.token_hex(32)
    t = repository.create_token(
        user_id=old.user_id, token_str=new_token, name=old.name,
        permissions=old.permissions, expired_at=old.expired_at
    )
    repository.delete_token(old.id)
    return {"token": new_token, "name": old.name, "permissions": old.permissions}


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


# ===== Phase 2: 多用户系统 =====

class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


@api_router.post("/auth/register")
async def register_user(user_data: UserRegister):
    """注册新用户"""
    from ..auth import hash_password
    if len(user_data.username) < 2:
        raise HTTPException(status_code=400, detail="Username too short")
    if len(user_data.password) < 6:
        raise HTTPException(status_code=400, detail="Password too short (min 6 chars)")

    user = repository.create_user(
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        role="user"
    )
    if not user:
        raise HTTPException(status_code=400, detail="Username already exists")
    return {"id": user.id, "username": user.username, "role": user.role}


@api_router.post("/auth/login")
async def login_user(user_data: UserLogin):
    """用户登录"""
    from ..auth import verify_password, generate_token
    user = repository.get_user_by_username(user_data.username)
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # 登录成功，生成临时会话 token
    session_token = "sess_" + __import__('secrets').token_hex(24)
    repository.create_token(
        user_id=user.id,
        token_str=session_token,
        name="session",
        permissions="read"
    )
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "token": session_token
    }


@api_router.get("/users")
async def list_users():
    """列出所有用户"""
    return repository.list_users()


@api_router.put("/users/{user_id}/role")
async def change_user_role(user_id: int, role: str = "user"):
    """修改用户角色"""
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    repository.update_user_role(user_id, role)
    return {"status": "ok"}


@api_router.put("/users/{user_id}/toggle")
async def toggle_user(user_id: int, is_active: bool = True):
    """启用/禁用用户"""
    repository.toggle_user_active(user_id, 1 if is_active else 0)
    return {"status": "ok"}


# ===== Phase 2: 世界地图数据 =====

@api_router.get("/map")
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
async def get_sources_health():
    """获取数据源健康度报告"""
    sources = repository.list_sources(enabled_only=False)
    health = []
    for s in sources:
        health.append({
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "enabled": bool(s.enabled),
            "node_count": s.node_count,
            "last_status": s.last_status,
            "last_fetched_at": s.last_fetched_at,
            "healthy": s.enabled == 1 and s.last_status == 0
        })
    return health


# ===== 源站 API 代理 =====

@api_router.get("/subs-check/{path:path}")
async def proxy_to_subs_check(path: str):
    """代理到 subs-check API"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://127.0.0.1:8199/{path}", follow_redirects=True)
        return JSONResponse(content=resp.json() if resp.headers.get('content-type', '').startswith('application/json') else resp.text, 
                          status_code=resp.status_code)