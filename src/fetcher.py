"""抓取模块，支持 m3u / yaml / markdown 表格三种格式、并发控制、失败重试

## 格式判定（按内容嗅探，不看后缀）

早期版本按后缀分派：`.yml`/`.yaml` → YAML，**其他一律当 m3u**。
这导致 `config/sources.yaml` 里 8 个 `.md` 结尾的源（Free-TV 各区域列表 + 其 fork）
返回 HTTP 200、打印 `got 0 channels`，**静默失效**——Free-TV 的 `.md` 是 markdown 表格，
不是 m3u 语法。见 `parse_markdown_table()`。

现在的判定顺序（先抓文本，再嗅探）：

1. 含 `#EXTINF` → m3u（这条优先，因为有仓库把 m3u 内容存成 `.md`）
2. 含 markdown 表格行 `| ... | [>](http...) | ... |` → markdown 表格
3. 能被 `yaml.safe_load` 解析且含 `streams` / list → YAML（Free-IPTV 格式）
4. 都不匹配 → 0 条 + 打 WARNING（不再静默）
"""
import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from .config import Config


class Channel:
    """频道对象"""

    def __init__(
        self,
        name: str,
        url: str,
        logo: str = "",
        group: str = "",
        id: str = "",  # noqa: A002 —— 历史/播放器口径就叫 tvg-id，属性名保持 ch.id
        **kwargs,
    ):
        # 唯一出口：m3u / markdown / yaml 三条解析分支都从这里过，
        # 名字里的 Free-TV 来源标记（ⒼⓈⓉⒻⓎⓃ）在这里统一剥掉，见 strip_source_markers()。
        self.name = strip_source_markers(name)
        self.url = url.strip()
        self.logo = logo.strip() if logo else ""
        self.group = group.strip() if group else ""
        # tvg-id：EPG 绑定键（例：`CelestialMovies.hk@SD`）。源里没有就是空串 ——
        # 绝不用频道名伪造，伪造出来的 id 在节目表里查不到，比空串更糟。
        self.id = id.strip() if id else ""
        self.raw_attrs = kwargs
        # _normalized_name 通过 kwargs 传入（grouper.py 依赖此属性）
        self._normalized_name = kwargs.pop("_normalized_name", "") if kwargs else ""

    def __repr__(self):
        return f"<Channel {self.name} ({self.group})>"


# Free-TV 列表里用来标注来源/可访问性的标记字符，不属于频道名。
# 含义（Free-TV README 只定义了前三条）：Ⓖ GeoIP 屏蔽 · Ⓢ 非 HD · Ⓨ YouTube 直播，
# Ⓣ/Ⓕ/Ⓝ 未说明。它们既出现在 markdown 表格源里，也出现在官方 playlist.m3u8 的
# m3u 源里（实测 2053 条 EXTINF 里 467 条带标记），所以剥离要做在所有分支的共用出口上。
_SOURCE_NAME_MARKERS = "ⒼⓈⓉⒻⓎⓃ"
_MARKER_CHARS_RE = re.compile("[" + _SOURCE_NAME_MARKERS + "]+")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_source_markers(name: str) -> str:
    """去掉频道名里的来源标记字符，并收干净留下的空格。

    覆盖「标记在尾部」「标记夹在中间」「多个标记连着」「标记前后有空格」
    以及标记与名字黏连（`PhoenixⒼ`）这几种真实形态：

        'HOY TV Ⓖ'            -> 'HOY TV'
        'BBC Parliament Ⓢ Ⓣ' -> 'BBC Parliament'
        'PhoenixⒼ'            -> 'Phoenix'
        'MTV Azerbaijan Ⓢ Ⓨ' -> 'MTV Azerbaijan'

    只动前面列出的那 6 个字符；标记与文字黏连时补一个空格而不是直接删掉，
    避免 `AⒼB` 被粘成 `AB` 这种凭空造词的后果。
    """
    if not name:
        return ""
    cleaned = _MARKER_CHARS_RE.sub(" ", name)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


_MD_LINK_RE = re.compile(r"\[>?\]?\((?P<url>https?://[^)\s]+)\)")
_MD_LOGO_RE = re.compile(r'src="(?P<logo>https?://[^"]+)"')

# 名字里若还残留 `tvg-…=` / `group-title=`，说明这条 EXTINF 把属性写到了
# 时长后面的逗号之后（`#EXTINF:-1,tvg-id="X" …`），见 parse_m3u_text 的兜底。
_INLINE_ATTR_RE = re.compile(r'(?:tvg-(?:id|name|logo|chnid)|group-title|attribute)=')


