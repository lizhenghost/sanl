import sqlite3
import json
import logging
import os
from contextlib import contextmanager
from typing import List, Optional

from .models import Source, Node, CheckJob, NodeStatus, User, Token
from ..config import get_config

logger = logging.getLogger(__name__)

DB_PATH = None


def _migrate(conn):
    """增量迁移：为已有库补新列（幂等）"""
    def add_column(table, column, decl):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    add_column("nodes", "country_code", "TEXT")
    add_column("nodes", "fail_count", "INTEGER NOT NULL DEFAULT 0")
    add_column("sources", "fail_count", "INTEGER NOT NULL DEFAULT 0")
    add_column("sources", "category", "TEXT DEFAULT 'free'")
    add_column("nodes", "fingerprint", "TEXT")
    add_column("nodes", "last_seen_at", "INTEGER")

    # 回填历史行的节点指纹（NULL 指纹会让 NOT IN 失效、造成重复插入）
    null_rows = conn.execute(
        "SELECT id, node_type, node_data FROM nodes WHERE fingerprint IS NULL"
    ).fetchall()
    if null_rows:
        for r in null_rows:
            try:
                data = json.loads(r["node_data"] or "{}")
                fp = node_fingerprint(r["node_type"], data)
            except Exception:
                continue
            dup = conn.execute(
                "SELECT id FROM nodes WHERE fingerprint = ? AND id != ?", (fp, r["id"])
            ).fetchone()
            if dup:
                # 同指纹重复行：保留较小 id，删除较大 id
                keep_id, drop_id = min(dup["id"], r["id"]), max(dup["id"], r["id"])
                conn.execute("DELETE FROM nodes WHERE id = ?", (drop_id,))
                conn.execute("UPDATE nodes SET fingerprint = ? WHERE id = ?", (fp, keep_id))
            else:
                conn.execute("UPDATE nodes SET fingerprint = ? WHERE id = ?", (fp, r["id"]))
        conn.commit()

    # 节点指纹唯一索引（回填后清理历史重复行：同指纹保留最小 id）
    conn.execute("""
        DELETE FROM nodes WHERE fingerprint IS NOT NULL AND id NOT IN (
            SELECT MIN(id) FROM nodes WHERE fingerprint IS NOT NULL GROUP BY fingerprint
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_fingerprint ON nodes(fingerprint)")

    # CF 优选端点表（ip/domain:port 列表，非代理节点，独立管理）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cf_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 443,
            remark TEXT,
            source_id INTEGER,
            last_seen_at INTEGER,
            UNIQUE(host, port)
        )
    """)
    conn.commit()


# ===== 节点指纹 / 批量 Upsert =====

def node_fingerprint(node_type: str, data: dict) -> str:
    """稳定唯一键：type|server|port|凭据 —— 用于跨源去重与测试结果回填"""
    t = (node_type or "").lower().strip()
    server = str(data.get("server", "")).strip().lower()
    port = int(data.get("port", 0) or 0)
    cred = (data.get("password") or data.get("uuid") or data.get("public-key")
            or data.get("psk") or data.get("auth-str") or "")
    if not cred and t in ("ss", "ssr"):
        cred = f"{data.get('cipher', data.get('method', ''))}:{data.get('password', '')}"
    if t in ("socks5", "socks", "http") and not cred:
        cred = f"{data.get('username', '')}:{data.get('password', '')}"
    raw = f"{t}|{server}|{port}|{cred}"
    import hashlib
    return hashlib.md5(raw.encode()).hexdigest()


def upsert_nodes_bulk(items: List[dict]) -> dict:
    """
    批量写入节点（单事务，池导入专用）。
    items: [{subscribe_url, source_id, node_name, node_type, node_data}]
    返回 {inserted, updated}（以事务前后总行数差判定新插入数）
    """
    now = int(__import__('time').time())
    with get_connection() as conn:
        before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        for it in items:
            fp = node_fingerprint(it["node_type"], it["node_data"])
            conn.execute(
                """INSERT INTO nodes (subscribe_url, source_id, node_name, node_type,
                                      node_data, status, fingerprint, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, 'unknown', ?, ?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                       source_id   = excluded.source_id,
                       subscribe_url = excluded.subscribe_url,
                       node_name   = CASE WHEN excluded.node_name != '' THEN excluded.node_name ELSE nodes.node_name END,
                       node_data   = excluded.node_data,
                       last_seen_at = excluded.last_seen_at""",
                (it["subscribe_url"], it["source_id"], it["node_name"],
                 it["node_type"], json.dumps(it["node_data"]), fp, now)
            )
        after = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        conn.commit()
    inserted = max(0, after - before)
    return {"inserted": inserted, "updated": max(0, len(items) - inserted)}


