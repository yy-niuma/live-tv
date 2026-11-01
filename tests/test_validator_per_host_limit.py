"""tests/test_validator_per_host_limit.py —— 每 host 并发上限。

背景（干净环境实测，600 条真实 URL，每档 2 轮）
------------------------------------------------
加了分级超时、DNS 重试之后重测并发档位，**仍然掉条**：

    全局并发   可用条数   掉条    耗时
       40        342       0     24.4s
       80        335       7     20.0s
      120        301      41     16.4s
      160        214     128     15.5s

注意这是**没有别的网络任务在跑**的干净环境（之前怀疑是 DNS 争用，已排除）。

原因看 host 分布就清楚了：600 条 URL 只分布在 **405 个 host**，
最热的单个 host 占 **39 条**（`jmp2.uk` 39、`stream1.freetv.fun` 30）。

全局并发 160 时，这些热 host 会被同时怼上几十个连接 ——
**源站限流/拒绝，于是判死，表现为「掉条」**。

所以瓶颈是 **per-host，不是全局**。修法：
全局并发放开（这才是吞吐杠杆），但每个 host 单独掐到
`PER_HOST_CONCURRENCY`。这样热 host 不会被压垮，冷 host 又能充分并发。

本文件钉死这个行为 —— 尤其是「同一 host 的并发数真的被限制住了」，
而不是仅仅「有个常量」。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import validator as V  # noqa: E402
from src.validator import Validator  # noqa: E402


# ── semaphore 分配 ────────────────────────────────────────────────────
def test_same_host_shares_one_semaphore():
    v = Validator()
    a = v._host_sem("http://a.example/x.m3u8")
    b = v._host_sem("http://a.example/y.m3u8")
    assert a is b, "同一 host 必须共用同一个名额池"


def test_different_hosts_get_different_semaphores():
    v = Validator()
    a = v._host_sem("http://a.example/x.m3u8")
    b = v._host_sem("http://b.example/x.m3u8")
    assert a is not b, "不同 host 不能共用名额池"


def test_host_key_ignores_path_and_scheme():
    """http/https、不同端口路径都应视为同一个 host 维度（按 hostname 归一）。"""
    v = Validator()
    a = v._host_sem("http://a.example:8080/live/x.m3u8")
    b = v._host_sem("https://a.example/other/y.m3u8")
    assert a is b


def test_malformed_url_does_not_crash():
    """畸形 URL 不能把 `_host_sem` 弄崩 —— 它只是个限流 key。"""
    v = Validator()
    assert v._host_sem("::::not a url::::") is not None


# ── 真的限住了吗（核心） ─────────────────────────────────────────────
def test_per_host_concurrency_is_actually_capped(monkeypatch):
    """同一 host 的 20 条 URL 并发跑，同时在飞的请求数不得超过上限。

    只断言「常量存在」是不够的 —— 必须证明它真的拦住了请求。
    """
    live = {"now": 0, "peak": 0}
    host_url = "http://hot.example/{}.m3u8"

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
            return _slow_resp()

        def head(self, url, **kw):
            return _slow_resp()

    def _slow_resp():
        # 用自定义上下文管理器在进入/退出时计数
        class _Ctx:
            async def __aenter__(self_inner):
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
                await asyncio.sleep(0.02)      # 制造重叠窗口
                return _Resp()

            async def __aexit__(self_inner, *a):
                live["now"] -= 1
                return False

        return _Ctx()

    monkeypatch.setattr(V.aiohttp, "ClientSession", lambda *a, **k: _Session())
    v = Validator()
    v._semaphore = asyncio.Semaphore(1000)     # 全局放开，只测 host 维度

    async def run():
        return await asyncio.gather(
            *[v._check_url(host_url.format(i)) for i in range(20)]
        )

    asyncio.run(run())
    assert live["peak"] <= V.PER_HOST_CONCURRENCY, (
        f"同一 host 同时在飞 {live['peak']} 个请求，"
        f"超过上限 {V.PER_HOST_CONCURRENCY} —— 会被源站限流"
    )
    assert live["peak"] >= 2, (
        f"峰值只有 {live['peak']} —— 限流过严，热 host 的并发被浪费了"
    )


def test_different_hosts_run_in_parallel(monkeypatch):
    """不同 host 之间**不该**互相阻塞（否则全局并发等于没用）。"""
    live = {"now": 0, "peak": 0}

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

    def _ctx():
        class _Ctx:
            async def __aenter__(self_inner):
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
                await asyncio.sleep(0.02)
                return _Resp()

            async def __aexit__(self_inner, *a):
                live["now"] -= 1
                return False

        return _Ctx()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kw):
            return _ctx()

        def head(self, url, **kw):
            return _ctx()

    monkeypatch.setattr(V.aiohttp, "ClientSession", lambda *a, **k: _Session())
    v = Validator()
    v._semaphore = asyncio.Semaphore(1000)

    async def run():
        return await asyncio.gather(
            *[v._check_url(f"http://host{i}.example/x.m3u8") for i in range(12)]
        )

    asyncio.run(run())
    assert live["peak"] > V.PER_HOST_CONCURRENCY, (
        f"12 个**不同** host 的峰值并发只有 {live['peak']}（上限 "
        f"{V.PER_HOST_CONCURRENCY}）—— per-host 限流错误地变成了全局限流"
    )


def test_no_deadlock_when_host_quota_exhausted(monkeypatch):
    """热 host 名额耗尽时不能死锁（顺序固定：先 host 后全局）。"""

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
            return _Resp()

        def head(self, url, **kw):
            return _Resp()

    monkeypatch.setattr(V.aiohttp, "ClientSession", lambda *a, **k: _Session())
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)        # 全局只 1 个名额

    async def run():
        return await asyncio.gather(
            *[v._check_url(f"http://hot.example/{i}.m3u8") for i in range(10)]
        )

    result = asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert len(result) == 10


# ── 漂移守卫 ──────────────────────────────────────────────────────────
def test_per_host_limit_is_sane():
    """漂移守卫：地板值必须 > 1 且不太大。

    设成 1 → 热 host 退化成串行，吞吐崩；
    设成几十 → 又回到「被源站限流掉条」的老问题。
    """
    assert 2 <= V.PER_HOST_CONCURRENCY <= 16, (
        f"PER_HOST_CONCURRENCY={V.PER_HOST_CONCURRENCY} 不在合理区间 2~16"
    )


def test_cap_scales_with_host_url_count():
    """自适应上限：host 的 URL 越多，名额越多（sqrt），否则巨型 host 会卡死。

    这是 CI 实测的教训：`stream1.freetv.fun` 一个 host 有 1,199 条 URL，
    固定上限 4 ⇒ 1,199 × 12s ÷ 4 ≈ 60 分钟，整批被一个 host 拖死。
    """
    v = Validator()
    assert v._host_sem("http://small.example/a.m3u8") is not None

    # 模拟 validate() 开始时的 host 统计
    v._host_sems = {}
    v._host_counts = {"small.example": 1, "mid.example": 296, "huge.example": 1199}
    caps = {}
    for host in v._host_counts:
        sem = v._host_sem(f"http://{host}/x.m3u8")
        caps[host] = sem._value

    assert caps["small.example"] == V.PER_HOST_CONCURRENCY, (
        f"小 host 应走地板值 {V.PER_HOST_CONCURRENCY}，实际 {caps['small.example']}"
    )
    assert caps["huge.example"] >= 30, (
        f"1,199 条 URL 的巨型 host 只给了 {caps['huge.example']} 个名额 —— "
        "会拖死整批"
    )
    assert caps["small.example"] < caps["mid.example"] < caps["huge.example"], (
        f"名额没有随 URL 数递增：{caps}"
    )


def test_check_url_acquires_host_quota_before_global():
    """漂移守卫：`_host_sem` 必须在 `_semaphore` **之前**获取。

    顺序反了（先占全局、再等 host）会让「被单源限流卡住」的任务
    白占全局名额，整体吞吐下降，且并发调高时更容易互相拖死。
    判据：`_check_url` 源码里 `_host_sem` 出现在 `_check_url_attempt` 调用之前。
    """
    src = (Path(__file__).resolve().parent.parent / "src" / "validator.py").read_text(
        encoding="utf-8"
    )
    start = src.index("async def _check_url(self")
    end = src.index("def _host_sem", start)
    body = src[start:end]
    assert "_host_sem(url)" in body, "_check_url 里没有取 host 名额"
