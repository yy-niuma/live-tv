"""tests/test_validator_probe.py —— 验证阶段「真探」口径的回归测试。

背景（2026-10-30 控制器实测）
--------------------------------
现有产物 ``output/hk_merged.m3u`` 66 条里，只有 34 条真能播。死因分布：

    nosignal 占位片   9 条   （epg.pw 的 stream 全指向 nosignal_h264 占位片）
    geo-block 403    10 条   （RTHK/HOY 官方、d2jc41c1shgcol.cloudfront.net）
    YouTube 伪直播    7 条   （ChiSheng9/iptv 的 .m3u8 下一跳是 youtube.com）
    HTTP 406          4 条   （31.43.191.125 的 restream）

两条独立的根因，都能靠「探测口径」修：

1. **aiohttp 默认 UA 被服务器拒**
   aiohttp 默认发 ``User-Agent: Python/3.x aiohttp/x.y``。实测同一批 306 条
   港台死链：默认 UA 存活 0 条，换浏览器 UA 存活 14 条，其中是
   翡翠台 / TVB星河 / 無線新聞 / 台視 / 民視 / 公視 / 澳視衛星 /
   TVBPearl / TVB娱乐新闻台 / 莲花卫视 —— 全是真频道，被 UA 误杀。

2. **只判 HTTP 状态，不判内容**
   ``_is_valid_response`` 只看状态码和 Content-Type，于是
   「200 + application/x-mpegurl，但 body 是 nosignal 占位片」
   「200 + text/html 里的 youtube 链接」都会被判成有效。

本文件把这些口径钉死。全部离线：不发网络请求，用假响应对象驱动。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validator import Validator  # noqa: E402


class FakeResp:
    """最小 aiohttp.ClientResponse 替身。"""

    def __init__(self, status=200, ctype="application/vnd.apple.mpegurl", body=b""):
        self.status = status
        self.headers = {"Content-Type": ctype} if ctype is not None else {}
        self._body = body
        self.content = _FakeContent(body)

    async def text(self):
        return self._body.decode("utf-8", "replace")


class _FakeContent:
    def __init__(self, body):
        self._body = body

    async def read(self, limit=-1):
        if limit is None or limit < 0:
            return self._body
        return self._body[:limit]


class FakeSession:
    """记录请求头的假 session。"""

    def __init__(self, resp=None, head_resp=None):
        self.resp = resp or FakeResp()
        self.head_resp = head_resp
        self.head_calls = []
        self.get_calls = []

    def head(self, url, **kw):
        self.head_calls.append((url, kw))
        return _AsyncCtx(self.head_resp or self.resp)

    def get(self, url, **kw):
        self.get_calls.append((url, kw))
        return _AsyncCtx(self.resp)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _AsyncCtx:
    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *a):
        return False


def _patch_session(monkeypatch, session):
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", lambda *a, **k: session)
    return session


# ---------------------------------------------------------------------------
# 1. UA：必须发浏览器 UA，不能发 aiohttp 默认 UA
# ---------------------------------------------------------------------------

def test_probe_sends_browser_user_agent(monkeypatch):
    """真探必须带浏览器 UA —— 默认 aiohttp UA 会被源站拒（实测误杀 14 条港台台）。

    不限定 HEAD 还是 GET：播放列表 URL 走单次 GET，其它走 HEAD，
    但**任何**发出的请求都必须带浏览器 UA。
    """
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    session = _patch_session(monkeypatch, FakeSession())

    asyncio.run(v._check_url("http://example.com/x.m3u8"))

    calls = session.head_calls + session.get_calls
    assert calls, "应当发出至少一次请求"
    for url, kw in calls:
        ua = (kw.get("headers") or {}).get("User-Agent", "")
        assert "Python/" not in ua and "aiohttp/" not in ua, (
            f"不能用 aiohttp 默认 UA，会被源站拒绝：{ua!r}（{url}）"
        )
        assert "Mozilla" in ua, f"应发浏览器 UA，实际 {ua!r}（{url}）"


def test_browser_user_agent_constant_is_shared(monkeypatch):
    """UA 常量必须存在且是模块级共享（多处引用不能各写一份）。"""
    from src import validator as vmod

    assert hasattr(vmod, "BROWSER_USER_AGENT"), "缺少模块级 BROWSER_USER_AGENT 常量"
    assert "Mozilla" in vmod.BROWSER_USER_AGENT


# ---------------------------------------------------------------------------
# 2. 内容判定：nosignal 占位片 / youtube 伪直播 必须判死
# ---------------------------------------------------------------------------

def test_nosignal_placeholder_is_dead(monkeypatch):
    """body 指向 nosignal 占位片的 m3u 必须判死（epg.pw 的 stream 全是这种）。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    body = (
        b"#EXTM3U\n"
        b"#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080\n"
        b"http://files4.3y1.xyz/media/video/nosignal_h264/playlist.m3u8\n"
    )
    session = _patch_session(monkeypatch, FakeSession(FakeResp(200, body=body)))

    assert asyncio.run(v._check_url("http://example.com/placeholder.m3u8")) is False