def mark_missing_inactive(active_fps: set, include_manual: bool = False):
    """把不在 active_fps 里的节点置为 inactive（默认只处理自动抓取节点，手动导入永不降级）"""
    if not active_fps:
        return 0
    fps = list(active_fps)[:20000]
    placeholders = ",".join("?" * len(fps))
    manual_filter = "" if include_manual else \
        " AND (source_id IS NULL OR source_id NOT IN (SELECT id FROM sources WHERE source_type = 'manual'))"
    with get_connection() as conn:
        cur = conn.execute(
            f"""UPDATE nodes SET status = 'inactive', updated_at = ?
                WHERE status IN ('active') AND fingerprint NOT IN ({placeholders}){manual_filter}""",
            [int(__import__('time').time())] + fps
        )
        n = cur.rowcount
        conn.commit()
    return n


def apply_check_results(results: List[dict]) -> dict:
    """
    测速结果回填（不删任何节点）。
    results: [{node_type, node_data, node_name, download_speed?, latency?, country?}]
    来自 subs-check all.yaml 的存活节点。匹配指纹 → status=active + 指标更新；
    未匹配的旧 active → inactive（仅 auto 源，手动导入永不降级）。
    返回 {alive, marked_inactive}
    """
    now = int(__import__('time').time())
    alive = len(results)
    with get_connection() as conn:
        for r in results:
            fp = node_fingerprint(r["node_type"], r["node_data"])
            conn.execute(
                """INSERT INTO nodes (subscribe_url, source_id, node_name, node_type, node_data,
                                      status, fingerprint, download_speed, latency, country,
                                      last_checked_at, last_seen_at)
                   VALUES ('subs-check://alive', NULL, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                       status = 'active',
                       fail_count = 0,
                       node_name = CASE WHEN excluded.node_name != '' THEN excluded.node_name ELSE nodes.node_name END,
                       download_speed = COALESCE(excluded.download_speed, nodes.download_speed),
                       latency = COALESCE(excluded.latency, nodes.latency),
                       country = COALESCE(excluded.country, nodes.country),
                       last_checked_at = excluded.last_checked_at,
                       last_seen_at = excluded.last_seen_at""",
                (r.get("node_name", ""), r["node_type"], json.dumps(r["node_data"]), fp,
                 r.get("download_speed"), r.get("latency"), r.get("country"), now, now)
            )
        conn.commit()

    fps = {node_fingerprint(r["node_type"], r["node_data"]) for r in results}
    marked = mark_missing_inactive(fps)
    return {"alive": alive, "marked_inactive": marked}


def get_cf_endpoints(limit: int = 5000) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT host, port, remark, source_id, last_seen_at FROM cf_endpoints ORDER BY id LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_cf_endpoints(items: List[dict], source_id: Optional[int] = None) -> int:
    """items: [{host, port, remark}]"""
    now = int(__import__('time').time())
    n = 0
    with get_connection() as conn:
        for it in items:
            try:
                conn.execute(
                    """INSERT INTO cf_endpoints (host, port, remark, source_id, last_seen_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(host, port) DO UPDATE SET
                           remark = CASE WHEN excluded.remark != '' THEN excluded.remark ELSE cf_endpoints.remark END,
                           source_id = excluded.source_id,
                           last_seen_at = excluded.last_seen_at""",
                    (it["host"], int(it.get("port", 443)), it.get("remark", ""), source_id, now)
                )
                n += 1
            except Exception:
                continue
        conn.commit()
    return n


def count_cf_endpoints() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM cf_endpoints").fetchone()[0]


def init_db():
    """初始化数据库，创建表结构"""
    global DB_PATH
    config = get_config()
    DB_PATH = config.get("database", {}).get("path", "./data/nodes.db")
    
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    with get_connection() as conn:
        # 读取 schema SQL
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r") as f:
            schema = f.read()
        conn.executescript(schema)
        _migrate(conn)
        conn.commit()


