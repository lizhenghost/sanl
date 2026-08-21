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

    async def close(self):
        await self.client.aclose()