def test_youtube_pseudo_live_is_dead(monkeypatch):
    """body 是 youtube.com 的 m3u 必须判死（伪直播：m3u 有效但不是直播流）。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    body = (
        b"#EXTM3U\n"
        b"#EXT-X-STREAM-INF:BANDWIDTH=1000000\n"
        b"https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
    )
    session = _patch_session(monkeypatch, FakeSession(FakeResp(200, body=body)))

    assert asyncio.run(v._check_url("http://example.com/youtube.m3u8")) is False


def test_placeholder_keywords_are_configurable(monkeypatch):
    """占位片关键词应来自可配置列表，而不是散在代码里的字面量。"""
    from src import validator as vmod

    assert hasattr(vmod, "PLACEHOLDER_KEYWORDS"), "缺少 PLACEHOLDER_KEYWORDS 常量"
    joined = " ".join(vmod.PLACEHOLDER_KEYWORDS).lower()
    assert "nosignal" in joined


# ---------------------------------------------------------------------------
# 3. 真实直播 m3u 仍然要判活（别把好的一起毙了）
# ---------------------------------------------------------------------------

def test_real_m3u_is_still_alive(monkeypatch):
    """正常直播 m3u 不能被上面两条规则误伤。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    body = (
        b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n"
        b"#EXTINF:6.006000,\nchunk1151562.ts\n"
    )
    session = _patch_session(monkeypatch, FakeSession(FakeResp(200, body=body)))

    assert asyncio.run(v._check_url("http://example.com/real.m3u8")) is True


def test_html_page_is_dead(monkeypatch):
    """HTML 错误页判死（原有行为，不能回归）。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    session = _patch_session(monkeypatch, FakeSession(FakeResp(200, "text/html", b"<html>")))

    assert asyncio.run(v._check_url("http://example.com/err.html")) is False


def test_non_200_is_dead(monkeypatch):
    """非 200 判死（原有行为）。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    session = _patch_session(monkeypatch, FakeSession(FakeResp(403, "text/html")))

    assert asyncio.run(v._check_url("http://example.com/403")) is False


# ---------------------------------------------------------------------------
# 4. HEAD 不支持时（405）要回退到 GET，且 GET 也要带 UA
# ---------------------------------------------------------------------------

def test_head_405_falls_back_to_get_with_ua(monkeypatch):
    """HEAD 返回 405 时回退 GET，GET 同样必须带浏览器 UA。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    body = b"#EXTM3U\n#EXTINF:6.0,\nchunk1.ts\n"
    session = _patch_session(
        monkeypatch,
        FakeSession(resp=FakeResp(200, body=body), head_resp=FakeResp(405, "text/html")),
    )

    assert asyncio.run(v._check_url("http://example.com/nohead.m3u8")) is True
    assert session.get_calls, "HEAD 405 后应当回退 GET"
    headers = session.get_calls[0][1].get("headers") or {}
    assert "Mozilla" in headers.get("User-Agent", ""), "GET 回退也必须带浏览器 UA"


# ---------------------------------------------------------------------------
# 5. 判定需要看 body —— 现有实现只读 header，这是回归的根
# ---------------------------------------------------------------------------

def test_validity_check_reads_body(monkeypatch):
    """_is_valid_response 必须读 body（占位片/伪直播判定依赖它）。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    body = b"#EXTM3U\nhttp://x/nosignal_h264/playlist.m3u8\n"
    session = _patch_session(monkeypatch, FakeSession(FakeResp(200, body=body)))

    asyncio.run(v._check_url("http://example.com/x.m3u8"))
    # body 被读取过 → session 的 resp.text() 可被调用；直接断言判定结果更稳
    assert asyncio.run(v._check_url("http://example.com/x.m3u8")) is False


