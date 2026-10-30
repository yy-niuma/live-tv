"""验证模块：HEAD 优先、Content-Type 检查、代理域名拒绝、CDN 白名单跳过、熔断跳过已知死链"""
import asyncio
import re
from typing import List, Set
from urllib.parse import urljoin, urlparse, urlsplit

import aiohttp

from .config import Config
from .fetcher import Channel
from .lib import stream_health

# 浏览器 UA。aiohttp 默认发 `Python/3.x aiohttp/x.y`，大量源站按 UA 拦截，
# 实测同一批 306 条港台死链：默认 UA 存活 0 条，换这个 UA 存活 14 条
# （翡翠台 / TVB星河 / 無線新聞 / 台視 / 民視 / 公視 / 澳視衛星 / TVBPearl /
#   TVB娱乐新闻台 / 莲花卫视）—— 全是真频道被 UA 误杀。
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 占位片 / 维护卡关键词。命中即判死：有码流但没有节目。
# epg.pw 的 stream 全部指向 nosignal_h264 占位片，是产物里最大的一类假阳性。
PLACEHOLDER_KEYWORDS = (
    "nosignal",
    "no_signal",
    "nosignals",
    "placeholder",
    "maintenance",
    "offline",
    "under_maintenance",
)

# 伪直播关键词：m3u 本身有效，但下一跳是点播平台而不是直播流。
PSEUDO_LIVE_KEYWORDS = (
    "youtube.com",
    "youtu.be",
    "www.youtube.com",
)


def _is_playlist_content_type(content_type: str) -> bool:
    """Content-Type 是否「可能是」播放列表（需要再 GET 一次读 body）。

    只有可能是播放列表才值得补一次 GET：它是几 KB 文本，判占位片/伪直播很便宜。
    视频流（video/*）不补，避免下载大文件。

    **必须收 `text/plain`**：实测 `fast.hidns.vip` / `cdn6.cc.cd` 这类聚合源的
    播放列表全部以 `Content-Type: text/plain` 返回，分片甚至标成 `image/jpeg`。
    如果只认 `mpegurl`，这批真能播的源会被自己的口径判死。

    但收 `text/plain` 会把「HTML 错误页被标成 text/plain」也放进来 —— 所以
    判断播放列表**最终以 body 是否以 `#EXTM3U` 开头为准**，见 `_is_valid_content`。
    Content-Type 只是「要不要去读 body」的触发器，不是结论。
    """
    ct = (content_type or "").lower()
    return "mpegurl" in ct or "x-mpegurl" in ct or "application/vnd.apple" in ct or "text/plain" in ct


def _body_is_playlist(body: str) -> bool:
    """body 是否是 m3u 播放列表：剥掉 BOM/空白后以 `#EXTM3U` 开头。

    这是播放列表的**唯一可靠签名**。Content-Type 实测被大量服务器标错
    （播放列表标 text/plain、分片标 image/jpeg），拿 Content-Type 当结论
    会把活源判死，也会把 HTML 错误页当活源放行。
    """
    if not body:
        return False
    return body.lstrip("\ufeff \t\r\n").startswith("#EXTM3U")


# master 播放列表的下一跳标记
STREAM_INF_TAG = "#EXT-X-STREAM-INF"


def _first_child_uri(body: str) -> str:
    """摘出 master 播放列表里第一个子流的 URI（`#EXT-X-STREAM-INF` 之后第一条非注释行）。

    只取第一个：目的是识别「整棵树都不可达」，不是给每个码率做健康检查。
    返回 `""` 表示不是 master 或格式异常。
    """
    if not body:
        return ""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(STREAM_INF_TAG):
            for nxt in lines[i + 1:]:
                cand = nxt.strip()
                if cand and not cand.startswith("#"):
                    return cand
            return ""
    return ""


def _looks_like_playlist_url(url: str) -> bool:
    """URL 路径是否以播放列表后缀结尾（.m3u8 / .m3u）。

    这类 URL 反正要 GET 读 body 才能判占位片，跳过 HEAD 直接 GET，
    省掉一半请求。实测验证阶段 1687s → ~900s。
    """
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return False
    return path.endswith(".m3u8") or path.endswith(".m3u")


