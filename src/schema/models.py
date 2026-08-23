from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class NodeStatus(str, Enum):
    UNKNOWN = "unknown"
    ACTIVE = "active"
    INACTIVE = "inactive"
    CHECKING = "checking"
    DEAD = "dead"          # 自动黑名单：连续3轮测速失败（大纲 H.3）
    BANNED = "banned"      # 手动封禁（大纲 H.3）


class SourceType(str, Enum):
    GITHUB = "github"
    TELEGRAM = "telegram"
    STATIC_JSON = "static_json"
    UNKNOWN = "unknown"


@dataclass
class Source:
    id: Optional[int] = None
    name: str = ""
    url: str = ""
    source_type: str = SourceType.UNKNOWN.value
    enabled: int = 1
    speed_test: int = 1   # 是否参与测速（1=参加, 0=不参加）
    last_fetched_at: Optional[int] = None
    last_status: int = 0
    node_count: int = 0
    fail_count: int = 0
    stream_flags: Optional[str] = None
    category: str = "free"
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


@dataclass
class Node:
    id: Optional[int] = None
    subscribe_url: str = ""
    source_id: Optional[int] = None
    node_name: Optional[str] = None
    node_type: str = ""
    node_data: str = ""
    status: str = NodeStatus.UNKNOWN.value
    country: Optional[str] = None
    country_code: Optional[str] = None
    fail_count: int = 0
    stream_flags: Optional[str] = None
    provider: Optional[str] = None
    latency: Optional[int] = None
    download_speed: Optional[int] = None
    score: Optional[float] = 0.0
    last_checked_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    fingerprint: Optional[str] = None
    last_seen_at: Optional[int] = None
    favorite: int = 0


@dataclass
class CheckJob:
    id: Optional[int] = None
    job_type: str = ""
    status: str = "pending"
    result: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    created_at: Optional[int] = None


@dataclass
class User:
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    role: str = "user"
    is_active: int = 1
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


@dataclass
class Token:
    id: Optional[int] = None
    user_id: Optional[int] = None
    token: str = ""
    name: str = "default"
    permissions: str = "read"
    is_active: int = 1
    expired_at: Optional[int] = None
    last_used_at: Optional[int] = None
    traffic_limit_mb: float = 0   # 流量限额（MB，0=不限）；缺此字段会导致 Token(**dict) 全部 500
    created_at: Optional[int] = None