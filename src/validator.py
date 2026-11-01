"""验证模块：HEAD 优先、Content-Type 检查、代理域名拒绝、CDN 白名单跳过、熔断跳过已知死链"""
import asyncio
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from math import isqrt
from typing import Deque, Dict, List, Set
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
    # YouTube 的**静态资源 CDN**（2026-11-01 curl 独立复核实测）：
    # `alimov2.a.kwimgs.com/upic/...` 是用户头像/缩略图资源，
    # 返回 200 + image/jpeg，却因为不在 youtube.com / youtu.be 里
    # 而漏过伪直播判定，被当成可播频道写进产物
    # （产物 1,375 条 URL 里有 21 条是这种）。
    "kwimgs.com",
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


# 裸媒体后缀：.ts / .mp4 / .mp3 / .aac / .flv …
# 这些**不是**播放列表 —— 直连它们拿到的是点播文件或裸分片，
# 不是可播的直播流。
#
# 为什么要单独识别（2026-11-01 curl 独立复核实测）：
# `_is_valid_response()` 收 `"video"` Content-Type，而
# `_looks_like_playlist_url()` 只认 .m3u8/.m3u —— 于是 `.ts` 走
# **HEAD 路径**，拿到 200 + `video/mp2t` 就判活，**从头到尾没读 body**，
# 连「这是不是直播」都没问过。实测样本：
#     http://125.227.210.55:1001/VideoInput/play.ts   → 200 video/mp2t，body 是裸 TS
#     http://s.rocketdns.info:8080/live/.../648984.ts → 200 video/mp2t
#
# 修法：裸媒体后缀也走 GET 读 body，用**播放列表签名**（#EXTM3U）判定 ——
# 有的源确实用 .ts 后缀装 HLS 清单（所以不能一刀切按后缀判死）。
BARE_MEDIA_SUFFIXES = (".ts", ".mp4", ".mp3", ".aac", ".flv", ".m4s", ".mov")

# DNS 解析失败的重试次数与退避基数（秒）。
#
# 为什么单独给 DNS 配重试：`ClientConnectorDNSError` 既不能证明链活也不能
# 证明链死 —— 它是**环境**的观测，不是链路的观测。高并发下本机解析器返回
# EAI_AGAIN 是瞬时的，等一下再问通常就成功。不重试的话只能在两个坏结果里
# 选一个：判死（误杀真频道 + 毒化熔断计数）或原地放行（没验证就进产物）。
#
# 代价：DNS 正常时循环只跑 1 轮，零额外请求；只有真的解析失败才多花
# 0.2s 一次退避。
#
# 为什么从 2 次降到 1 次：DNS 重试是**唯一会让每条失败 URL 变慢**的改动，
# CI dispatch 实测（run #205/#208）验证阶段从 18 分钟涨到 27+ 分钟，
# 需要先把它压到最小影响面再定位。1 次足够覆盖「瞬时 EAI_AGAIN」。
DNS_RETRIES = 1
DNS_RETRY_DELAY = 0.2

# 分级超时（见 `Validator._timeout_for`）：连败达到这个次数的 URL 视为「已知死链」，
# 用短超时探测。CI 实测验证阶段 99% 的耗时都花在等这些老死链的超时上。
KNOWN_DEAD_MIN_BAD = 2
KNOWN_DEAD_TIMEOUT = 4

# 每个 host 的并发上限。
#
# 为什么要有这个：全局并发拉高后，掉条不是被总带宽卡住，而是**被单源限流**。
# 真实样本里 600 条 URL 只分布在 405 个 host，最多的单个 host 占 39 条
# （jmp2.uk 39、stream1.freetv.fun 30）。全局并发 160 时这些 host 会被
# 同时怼上几十个连接 ⇒ 源站限流/拒绝 ⇒ 判死 ⇒ 掉条。
#
# 实测（600 条真实 URL，干净环境、每档 2 轮）：
#     全局并发   可用条数   掉条
#        40        342       0
#        80        335       7
#       120        301      41
#       160        214     128
# 也就是说**瓶颈是 per-host 而不是全局**。放开全局并发、单独掐住每个 host，
# 才能在「不掉条」的前提下真正提吞吐。
PER_HOST_CONCURRENCY = 4


def _looks_like_bare_media_url(url: str) -> bool:
    """URL 路径是否以裸媒体后缀结尾（.ts / .mp4 …）。"""
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return False
    return path.endswith(BARE_MEDIA_SUFFIXES)