class Validator:
    """频道 URL 验证器

    熔断（URL 级指数退避）：
    - 一次跑批里 99% 的耗时都在验证阶段，而实测快照里 59% 的 URL 是死链；
      旧版每轮都把这些死链重探一遍。
    - 现在 `_validate_one` 的顺序是：空 URL → 代理黑名单 → **CDN 白名单** →
      **熔断冻结期** → 真探。冻结期内的 URL **0 请求**直接判不可用。
    - **白名单命中不更新熔断状态**（一个包都没发 = 没有观测），语义见
      `_validate_one` 的注释与 `tests/test_stream_health_circuit.py`。
    - 状态文件默认 `config/stream_health.json`；不存在就是空状态，
      验证流程照常跑（不因缺文件而崩），只有真正探测过的条目才会被写回。
    """

    def __init__(
        self,
        config: Config = None,
        max_concurrent: int = 20,
        timeout: int = 10,
        health_file=None,
    ):
        self.config = config or Config()
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._semaphore: asyncio.Semaphore = None
        # 惰性：构造 Validator 不等于读文件；health_file=None 走 DEFAULT_PATH
        self.health_file = health_file
        self._circuit: stream_health.Circuit | None = None

    # -- 熔断状态 ------------------------------------------------
    @property
    def circuit(self) -> stream_health.Circuit:
        """惰性加载熔断状态（文件不存在 → 空状态，绝不抛）。"""
        if self._circuit is None:
            self._circuit = stream_health.Circuit(self.health_file)
        return self._circuit

    def _is_frozen(self, url: str) -> bool:
        try:
            return self.circuit.is_frozen(url)
        except Exception:  # 熔断是优化，不是门禁依赖：任何异常都放行探测
            return False

    def _record(self, url: str, ok: bool) -> None:
        try:
            if ok:
                self.circuit.record_success(url)
            else:
                self.circuit.record_failure(url)
        except Exception:
            pass

    def persist_health(self) -> None:
        """把本次的熔断状态写回文件（无变化则不写；任何失败都只警告）。"""
        circuit = self._circuit
        if circuit is None or not circuit.dirty:
            return
        try:
            circuit.save()
        except OSError as exc:
            print(f"[Health] 熔断状态写回失败（不影响验证结果）：{exc}")

    async def validate(self, channels: List[Channel]) -> List[Channel]:
        """验证频道列表，返回有效频道。

        判定口径（保守）：**只有探测真正成功、结果就是布尔 `True` 才算有效**。
        `gather(return_exceptions=True)` 会把子任务抛出的异常对象原样放进结果列表，
        而异常对象在布尔上下文里恒为真 —— 所以这里必须用 `valid is True` 严格比对，
        不能用 `if valid`。否则 `urlparse` 抛 ValueError 的畸形 IPv6 字面量
        （如 `http://[::1/list.m3u8`）、url 非字符串抛 AttributeError 的条目，
        都会被当成「验证通过」留在产物里。宁可漏一条，也不把死链放进去。
        """
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        tasks = [self._validate_one(ch) for ch in channels]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # 整批跑完再落盘：不拖慢单条探测，也避免并发写文件
        self.persist_health()
        return [ch for ch, valid in zip(channels, results) if valid is True]

    async def _validate_one(self, channel: Channel) -> bool:
        """验证单个频道。

        顺序是有意为之（熔断与白名单的先后关系，测试钉死）：
        1. 空 URL → False
        2. 代理黑名单 → False（不记熔断：这是我们主动拒绝，不是链路死了）
        3. CDN 白名单 → **True，且不更新熔断状态**
           —— 一个请求都没发，没有观测可记。记「成功」会让死掉的白名单
           链路被永久清零、永远进不了熔断器（正是 81 条里 15 条 0 请求、
           其中 7 条实测 403 的那个盲区）；记「失败」则是凭空造证据。
        4. 熔断冻结期内 → **False，0 请求**（核心收益：跳过已知死链）
        5. 真探 HEAD/GET → 按结果更新计数（成功清零 / 失败累加）
        """
        url = channel.url
        if not url:
            return False

        # 0. 只认 http(s)：别的 scheme（ftp:// 等）是结构非法，aiohttp 也会拒。
        #    在这里挡掉 = 0 请求，也**不进熔断计数**（它不是一个真实的链路观测）。
        if urlparse(url).scheme.lower() not in ("http", "https"):
            return False

        # 1. 检查代理域名（主动拒绝，不是链路故障，不记熔断）
        if self._is_proxy_domain(url):
            return False

        # 2. 白名单 CDN：跳过协议层校验，但**播放列表仍要读 body 判内容**
        #    （不更新熔断状态：0 请求 = 无观测，记成功会让 403 永久清零）
        if self._is_whitelisted_cdn(url):
            return await self._check_whitelisted(url)

        # 3. 熔断：冻结期内不再探测（0 请求）
        if self._is_frozen(url):
            return False

        # 4. HEAD 请求验证
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

    async def _check_whitelisted(self, url: str) -> bool:
        """白名单主机的判定：跳过协议层，但对播放列表仍做内容层检查。

        为什么需要这一步：白名单原来的语义是「命中即 0 请求放行」。但
        `raw.githubusercontent.com` 也在白名单里，而 ChiSheng9/iptv 这类
        仓库的 m3u **下一跳指向 youtube.com** —— 命中白名单就永远不会
        读 body，于是「有码流没节目」的伪直播长期占据产物（CI 白名单
        盲区门禁实测 5/64 命中：4 条 youtube 伪直播 + 1 条 403）。

        刻意保留的不对称：
        - **非播放列表 URL**（没有 .m3u8/.m3u 后缀）→ 仍然 0 请求放行，
          保留原来「省请求」的语义；
        - **读 body 失败**（geo-block 403、超时）→ 保守放行。白名单里的
          cloudfront/akamai 在本机常返回 403（地理封锁），但频道本身是活的；
          「读不到」不能当成「假」的证据。
        """
        if not _looks_like_playlist_url(url):
            return True
        # 必须走同一个 semaphore：validate() 是 gather 全部频道，
        # 不设限会让白名单里的播放列表 URL 一次性全打出去。
        async with self._semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        url,
                        headers={"User-Agent": BROWSER_USER_AGENT},
                        allow_redirects=True,
                    ) as resp:
                        body = await self._read_body(resp)
            except Exception:
                return True
        return self._is_valid_content(body)

    async def _check_url(self, url: str) -> bool:
        """请求验证 URL 可访问性，并把**真实观测**写回熔断状态。

        判定分两层（两层都要过才算活）：
        1. 协议层：状态码 200 + Content-Type 不是 HTML；
        2. 内容层：播放列表的 body 里不能有占位片标记（nosignal / maintenance…）
           也不能指向点播平台（youtube.com）—— 这类是「有码流没节目」的
           伪直播，epg.pw 的 stream 全部是 nosignal 占位片。

        为什么要 GET 一次：HEAD 没有 body，判不出占位片。只对**播放列表类型**
        （mpegurl）补一次 GET 并只读前 4KB —— 播放列表是几 KB 的文本，
        代价可忽略；视频流（video/*）不补 GET，避免下载大文件。

        `aiohttp.InvalidURL`（无 scheme / 相对路径 / ftp:// 等）是结构非法，
        不是「这条链路死了」—— 它根本没到网络上，所以**不记熔断**（否则
        拼错的 URL 会白白占掉一个冻结名额，也会污染共享的快照文件）。
        其余 ClientError / 超时 / 非 200 / HTML 都是真实失败，累加计数。
        """
        headers = {"User-Agent": BROWSER_USER_AGENT}
        async with self._semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # 播放列表 URL：HEAD 拿不到 body，反正要补一次 GET，
                    # 干脆直接 GET 一次读前 4KB —— 省掉一半请求。
                    # 实测这一步把验证阶段从 1687s 拉回 ~900s。
                    if _looks_like_playlist_url(url):
                        async with session.get(url, headers=headers,
                                               allow_redirects=True) as resp:
                            if not self._is_valid_response(resp):
                                return self._finish(url, False)
                            body = await self._read_body(resp)
                            return self._finish(
                                url, await self._judge_body(session, url, body)
                            )
                    # 先尝试 HEAD
                    async with session.head(url, headers=headers,
                                            allow_redirects=True) as resp:
                        if resp.status == 405:
                            # HEAD 不支持，尝试 GET
                            async with session.get(url, headers=headers,
                                                   allow_redirects=True) as get_resp:
                                ok = self._is_valid_response(get_resp)
                                if ok:
                                    body = await self._read_body(get_resp)
                                    ok = await self._judge_body(session, url, body)
                                return self._finish(url, ok)
                        if not self._is_valid_response(resp):
                            return self._finish(url, False)
                        if not _is_playlist_content_type(
                            resp.headers.get("Content-Type", "")
                        ):
                            return self._finish(url, True)
                        # Content-Type 说是播放列表（URL 后缀没暴露）：
                        # 补一次 GET 读 body，判占位片 / 伪直播
                        async with session.get(url, headers=headers,
                                               allow_redirects=True) as get_resp:
                            body = await self._read_body(get_resp)
                            return self._finish(
                                url, await self._judge_body(session, url, body)
                            )
            except aiohttp.InvalidURL:
                return False
            except (aiohttp.ClientError, asyncio.TimeoutError):
                self._record(url, False)
                return False

    async def _judge_body(self, session, url: str, body) -> bool:
        """内容层判定 + 假 200 深挖。

        `_is_valid_content` 只看 body 自身的标记；master 播放列表还要看它
        指向的子流能不能到 —— 见 `_children_reachable`。
        """
        if not self._is_valid_content(body):
            return False
        return await self._children_reachable(session, url, body)

    async def _children_reachable(self, session, base_url: str,
                                  body, ) -> bool:
        """master 播放列表再往下探一跳（1 次 GET）。

        **为什么必须探**：RTHK 官方 feeds 是「假 200」—— master 自身 200 且是
        合法 m3u，但里面的 akamaized 子流在本机全部 403（纯 geo-block，加
        Referer/Origin 无效）。只看 master 会把这种死链判活，进而让它在同名
        合并里压过实测可播的替代源 —— RTHK 31 / RTHK 32 就是这么被拖死的：
        快照里 `rthktv31-live.akamaized.net/.../master.m3u8` 是 `True`，
        `fast.hidns.vip/163189/rthk31` 也是 `True`，打平后按 CDN 优先级
        (`rthk.hk` 属 hk_patterns) 选了死链。

        只探第一个子流；解析不出 URI / 读不到都**保守放行**（不能把解析失败
        当成「流死了」的证据）。
        """
        child = _first_child_uri(body)
        if not child:
            return True
        try:
            child_url = urljoin(base_url, child)
        except ValueError:
            return True
        try:
            async with session.get(child_url,
                                   headers={"User-Agent": BROWSER_USER_AGENT},
                                   allow_redirects=True) as resp:
                if resp.status != 200:
                    return False
                ctype = (resp.headers.get("Content-Type", "") or "").lower()
                if "text/html" in ctype:
                    # 子流回的是 HTML 错误页/拦截页 —— 状态码 200 也不算到
                    return False
                if not _is_playlist_content_type(ctype):
                    # 子流直接是分片/TS（master 写法不规范）→ 200 就算到
                    return True
                child_body = await self._read_body(resp)
                if child_body is None:
                    return True
                return _body_is_playlist(child_body)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    def _finish(self, url: str, ok: bool) -> bool:
        """统一的「有观测」出口：记账 + 返回判定。"""
        self._record(url, ok)
        return ok

    async def _read_body(self, resp, limit: int = 4096):
        """读响应体前 limit 字节。

        返回 `None` 表示**读不到**（异常），返回 `""` 表示真的读到了空 body。
        两者语义必须分开：读不到（geo-block / chunked 异常）不能当成「假」的
        证据；而 200 + 空 body 的「播放列表」根本不是播放列表。合并成 `""`
        会让这两种情况互相污染。

        只读前 4KB：占位片标记（nosignal）出现在播放列表的头部就够判了。
        """
        try:
            raw = await resp.content.read(limit)
            return raw.decode("utf-8", "replace")
        except Exception:
            return None

    def _is_valid_response(self, resp: aiohttp.ClientResponse) -> bool:
        """协议层判定：状态码 + Content-Type（同步纯逻辑，无网络）。

        **不看 body**：body 需要异步读，放在 `_check_url` 里按需调用
        `_is_valid_content`。这里保持同步，是为了不破坏既有调用契约。
        """
        if resp.status != 200:
            return False
        content_type = resp.headers.get("Content-Type", "")
        # 拒绝 HTML
        if "text/html" in content_type.lower():
            return False
        # 接受视频类型或空 Content-Type。
        # `text/plain` 必须收：聚合源的播放列表就长这样（实测 hidns/cdn6）。
        valid_types = ["video", "audio", "application/octet-stream", "application/x-mpegurl", "application/vnd.apple.mpegurl", "text/plain"]
        if content_type and not any(vt in content_type.lower() for vt in valid_types):
            return False
        return True

    def _is_valid_content(self, body) -> bool:
        """内容层判定：真播放列表 / 占位片 / 伪直播。

        - `body is None`（读不到）→ **保守放行**：geo-block 的 403、chunked
          读取异常都会走到这里，「读不到」不能当成「假」的证据。
        - 空 body → 不可用：`Content-Type` 说是播放列表却一个字都没有。
        - **不以 `#EXTM3U` 开头 → 不可用**：这是播放列表的真签名。少了这一条，
          被标成 `text/plain` 的 HTML 错误页会被当成活源（实测 epg.pw 的
          nosignal 占位片与 Cloudflare 的错误页都走这条路混进来）。
        - 占位片：有码流没节目（nosignal / maintenance / offline…）
        - 伪直播：m3u 本身有效，但下一跳是点播平台（youtube.com）
        """
        if body is None:
            return True
        if not body.strip():
            return False
        if not _body_is_playlist(body):
            return False
        low = body.lower()
        if any(k in low for k in PLACEHOLDER_KEYWORDS):
            return False
        if any(k in low for k in PSEUDO_LIVE_KEYWORDS):
            return False
        return True
