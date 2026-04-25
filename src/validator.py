"""验证模块：HEAD 优先、Content-Type 检查、代理域名拒绝、CDN 白名单跳过"""
import asyncio
import re
from typing import List, Set
from urllib.parse import urlparse

import aiohttp

from .config import Config
from .fetcher import Channel


class Validator:
    """频道 URL 验证器"""

    def __init__(self, config: Config = None, max_concurrent: int = 20, timeout: int = 10):
        self.config = config or Config()
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._semaphore: asyncio.Semaphore = None

    async def validate(self, channels: List[Channel]) -> List[Channel]:
        """验证频道列表，返回有效频道"""
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = [self._validate_one(ch) for ch in channels]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [ch for ch, valid in zip(channels, results) if valid]

    async def _validate_one(self, channel: Channel) -> bool:
        """验证单个频道"""
        url = channel.url
        if not url:
            return False

        # 1. 检查代理域名
        if self._is_proxy_domain(url):
            return False

        # 2. 白名单 CDN 直接通过（跳过验证）
        if self._is_whitelisted_cdn(url):
            return True

        # 3. HEAD 请求验证
        return await self._check_url(url)

    def _is_proxy_domain(self, url: str) -> bool:
        """检查是否为代理域名"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        for pd in self.config.proxy_domains:
            if pd in domain:
                return True
        return False

    def _is_whitelisted_cdn(self, url: str) -> bool:
        """检查是否为白名单 CDN"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        for wl in self.config.whitelist:
            if wl in domain:
                return True
        return False

    async def _check_url(self, url: str) -> bool:
        """HEAD 请求检查 URL 可访问性"""
        async with self._semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # 先尝试 HEAD
                    async with session.head(url, allow_redirects=True) as resp:
                        if resp.status == 405:
                            # HEAD 不支持，尝试 GET
                            async with session.get(url, allow_redirects=True) as get_resp:
                                return self._is_valid_response(get_resp)
                        return self._is_valid_response(resp)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                return False

    def _is_valid_response(self, resp: aiohttp.ClientResponse) -> bool:
        """检查响应是否有效（状态码、Content-Type）"""
        if resp.status != 200:
            return False
        content_type = resp.headers.get("Content-Type", "")
        # 拒绝 HTML
        if "text/html" in content_type.lower():
            return False
        # 接受视频类型或空 Content-Type
        valid_types = ["video", "audio", "application/octet-stream", "application/x-mpegurl", "application/vnd.apple.mpegurl"]
        if content_type and not any(vt in content_type.lower() for vt in valid_types):
            return False
        return True
