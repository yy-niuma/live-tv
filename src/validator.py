"""验证模块：HEAD 优先、Content-Type 检查、代理域名拒绝、CDN 白名单跳过、熔断跳过已知死链"""
import asyncio
import re
from typing import List, Set
from urllib.parse import urlparse

import aiohttp

from .config import Config
from .fetcher import Channel
from .lib import stream_health


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

        # 2. 白名单 CDN 直接通过（跳过验证，且**不**更新熔断状态）
        if self._is_whitelisted_cdn(url):
            return True

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

    async def _check_url(self, url: str) -> bool:
        """HEAD 请求检查 URL 可访问性，并把**真实观测**写回熔断状态。

        `aiohttp.InvalidURL`（无 scheme / 相对路径 / ftp:// 等）是结构非法，
        不是「这条链路死了」—— 它根本没到网络上，所以**不记熔断**（否则
        拼错的 URL 会白白占掉一个冻结名额，也会污染共享的快照文件）。
        其余 ClientError / 超时 / 非 200 / HTML 都是真实失败，累加计数。
        """
        async with self._semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # 先尝试 HEAD
                    async with session.head(url, allow_redirects=True) as resp:
                        if resp.status == 405:
                            # HEAD 不支持，尝试 GET
                            async with session.get(url, allow_redirects=True) as get_resp:
                                return self._finish(url, self._is_valid_response(get_resp))
                        return self._finish(url, self._is_valid_response(resp))
            except aiohttp.InvalidURL:
                return False
            except (aiohttp.ClientError, asyncio.TimeoutError):
                self._record(url, False)
                return False

    def _finish(self, url: str, ok: bool) -> bool:
        """统一的「有观测」出口：记账 + 返回判定。"""
        self._record(url, ok)
        return ok

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
