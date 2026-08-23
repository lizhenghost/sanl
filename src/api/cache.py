"""进程内 TTL 缓存（读多写少接口）—— 避免高频轮询反复打 SQLite，降低成本。

- cached(ttl, name): async 装饰器，缓存端点返回值（key 含 path+query）
- invalidate_all(): 数据变更时清空全部缓存（写操作低频，清空可保正确且命中率高）
- cache_stats(): 命中/未命中计数，供管理面板
- Cache-Control + X-Cache 响应头：让浏览器/CDN 也参与缓存
"""
import time
import threading
import json
import hashlib
from functools import wraps

_CACHE = {}
_LOCK = threading.Lock()
_STATS = {"hit": 0, "miss": 0}

DEFAULT_TTL = 5  # 秒


def _key_of(fn, args, kwargs):
    """缓存 key = 函数名 + 可序列化的参数。跳过 Request / Response 等不可序列化对象；
    query 参数（如 limit/offset/sort/status）会自动区分不同查询。"""
    name = fn.__name__
    parts = []
    for a in args:
        if a is None or isinstance(a, (int, float, str, bool, type(None), list, dict, tuple)):
            parts.append(repr(a))
    for k in sorted(kwargs.keys()):
        v = kwargs[k]
        if any(isinstance(v, t) for t in (dict, list, tuple, int, float, str, bool, type(None))):
            parts.append(f"{k}={v!r}")
    return name + ":" + "|".join(parts)


def _etag_of(data):
    """从返回值生成弱 ETag（W/"hash"）。"""
    try:
        raw = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = str(data)
    return 'W/"' + hashlib.md5(raw.encode()).hexdigest()[:16] + '"'


def cached(ttl=DEFAULT_TTL, name=None):
    """async 端点缓存。key 含函数名 + 全部可序列化参数，天然区分不同查询。
    返回 JSONResponse 时附带 Cache-Control + X-Cache + ETag 响应头。
    使用 jsonable_encoder 确保兼容 Pydantic response_model。"""
    def deco(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            from fastapi.responses import JSONResponse
            from fastapi.encoders import jsonable_encoder

            key = name or _key_of(fn, args, kwargs)
            now = time.time()
            with _LOCK:
                hit = _CACHE.get(key)
                if hit and hit[0] > now:
                    _STATS["hit"] += 1
                    value = hit[1]
                    # 命中缓存 → 附加响应头
                    if isinstance(value, (dict, list)):
                        value = jsonable_encoder(value)
                        etag = _etag_of(value)
                        resp = JSONResponse(value)
                        resp.headers["Cache-Control"] = f"public, max-age={int(ttl)}"
                        resp.headers["X-Cache"] = "HIT"
                        resp.headers["ETag"] = etag
                        return resp
                    return value
            value = await fn(*args, **kwargs)
            # 缓存前用 jsonable_encoder 转为纯 dict/list（兼容 Pydantic Model）
            cached_value = jsonable_encoder(value) if not isinstance(value, (str, bytes, int, float, bool, type(None))) else value
            with _LOCK:
                _CACHE[key] = (now + ttl, cached_value)
                _STATS["miss"] += 1
            # 未命中但已缓存结果 → 附加响应头
            if isinstance(cached_value, (dict, list)):
                etag = _etag_of(cached_value)
                resp = JSONResponse(cached_value)
                resp.headers["Cache-Control"] = f"public, max-age={int(ttl)}"
                resp.headers["X-Cache"] = "MISS"
                resp.headers["ETag"] = etag
                return resp
            return value
        return wrapper
    return deco


def invalidate_all():
    with _LOCK:
        _CACHE.clear()


def cache_stats():
    with _LOCK:
        return dict(_STATS, size=len(_CACHE))
