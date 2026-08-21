"""
认证鉴权模块
支持 Token 鉴权 + 用户名密码登录
"""
import hashlib
import secrets
import logging
from fastapi import Request, HTTPException, Header
from typing import Optional

from .schema import repository

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """密码哈希（SHA-256 + salt）"""
    salt = "nodepool_salt_2026"
    return hashlib.sha256((salt + password).encode()).hexdigest()


def generate_token(length: int = 32) -> str:
    """生成安全随机 Token"""
    return "np_" + secrets.token_hex(length)


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    return hash_password(password) == password_hash


async def get_current_user(request: Request) -> Optional[dict]:
    """从请求中获取当前用户（Session 或 Token）"""
    # 1. 尝试 Header Authorization
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token_str = auth[7:]
        token_info = repository.validate_token(token_str)
        if token_info:
            user = repository.get_user_by_id(token_info["user_id"]) if token_info["user_id"] else None
            return {
                "authenticated": True,
                "method": "token",
                "token": token_info,
                "user": user
            }

    # 2. 尝试 URL 参数 ?token=xxx
    token_str = request.query_params.get("token", "")
    if token_str:
        token_info = repository.validate_token(token_str)
        if token_info:
            user = repository.get_user_by_id(token_info["user_id"]) if token_info["user_id"] else None
            return {
                "authenticated": True,
                "method": "token",
                "token": token_info,
                "user": user
            }

    # 3. 尝试 X-API-Key header
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        token_info = repository.validate_token(api_key)
        if token_info:
            user = repository.get_user_by_id(token_info["user_id"]) if token_info["user_id"] else None
            return {
                "authenticated": True,
                "method": "token",
                "token": token_info,
                "user": user
            }

    return {"authenticated": False, "method": None, "token": None, "user": None}


async def require_auth(request: Request, require_admin: bool = False) -> dict:
    """要求认证，未认证则抛出 401"""
    auth_info = await get_current_user(request)
    if not auth_info["authenticated"]:
        raise HTTPException(status_code=401, detail="Authentication required")
    if require_admin:
        user = auth_info.get("user")
        if not user or user.role != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
    return auth_info


async def require_token(request: Request) -> Optional[dict]:
    """要求有效 Token（用于订阅端点），未认证时返回 None"""
    auth_info = await get_current_user(request)
    return auth_info if auth_info["authenticated"] else None