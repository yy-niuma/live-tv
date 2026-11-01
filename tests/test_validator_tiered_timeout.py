"""tests/test_validator_tiered_timeout.py —— 分级超时：已知死链用短超时。

背景（CI 实测算出来的账）
--------------------------
CI run 41277155230：整个 `update` job 18 分钟，其中**验证 1,070 秒 = 99%**。
抓取只要 9.9 秒。

健康快照（18,952 条 URL）当时的状态：

    ok=10,003   死链=8,949（47.2%）
    bad_count 分布：{0: 10,003, 1: 455, 2: 117, 3: 8,377}

死链在 `total=10s` 下基本耗满超时：

    8,949 × 10s ÷ 并发 80 = 1,119s
    对比 CI 实测验证       1,070s   ← 几乎完全吻合

**验证阶段的全部耗时都花在等死链超时上**，而其中 8,377 条已经连续失败 3 次。

为什么这些老死链每轮都被重探：冻结期 `min(24h, 60 × 2^bad_count)`，
`bad_count=3` 时只有 **8 分钟**，CI 两轮间隔远大于此 ——
下一轮开始时早就过期，衰减成 `bad_count=2`，再拿满 10s 探一次。**无限循环。**

修法：**分级超时**
  - `bad_count == 0`（没失败过） → 完整超时（严格度不变）
  - `bad_count == 1`（失败一次） → 完整超时（给一次翻身机会）
  - `bad_count >= 2`            → 短超时（`KNOWN_DEAD_TIMEOUT`）

本文件钉死这个分界，防止后人把「新 URL 也用短超时」或
「老死链又退回完整超时」这两种退化做出来。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import validator as V  # noqa: E402
from src.validator import Validator  # noqa: E402


class _Entry:
    def __init__(self, bad_count):
        self.bad_count = bad_count


class _FakeCircuit:
    """只实现 `entry()`，足够 `_timeout_for` 用。"""

    def __init__(self, bad_count):
        self._e = _Entry(bad_count)

    def entry(self, url):
        return self._e


def _validator(bad_count):
    v = Validator()
    v._circuit = _FakeCircuit(bad_count)
    return v


# ── 核心分界 ─────────────────────────────────────────────────────────
def test_unknown_url_gets_full_timeout():
    """从没失败过的 URL（含首次见到）→ 完整超时，严格度不能打折。"""
    v = _validator(0)
    assert v._timeout_for("http://a/x.m3u8").total == v.timeout


def test_once_failed_url_still_gets_full_timeout():
    """失败过 **1 次** → 仍然完整超时。

    给「偶发失败」一次翻身机会：DNS 抖动、源站临时重启都会造成单次失败，
    不该因此就被降级成短超时 —— 那会让恢复中的链路彻底判不回来。
    """
    v = _validator(1)
    assert v._timeout_for("http://a/x.m3u8").total == v.timeout


def test_known_dead_url_gets_short_timeout():
    """连败 >= 2 次 → 短超时。这是提速的来源。"""
    v = _validator(V.KNOWN_DEAD_MIN_BAD)
    assert v._timeout_for("http://a/x.m3u8").total == V.KNOWN_DEAD_TIMEOUT


def test_frozen_dead_url_also_gets_short_timeout():
    """连败 3 次（冻结档）→ 同样是短超时。"""
    v = _validator(3)
    assert v._timeout_for("http://a/x.m3u8").total == V.KNOWN_DEAD_TIMEOUT


def test_short_timeout_is_actually_shorter():
    """短超时必须**真的更短**，否则这个优化等于没做。"""
    assert V.KNOWN_DEAD_TIMEOUT < Validator().timeout, (
        f"KNOWN_DEAD_TIMEOUT={V.KNOWN_DEAD_TIMEOUT} 不小于默认超时 "
        f"{Validator().timeout} —— 分级超时失效"
    )


# ── 请求必须真的带上这个超时 ─────────────────────────────────────────
def test_requests_actually_carry_the_tiered_timeout(monkeypatch):
    """超时不只算出来，还要**传给请求** —— 否则等于白算。

    用一个记录 `timeout` 参数的假 session 跑一次，断言传进去的是短超时。
    """
    seen = []

    class _Content:
        async def read(self, limit=-1):
            return b"#EXTM3U\n"

    class _Resp:
        status = 200
        headers = {"Content-Type": "application/vnd.apple.mpegurl"}
        content = _Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kw):
            seen.append(kw.get("timeout"))
            return _Resp()

        def head(self, url, **kw):
            seen.append(kw.get("timeout"))
            return _Resp()

    monkeypatch.setattr(V.aiohttp, "ClientSession", lambda *a, **k: _Session())
    v = _validator(V.KNOWN_DEAD_MIN_BAD)
    v._semaphore = __import__("asyncio").Semaphore(2)

    import asyncio

    asyncio.run(v._check_url("http://a/x.m3u8"))

    assert seen, "根本没发请求"
    assert all(
        t is not None and t.total == V.KNOWN_DEAD_TIMEOUT for t in seen
    ), f"请求没带上分级超时：{[(t.total if t else None) for t in seen]}"


# ── 漂移守卫 ─────────────────────────────────────────────────────────
def test_tier_boundary_constant_is_sane():
    """漂移守卫：`KNOWN_DEAD_MIN_BAD` 必须 >= 2。

    改成 1 等于「失败一次就降级超时」，恢复中的链路会被短超时反复打死；
    改成 0 等于全部用短超时，严格度全崩。
    """
    assert V.KNOWN_DEAD_MIN_BAD >= 2, (
        f"KNOWN_DEAD_MIN_BAD={V.KNOWN_DEAD_MIN_BAD} —— 失败 1 次就降级超时太激进"
    )


def test_max_body_read_does_not_use_tiered_timeout_by_accident():
    """漂移守卫：`_children_reachable`（子流探测）不受分级超时影响。

    分级超时只作用在**顶层 URL** 的探测上。子流探测如果也被缩短，
    master 明明可达却被判成「子流全挂」→ 误判死。
    """
    src = (Path(__file__).resolve().parent.parent / "src" / "validator.py").read_text(
        encoding="utf-8"
    )
    start = src.index("async def _children_reachable")
    rest = src[start + 1:]
    end = rest.index("    async def ") if "    async def " in rest else len(rest)
    body = rest[:end]
    assert "timeout=tmo" not in body, (
        "_children_reachable 里带了分级超时 —— 子流探测不该被缩短"
    )
