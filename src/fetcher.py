"""抓取模块，支持 m3u 解析、并发控制、失败重试"""
import asyncio
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from dataclasses import dataclass
import aiohttp

from .config import Config


class Channel:
    """频道对象"""

    def __init__(self, name: str, url: str, logo: str = "", group: str = "", **kwargs):
        self.name = name.strip()
        self.url = url.strip()
        self.logo = logo.strip() if logo else ""
        self.group = group.strip() if group else ""
        self.raw_attrs = kwargs
        # _normalized_name 通过 kwargs 传入（grouper.py 依赖此属性）
        self._normalized_name = kwargs.pop("_normalized_name", "") if kwargs else ""

    def __repr__(self):
        return f"<Channel {self.name} ({self.group})>"


class Fetcher:
    """频道抓取器"""

    _EXTINF_RE = re.compile(
        r"#EXTINF:(?P<duration>-?\d+)\s*(?P<attributes>[^,]*),\s*(?P<name>.+)"
    )
    _ATTR_RE = re.compile(r'(?P<key>tvg-(?:name|logo|chnid)|group-title|attribute)="(?P<value>[^"]*)"')

    def __init__(self, config: Config = None, max_concurrent: int = 10, max_retries: int = 3):
        self.config = config or Config()
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def fetch_all(self) -> List[Channel]:
        """从所有启用的数据源抓取频道"""
        sources = self.config.sources
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        tasks = [self._fetch_source(source) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        channels = []
        for result in results:
            if isinstance(result, Exception):
                print(f"[Fetcher] Error: {result}")
            elif result:
                channels.extend(result)

        # 去重（按 URL）
        seen = set()
        unique = []
        for ch in channels:
            if ch.url and ch.url not in seen:
                seen.add(ch.url)
                unique.append(ch)
        return unique

    async def _fetch_source(self, source: Dict) -> List[Channel]:
        """从单个数据源抓取"""
        name = source.get("name", "unknown")
        url = source.get("url", "")
        priority = source.get("priority", 999)

        for attempt in range(self.max_retries):
            try:
                channels = await self._fetch_url(url)
                print(f"[Fetcher] {name}: got {len(channels)} channels")
                for ch in channels:
                    ch.raw_attrs["_source"] = name
                    ch.raw_attrs["_priority"] = priority
                return channels
            except Exception as e:
                print(f"[Fetcher] {name} attempt {attempt+1} failed: {e}")
                await asyncio.sleep(1 * (attempt + 1))

        print(f"[Fetcher] {name}: all retries exhausted")
        return []

    async def _fetch_url(self, url: str) -> List[Channel]:
        """获取 URL 内容并解析"""
        async with self._semaphore:
            parsed = urlparse(url)
            is_yaml = parsed.path.endswith(".yml") or parsed.path.endswith(".yaml")

            if is_yaml:
                return await self._fetch_yaml(url)
            else:
                return await self._fetch_m3u(url)

    async def _fetch_m3u(self, url: str) -> List[Channel]:
        """获取并解析 m3u"""
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                text = await resp.text()

        channels = []
        lines = text.splitlines()
        i = 0
        current: Dict = {}

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            if line.startswith("#EXTM3U"):
                i += 1
                continue

            if line.startswith("#EXTINF:"):
                m = self._EXTINF_RE.match(line)
                if m:
                    attrs_str = m.group("attributes")
                    attrs = {}
                    for am in self._ATTR_RE.finditer(attrs_str):
                        key = am.group("key").replace("tvg-", "")
                        attrs[key] = am.group("value")
                    current = {
                        "name": m.group("name"),
                        "duration": m.group("duration"),
                        "logo": attrs.get("logo", ""),
                        "group": attrs.get("group-title", ""),
                    }
            elif line.startswith("http"):
                if current:
                    ch = Channel(
                        name=current.get("name", "Unknown"),
                        url=line,
                        logo=current.get("logo", ""),
                        group=current.get("group", ""),
                    )
                    channels.append(ch)
                    current = {}
            i += 1

        return channels

    async def _fetch_yaml(self, url: str) -> List[Channel]:
        """获取并解析 YAML（Free-IPTV 格式）"""
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                text = await resp.text()

        import yaml
        data = yaml.safe_load(text)
        channels = []

        if isinstance(data, dict) and "streams" in data:
            for item in data["streams"]:
                name = item.get("name", "Unknown")
                url = item.get("url", "")
                if url:
                    ch = Channel(
                        name=name,
                        url=url,
                        logo=item.get("logo", ""),
                        group=item.get("group", ""),
                    )
                    channels.append(ch)
        elif isinstance(data, list):
            for item in data:
                name = item.get("title", item.get("name", "Unknown"))
                url = item.get("file", item.get("url", ""))
                if url:
                    ch = Channel(
                        name=name,
                        url=url,
                        logo=item.get("logo", ""),
                        group=item.get("category", ""),
                    )
                    channels.append(ch)

        return channels