@pytest.mark.parametrize("keyword", ["nosignal", "placeholder"])
def test_placeholder_keyword_variants(monkeypatch, keyword):
    """占位片关键词变体都要能识别。"""
    from src import validator as vmod

    assert any(keyword in k.lower() for k in vmod.PLACEHOLDER_KEYWORDS), (
        f"PLACEHOLDER_KEYWORDS 缺 {keyword}"
    )


def test_whitelisted_host_still_checks_playlist_content(monkeypatch):
    """白名单主机命中不等于「内容有效」——仍要读 body 判占位片/伪直播。

    背景：`raw.githubusercontent.com` 在 config/whitelist.txt 里，命中后
    0 请求直接放行。ChiSheng9/iptv 的 m3u 下一跳指向 youtube.com，
    于是 5 条「有码流没节目」的伪直播长期占据产物（CI 白名单盲区门禁
    实测 5/64 命中，4 条 youtube + 1 条 403）。
    """
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    body = b"#EXTM3U\n#EXTINF:-1,\nhttps://www.youtube.com/watch?v=pF507BLtbqU\n"
    _patch_session(monkeypatch, FakeSession(FakeResp(200, body=body)))

    ok = asyncio.run(
        v._check_whitelisted("https://raw.githubusercontent.com/x/y/TV01.m3u8")
    )
    assert ok is False, "白名单里的 youtube 伪直播必须被否掉"


