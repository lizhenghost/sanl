"""订阅转换模块 —— Sanl 第二大功能块

把任意订阅链接 / 节点链接 / Base64 / Clash YAML / sing-box JSON
转换为目标格式（clash / singbox / surge / loon / qx / v2ray / base64 / mixed / txt）。
纯 Python 实现，复用 importer.parse_content + subscribe.generate_by_format，
不依赖外部 subconverter 二进制。
"""
import asyncio
import logging
import re
from typing import List, Optional, Tuple

import httpx
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from .importer import parse_content, _b64decode, SUPPORTED_PREFIXES
from .subscribe import generate_by_format, EXPORT_CONTENT_TYPES
from ..schema.models import Node

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FETCH_BYTES = 5 * 1024 * 1024   # 单个订阅最多 5MB
FETCH_TIMEOUT = 20.0
CONCURRENCY = 8
MAX_INPUT_URLS = 20

# 模拟常见客户端 UA，机场订阅会按 UA 下发对应格式（都能被 parse_content 吃）
FETCH_UA = ("clash.meta/v1.18.1 (Sanl converter; like v2rayN/6.45)")

URL_RE = re.compile(r"^https?://", re.I)


class ConvertRequest(BaseModel):
    input: str = Field(..., description="订阅链接（多行/|分隔）或节点链接/Base64/Clash YAML/sing-box JSON")
    target: str = Field("clash", description="目标格式")
    include: str = Field("", description="包含关键词，逗号分隔（匹配节点名）")
    exclude: str = Field("", description="排除关键词，逗号分隔")
    dedupe: bool = Field(True, description="按服务器+端口去重")


class ConvertResponse(BaseModel):
    ok: bool
    target: str
    fetched: int = 0            # 成功拉取的订阅数
    parsed: int = 0             # 解析出的节点数
    exported: int = 0           # 过滤后导出的节点数
    content: str = ""
    content_type: str = "text/plain; charset=utf-8"
    errors: List[str] = []


async def _fetch_one(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore,
                     errors: List[str]) -> Optional[str]:
    """拉取单个订阅 URL，失败记入 errors 返回 None"""
    async with sem:
        for attempt in (0, 1):
            try:
                resp = await client.get(url, headers={"User-Agent": FETCH_UA})
                resp.raise_for_status()
                text = resp.content[:MAX_FETCH_BYTES].decode("utf-8", "ignore")
                if text.strip():
                    return text
                errors.append(f"订阅内容为空: {url[:80]}")
                return None
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(1.0)  # 一次网络抖动重试
                    continue
                errors.append(f"拉取失败 {url[:80]}: {type(e).__name__}")
                return None
    return None


def _parse_part(text: str, errors: List[str], label: str = "") -> List[Tuple[str, dict, str]]:
    """解析单个来源内容；识别失败时自动尝试整体 Base64 解码后再解析（每源格式隔离）"""
    parsed = parse_content(text, cf_as_nodes=True)
    items = parsed.get("nodes") or []
    if items:
        return items
    # 整段可能是 Base64 订阅（拼接后逐行解析会失效，这里按源整体重试）
    try:
        decoded = _b64decode(text).decode("utf-8", "ignore")
        if decoded.strip() and any(decoded.strip().lower().startswith(p) for p in SUPPORTED_PREFIXES):
            inner = parse_content(decoded, cf_as_nodes=True)
            if inner.get("nodes"):
                return inner["nodes"]
            errors.extend((f"[{label}] " + e) for e in (inner.get("errors") or []))
            return []
    except Exception:
        pass
    errors.extend((f"[{label}] " + e) for e in (parsed.get("errors") or [])[:3])
    return []


async def _collect_input(raw: str, errors: List[str]) -> Tuple[List[Tuple[str, dict, str]], int]:
    """拉取输入中的 http(s) 订阅并逐源独立解析；非 URL 内容合并为一块解析。
    返回 (全部节点, 成功拉取的订阅数) —— 每源格式隔离，避免 base64 与 yaml 互相污染"""
    lines = re.split(r"\n+", raw)
    urls, inline_parts = [], []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if URL_RE.match(stripped) and "\n" not in stripped and len(stripped) < 2048:
            urls.append(stripped)
        else:
            inline_parts.append(line)

    if len(urls) > MAX_INPUT_URLS:
        errors.append(f"订阅链接过多（>{MAX_INPUT_URLS}），已截断")
        urls = urls[:MAX_INPUT_URLS]

    fetched = 0
    all_items: List[Tuple[str, dict, str]] = []

    async def _fetch_text(client, url) -> Optional[str]:
        nonlocal fetched
        sem_local = asyncio.Semaphore(1)
        t = await _fetch_one(client, url, sem_local, errors)
        if t is not None:
            fetched += 1
        return t

    if urls:
        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT,
                                     verify=True) as client:
            texts = await asyncio.gather(*[_fetch_one(client, u, sem, errors) for u in urls], return_exceptions=True)
        for url, text in zip(urls, texts):
            if isinstance(text, Exception):
                continue
            if text:
                fetched += 1
                all_items.extend(_parse_part(text, errors, label=url[:60]))

    if inline_parts:
        all_items.extend(_parse_part("\n".join(inline_parts), errors, label="粘贴内容"))

    return all_items, fetched


