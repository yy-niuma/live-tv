"""tests/test_validator_master_child.py —— master 播放列表「假 200」的回归测试。

背景（2026-10-31 实测）
------------------------
RTHK 官方 feeds 是「假 200」：

    https://rthktv31-live.akamaized.net/hls/live/2036818/RTHKTV31/master.m3u8

master 自身返回 200，Content-Type 也是 mpegurl，body 是合法 m3u —— 但它下面
的 akamaized 子流在本机全部 403（纯 geo-block，加 Referer/Origin 无效）。

旧口径只看 master，于是把这条死链判成「可播」，写进 `config/stream_health.json`。
后果是连锁的：同名合并时它和真正可播的替代源（`fast.hidns.vip/163189/rthk31`）
都是 `True`，打平后按 CDN 优先级（`rthk.hk` 属 hk_patterns）选了死链 ——
产物里 RTHK 31 / RTHK 32 一直是死链，新加的活源进不去。

修法：master 播放列表再往下探一跳（1 次 GET），子流也不可达就判死。
只探第一个子流，「整棵树不可达」才是要识别的信号，不是给每个码率做体检。

全部离线：不发真实网络请求，用按 URL 路由的假 session 驱动。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validator import Validator, _first_child_uri  # noqa: E402

MASTER_URL = "https://rthktv31-live.akamaized.net/hls/live/2036818/RTHKTV31/master.m3u8"
CHILD_ABS = "https://rthktv31-live.akamaized.net/hls/live/2036818/RTHKTV31/index.m3u8"

MASTER_BODY = (
    b"#EXTM3U\n"
    b"#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\n"
    b"https://rthktv31-live.akamaized.net/hls/live/2036818/RTHKTV31/index.m3u8\n"
)


class _FakeContent:
    def __init__(self, body):
        self._body = body

    async def read(self, limit=-1):
        if limit is None or limit < 0:
            return self._body
        return self._body[:limit]


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


class RouteSession:
    """按 URL 返回不同响应的假 session；未登记的 URL 返回 404。"""

    def __init__(self, routes):
        self.routes = routes
        self.get_calls = []
        self.head_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _pick(self, url):
        return self.routes.get(url, FakeResp(status=404, ctype="text/html", body=b""))

    def get(self, url, **kw):
        self.get_calls.append((url, kw))
        return _AsyncCtx(self._pick(url))

    def head(self, url, **kw):
        self.head_calls.append((url, kw))
        return _AsyncCtx(self._pick(url))


def _patch(monkeypatch, routes):
    session = RouteSession(routes)
    monkeypatch.setattr("src.validator.aiohttp.ClientSession", lambda *a, **k: session)
    v = Validator()
    v._semaphore = asyncio.Semaphore(2)
    return v, session


# ---------------------------------------------------------------------------
# 1. _first_child_uri：纯解析
# ---------------------------------------------------------------------------

def test_first_child_uri_takes_line_after_stream_inf():
    assert _first_child_uri(MASTER_BODY.decode()) == CHILD_ABS


def test_first_child_uri_supports_root_relative_and_skips_comments():
    body = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1\n"
        "# 注释行要跳过\n"
        "\n"
        "/live/xingjiaoge-tvbsxw.m3u8?hls_ctx=abc\n"
    )
    assert _first_child_uri(body) == "/live/xingjiaoge-tvbsxw.m3u8?hls_ctx=abc"


def test_first_child_uri_empty_for_media_playlist():
    """普通 media 播放列表（无 STREAM-INF）没有下一跳。"""
    media = "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    assert _first_child_uri(media) == ""


def test_first_child_uri_strips_crlf():
    """RTHK 的播放列表是 CRLF 行尾，摘出来的 URI 不能带 `\\r`（会拼坏 URL）。"""
    body = (
        "#EXTM3U\r\n"
        "#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=636906,RESOLUTION=432x240\r\n"
        "stream4/streamPlaylist.m3u8\r\n"
    )
    assert _first_child_uri(body) == "stream4/streamPlaylist.m3u8"


def test_first_child_uri_empty_for_garbage():
    assert _first_child_uri("") == ""
    assert _first_child_uri("#EXTM3U\n") == ""


# ---------------------------------------------------------------------------
# 2. 假 200：master 活、子流死 → 整条判死
# ---------------------------------------------------------------------------

def test_master_with_403_child_is_rejected(monkeypatch):
    """RTHK 官方 feeds 的原型：master 200 + 子流 403 必须判死。"""
    v, session = _patch(monkeypatch, {
        MASTER_URL: FakeResp(200, "application/vnd.apple.mpegurl", MASTER_BODY),
        CHILD_ABS: FakeResp(403, "text/html", b"<html>Access Denied</html>"),
    })

    assert asyncio.run(v._check_url(MASTER_URL)) is False
    # 真的去探了子流，而不是凭 master 下结论
    assert [u for u, _ in session.get_calls] == [MASTER_URL, CHILD_ABS]


def test_master_with_200_child_is_accepted(monkeypatch):
    """子流可达且是合法播放列表 → 放行。"""
    media = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    v, session = _patch(monkeypatch, {
        MASTER_URL: FakeResp(200, "application/vnd.apple.mpegurl", MASTER_BODY),
        CHILD_ABS: FakeResp(200, "application/vnd.apple.mpegurl", media),
    })

    assert asyncio.run(v._check_url(MASTER_URL)) is True


def test_master_with_html_child_is_rejected(monkeypatch):
    """子流 200 但 body 是 HTML 错误页 → 判死（不能凭状态码放行）。"""
    v, session = _patch(monkeypatch, {
        MASTER_URL: FakeResp(200, "application/vnd.apple.mpegurl", MASTER_BODY),
        CHILD_ABS: FakeResp(200, "text/html", b"<html>error</html>"),
    })

    assert asyncio.run(v._check_url(MASTER_URL)) is False


def test_master_with_text_plain_child_playlist_is_accepted(monkeypatch):
    """子流 Content-Type 标成 text/plain（hidns 那族）→ 仍按 body 签名放行。"""
    media = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    v, session = _patch(monkeypatch, {
        MASTER_URL: FakeResp(200, "text/plain", MASTER_BODY),
        CHILD_ABS: FakeResp(200, "text/plain", media),
    })

    assert asyncio.run(v._check_url(MASTER_URL)) is True


def test_root_relative_child_is_resolved_against_master(monkeypatch):
    """SRS 的 root-relative 子列表必须用 urljoin 拼，不能拼成 host//live/..."""
    body = (
        b"#EXTM3U\n"
        b"#EXT-X-STREAM-INF:BANDWIDTH=1\n"
        b"/live/xingjiaoge-tvbsxw.m3u8?hls_ctx=abc\n"
    )
    master = "http://jnzq.ohoyee.com:9080/live/x.m3u8"
    child = "http://jnzq.ohoyee.com:9080/live/xingjiaoge-tvbsxw.m3u8?hls_ctx=abc"
    media = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    v, session = _patch(monkeypatch, {
        master: FakeResp(200, "application/vnd.apple.mpegurl", body),
        child: FakeResp(200, "application/vnd.apple.mpegurl", media),
    })

    assert asyncio.run(v._check_url(master)) is True
    assert [u for u, _ in session.get_calls] == [master, child]