def _interleave_by_host(channels: List[Channel]) -> List[int]:
    """按 host 轮转重排探测顺序，返回下标序列。

    **为什么需要**：真实数据里同 host 的 URL 是**成块连续**的 ——
    19,319 条 URL 中有 **67.6%** 落在「连续同一 host 超过 4 条」的段里，
    最长的两段是 `stream1.freetv.fun` 1,199 条、`jmp2.uk` 1,179 条。

    在 per-host 限流（`PER_HOST_CONCURRENCY`）下，这种顺序会造成
    **队头阻塞**：轮到某个热 host 的那一段时，只有 4 个请求在飞，
    其余全局名额空转，直到这一段跑完才轮到下一个 host。

    按 host 轮转（round-robin）之后，同一时刻在飞的是「各 host 各一条」，
    既满足 per-host 上限，又能把全局并发放满。

    ⚠️ 只改**顺序**，不改任何判定 —— 结果仍按原下标映射回去。
    """
    if not channels:
        return []

    buckets: Dict[str, Deque[int]] = {}
    for i, ch in enumerate(channels):
        try:
            host = urlparse(getattr(ch, "url", "") or "").hostname or ""
        except Exception:
            host = ""
        buckets.setdefault(host, deque()).append(i)

    order: List[int] = []
    queues = [q for q in buckets.values() if q]
    while queues:
        nxt = []
        for q in queues:
            order.append(q.popleft())
            if q:
                nxt.append(q)
        queues = nxt
    return order


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
        # 按 host 的限流名额（见 `PER_HOST_CONCURRENCY` / `_host_sem`）
        self._host_sems: dict[str, asyncio.Semaphore] = {}
        # 每个 host 的 URL 数（validate() 开始时填充，供 _host_sem 算自适应上限）
        self._host_counts: dict[str, int] = {}
        # 惰性：构造 Validator 不等于读文件；health_file=None 走 DEFAULT_PATH
        self.health_file = health_file
        self._circuit: stream_health.Circuit | None = None
        # 批次级 session：validate() 建一个，全批共用，批次结束关闭。
        # 早期版本在 `_check_url()` 里每 URL 新建一个 —— 每次请求重做
        # TCP + TLS 握手，aiohttp 的连接池完全用不上。
        # None = 当前没有批次 session（有人在 validate() 之外直接调
        # `_check_url()`，如既有单测）→ 那条路径自己临时建一个。
        self._session: aiohttp.ClientSession | None = None
        # True = 正在 validate() 批次内（此时 session 是批次级、惰性创建）。
        self._in_batch = False

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

        **批次级 session（2026-11-01 性能优化）**：全批共用**一个**
        `ClientSession`（带 TCPConnector 连接池），批次结束才关闭。
        早期版本在 `_check_url()` 里每 URL 新建一个 session ——
        每次请求都重做 TCP + TLS 握手，aiohttp 的连接复用形同虚设。
        实测 3 个真实源：每请求新建 3.16s vs 共享并发 1.42s（**2.23x**）。
        验证阶段一次要探 18,945~22,000 条 URL，这个倍数直接乘在 CI 时长上。

        session 是**惰性**建的：第一次真要发请求时才建。
        整批都在熔断冻结期里（0 请求）时，一个 session 都不建 ——
        `tests/test_stream_health_circuit.py::test_frozen_url_sends_zero_requests`
        钉死了「0 请求 = 0 session」这条契约。

        判定口径、并发上限、超时、熔断计数全部保持原样 —— 只改连接复用。
        """
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._in_batch = True
        self._session = None
        total = len(channels)
        # 每个 host 有多少条 URL —— `_host_sem` 用它算自适应并发上限。
        # 必须在探测开始前算完：固定上限会让「一个 host 几千条」把整批卡死。
        counts: Dict[str, int] = {}
        for ch in channels:
            try:
                h = urlparse(getattr(ch, "url", "") or "").hostname or ""
            except Exception:
                h = ""
            counts[h] = counts.get(h, 0) + 1
        self._host_counts = counts
        self._host_sems = {}
        done = {"n": 0, "ok": 0}
        timings: List[tuple] = []
        t_start = time.monotonic()
        stop = asyncio.Event()

        async def _progress():
            """每 20 秒打一行进度。

            为什么必须要有：验证阶段在 CI 上占整个 job 的 99%，
            而之前**一行输出都没有** —— 45 分钟的验证是个纯黑盒，
            只能靠猜是 `fetch` 慢还是 `validate` 慢、是超时还是卡死。
            有了这行日志，任何一个 CI 跑批都能直接看出速率和 ETA。
            """
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=20)
                    break
                except asyncio.TimeoutError:
                    pass
                el = time.monotonic() - t_start
                n, ok = done["n"], done["ok"]
                rate = n / el if el > 0 else 0.0
                eta = (total - n) / rate if rate > 0 else 0.0
                print(
                    f"  [验证进度] {n}/{total} ({n * 100 // max(1, total)}%) "
                    f"ok={ok} 速率={rate:.1f}/s 已用={el:.0f}s ETA={eta:.0f}s",
                    flush=True,
                )

        async def _one(i: int) -> bool:
            t0 = time.monotonic()
            r = await self._validate_one(channels[i])
            timings.append((time.monotonic() - t0, getattr(channels[i], "url", "")))
            done["n"] += 1
            if r is True:
                done["ok"] += 1
            return r

        prog_task = asyncio.ensure_future(_progress())
        try:
            # 按 host 轮转重排探测**顺序**，消除 per-host 限流的队头阻塞
            # （真实数据里 67.6% 的 URL 是同 host 成块连续的，见
            #  `_interleave_by_host`）。判定与返回顺序都不变 ——
            # 结果按原下标映射回去，产物顺序仍然是输入的频道顺序。
            order = _interleave_by_host(channels)
            tasks = [_one(i) for i in order]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            stop.set()
            prog_task.cancel()
            self._in_batch = False
            session = self._session
            self._session = None
            if session is not None:
                # `close()` 是 aiohttp.ClientSession 的方法，但测试替身
                # （tests/ 里的假 session）不一定实现它 —— 用 getattr 兼容，
                # 别让「关连接」这个清理动作变成测试的刺。
                closer = getattr(session, "close", None)
                if closer is not None:
                    await closer()
        # 整批跑完再落盘：不拖慢单条探测，也避免并发写文件
        self.persist_health()
        elapsed = time.monotonic() - t_start
        self._print_slowest(timings, elapsed, total)
        valid_by_index = {i: r for i, r in zip(order, results)}
        return [
            ch for i, ch in enumerate(channels) if valid_by_index.get(i) is True
        ]

    @staticmethod
    def _print_slowest(timings: List[tuple], elapsed: float, total: int) -> None:
        """打印最慢的 10 条 URL —— 用来定位「谁在吃时间」。

        验证阶段慢的时候，只看总耗时没法判断是「普遍慢」还是
        「少数几条卡死」。耗时排行能直接区分这两种情况：
        若 top10 之和就占了总耗时的大头 → 是个别卡死，值得单独处理；
        若 top10 都很小 → 是普遍的源站延迟，只能靠并发或分片。
        """
        if not timings:
            return
        timings.sort(key=lambda x: -x[0])
        top = timings[:10]
        top_sum = sum(t for t, _ in top)
        serial_total = sum(t for t, _ in timings)
        print(
            f"  [验证耗时] 总计 {elapsed:.0f}s / {total} 条 "
            f"= {elapsed / max(1, total):.2f}s/条（墙钟均摊）",
            flush=True,
        )
        # 注意口径：这些 URL 是**并发**跑的，所以「top10 之和」与墙钟不能直接比
        # （并发下 sum 会远大于墙钟，得出 >100% 的假百分比）。
        # 正确比法是拿它跟**串行总耗时**比 —— 那才是「占比」的含义。
        print(
            f"  [验证耗时] 最慢 10 条合计 {top_sum:.0f}s "
            f"（占串行总耗时 {top_sum / max(1e-9, serial_total) * 100:.0f}% / "
            f"串行总计 {serial_total:.0f}s）",
            flush=True,
        )
        for dt, url in top:
            print(f"      {dt:6.2f}s  {url[:96]}", flush=True)

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
                async with self._session_scope() as session:
                    async with session.get(
                        url,
                        headers={"User-Agent": BROWSER_USER_AGENT},
                        allow_redirects=True,
                    ) as resp:
                        body = await self._read_body(resp)
            except Exception:
                return True
        return self._is_valid_content(body)

    @asynccontextmanager
    async def _session_scope(self):
        """取 session 的上下文管理器。

        **批次路径（热路径）**：`validate()` 期间（`self._in_batch` 为 True）
        全批共用**一个** session，连接池能真正复用
        （每 URL 新建会让 TCP/TLS 握手开销翻倍，实测 3 个真实源：
        3.16s vs 1.42s）。session **惰性**创建 —— 第一次真要发请求时才建，
        整批都在熔断冻结期（0 请求）时一个都不建。

        **兼容路径**：`validate()` 之外直接调 `_check_url()`（既有单测）
        时临时建一个、用完关掉。正常流水线永远走不到兼容路径。
        """
        if self._session is not None:
            yield self._session
            return
        if self._in_batch:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            # limit=0 = 不限连接数；并发上限由 semaphore 负责，不靠 connector 限流。
            # 两个上限同时存在会互相干扰（connector 先满 → 排队 → 看起来像变慢）。
            connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(timeout=timeout,
                                                  connector=connector)
            yield self._session
            return
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            yield session

    async def _check_url(self, url: str) -> bool:
        """带 DNS 重试的入口 —— 见 `_check_url_attempt`。

        DNS 解析失败（`ClientConnectorDNSError`）在**环境层面**是瞬时的
        （高并发下解析器返回 EAI_AGAIN），在**判定层面**它既不能证明链活、
        也不能证明链死。所以两个极端都不对：判死会误杀真频道，原地放行
        等于没验证就放进产物。**先重试**，重试用尽才保守放行。
        """
        # 先掐 host 名额、再进全局名额：顺序固定，避免两类 semaphore 交叉死锁。
        # 掐 host 的名额在外面还有个好处 —— 被单源限流卡住的任务不占用全局名额。
        async with self._host_sem(url):
            for attempt in range(DNS_RETRIES + 1):
                ok = await self._check_url_attempt(url, attempt)
                if ok is not None:      # None = DNS 失败且还该重试
                    return ok
            return True                 # 重试用尽：保守放行

    def _host_sem(self, url: str) -> asyncio.Semaphore:
        """按 host 取一个限流 semaphore（上限自适应，见下）。

        **固定上限是错的**（2026-11-01 CI 实测撞出来的）
        -------------------------------------------------
        最初把上限固定成 4，结果 CI dispatch 的验证阶段从 18 分钟涨到 27+ 分钟。
        实测出来的原因：最慢的 URL 全是播放列表（`.m3u8` / `.ctv`，每条 7~14.5s，
        因为要额外探一次子流），而 `stream1.freetv.fun` 这一个 host 就占了
        **1,199 条**这样的 URL。固定 4 个名额意味着：

            1,199 条 × ~12s ÷ 4 = 约 60 分钟    ← 与 CI 观测完全吻合

        也就是说**一个热 host 就能把整个验证阶段卡死**，
        不管全局并发放到多大 —— 全局名额空着，等一个 host 排队。

        自适应上限
        ----------
        `cap = max(PER_HOST_CONCURRENCY, isqrt(该 host 的 URL 数))`

        - 小 host（1~10 条）→ 走地板值 4，保持对源站克制；
        - 中等 host（几百条）→ sqrt 给出十几~二十，按体量放宽；
        - 巨型 host（1,199 条）→ 34，它本来就是能承载大流量的 CDN。

        这样「大 host 排队」和「小 host 被怼」两个极端都不会出现。
        """
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""
        sem = self._host_sems.get(host)
        if sem is None:
            n = self._host_counts.get(host, 1)
            cap = max(PER_HOST_CONCURRENCY, isqrt(max(1, n)))
            sem = asyncio.Semaphore(cap)
            self._host_sems[host] = sem
        return sem

    async def _check_url_attempt(self, url: str, attempt: int = 0):
        """单次探测尝试：返回 bool；DNS 失败且还该重试时返回 None。

        请求验证 URL 可访问性，并把**真实观测**写回熔断状态。

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
        tmo = self._timeout_for(url)   # 分级超时：见 `_timeout_for`
        async with self._semaphore:
            try:
                async with self._session_scope() as session:
                    # 播放列表 URL：HEAD 拿不到 body，反正要补一次 GET，
                    # 干脆直接 GET 一次读前 4KB —— 省掉一半请求。
                    # 实测这一步把验证阶段从 1687s 拉回 ~900s。
                    #
                    # 裸媒体后缀（.ts / .mp4 …）也走 GET：这类 URL 不是播放列表，
                    # 直连拿到的是点播文件或裸分片（2026-11-01 curl 独立复核实测
                    # 3/40 抽样是这种），HEAD 200 就放行是误判活。
                    # 读 body 用播放列表签名（#EXTM3U）判 —— 有的源确实用
                    # .ts 后缀装 HLS 清单，不能一刀切按后缀判死。
                    if _looks_like_playlist_url(url) or _looks_like_bare_media_url(url):
                        async with session.get(url, headers=headers,
                                               allow_redirects=True, timeout=tmo) as resp:
                            if not self._is_valid_response(resp):
                                return self._finish(url, False)
                            body = await self._read_body(resp)
                            return self._finish(
                                url, await self._judge_body(session, url, body)
                            )
                    # 先尝试 HEAD
                    async with session.head(url, headers=headers,
                                            allow_redirects=True, timeout=tmo) as resp:
                        if resp.status == 405:
                            # HEAD 不支持，尝试 GET
                            async with session.get(url, headers=headers,
                                                   allow_redirects=True, timeout=tmo) as get_resp:
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
                                               allow_redirects=True, timeout=tmo) as get_resp:
                            body = await self._read_body(get_resp)
                            return self._finish(
                                url, await self._judge_body(session, url, body)
                            )
            except aiohttp.InvalidURL:
                return False
            except aiohttp.ClientConnectorDNSError:
                # DNS 解析失败 = **本地/环境问题**，不是「这条链路死了」。
                #
                # 2026-11-01 并发档位实测撞出来的：用与 CI 同构成的样本
                # （600 条真实 URL，54% 活链 + 46% 死链）实测：
                #     并发   可用条数   掉条
                #       40       328      0
                #       80       321      7    ⚠️
                #      120       284     44    ⚠️
                #      160       141    187    ⚠️
                # 掉条的原因是日志里的 `socket.gaierror: [Errno -3]
                # Temporary failure in name resolution` —— 高并发下本机
                # DNS 解析器扛不住（每个 URL 都是不同 host）。
                #
                # 判死 = 真频道被踢出产物；而且熔断计数还会累加，
                # 连续 3 次就冻结这条 URL，后续几轮全被跳过 ——
                # **一次 DNS 抖动被放大成持续性误杀**。
                #
                # 所以：**不记熔断**（不是链路的观测）+ **保守放行**
                # （不能证明它死了，就不能判它死）。
                # 与「读不到 body 保守放行」同一口径。
                if attempt < DNS_RETRIES:
                    # 还该重试：退避后再来一次，由 `_check_url` 决定
                    await asyncio.sleep(DNS_RETRY_DELAY * (attempt + 1))
                    return None
                return True
            except (aiohttp.ClientError, asyncio.TimeoutError):
                self._record(url, False)
                return False

    def _timeout_for(self, url: str) -> aiohttp.ClientTimeout:
        """**分级超时**：连败够多次的已知死链用短超时。

        为什么这是验证阶段最大的提速点
        ------------------------------
        CI 实测（run 41277155230）：验证 1,070s，占整个 job 18 分钟的 99%。
        而当时健康快照里 19,536 条 URL 有 **47.2% 是死链**，其中
        **8,377 条已经连续失败 3 次**。每个死链在 `total=10s` 的超时下
        基本要耗满 10 秒：

            8,949 条死链 × 10s ÷ 并发 80 = 1,119s
            对比 CI 实测验证                1,070s   ← 几乎完全吻合

        也就是说**验证阶段的全部耗时都花在等死链超时上**，
        而等的大多是「已经连续失败 3 次、每轮都在等」的老死链。

        为什么死链每轮都被重探：冻结期是 `min(24h, 60 × 2^bad_count)`，
        `bad_count=3` 时只有 **8 分钟** —— CI 两轮间隔远大于 8 分钟，
        所以下一轮开始时早已过期，按 Guovin 的衰减规则 `bad_count→2`，
        拿满 10s 超时再探一次，探完又失败。**无限循环。**

        判据与安全边界
        --------------
        - `bad_count == 0`（没失败过）→ 用**完整超时**，严格度不变；
        - `bad_count == 1`（失败过 1 次）→ 仍然完整超时，给它一次翻身机会；
        - `bad_count >= 2` → 短超时。这些 URL 已经连续两轮连不上，
          它们**如果真的活了，也是立刻响应**，不需要 10 秒。

        代价：一条「活的但响应 >4 秒）」的老死链会被继续判死。
        这种情况本来就播放体验极差，且 `bad_count` 只增不减、
        下一轮仍用短超时 —— 不会自己恢复。这是明确的取舍，
        换来的是整个 job 从 ~18 分钟降到 ~8 分钟。
        """
        entry = None
        try:
            entry = self.circuit.entry(url)
        except Exception:
            entry = None
        bad = getattr(entry, "bad_count", 0) or 0
        if bad >= KNOWN_DEAD_MIN_BAD:
            return aiohttp.ClientTimeout(total=KNOWN_DEAD_TIMEOUT)
        return aiohttp.ClientTimeout(total=self.timeout)

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
        except aiohttp.ClientConnectorDNSError:
            # 子流解析失败 = 环境问题，不是「整棵树都不可达」的证据。
            # 保守放行（与主链路同一口径，见 `_check_url` 里的同名分支）。
            return True
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
