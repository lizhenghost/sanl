"""
鉴权模块（精简版）
仅保留 Token 鉴权——用户/密码系统已移除
"""
import secrets
import logging
from fastapi import Request
from typing import Optional

from .schema import repository

logger = logging.getLogger(__name__)


def generate_token(length: int = 32) -> str:
    """生成安全随机 Token（订阅短链用）"""
    return "np_" + secrets.token_hex(length)


async def get_current_user(request: Request) -> Optional[dict]:
    """从请求中获取 Token 鉴权信息（Header/Query/API-Key）"""
    # 1. Header Authorization: Bearer xxx
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token_info = repository.validate_token(auth[7:])
        if token_info:
            return {"authenticated": True, "method": "token", "token": token_info}

    # 2. URL 参数 ?token=xxx
    token_str = request.query_params.get("token", "")
    if token_str:
        token_info = repository.validate_token(token_str)
        if token_info:
            return {"authenticated": True, "method": "token", "token": token_info}

    # 3. X-API-Key header
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        token_info = repository.validate_token(api_key)
        if token_info:
            return {"authenticated": True, "method": "token", "token": token_info}

    return {"authenticated": False, "method": None, "token": None}


async def require_token(request: Request) -> Optional[dict]:
    """要求有效 Token（订阅端点用），未认证时返回 None"""
    auth_info = await get_current_user(request)
    return auth_info if auth_info["authenticated"] else None
