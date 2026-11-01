"""tests/test_session_reuse.py —— 网络会话复用（性能优化，行为必须不变）。

背景（2026-11-01 实测）
-----------------------
`src/validator.py` 与 `src/fetcher.py` 在**每个 URL 上新建一个
`aiohttp.ClientSession`**：

    validator.py:266   async with aiohttp.ClientSession(timeout=timeout) as session:
    validator.py:299   async with aiohttp.ClientSession(timeout=timeout) as session:
    fetcher.py:187     async with aiohttp.ClientSession(timeout=timeout) as session:

后果：每次请求都要重新做 TCP 握手 + TLS 握手（对 https 是 2 个 RTT），
连接池完全用不上 —— aiohttp 的连接复用能力形同虚设。

实测（3 个真实源，同一台机器）：
    每请求新建 session: 3.16s
    共享 session 并发:  1.42s
    提升: 2.23x

验证阶段一次要探 22,000 条 URL（实测 `stream_health.json` 有 18,945 条），
乘上 2 倍多的开销就是几十分钟 —— CI 的 update job `timeout-minutes: 45`
里验证一阶段就吃掉大半。

修法：把 `ClientSession` 提到**批次级别**（一次 `validate()` / `fetch_all()`
共用一个 session + 一个 TCPConnector），而不是每 URL 一个。

**行为不变**：判定口径、并发上限、超时、熔断计数、HEAD→GET 回退
全部保持原样。本文件只钉住「复用」这件事，不钉住别的。

三条红线（回归时重点看）：
1. 一次批次只建**一个** session；
2. session 在批次**结束时**关闭（不能泄漏连接）；
3. 判定结果与复用前逐条一致（行为不变）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

from src.fetcher import Channel, Fetcher  # noqa: E402
from src.validator import Validator  # noqa: E402


class _FakeResponse:
    """够用的假响应：200 + 非 HTML Content-Type。"""

    def __init__(self, status=200, ctype="application/vnd.apple.mpegurl", body=b""):
        self.status = status
        self.headers = {"Content-Type": ctype}
        self._body = body

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def text(self):
        return self._body.decode("utf-8", "replace")

    @property
    def content(self):
        resp = self

        class _Content:
            async def read(self, limit=-1):
                return resp._body if limit < 0 else resp._body[:limit]

        return _Content()


class _FakeSession:
    """记录自己被创建了几次、被关闭了几次。"""

    instances: list["_FakeSession"] = []

    def __init__(self, *args, **kwargs):
        self.closed = False
        self.get_calls: list[str] = []
        self.head_calls: list[str] = []
        _FakeSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False

    async def close(self):
        self.closed = True

    def get(self, url, **kwargs):
        self.get_calls.append(url)
        return _Ctx(_FakeResponse(body=b"#EXTM3U\n"))

    def head(self, url, **kwargs):
        self.head_calls.append(url)
        return _Ctx(_FakeResponse())


class _Ctx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_sessions(monkeypatch):
    _FakeSession.instances = []
    yield
    _FakeSession.instances = []


# ── Validator：一次批次只建一个 session ────────────────────────────────
async def test_validator_reuses_one_session_per_batch(monkeypatch):
    """一批 5 个频道的验证，只应创建 1 个 ClientSession。"""
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", _FakeSession)

    validator = Validator(max_concurrent=4, timeout=5)
    channels = [Channel(name=f"c{i}", url=f"http://example.invalid/{i}.m3u8")
                for i in range(5)]

    result = await validator.validate(channels)

    assert len(result) == 5
    assert len(_FakeSession.instances) == 1, (
        f"一次批次建了 {len(_FakeSession.instances)} 个 session —— "
        "每 URL 新建 session 会让 TCP/TLS 握手开销翻倍"
    )


async def test_validator_closes_session_after_batch(monkeypatch):
    """批次结束后 session 必须被关闭（否则连接泄漏）。"""
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", _FakeSession)

    validator = Validator(max_concurrent=4, timeout=5)
    channels = [Channel(name="c", url="http://example.invalid/a.m3u8")]
    await validator.validate(channels)

    assert _FakeSession.instances, "应该至少建了一个 session"
    assert all(s.closed for s in _FakeSession.instances), (
        "session 没有被关闭 —— 每次批次都会泄漏连接"
    )


async def test_validator_reuse_preserves_verdict(monkeypatch):
    """复用不改变判定结果：不可播的 URL 仍判不可播。"""
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", _FakeSession)

    validator = Validator(max_concurrent=4, timeout=5)
    channels = [
        Channel(name="alive", url="http://example.invalid/alive.m3u8"),
        # 非 http scheme → 直接 False
        Channel(name="dead", url="ftp://example.invalid/dead.m3u8"),
        Channel(name="empty", url=""),  # 空 URL → False
    ]

    result = await validator.validate(channels)

    assert [ch.name for ch in result] == ["alive"]


# ── Fetcher：一次批次只建一个 session ──────────────────────────────────
async def test_fetcher_reuses_one_session_per_batch(monkeypatch):
    """一次 fetch_all 只建 1 个 ClientSession（3 个源）。

    假响应按 URL 返回**不同**的频道 URL —— `fetch_all()` 末尾按 URL 去重，
    三个源返回同一个 URL 的话结果会被去重成 1 条（与本测试无关的干扰）。
    """

    class _TextSession(_FakeSession):
        def get(self, url, **kwargs):
            self.get_calls.append(url)
            body = f"#EXTM3U\n#EXTINF:-1,A\nhttp://x/{url.rsplit('/', 1)[-1]}.m3u8\n"
            return _Ctx(_FakeResponse(body=body.encode()))

    monkeypatch.setattr("src.fetcher.aiohttp.ClientSession", _TextSession)

    fetcher = Fetcher(max_concurrent=4, max_retries=1)
    sources = [
        {"name": "s1", "url": "http://example.invalid/1.m3u", "enabled": True},
        {"name": "s2", "url": "http://example.invalid/2.m3u", "enabled": True},
        {"name": "s3", "url": "http://example.invalid/3.m3u", "enabled": True},
    ]
    fetcher.config._sources = sources

    channels = await fetcher.fetch_all()

    assert len(channels) == 3
    assert len(_FakeSession.instances) == 1, (
        f"fetch_all 建了 {len(_FakeSession.instances)} 个 session —— "
        "抓取阶段同样浪费在重复握手上"
    )


async def test_fetcher_closes_session_after_batch(monkeypatch):
    """fetch_all 结束后 session 必须关闭。"""

    class _TextSession(_FakeSession):
        def get(self, url, **kwargs):
            self.get_calls.append(url)
            return _Ctx(_FakeResponse(body=b"#EXTM3U\n#EXTINF:-1,A\nhttp://x/1.m3u8\n"))

    monkeypatch.setattr("src.fetcher.aiohttp.ClientSession", _TextSession)

    fetcher = Fetcher(max_concurrent=4, max_retries=1)
    fetcher.config._sources = [
        {"name": "s1", "url": "http://example.invalid/1.m3u", "enabled": True},
    ]
    await fetcher.fetch_all()

    assert _FakeSession.instances
    assert all(s.closed for s in _FakeSession.instances)


# ── 漂移守卫：源码里不能再出现「每个 URL 新建 session」的写法 ─────────
def _session_creation_lines(path: Path) -> list[int]:
    """返回文件里所有真正**新建** session 的行号。

    判据：`aiohttp.ClientSession(` 出现在**代码**里（不在 docstring 里）。
    docstring 提到这个名字是正常的（说明里会写），所以先把注释与
    文档字符串剥掉再数 —— 否则文档提及也会被算成「新建点」。
    """
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    code_lines: set[int] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
                # 多行字符串（docstring）→ 整段跳过
                for ln in range(tok.start[0], tok.end[0] + 1):
                    code_lines.discard(ln)
                continue
            if tok.type == tokenize.STRING:
                continue
            for ln in range(tok.start[0], tok.end[0] + 1):
                code_lines.add(ln)
    except tokenize.TokenError:
        pass
    hits = []
    for idx, line in enumerate(src.splitlines(), start=1):
        if idx in code_lines and "aiohttp.ClientSession(" in line:
            hits.append(idx)
    return hits


def test_validator_creates_session_only_at_batch_level():
    """漂移守卫：validator.py 里真正新建 session 的地方**最多 2 处**。

    2 处是：
      1. `_session_scope()` 的**批次路径**（`validate()` 内，全批共用）—— 热路径；
      2. `_session_scope()` 的**兼容路径**（`validate()` 外直接调 `_check_url()`
         时临时建一个）—— 只在单测里走到。

    早期版本在 `_check_url()` / `_check_whitelisted()` 里各建一个 ——
    那是「每 URL 新建」，会让 TCP/TLS 握手开销翻倍。

    更精确的守卫见 `test_validator_session_scope_has_batch_path`。
    """
    hits = _session_creation_lines(ROOT / "src" / "validator.py")
    assert len(hits) <= 2, (
        f"validator.py 在这些行新建 session: {hits} —— "
        "最多 2 处（批次级 + 兼容路径），更多就是回到每 URL 新建 session"
    )


def test_validator_session_scope_has_batch_path():
    """漂移守卫（精确版）：`validate()` 期间必须走批次 session。

    判据：`_session_scope()` 里，批次路径的 `ClientSession(` 必须落在
    `if self._in_batch:` 分支**之内**（缩进比守卫深）；
    兼容路径必须在该分支**之外**（缩进相同或更浅）。
    这样「有批次 session 时不会再建第二个」这条性质由结构保证。
    """
    src = (ROOT / "src" / "validator.py").read_text(encoding="utf-8")
    hits = _session_creation_lines(ROOT / "src" / "validator.py")
    assert len(hits) == 2, f"预期 2 处（批次 + 兼容），实际 {hits}"

    guard = "if self._in_batch:"
    assert guard in src, "validator.py 缺少批次路径守卫（if self._in_batch:）"

    lines = src.splitlines()

    def indent_of(lineno: int) -> int:
        line = lines[lineno - 1]
        return len(line) - len(line.lstrip())

    guard_line = next(i for i, line in enumerate(lines, start=1) if guard in line)
    guard_indent = indent_of(guard_line)

    # 批次路径：缩进比守卫深（在分支内）
    batch_lines = [ln for ln in hits if indent_of(ln) > guard_indent]
    assert len(batch_lines) == 1, (
        f"应有且仅有 1 处批次路径的新建 session，实际 {batch_lines}"
    )

    # 兼容路径：缩进不比守卫深（在分支外）
    compat_lines = [ln for ln in hits if indent_of(ln) <= guard_indent]
    assert len(compat_lines) == 1, (
        f"应有且仅有 1 处兼容路径的新建 session，实际 {compat_lines}"
    )


def test_fetcher_creates_session_only_at_batch_level():
    """漂移守卫：fetcher.py 里真正新建 session 的地方**只能有 1 处**。

    注意：`_get_text()` 里有一条**兼容路径**（没有批次 session 时临时建一个），
    那是给「单次调用」用的（体检脚本、测试直接调 `_get_text`）。
    所以守卫不是「文件里出现几次」，而是「**热路径**上新建了几次」——
    见下面 `test_fetcher_hot_path_does_not_create_session`。
    """
    hits = _session_creation_lines(ROOT / "src" / "fetcher.py")
    assert len(hits) <= 2, (
        f"fetcher.py 在这些行新建 session: {hits} —— "
        "最多 2 处（批次级 + 单次调用兼容路径），更多就是回到每 URL 新建"
    )


def test_fetcher_hot_path_does_not_create_session():
    """漂移守卫（精确版）：`fetch_all()` 与 `_get_text()` 的**热路径**里
    不得出现「每 URL 新建 session」。

    具体判据：`_get_text()` 里新建 session 的那一行，
    必须在**批次 session 缺失**的分支里（即 `if self._session is None` 之后）。
    真实实现是：批次 session 存在 → 直接用；不存在 → 才新建。
    """
    src = (ROOT / "src" / "fetcher.py").read_text(encoding="utf-8")
    hits = _session_creation_lines(ROOT / "src" / "fetcher.py")
    assert len(hits) == 2, f"预期 2 处（批次 + 兼容），实际 {hits}"

    # 兼容路径的新建点必须在 `self._session is None` 的守卫之后
    guard = "if self._session is not None:"
    assert guard in src, "fetcher.py 缺少批次 session 优先的守卫"

    compat_line = hits[-1]
    guard_line = next(
        i for i, line in enumerate(src.splitlines(), start=1)
        if guard in line
    )
    assert compat_line > guard_line, (
        "兼容路径的新建 session 必须排在批次 session 守卫之后 —— "
        "否则批量路径会先建一个再丢弃"
    )