@contextmanager
def get_connection():
    """获取数据库连接（上下文管理器）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ===== Source CRUD =====

def add_source(name: str, url: str, source_type: str = "unknown") -> Optional[Source]:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO sources (name, url, source_type) VALUES (?, ?, ?)",
            (name, url, source_type)
        )
        source_id = cursor.lastrowid
        # 手动提交确保数据写入
        conn.commit()
        return get_source(source_id)


def get_source(source_id: int) -> Optional[Source]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row:
            return Source(**dict(row))
    return None


def list_sources(enabled_only: bool = True) -> List[Source]:
    with get_connection() as conn:
        if enabled_only:
            rows = conn.execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
        return [Source(**dict(r)) for r in rows]


def update_source_status(source_id: int, status: int, node_count: int = 0):
    with get_connection() as conn:
        conn.execute(
            "UPDATE sources SET last_status = ?, node_count = ?, updated_at = ? WHERE id = ?",
            (status, node_count, int(__import__('time').time()), source_id)
        )


def enable_source(source_id: int, enabled: int = 1):
    with get_connection() as conn:
        conn.execute(
            "UPDATE sources SET enabled = ?, updated_at = ? WHERE id = ?",
            (enabled, int(__import__('time').time()), source_id)
        )


# ===== Node CRUD =====

def add_node(subscribe_url: str, source_id: Optional[int], node_name: str, node_type: str, node_data: dict, status: Optional[str] = None) -> Node:
    with get_connection() as conn:
            node_status = status or NodeStatus.UNKNOWN.value
            cursor = conn.execute(
                """INSERT INTO nodes (subscribe_url, source_id, node_name, node_type, node_data, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (subscribe_url, source_id, node_name, node_type, json.dumps(node_data), node_status)
            )
            node_id = cursor.lastrowid
            return get_node(node_id)


