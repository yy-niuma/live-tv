"""tests/test_validator_host_interleave.py —— 按 host 轮转重排探测顺序。

背景
----
加了 per-host 并发上限（`PER_HOST_CONCURRENCY`）之后，CI 上的验证阶段
反而变慢了。原因不是限流太严，而是**探测顺序**：

真实数据里同 host 的 URL 是**成块连续**的。19,319 条 URL 的实测分布：

    连续同一 host 的段共 5,155 段，其中长度 > 4 的段合计 **13,058 条（67.6%）**
    最长的两段：stream1.freetv.fun **1,199 条**、jmp2.uk **1,179 条**

在这种顺序下，轮到某个热 host 的那一段时只有 4 个请求在飞
（per-host 上限），其余全局名额**空转**，直到整段跑完才轮到下一个 host。
这就是队头阻塞。

修法：`_interleave_by_host()` 按 host 轮转重排**探测顺序**，
让同一时刻在飞的是「各 host 各一条」。只改顺序，不改判定。

本文件钉死两件事：
1. 重排后判定结果与返回顺序**完全不变**（这是安全的底线）；
2. 重排后连续同 host 的段长被压平（这是修好的证明）。
"""

from __future__ import annotations

import asyncio
import sys
from itertools import groupby
from pathlib import Path
from urllib.parse import urlsplit

import pytest  # noqa: F401  （pytest 由 runner 注入，这里显式留位）

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetcher import Channel  # noqa: E402
from src.validator import Validator, _interleave_by_host  # noqa: E402


def _mk(urls):
    return [Channel(name=f"c{i}", url=u) for i, u in enumerate(urls)]


def _max_same_host_run(indices, channels):
    hosts = [urlsplit(channels[i].url).hostname or "?" for i in indices]
    runs = [len(list(g)) for _, g in groupby(hosts)]
    return max(runs) if runs else 0


# ── 顺序重排本身 ─────────────────────────────────────────────────────
def test_interleave_flattens_same_host_runs():
    """3 个等量 host 各 20 条 → 重排后连续同 host 段长必须降到 1。

    ⚠️ 注意：当某个 host 的数量压倒性地多（例如 50 条 vs 其他各 1 条），
    其他 host 轮流跑完后，剩下的同 host 条目**必然连续** —— 那是数据本身
    决定的，轮转压不平。所以这里用等量 host 来验证轮转本身有效；
    真实数据里不等量的情况见 `test_real_shape_head_is_round_robin`。
    """
    urls = []
    for host in ("a.example", "b.example", "c.example"):
        urls += [f"http://{host}/{i}.m3u8" for i in range(20)]
    channels = _mk(urls)

    order = _interleave_by_host(channels)
    assert _max_same_host_run(order, channels) == 1, (
        "等量 host 重排后仍存在连续同 host —— 轮转没生效"
    )


def test_real_shape_head_is_round_robin():
    """真实数据形态：1,199 条 `hot` + 若干其他 host。

    轮转的收益在**队头**：开头必须是「各 host 各一条」，让全局并发
    一开始就铺满，而不是先被 1,199 条同 host 堵死。
    """
    hot = [f"http://hot.example/{i}.m3u8" for i in range(200)]
    others = [f"http://h{i}.example/x.m3u8" for i in range(30)]
    channels = _mk(hot + others)

    order = _interleave_by_host(channels)
    head_hosts = [urlsplit(channels[i].url).hostname for i in order[:30]]
    assert len(set(head_hosts)) == 30, (
        f"前 30 个探测目标只覆盖 {len(set(head_hosts))} 个 host —— "
        "队头没有铺开，全局并发放不满"
    )


def test_interleave_preserves_all_indices():
    """重排必须是**排列**：每个下标恰好出现一次，不丢不重。"""
    channels = _mk(
        [f"http://a.example/{i}.m3u8" for i in range(7)]
        + [f"http://b.example/{i}.m3u8" for i in range(5)]
        + [f"http://c.example/{i}.m3u8" for i in range(3)]
    )
    order = _interleave_by_host(channels)
    assert sorted(order) == list(range(len(channels)))


def test_empty_input():
    assert _interleave_by_host([]) == []


def test_malformed_url_does_not_crash():
    channels = [Channel(name="x", url="::::bad::::"), Channel(name="y", url="")]
    order = _interleave_by_host(channels)
    assert sorted(order) == [0, 1]


# ── 判定与返回顺序不变（安全底线） ───────────────────────────────────
def test_verdicts_and_order_unchanged(monkeypatch):
    """重排只改探测顺序：**判定集合**和**返回顺序**都必须与原来一致。"""
    from src import validator as V

    alive_hosts = {"a.example", "c.example"}

    class _Content:
        def __init__(self, body):
            self._body = body

        async def read(self, limit=-1):
            return self._body

    class _Resp:
        def __init__(self, ok):
            self.status = 200 if ok else 500
            self.headers = {"Content-Type": "application/vnd.apple.mpegurl"}
            self.content = _Content(b"#EXTM3U\n")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def _resp(self, url):
            return _Resp(urlsplit(url).hostname in alive_hosts)

        def get(self, url, **kw):
            return self._resp(url)

        def head(self, url, **kw):
            return self._resp(url)

    monkeypatch.setattr(V.aiohttp, "ClientSession", lambda *a, **k: _Session())

    # 构造「同 host 成块」的输入，模拟真实数据
    urls = (
        [f"http://a.example/{i}.m3u8" for i in range(5)]
        + [f"http://b.example/{i}.m3u8" for i in range(5)]
        + [f"http://c.example/{i}.m3u8" for i in range(5)]
    )
    channels = _mk(urls)

    v = Validator(health_file=str(Path("/tmp") / "_interleave_test_health.json"))
    v._semaphore = asyncio.Semaphore(8)
    valid = asyncio.run(v.validate(channels))

    got_urls = [c.url for c in valid]
    expected = [u for u in urls if urlsplit(u).hostname in alive_hosts]
    assert got_urls == expected, (
        "重排改变了返回顺序或判定 —— 必须按原输入顺序返回有效频道"
    )