@dataclass
class ParseResult:
    """一次解析的结果 —— 带上「用什么格式解析的」，便于排错"""

    channels: List[Channel]
    format: str  # m3u | markdown | yaml | empty


class Fetcher:
    """频道抓取器"""

    _EXTINF_RE = re.compile(
        r"#EXTINF:(?P<duration>-?\d+)\s*(?P<attributes>[^,]*),\s*(?P<name>.+)"
    )
    # 属性白名单。`id` 必须在这里 —— 源里（iptv-org 的 streams/*.m3u）用 tvg-id 做
    # EPG 主键，之前漏捕它，导致产物有 x-tvg-url 却没有任何绑定键，节目表接不上。
    # 前缀剥离见 parse_m3u_text（key.replace("tvg-", "")），`tvg-id` → `id`。
    _ATTR_RE = re.compile(
        r'(?P<key>tvg-(?:id|name|logo|chnid)|group-title|attribute)="(?P<value>[^"]*)"'
    )

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
        headers = source.get("headers") or None
        print(f"  → 正在抓取: {name} ...")

        for attempt in range(self.max_retries):
            try:
                channels = await self._fetch_url(url, headers=headers)
                if channels:
                    print(f"[Fetcher] {name}: got {len(channels)} channels")
                else:
                    # 曾经这里是静默的 —— HTTP 200 + 0 条会让整条流水线「看起来正常」
                    print(
                        f"[Fetcher] WARNING: {name} 返回 0 个频道 "
                        f"(格式可能不被支持，或源内容为空) url={url}"
                    )
                for ch in channels:
                    ch.raw_attrs["_source"] = name
                    ch.raw_attrs["_priority"] = priority
                return channels
            except Exception as e:
                print(f"[Fetcher] {name} attempt {attempt+1} failed: {e}")
                await asyncio.sleep(1 * (attempt + 1))

        print(f"[Fetcher] {name}: all retries exhausted")
        return []

    async def _fetch_url(self, url: str, headers: Optional[Dict[str, str]] = None) -> List[Channel]:
        """获取 URL 内容并按内容嗅探格式解析"""
        text = await self._get_text(url, headers=headers)
        return self.parse_text(text).channels

    async def _get_text(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        if self._semaphore is None:
            # 允许不经过 fetch_all() 直接调用（脚本/测试常用）
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        timeout = aiohttp.ClientTimeout(total=30)
        async with self._semaphore:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.text()

    # ── 纯函数解析层（无网络，方便单测）─────────────────────────────

    def parse_text(self, text: str) -> ParseResult:
        """按内容嗅探格式并解析。顺序见模块 docstring。"""
        if not text or not text.strip():
            return ParseResult([], "empty")

        # 1) m3u 优先：有仓库把 m3u 存成 .md，不能按后缀判
        if "#EXTINF" in text:
            chans = self.parse_m3u_text(text)
            if chans:
                return ParseResult(chans, "m3u")

        # 2) markdown 表格（Free-TV 的 lists/*.md）
        chans = self.parse_markdown_table(text)
        if chans:
            return ParseResult(chans, "markdown")

        # 3) YAML（Free-IPTV 格式）
        chans = self.parse_yaml_text(text)
        if chans:
            return ParseResult(chans, "yaml")

        return ParseResult([], "empty")

    def parse_m3u_text(self, text: str) -> List[Channel]:
        """解析 m3u / m3u8 文本"""
        channels: List[Channel] = []
        current: Dict[str, Any] = {}

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#EXTM3U"):
                continue

            if line.startswith("#EXTINF:"):
                m = self._EXTINF_RE.match(line)
                if m:
                    attrs_str = m.group("attributes")
                    name = m.group("name")
                    # 有些源把属性写在「时长」后面的逗号*之后*：
                    #     #EXTINF:-1,tvg-id="CCTV1" tvg-name="CCTV1" group-title="X",CCTV1-4K
                    # `attributes` 是 `[^,]*`，遇到 `-1,` 只抓到空串，剩下的整串属性
                    # 会被当成频道名（实测 6 条 CCTV 4K 条目带出一整串 `tvg-…` 垃圾名）。
                    # 这里把名字里最后一个逗号之前的部分拨回属性区，真名取最后一段。
                    if _INLINE_ATTR_RE.search(name):
                        head, sep, tail = name.rpartition(",")
                        if sep and tail.strip():
                            attrs_str = f"{attrs_str} {head}"
                            name = tail
                    attrs = {}
                    for am in self._ATTR_RE.finditer(attrs_str):
                        key = am.group("key").replace("tvg-", "")
                        attrs[key] = am.group("value")
                    current = {
                        "name": name,
                        "duration": m.group("duration"),
                        "logo": attrs.get("logo", ""),
                        "group": attrs.get("group-title", ""),
                        # 正则未锚定，`x-tvg-id="..."` 里的 `tvg-id` 同样命中，
                        # 因此这里只需认 "id"；源里没有就是空串，不伪造
                        "id": attrs.get("id", ""),
                    }
            elif line.startswith("http"):
                if current:
                    channels.append(
                        Channel(
                            name=current.get("name", "Unknown"),
                            url=line,
                            logo=current.get("logo", ""),
                            group=current.get("group", ""),
                            id=current.get("id", ""),
                        )
                    )
                    current = {}

        return channels

    def parse_markdown_table(self, text: str) -> List[Channel]:
        """解析 markdown 表格形式的频道列表（Free-TV `lists/*.md`）。

        形如：

            | #   | Channel | Link | Logo | EPG id |
            |:---:|:-------:|:----:|:----:|:------:|
            | 31  | RTHK TV 31 | [>](https://x/master.m3u8) | <img src="https://y.png"/> | RTHKTV31.hk |

        - 频道名 = 链接列**左边那一列**
        - logo = 行内 `<img src="...">`
        - 名字里的来源标记（`Ⓖ` GeoIP 屏蔽、`Ⓢ` 非 HD、`Ⓨ` YouTube 直播等）去掉，
          它们不是频道名的一部分。标记可能在尾部，也可能夹在中间
          （`BBC Parliament Ⓢ Ⓣ`），统一走 `strip_source_markers()`
        """
        channels: List[Channel] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("|") or line.count("|") < 3:
                continue

            m = _MD_LINK_RE.search(line)
            if not m:
                continue  # 表头 / 分隔行 / 没有链接的行

            url = m.group("url")
            cells = [c.strip() for c in line.strip("|").split("|")]

            # 找到含链接的单元格，名字取它左边一格
            link_idx = next((i for i, c in enumerate(cells) if url in c), -1)
            name = ""
            if link_idx > 0:
                name = cells[link_idx - 1]
            if not name:
                continue

            # 剥离来源标记（Channel 出口也会做，这里提前做是为了让空名判断有意义）
            name = strip_source_markers(name)
            if not name:
                continue

            logo_m = _MD_LOGO_RE.search(line)
            channels.append(
                Channel(
                    name=name,
                    url=url,
                    logo=logo_m.group("logo") if logo_m else "",
                    group="",  # markdown 表格没有分组列，交给 categorizer 按名字判
                )
            )

        return channels

    def parse_yaml_text(self, text: str) -> List[Channel]:
        """解析 YAML（Free-IPTV 格式）文本"""
        try:
            import yaml
        except ImportError:
            return []

        try:
            data = yaml.safe_load(text)
        except Exception:
            return []

        channels: List[Channel] = []

        if isinstance(data, dict) and "streams" in data:
            for item in data["streams"]:
                if not isinstance(item, dict):
                    continue
                url = item.get("url", "")
                if url:
                    channels.append(
                        Channel(
                            name=item.get("name", "Unknown"),
                            url=url,
                            logo=item.get("logo", ""),
                            group=item.get("group", ""),
                        )
                    )
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = item.get("title", item.get("name", "Unknown"))
                url = item.get("file", item.get("url", ""))
                if url:
                    channels.append(
                        Channel(
                            name=name,
                            url=url,
                            logo=item.get("logo", ""),
                            group=item.get("category", ""),
                        )
                    )

        return channels

    # ── 兼容旧接口 ──────────────────────────────────────────────

    async def _fetch_m3u(self, url: str) -> List[Channel]:
        """抓取并解析（保留旧名，行为已改为内容嗅探）"""
        return await self._fetch_url(url)

    async def _fetch_yaml(self, url: str) -> List[Channel]:
        """抓取并按 YAML 解析（保留旧名）"""
        text = await self._get_text(url)
        result = self.parse_yaml_text(text)
        if not result:
            print(f"[Fetcher] WARNING: {url} 用 YAML 解析出 0 个频道")
        return result