# ---------------------------------------------------------------------------
# 3. 非 master 不多发请求（代价可控）
# ---------------------------------------------------------------------------

def test_media_playlist_makes_no_extra_request(monkeypatch):
    """没有 STREAM-INF 的播放列表只有 1 次 GET —— 深挖不能给全量加负担。"""
    media = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    url = "https://fast.hidns.vip/163189/rthk31"
    v, session = _patch(monkeypatch, {
        url: FakeResp(200, "text/plain", media),
    })

    # 无 .m3u8 后缀 → 走 HEAD 拿 text/plain → 补 GET 读 body 这条路
    assert asyncio.run(v._check_url(url)) is True
    body_gets = [u for u, _ in session.get_calls if u == url]
    assert len(body_gets) == 1, f"非 master 不该有子流请求：{session.get_calls}"


def test_child_probe_uses_browser_user_agent(monkeypatch):
    """探子流也必须带浏览器 UA，否则又是 UA 误杀。"""
    media = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    v, session = _patch(monkeypatch, {
        MASTER_URL: FakeResp(200, "application/vnd.apple.mpegurl", MASTER_BODY),
        CHILD_ABS: FakeResp(200, "application/vnd.apple.mpegurl", media),
    })

    assert asyncio.run(v._check_url(MASTER_URL)) is True
    for url, kw in session.get_calls:
        ua = (kw.get("headers") or {}).get("User-Agent", "")
        assert "Mozilla" in ua, f"子流请求也要浏览器 UA：{url} / {ua!r}"