def _filter_nodes(items: List[Tuple[str, dict, str]], include: str,
                  exclude: str, dedupe: bool) -> List[Tuple[str, dict, str]]:
    """关键词过滤（匹配节点名）+ 指纹去重"""
    inc = [k.strip().lower() for k in re.split(r"[,，|]", include) if k.strip()]
    exc = [k.strip().lower() for k in re.split(r"[,，|]", exclude) if k.strip()]

    seen, out = set(), []
    for ptype, data, name in items:
        if inc and not any(k in (name or "").lower() for k in inc):
            continue
        if exc and any(k in (name or "").lower() for k in exc):
            continue
        if dedupe:
            host = str(data.get("server") or data.get("host") or "").lower().strip("[]")
            port = str(data.get("port") or "")
            fp = f"{ptype}:{host}:{port}"
            if host and fp in seen:
                continue
            if host:
                seen.add(fp)
        out.append((ptype, data, name))
    return out


@router.post("/convert", response_model=ConvertResponse)
async def convert_subscription(req: ConvertRequest):
    """订阅转换：任意输入 → 目标格式（Sanl 第二大模块）"""
    errors: List[str] = []
    if not req.input.strip():
        return ConvertResponse(ok=False, target=req.target, errors=["输入为空"])

    if req.target not in EXPORT_CONTENT_TYPES:
        return ConvertResponse(ok=False, target=req.target,
                               errors=[f"未知目标格式: {req.target}（支持: {', '.join(EXPORT_CONTENT_TYPES)}）"])

    try:
        items, fetched = await _collect_input(req.input, errors)
    except Exception as e:
        logger.exception("collect input failed")
        return ConvertResponse(ok=False, target=req.target, errors=[f"拉取订阅异常: {e}"])

    if not items:
        return ConvertResponse(ok=False, target=req.target, fetched=fetched,
                               errors=errors + ["没有可用内容（订阅拉取失败或输入为空）"])

    filtered = _filter_nodes(items, req.include, req.exclude, req.dedupe)

    if not filtered:
        return ConvertResponse(ok=False, target=req.target, fetched=fetched,
                               parsed=len(items), errors=errors + ["解析后无可用节点"])

    # 构造临时 Node 列表交给导出器
    nodes = [Node(node_name=name, node_type=ptype,
                  node_data=__import__("json").dumps(data, ensure_ascii=False))
             for ptype, data, name in filtered]

    try:
        content = generate_by_format(req.target, nodes)
    except Exception as e:
        logger.exception("generate failed")
        return ConvertResponse(ok=False, target=req.target, fetched=fetched,
                               parsed=len(items), errors=errors + [f"导出失败: {e}"])

    # 检查导出器是否因协议不兼容过滤了所有节点（如 Clash 基础版过滤 hysteria2）
    import re
    proxy_lines = re.findall(r'^- name:', content, re.MULTILINE)
    actual_exported = len(proxy_lines)
    if actual_exported == 0 and len(filtered) > 0:
        return ConvertResponse(
            ok=False, target=req.target, fetched=fetched,
            parsed=len(items), exported=0,
            content="", errors=errors + [
                f"所有 {len(filtered)} 个节点被导出器过滤（协议 {req.target} 不支持 {filtered[0][0]}）"
            ])

    return ConvertResponse(
        ok=True, target=req.target, fetched=fetched,
        parsed=len(items), exported=actual_exported,
        content=content, content_type=EXPORT_CONTENT_TYPES[req.target],
        errors=errors,
    )


@router.get("/convert/formats")
async def convert_formats():
    """支持的转换格式清单（前端下拉用）"""
    return {"formats": [
        {"key": "clash",       "name": "Clash",           "ct": EXPORT_CONTENT_TYPES["clash"]},
        {"key": "clash-meta",  "name": "Clash.Meta",      "ct": EXPORT_CONTENT_TYPES["clash-meta"]},
        {"key": "singbox",     "name": "Sing-box",        "ct": EXPORT_CONTENT_TYPES["singbox"]},
        {"key": "v2ray",       "name": "V2Ray (明文链接)", "ct": EXPORT_CONTENT_TYPES["v2ray"]},
        {"key": "base64",      "name": "Base64 订阅",      "ct": EXPORT_CONTENT_TYPES["base64"]},
        {"key": "mixed",       "name": "Mixed 混合链接",   "ct": EXPORT_CONTENT_TYPES["mixed"]},
        {"key": "surge",       "name": "Surge",           "ct": EXPORT_CONTENT_TYPES["surge"]},
        {"key": "loon",        "name": "Loon",            "ct": EXPORT_CONTENT_TYPES["loon"]},
        {"key": "qx",          "name": "Quantumult X",    "ct": EXPORT_CONTENT_TYPES["qx"]},
        {"key": "txt",         "name": "TXT 明文",         "ct": EXPORT_CONTENT_TYPES["txt"]},
    ]}
