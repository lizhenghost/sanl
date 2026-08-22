"""
免费节点源抓取器
支持：GitHub Raw、通用 HTTP、静态文件、Telegram 频道、静态 JSON
"""
import re
import json
import os
import logging
from typing import List, Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# 常见订阅协议前缀
SUB_PROTOCOLS = [
    'vmess://', 'vless://', 'ss://', 'trojan://', 'hysteria2://',
    'hy2://', 'snell://', 'socks5://', 'http://', 'https://',
]

# 静态数据源文件路径
STATIC_SOURCES_FILE = "presets/free_sources.json"
STATIC_DIR = "data/static"

# GitHub raw 被墙时的镜像加速前缀（依次回退）
GH_MIRRORS = [
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
]


@dataclass
class FetchedSource:
    name: str
    url: str
    raw_content: Optional[str] = None
    error: Optional[str] = None


class Scraper:
    def __init__(self, proxy_urls: Optional[List[str]] = None):
        self.proxy_urls = proxy_urls or []
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    async def fetch_github_raw(self, repo_url: str) -> Optional[FetchedSource]:
        """从 GitHub raw URL 获取订阅内容"""
        try:
            url = repo_url
            if "github.com" in repo_url and "/raw/" not in repo_url:
                match = re.search(r'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)', repo_url)
                if match:
                    user, repo, branch, path = match.groups()
                    url = f"https://raw.githubusercontent.com/{user}/{repo}/refs/heads/{branch}/{path}"

            logger.info(f"Fetching GitHub source: {url}")
            resp = await self.client.get(url)
            resp.raise_for_status()
            content = resp.text.strip()

            name = url.split('/')[-1].replace('.txt', '').replace('.yaml', '').replace('.yml', '') or f"GitHub-{url.split('/')[-2]}"
            return FetchedSource(name=name, url=url, raw_content=content)

        except Exception as e:
            logger.error(f"Failed to fetch GitHub source {repo_url}: {e}")
            return FetchedSource(name=repo_url, url=repo_url, error=str(e))

    async def fetch_http(self, url: str) -> Optional[FetchedSource]:
        """从通用 HTTP URL 获取订阅内容"""
        try:
            logger.info(f"Fetching HTTP source: {url}")
            resp = await self.client.get(url)
            resp.raise_for_status()
            content = resp.text.strip()

            name = url.split('/')[-1].split('?')[0] or f"HTTP-{url[:30]}"
            return FetchedSource(name=name, url=url, raw_content=content)

        except Exception as e:
            logger.error(f"Failed to fetch HTTP source {url}: {e}")
            return FetchedSource(name=url, url=url, error=str(e))

    async def fetch_static_file(self, url: str) -> Optional[FetchedSource]:
        """从本地 static 文件读取（url 格式: data:static/xxx.txt）"""
        try:
            if not url.startswith("data:"):
                raise ValueError("static url must start with data:")
            rel_path = url[5:]
            # 实际存储路径统一为 data/static/xxx.txt
            actual_path = f"data/static/{os.path.basename(rel_path)}"
            if not os.path.exists(actual_path):
                raise FileNotFoundError(actual_path)
            with open(actual_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            name = os.path.basename(actual_path).replace('.txt', '')
            return FetchedSource(name=name, url=url, raw_content=content)

        except Exception as e:
            logger.error(f"Failed to load static source {url}: {e}")
            return FetchedSource(name=url, url=url, error=str(e))

    async def fetch_telegram_channel(self, channel_url: str) -> Optional[FetchedSource]:
        """从 Telegram 频道获取订阅（通过 t.me 预览）"""
        try:
            preview_url = f"https://t.me/s/{channel_url.replace('@', '').strip('/')}"
            logger.info(f"Fetching Telegram channel: {preview_url}")
            resp = await self.client.get(preview_url, timeout=15.0)
            resp.raise_for_status()
            content = resp.text

            subs = re.findall(r'(https?://[^\s"<>\']+)', content)
            valid_subs = [s for s in subs if any(s.startswith(p) for p in SUB_PROTOCOLS)]

            name = channel_url.replace('@', '').replace('https://t.me/', '').strip('/')
            return FetchedSource(name=name, url=channel_url, raw_content=content)

        except Exception as e:
            logger.error(f"Failed to fetch Telegram channel {channel_url}: {e}")
            return FetchedSource(name=channel_url, url=channel_url, error=str(e))

    async def fetch_static_json(self, json_path: str = STATIC_SOURCES_FILE) -> List[FetchedSource]:
        """从静态 JSON 文件读取数据源"""
        try:
            if not os.path.exists(json_path):
                return []
            with open(json_path, 'r', encoding='utf-8') as f:
                sources = json.load(f)

            results = []
            for src in sources:
                if not isinstance(src, dict):
                    continue
                stype = str(src.get("type", "")).lower().strip()
                url = src.get("url", "")
                name = src.get("name", "Unknown")

                if stype == "github":
                    r = await self.fetch_github_raw(url)
                elif stype == "http":
                    r = await self.fetch_http(url)
                elif stype == "static":
                    r = await self.fetch_static_file(url)
                elif stype == "telegram":
                    r = await self.fetch_telegram_channel(url)
                else:
                    r = FetchedSource(name=name, url=url, error=f"Unsupported type: {stype}")

                if r:
                    r.name = name
                    results.append(r)
            return results
        except Exception as e:
            logger.error(f"Failed to load static sources from {json_path}: {e}")
            return []

    async def fetch_all(self) -> List[FetchedSource]:
        """获取所有数据源"""
        return await self.fetch_static_json()

    async def _get_with_mirrors(self, url: str) -> Optional[str]:
        """直连优先，失败后依次尝试 GitHub 镜像前缀（仅对 raw.githubusercontent.com / github.com 生效）"""
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            return resp.text.strip()
        except Exception as e:
            if "github" not in url:
                logger.error(f"Failed to fetch {url}: {e}")
                return None
            logger.warning(f"直连失败({e})，尝试镜像回退: {url}")
            for m in GH_MIRRORS:
                try:
                    resp = await self.client.get(m + url, timeout=20.0)
                    resp.raise_for_status()
                    text = resp.text.strip()
                    if text:
                        logger.info(f"镜像成功: {m}")
                        return text
                except Exception as me:
                    logger.warning(f"镜像失败 {m}: {me}")
            return None

    async def fetch_source(self, url: str, source_type: str = "http") -> Optional[FetchedSource]:
        """按 URL/类型自动分发的统一抓取入口（池导入用）"""
        st = (source_type or "").lower()
        try:
            if url.startswith("data:"):
                return await self.fetch_static_file(url)
            if st == "telegram" or "t.me/" in url:
                return await self.fetch_telegram_channel(url)
            if "github.com" in url or "raw.githubusercontent.com" in url or st == "github":
                content = await self._github_raw_content(url)
                name = url.rstrip('/').split('/')[-1].split('?')[0] or f"github-{url.split('/')[-2]}"
                if content is None:
                    return FetchedSource(name=name, url=url, error="直连与镜像均失败")
                return FetchedSource(name=name, url=url, raw_content=content)
            # 通用 HTTP（含 pages.dev / base64 / clash / singbox 订阅）
            content = await self._get_with_mirrors(url)
            name = url.rstrip('/').split('/')[-1].split('?')[0][:60] or f"http-{url[:30]}"
            if content is None:
                return FetchedSource(name=name, url=url, error="HTTP 抓取失败")
            return FetchedSource(name=name, url=url, raw_content=content)
        except Exception as e:
            return FetchedSource(name=url, url=url, error=str(e))

    async def _github_raw_content(self, repo_url: str) -> Optional[str]:
        """github.com blob URL → raw URL，再走镜像回退链"""
        url = repo_url
        if "github.com" in repo_url and "/raw/" not in repo_url and "raw.githubusercontent.com" not in repo_url:
            match = re.search(r'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)', repo_url)
            if match:
                user, repo, branch, path = match.groups()
                url = f"https://raw.githubusercontent.com/{user}/{repo}/refs/heads/{branch}/{path}"
        return await self._get_with_mirrors(url)

    async def close(self):
        await self.client.aclose()
