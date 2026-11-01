"""tests/test_validator_dns_error.py —— DNS 解析失败不该判死。

背景（2026-11-01 并发档位实测撞出来的）
----------------------------------------
用**与 CI 同构成**的样本（600 条真实 URL，约 54% 活链 + 46% 死链）
跑并发档位实测，结果：

    并发   可用条数   基准    掉条    耗时(s)
      40       328     328      0     31.9
      80       321     328      7     14.5   ⚠️
     120       284     328     44     14.1   ⚠️
     160       141     328    187     23.9   ⚠️

掉条的原因**不是源站限流**，而是日志里的：

    socket.gaierror: [Errno -3] Temporary failure in name resolution

高并发下本机 DNS 解析器扛不住（每个 URL 都是不同 host），
解析失败被 `except (aiohttp.ClientError, asyncio.TimeoutError)` 捕获
→ 记一次失败 → **判死**。

这是**误验证**：DNS 抖动是**本地/环境问题**，不是「这条链路死了」。
把它当成死链，会让真频道被踢出产物（而且熔断计数还会累加，
让后续几轮都跳过这条 URL —— 一个 DNS 抖动能毒化好几轮）。

修法：`ClientConnectorDNSError` 单独捕获 →
  1. **不记熔断**（不是链路的观测，是环境的观测）；
  2. **保守放行**（与「读不到 body 保守放行」同一口径：
     不能证明它死了，就不能判它死）。

本文件钉死这个行为。
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import validator as V  # noqa: E402
from src.validator import Validator  # noqa: E402

DNS_URL = "http://nonexistent-host-for-test.invalid/live/x.m3u8"

def _dns_err():
    """构造一个真实的 DNS 解析失败异常（EAI_AGAIN）。"""
    return aiohttp.ClientConnectorDNSError(
        socket.gaierror(-3, "Temporary failure in name resolution"), OSError()
    )




class _FakeContent:
    def __init__(self, body):
        self._body = body

    async def read(self, limit=-1):
        return self._body if limit is None or limit < 0 else self._body[:limit]


class FakeResp:
    def __init__(self, status=200, ctype="application/vnd.apple.mpegurl", body=b""):
        self.status = status
        self.headers = {"Content-Type": ctype} if ctype is not None else {}
        self.content = _FakeContent(body)


class _AsyncCtx:
    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *a):
        return False


class DnsFailSession:
    """所有请求都抛 DNS 解析失败（模拟高并发下解析器扛不住）。"""

    def __init__(self):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, **kw):
        self.calls += 1
        raise _dns_err()

    def head(self, url, **kw):
        self.calls += 1
        raise _dns_err()


def _patch(monkeypatch):
    session = DnsFailSession()
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", lambda *a, **k: session)
    v = Validator()
    v._semaphore = asyncio.Semaphore(2)
    return v, session


# ── 核心：DNS 失败不判死 ───────────────────────────────────────────────
def test_dns_failure_does_not_kill_the_channel(monkeypatch):
    """DNS 解析失败 → 保守放行，不判死。

    判死 = 真频道被踢出产物（且熔断计数累加，后续几轮都跳过）。
    """
    v, session = _patch(monkeypatch)

    assert asyncio.run(v._check_url(DNS_URL)) is True, (
        "DNS 解析失败被判死 —— 这是本地/环境问题，不是链路死了"
    )
    assert session.calls >= 1, "应该真的试过连接"


def test_dns_failure_does_not_touch_circuit_state(monkeypatch, tmp_path):
    """DNS 失败**不记熔断** —— 它不是链路的观测，是环境的观测。

    记了的话：一次 DNS 抖动 → bad_count+1 → 连续 3 次就冻结，
    这条 URL 后面几轮全被跳过（0 请求直接判死）——
    一个环境问题被放大成持续性误杀。
    """
    from src.lib import stream_health as sh

    health = tmp_path / "health.json"
    v, session = _patch(monkeypatch)
    v.health_file = health

    asyncio.run(v._check_url(DNS_URL))
    v.persist_health()

    states = sh.load_states(health)
    assert DNS_URL not in states, (
        f"DNS 失败被记进了熔断状态：{states.get(DNS_URL)} —— "
        "环境问题不该占用链路的冻结名额"
    )


def test_real_connection_error_still_counts_as_failure(monkeypatch, tmp_path):
    """反向：真实的连接错误（不是 DNS）**仍然**记熔断、仍然判死。

    防的是「把修复做成「所有异常都放行」」—— 那会放跑真死链。
    """
    from src.lib import stream_health as sh

    class ConnFailSession(DnsFailSession):
        def get(self, url, **kw):
            self.calls += 1
            raise aiohttp.ClientConnectionError("connection refused")

        def head(self, url, **kw):
            self.calls += 1
            raise aiohttp.ClientConnectionError("connection refused")

    session = ConnFailSession()
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", lambda *a, **k: session)
    health = tmp_path / "health2.json"
    v = Validator()
    v._semaphore = asyncio.Semaphore(2)
    v.health_file = health

    assert asyncio.run(v._check_url(DNS_URL)) is False, (
        "连接被拒（真死链）必须判死"
    )
    v.persist_health()
    states = sh.load_states(health)
    assert DNS_URL in states, "真实的连接失败必须记进熔断状态"


# ── DNS 重试：失败后重试，成功就按真实结果走 ──────────────────────────
def test_dns_failure_is_retried_then_succeeds(monkeypatch):
    """第一次 DNS 失败、第二次成功 → 按**真实结果**判活（而不是保守放行）。

    这是 DNS 重试的核心价值：瞬时的 EAI_AGAIN 不该让判定的严格度打折扣。
    """
    calls = {"n": 0}

    class FlakySession(DnsFailSession):
        def get(self, url, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _dns_err()
            return _AsyncCtx(FakeResp(body=b"#EXTM3U\n#EXT-X-VERSION:3\n"))

        def head(self, url, **kw):
            return self.get(url, **kw)

    session = FlakySession()
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", lambda *a, **k: session)
    monkeypatch.setattr("src.validator.DNS_RETRY_DELAY", 0)
    v = Validator()
    v._semaphore = asyncio.Semaphore(2)

    assert asyncio.run(v._check_url(DNS_URL)) is True
    assert calls["n"] >= 2, "第一次 DNS 失败后应该重试"


def test_dns_retry_exhausted_falls_back_to_conservative_pass(monkeypatch):
    """重试用尽 → 保守放行，且**不记熔断**。"""

    class AlwaysDnsFail(DnsFailSession):
        def get(self, url, **kw):
            self.calls += 1
            raise _dns_err()

        def head(self, url, **kw):
            return self.get(url, **kw)

    session = AlwaysDnsFail()
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", lambda *a, **k: session)
    monkeypatch.setattr("src.validator.DNS_RETRY_DELAY", 0)
    v = Validator()
    v._semaphore = asyncio.Semaphore(2)

    assert asyncio.run(v._check_url(DNS_URL)) is True
    expected = V.DNS_RETRIES + 1
    assert session.calls == expected, (
        f"应该尝试 {expected} 次（1 次 + {V.DNS_RETRIES} 次重试），"
        f"实际 {session.calls} 次"
    )


def test_dns_retry_does_not_deadlock_under_full_concurrency(monkeypatch):
    """漂移守卫：重试逻辑必须在 semaphore **外面**，否则并发占满时死锁。

    所有并发名额都被「等重试」的任务占着，重试又去抢名额 → 永远等不到。
    判据：把 semaphore 设成 1、并发跑 3 条全 DNS 失败的 URL，必须能跑完。
    """

    class AlwaysDnsFail(DnsFailSession):
        def get(self, url, **kw):
            raise _dns_err()

        def head(self, url, **kw):
            return self.get(url, **kw)

    monkeypatch.setattr(
        "src.validator.aiohttp.ClientSession", lambda *a, **k: AlwaysDnsFail()
    )
    monkeypatch.setattr("src.validator.DNS_RETRY_DELAY", 0)
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)          # 只有一个名额

    async def run_all():
        return await asyncio.gather(
            *[v._check_url(f"http://h{i}.invalid/x.m3u8") for i in range(3)]
        )

    # wait_for 兜住死锁：5 秒跑不完就是死锁
    result = asyncio.run(asyncio.wait_for(run_all(), timeout=5))
    assert result == [True, True, True]


# ── 漂移守卫：DNS 必须单独捕获，不能混在 ClientError 里 ────────────────
def test_dns_error_is_caught_before_generic_client_error():
    """漂移守卫：`ClientConnectorDNSError` 的 except 分支必须排在
    `ClientError` **之前** —— 顺序反了，DNS 错误就又走通用分支判死了。

    判据用源码顺序：`except aiohttp.ClientConnectorDNSError` 所在行号
    必须小于 `except (aiohttp.ClientError` 所在行号。
    """
    src = (Path(__file__).resolve().parent.parent / "src" / "validator.py")
    src = src.read_text(encoding="utf-8")
    dns_at = src.find("except aiohttp.ClientConnectorDNSError")
    generic_at = src.find("except (aiohttp.ClientError")
    assert dns_at != -1, (
        "validator.py 里没有 `except aiohttp.ClientConnectorDNSError` —— "
        "DNS 解析失败会被当成普通 ClientError 判死"
    )
    assert generic_at != -1, "找不到通用 ClientError 分支（结构变了？）"
    assert dns_at < generic_at, (
        "DNS 专用分支必须排在通用 ClientError 分支之前 —— "
        "顺序反了 DNS 错误仍会判死"
    )