def get_or_create_manual_source(label: str = "手动导入") -> Source:
    """手动导入专用数据源（type=manual），按 label 复用"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE source_type = 'manual' AND name = ?", (label,)
        ).fetchone()
        if row:
            return Source(**dict(row))
        now = int(__import__('time').time())
        cur = conn.execute(
            """INSERT INTO sources (name, url, source_type, enabled, category, created_at, updated_at)
               VALUES (?, ?, 'manual', 1, 'manual', ?, ?)""",
            (label, f"manual://{label}", now, now)
        )
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
        return Source(**dict(row))


def get_node(node_id: int) -> Optional[Node]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row:
            d = dict(row)
            d['node_data'] = json.loads(d.get('node_data', '{}'))
            return Node(**d)
    return None


def list_nodes(status: Optional[str] = None, country: Optional[str] = None, node_type: Optional[str] = None,
               limit: int = 100, min_score: Optional[float] = None, min_speed: Optional[float] = None,
               max_latency: Optional[int] = None, sort: str = "latency", order: str = "asc",
               offset: int = 0, source_type: Optional[str] = None) -> List[Node]:
    with get_connection() as conn:
        query = "SELECT n.* FROM nodes n LEFT JOIN sources s ON n.source_id = s.id WHERE 1=1"
        params = []
        if status:
            query += " AND n.status = ?"
            params.append(status)
        if country:
            query += " AND n.country = ?"
            params.append(country)
        if node_type:
            query += " AND n.node_type = ?"
            params.append(node_type)
        if source_type:
            if source_type == "auto":
                query += " AND COALESCE(s.source_type, '') != 'manual'"
            else:
                query += " AND s.source_type = ?"
                params.append(source_type)
        if min_score is not None:
            query += " AND score >= ?"
            params.append(min_score)
        if min_speed is not None:
            # min_speed 单位 KB/s
            query += " AND download_speed >= ?"
            params.append(int(min_speed * 1024))
        if max_latency is not None:
            query += " AND latency IS NOT NULL AND latency <= ?"
            params.append(max_latency)

        # 排序白名单防注入
        sort_cols = {"latency": "latency", "speed": "download_speed", "score": "score",
                     "created": "created_at", "name": "node_name", "country": "country"}
        col = sort_cols.get(sort, "latency")
        direction = "DESC" if str(order).lower() == "desc" else "ASC"
        # NULL 值排最后
        query += f" ORDER BY ({col} IS NULL) ASC, {col} {direction} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        nodes = []
        for r in rows:
            d = dict(r)
            d['node_data'] = json.loads(d.get('node_data', '{}'))
            nodes.append(Node(**d))
        return nodes


def update_node_status(node_id: int, status: str, latency: Optional[int] = None, download_speed: Optional[int] = None):
    with get_connection() as conn:
        conn.execute(
            """UPDATE nodes SET status = ?, latency = ?, download_speed = ?, 
               last_checked_at = ?, updated_at = ? WHERE id = ?""",
            (status, latency, download_speed, int(__import__('time').time()), int(__import__('time').time()), node_id)
        )


def update_node_location(node_id: int, country: Optional[str] = None, provider: Optional[str] = None):
    with get_connection() as conn:
        conn.execute(
            "UPDATE nodes SET country = ?, provider = ?, updated_at = ? WHERE id = ?",
            (country, provider, int(__import__('time').time()), node_id)
        )


def get_active_nodes() -> List[Node]:
    return list_nodes(status=NodeStatus.ACTIVE.value)


def count_nodes(status: Optional[str] = None) -> int:
    with get_connection() as conn:
        if status:
            return conn.execute("SELECT COUNT(*) FROM nodes WHERE status = ?", (status,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]


# ===== Check Job =====

def add_check_job(job_type: str) -> CheckJob:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO check_jobs (job_type, status) VALUES (?, 'pending')",
            (job_type,)
        )
        job_id = cursor.lastrowid
        conn.commit()
        return CheckJob(id=job_id, job_type=job_type, status="pending")


def update_check_job(job_id: int, status: str, result: Optional[str] = None, error: Optional[str] = None):
    import time
    with get_connection() as conn:
        conn.execute(
            """UPDATE check_jobs SET status = ?, result = ?, error_message = ?,
               finished_at = ? WHERE id = ?""",
            (status, result, error, int(time.time()), job_id)
        )


def get_check_job(job_id: int) -> Optional[CheckJob]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM check_jobs WHERE id = ?", (job_id,)).fetchone()
        if row:
            return CheckJob(**dict(row))
    return None


# ===== User CRUD =====

def create_user(username: str, password_hash: str, role: str = "user") -> Optional[User]:
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role)
            )
            return User(id=cursor.lastrowid, username=username, role=role, is_active=1)
        except Exception as e:
            if "UNIQUE" in str(e):
                return None
            raise e


def get_user_by_username(username: str) -> Optional[User]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            return User(**dict(row))
    return None


def get_user_by_id(user_id: int) -> Optional[User]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            return User(**dict(row))
    return None


def list_users() -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, role, is_active, created_at FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def update_user_role(user_id: int, role: str):
    with get_connection() as conn:
        conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                     (role, int(__import__('time').time()), user_id))


def toggle_user_active(user_id: int, is_active: int):
    with get_connection() as conn:
        conn.execute("UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
                     (is_active, int(__import__('time').time()), user_id))


# ===== Token CRUD =====

def create_token(user_id: Optional[int], token_str: str, name: str = "default",
                 permissions: str = "read", expired_at: Optional[int] = None) -> Optional[Token]:
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO tokens (user_id, token, name, permissions, expired_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, token_str, name, permissions, expired_at)
            )
            return Token(id=cursor.lastrowid, user_id=user_id, token=token_str,
                         name=name, permissions=permissions, is_active=1)
        except Exception as e:
            if "UNIQUE" in str(e):
                return None
            raise e


def get_token_by_value(token_str: str) -> Optional[Token]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tokens WHERE token = ?", (token_str,)).fetchone()
        if row:
            return Token(**dict(row))
    return None


def list_tokens(user_id: Optional[int] = None) -> list:
    with get_connection() as conn:
        if user_id:
            rows = conn.execute("SELECT * FROM tokens WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tokens ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def toggle_token_active(token_id: int, is_active: int):
    with get_connection() as conn:
        conn.execute("UPDATE tokens SET is_active = ? WHERE id = ?", (is_active, token_id))


def delete_token(token_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM tokens WHERE id = ?", (token_id,))


def update_token_last_used(token_str: str):
    with get_connection() as conn:
        conn.execute("UPDATE tokens SET last_used_at = ? WHERE token = ?",
                     (int(__import__('time').time()), token_str))


def validate_token(token_str: str) -> Optional[dict]:
    """验证 token 有效性，返回 token 信息或 None"""
    token = get_token_by_value(token_str)
    if not token:
        return None
    if not token.is_active:
        return None
    if token.expired_at and int(__import__('time').time()) > token.expired_at:
        return None
    # 更新最后使用时间
    update_token_last_used(token_str)
    return {
        "id": token.id,
        "user_id": token.user_id,
        "token": token.token,
        "name": token.name,
        "permissions": token.permissions
    }


def clean_old_jobs(days: int = 7):
    import time
    cutoff = int(time.time()) - (days * 86400)
    with get_connection() as conn:
        conn.execute("DELETE FROM check_jobs WHERE finished_at < ?", (cutoff,))


def clean_old_nodes(days: int = 7):
    import time
    cutoff = int(time.time()) - (days * 86400)
    with get_connection() as conn:
        # 删除超过 N 天未检查的 inactive 节点
        conn.execute(
            "DELETE FROM nodes WHERE status = ? AND last_checked_at < ?",
            (NodeStatus.INACTIVE.value, cutoff)
        )


# ===== Scoring & Ranking =====

def calculate_node_score(node: Node) -> float:
    """
    多维度综合评分 (0-100)，权重参考方案 v2.1 附录 H：
      延迟 30% + 下载速度 25% + 稳定性 20% + 地理位置 15% + 协议先进性 10%
    """
    # 1. 延迟分 (30%): max(0, 100 - latency_ms/10)
    latency = node.latency or 0
    latency_score = max(0.0, 100.0 - latency / 10.0) if latency > 0 else 40.0  # 无数据给及格分

    # 2. 速度分 (25%): min(100, speed_mbps * 5)
    speed = node.download_speed or 0  # bytes/s
    speed_mbps = speed * 8 / 1_000_000 if speed else 0  # → Mbps
    speed_score = min(100.0, speed_mbps * 5.0)

    # 3. 稳定性分 (20%): 基于失败次数衰减
    fail_count = getattr(node, "fail_count", 0) or 0
    stability_score = max(0.0, 100.0 - fail_count * 25.0)

    # 4. 地理分 (15%): 优选地区 JP/HK/SG/US/TW/DE/GB/KR 加分
    preferred = {"🇯🇵", "🇭🇰", "🇸🇬", "🇺🇸", "🇹🇼", "🇩🇪", "🇬🇧", "🇰🇷", "🇳🇱", "🇫🇷"}
    geo_score = 80.0 if (node.country in preferred) else 40.0

    # 5. 协议分 (10%): 新协议加分
    proto_bonus = {
        "hysteria2": 100, "hy2": 100, "tuic": 90, "vless": 80,
        "trojan": 70, "vmess": 60, "ss": 50, "ssr": 30, "socks5": 30, "http": 20,
    }
    proto_score = float(proto_bonus.get((node.node_type or "").lower(), 40))

    total = (latency_score * 0.30 + speed_score * 0.25 + stability_score * 0.20
             + geo_score * 0.15 + proto_score * 0.10)
    return round(min(100.0, total), 1)


# 质量等级标签（附录 H.2）
GRADE_LABELS = [
    (90, "优质", "🟢"), (70, "可用", "🟡"), (50, "一般", "🟠"), (0, "劣质", "🔴"),
]


def score_grade(score: float) -> dict:
    """评分 → 等级标签"""
    for threshold, label, emoji in GRADE_LABELS:
        if score >= threshold:
            return {"grade": label, "emoji": emoji}
    return {"grade": "劣质", "emoji": "🔴"}


def update_node_geo(node_id: int, country: str, country_code: str):
    """更新节点 GeoIP 出口信息"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE nodes SET country = ?, country_code = ?, updated_at = ? WHERE id = ?",
            (country, country_code, int(__import__('time').time()), node_id)
        )


