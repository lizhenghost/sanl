"""
免费节点源抓取器
支持：GitHub Raw、Telegram 频道、静态 JSON
"""
import re
import json
import asyncio
import logging
from typing import List, Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# GitHub 订阅链接模式
GITHUB_SUB_PATTERN = re.compile(
    r'https?://raw\.githubusercontent\.com/[^/]+/[^/]+/refs/heads/[^/]+/[^/\s]+\.txt'
)

# 常见订阅协议前缀
SUB_PROTOCOLS = [
    'vmess://', 'vless://', 'ss://', 'trojan://', ' hysteria2://',
    'hysteria2://', 'snell://', 'socks5://', 'http://', 'https://',
]

# 静态数据源文件路径
STATIC_SOURCES_FILE = "data/sources.json"


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
            # 标准化 URL
            if "github.com" in repo_url and "/raw/" in repo_url:
                url = repo_url
            elif "gist.github.com" in repo_url:
                # Gist raw URL
                url = repo_url.replace("gist.github.com", "gist.githubusercontent.com").replace("/view", "/raw")
            else:
                # 尝试解析为 raw URL
                match = re.search(r'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)', repo_url)
                if match:
                    user, repo, branch, path = match.groups()
                    url = f"https://raw.githubusercontent.com/{user}/{repo}/refs/heads/{branch}/{path}"
                else:
                    url = repo_url

            logger.info(f"Fetching GitHub source: {url}")
            resp = await self.client.get(url)
            resp.raise_for_status()
            content = resp.text.strip()

            # 提取订阅链接
            lines = content.split('\n')
            subs = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # 检查是否是订阅链接
                if any(line.startswith(p) for p in SUB_PROTOCOLS):
                    subs.append(line)
                elif line.startswith('http') and ('sub' in line or 'list' in line or '.txt' in line):
                    subs.append(line)

            name = url.split('/')[-1].replace('.txt', '') or f"GitHub-{url.split('/')[-2]}"
            return FetchedSource(name=name, url=url, raw_content=content)

        except Exception as e:
            logger.error(f"Failed to fetch GitHub source {repo_url}: {e}")
            return FetchedSource(name=repo_url, url=repo_url, error=str(e))

    async def fetch_telegram_channel(self, channel_url: str) -> Optional[FetchedSource]:
        """从 Telegram 频道获取订阅（通过 t.me 预览）"""
        try:
            # Telegram 公共频道消息预览
            preview_url = f"https://t.me/s/{channel_url.replace('@', '').strip('/')}"
            logger.info(f"Fetching Telegram channel: {preview_url}")
            resp = await self.client.get(preview_url, timeout=15.0)
            resp.raise_for_status()
            content = resp.text

            # 提取订阅链接
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
                if isinstance(src, dict):
                    results.append(FetchedSource(
                        name=src.get("name", "Unknown"),
                        url=src.get("url", ""),
                        raw_content=json.dumps(src)
                    ))
            return results
        except Exception as e:
            logger.error(f"Failed to load static sources from {json_path}: {e}")
            return []

    async def fetch_all(self) -> List[FetchedSource]:
        """获取所有数据源"""
        results = []
        
        # 1. 静态 JSON
        static_sources = await self.fetch_static_json()
        results.extend(static_sources)
        
        # 2. GitHub 源（使用已知列表）
        github_urls = [
            "https://raw.githubusercontent.com/chengdoudou/free-node/main/clash.txt",
            "https://raw.githubusercontent.com/pepslsub/free/main/sub",
            "https://raw.githubusercontent.com/mai-gitp/sub/main/clash.sub",
            "https://raw.githubusercontent.com/Royaclead/Sub/main/Clash.meta.sub",
        ]
        for url in github_urls:
            result = await self.fetch_github_raw(url)
            results.append(result)
        
        return results

    async def close(self):
        await self.client.aclose()