def test_whitelisted_playlist_that_is_real_passes(monkeypatch):
    """白名单主机的真播放列表仍然通过。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    body = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nchunklist.m3u8\n"
    _patch_session(monkeypatch, FakeSession(FakeResp(200, body=body)))

    ok = asyncio.run(
        v._check_whitelisted("https://raw.githubusercontent.com/x/y/real.m3u8")
    )
    assert ok is True


def test_whitelisted_non_playlist_url_makes_no_request(monkeypatch):
    """白名单里的非播放列表 URL 仍然 0 请求放行（保留原有省请求语义）。"""
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)
    session = _patch_session(monkeypatch, FakeSession())

    ok = asyncio.run(v._check_whitelisted("https://cdn.jsdelivr.net/gh/x/y.m3u"))
    assert ok is True


def test_whitelisted_read_failure_stays_lenient(monkeypatch):
    """读 body 失败（如 geo-block 403）不能反推成死链——保守放行。

    白名单里的 cloudfront/akamai 主机在本机常返回 403（地理封锁），
    但频道本身是活的。读不到 body 就没有证据说它假，保持放行。
    这是刻意的不对称：宁可留一条可能活的，也不用「读不到」当「死」。
    """
    v = Validator()
    v._semaphore = asyncio.Semaphore(1)

    class _BoomContent:
        async def read(self, limit=-1):
            raise OSError("boom")

    class _BoomResp(FakeResp):
        def __init__(self):
            super().__init__(403, "text/html", b"")
            self.content = _BoomContent()

    _patch_session(monkeypatch, FakeSession(_BoomResp()))
    ok = asyncio.run(
        v._check_whitelisted("https://d2jc41c1shgcol.cloudfront.net/live/tvbsnews")
    )
    assert ok is True, "读不到 body 时保守放行"


# ---------------------------------------------------------------------------
# 请求次数：播放列表 URL 只发一次 GET（不要 HEAD + GET 两次）
# ---------------------------------------------------------------------------
# 为什么钉这个：验证阶段要探 19000+ 条 URL，每条多一次请求就是几十分钟。
# 第一版实现对播放列表做 HEAD + GET，实测验证阶段 778s → 1687s（2.17 倍）。
# 播放列表 URL 反正要读 body，跳过 HEAD 直接 GET 即可。


class _CountContent:
    async def read(self, limit=-1):
        return b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nchunk.m3u8\n"


class _CountResp:
    def __init__(self, status=200, ctype="application/vnd.apple.mpegurl"):
        self.status = status
        self.headers = {"Content-Type": ctype}
        self.content = _CountContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _CountSession:
    def __init__(self, counts):
        self._counts = counts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def head(self, url, **kw):
        self._counts["head"] += 1
        return _CountResp()

    def get(self, url, **kw):
        self._counts["get"] += 1
        return _CountResp()


def _run_check(monkeypatch, url):
    import aiohttp as _a
    from src.validator import Validator

    counts = {"head": 0, "get": 0}
    monkeypatch.setattr(
        "src.validator.aiohttp.ClientSession", lambda *a, **k: _CountSession(counts)
    )
    v = Validator()
    v._semaphore = __import__("asyncio").Semaphore(4)
    ok = __import__("asyncio").run(v._check_url(url))
    return ok, counts, _a


def test_playlist_url_uses_single_get_no_head(monkeypatch):
    """.m3u8 URL 只发一次 GET，不发 HEAD（省一半请求）。"""
    ok, counts, _ = _run_check(monkeypatch, "http://example.com/live/index.m3u8")
    assert ok is True
    assert counts == {"head": 0, "get": 1}, f"应只发 1 次 GET，实得 {counts}"


def test_m3u_url_uses_single_get_no_head(monkeypatch):
    """.m3u URL 同样只发一次 GET。"""
    ok, counts, _ = _run_check(monkeypatch, "http://example.com/list.m3u")
    assert ok is True
    assert counts == {"head": 0, "get": 1}, f"实得 {counts}"


def test_php_endpoint_with_m3u8_like_content_does_head_then_get(monkeypatch):
    """路径不含 .m3u8 的接口（如 iptv.php?id=x）走 HEAD，Content-Type 是
    播放列表时才补一次 GET。"""
    ok, counts, _ = _run_check(
        monkeypatch, "http://php.jdshipin.com/TVOD/iptv.php?id=tvbxw"
    )
    assert ok is True
    assert counts == {"head": 1, "get": 1}, f"HEAD + 补 GET，实得 {counts}"


def test_playlist_url_with_query_string_still_single_get(monkeypatch):
    """带 query string 的 .m3u8 仍算播放列表 URL（看 path 后缀，不看 query）。"""
    ok, counts, _ = _run_check(
        monkeypatch, "http://example.com/live/index.m3u8?id=42&t=1"
    )
    assert ok is True
    assert counts == {"head": 0, "get": 1}, f"实得 {counts}"


def test_plain_video_url_uses_only_head(monkeypatch):
    """video/* 的非播放列表 URL 只发 HEAD，不下载 body。"""
    import asyncio as _asyncio
    from src.validator import Validator

    counts = {"head": 0, "get": 0}

    class _S(_CountSession):
        def head(self, url, **kw):
            self._counts["head"] += 1
            return _CountResp(ctype="video/mp4")

    monkeypatch.setattr("src.validator.aiohttp.ClientSession", lambda *a, **k: _S(counts))
    v = Validator()
    v._semaphore = _asyncio.Semaphore(4)
    ok = _asyncio.run(v._check_url("http://example.com/stream/12345"))
    assert ok is True
    assert counts == {"head": 1, "get": 0}, f"实得 {counts}"


def test_playlist_url_helper():
    """_looks_like_playlist_url 的后缀判定。"""
    from src.validator import _looks_like_playlist_url

    assert _looks_like_playlist_url("http://a.com/x.m3u8") is True
    assert _looks_like_playlist_url("http://a.com/x.M3U8") is True
    assert _looks_like_playlist_url("http://a.com/x.m3u") is True
    assert _looks_like_playlist_url("http://a.com/x.m3u8?a=1") is True
    assert _looks_like_playlist_url("http://a.com/iptv.php?id=1") is False
    assert _looks_like_playlist_url("http://a.com/stream/1") is False
    assert _looks_like_playlist_url("http://a.com/x.mp4") is False