def record_source_failure(source_id: int, auto_disable_threshold: int = 5, disable_hours: int = 24):
    """记录源抓取失败；连续失败达到阈值自动禁用 N 小时（附录 G 防劣化）"""
    now = int(__import__('time').time())
    with get_connection() as conn:
        row = conn.execute("SELECT fail_count FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            return
        fail_count = (row["fail_count"] or 0) + 1
        if fail_count >= auto_disable_threshold:
            # 禁用 disable_hours 小时（用 updated_at 存禁用时间，恢复时判断）
            conn.execute(
                "UPDATE sources SET fail_count = ?, enabled = 0, updated_at = ? WHERE id = ?",
                (fail_count, now, source_id)
            )
            logger.warning(f"Source #{source_id} auto-disabled after {fail_count} failures (re-enable after {disable_hours}h)")
        else:
            conn.execute("UPDATE sources SET fail_count = ? WHERE id = ?", (fail_count, source_id))


def record_source_success(source_id: int):
    """记录源抓取成功，重置失败计数"""
    with get_connection() as conn:
        conn.execute("UPDATE sources SET fail_count = 0 WHERE id = ?", (source_id,))


def reenable_expired_sources(disable_hours: int = 24):
    """恢复禁用超时的源（禁用满 disable_hours 自动重新启用）"""
    now = int(__import__('time').time())
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, updated_at FROM sources WHERE enabled = 0 AND fail_count >= 5"
        ).fetchall()
        reenabled = 0
        for r in rows:
            if r["updated_at"] and now - r["updated_at"] >= disable_hours * 3600:
                conn.execute(
                    "UPDATE sources SET enabled = 1, fail_count = 0, updated_at = ? WHERE id = ?",
                    (now, r["id"])
                )
                reenabled += 1
        return reenabled


def get_check_job(job_id: int) -> Optional[dict]:
    """获取单个测速任务详情"""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM check_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("result"):
            try:
                d["result"] = json.loads(d["result"])
            except Exception:
                pass
        return d


def get_score_trend(limit: int = 30) -> list:
    """历史趋势：最近 N 次 completed 测速任务的 (时间, 总节点, 存活, 评分均值)"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, started_at, finished_at, result FROM check_jobs "
            "WHERE status = 'completed' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    trend = []
    for r in reversed(rows):
        total = alive = 0
        avg_score = 0.0
        try:
            result = json.loads(r["result"]) if r["result"] else {}
            total = result.get("total", 0) or 0
            alive = result.get("alive", 0) or result.get("available", 0) or 0
            avg_score = float(result.get("avg_score", 0) or 0)
        except Exception:
            pass
        trend.append({
            "job_id": r["id"],
            "time": r["finished_at"] or r["started_at"],
            "total": total,
            "alive": alive,
            "avg_score": avg_score,
        })
    return trend


def update_node_scores() -> int:
    """重新计算所有活跃节点的评分"""
    nodes = get_active_nodes()
    updated = 0
    with get_connection() as conn:
        for node in nodes:
            score = calculate_node_score(node)
            conn.execute("UPDATE nodes SET score = ?, updated_at = ? WHERE id = ?",
                         (score, int(__import__('time').time()), node.id))
            updated += 1
    return updated


def get_ranking(limit: int = 50, country: Optional[str] = None,
                node_type: Optional[str] = None, min_score: float = 0,
                offset: int = 0, source_type: Optional[str] = None,
                status: Optional[str] = None) -> List[Node]:
    """获取节点排名（按评分降序）；source_type: manual/auto"""
    with get_connection() as conn:
        query = ("SELECT n.* FROM nodes n LEFT JOIN sources s ON n.source_id = s.id "
                 "WHERE n.score >= ?")
        params = [min_score]
        if country:
            query += " AND n.country = ?"
            params.append(country)
        if node_type:
            query += " AND n.node_type = ?"
            params.append(node_type)
        if status:
            query += " AND n.status = ?"
            params.append(status)
        if source_type:
            if source_type == "auto":
                query += " AND COALESCE(s.source_type, '') != 'manual'"
            else:
                query += " AND s.source_type = ?"
                params.append(source_type)
        query += " ORDER BY n.score DESC, n.download_speed DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        nodes = []
        for r in rows:
            d = dict(r)
            d['node_data'] = json.loads(d.get('node_data', '{}'))
            nodes.append(Node(**d))
        return nodes


def get_ranking_stats() -> dict:
    """获取排名统计"""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM nodes WHERE score > 0").fetchone()[0]
        avg = conn.execute("SELECT AVG(score) FROM nodes WHERE score > 0").fetchone()[0]
        top = conn.execute("SELECT MAX(score) FROM nodes WHERE score > 0").fetchone()[0]
        return {
            "total_scored": total,
            "avg_score": round(avg or 0, 1),
            "top_score": round(top or 0, 1)
        }