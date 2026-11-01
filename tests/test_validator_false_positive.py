"""tests/test_validator_false_positive.py —— 验证器「误判活」的两类缺陷。

背景（2026-11-01 curl 独立复核实测）
------------------------------------
从 `config/stream_health.json` 里随机抽 40 条「判活」的 URL，用 **curl**
（不同的 HTTP 栈）独立复核，结果 **5 条判错（12.5%）**：

    BAD  http=200  ct=video/mp4              body=ftypisom…（MP4 点播文件）
    BAD  http=200  ct=video/mp4              body=ftypisom…
    BAD  http=200  ct=video/mp4              body=ftypisom…
    BAD  http=404  ct=application/vnd.apple  body=not found
    BAD  http=200  ct=application/vnd.apple  body=（gzip 二进制，未解压）

前两类是**真误验证**，根因不同：

## 缺陷 1：`.ts` / `.mp4` 直连被判活，但那是点播文件不是直播流

`_is_valid_response()` 收 `"video"` Content-Type，而 `_looks_like_playlist_url()`
只认 `.m3u8` / `.m3u` 后缀 —— 所以 `.ts` 走 **HEAD 路径**，
拿到 200 + `video/mp2t` 就判活，**从头到尾没读 body**，
连「这是不是直播」都没问过。

实测样本（判活且 URL 是 .ts）：
    http://125.227.210.55:1001/VideoInput/play.ts
    http://125.227.210.55:1004/VideoInput/play.ts
    http://125.227.210.55:3056/VideoInput/play.ts
    http://s.rocketdns.info:8080/live/monstercable/.../648984.ts

## 缺陷 2：YouTube 图片 CDN（kwimgs.com/upic/...）被判活

`https://alimov2.a.kwimgs.com/upic/2023/01/06/16/BMjAyMzAxMDYxNjMxMTNf...`
是 **YouTube 的缩略图资源**（`upic` = user picture），200 + image/jpeg，
根本不是播放列表。现有 `PSEUDO_LIVE_KEYWORDS` 只拦 `youtube.com` / `youtu.be`，
漏了 `kwimgs.com`（YouTube 的静态资源 CDN）。

产物里的实际占比：1,375 条 URL 中 23 条（1.7%）。

本文件钉死这两条修复。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validator import Validator  # noqa: E402


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


# 真实样本（2026-11-01 从 stream_health.json 判活集合里取出的）
TS_URL = "http://125.227.210.55:1001/VideoInput/play.ts"
KWIMGS_URL = (
    "https://alimov2.a.kwimgs.com/upic/2023/01/06/16/"
    "BMjAyMzAxMDYxNjMxMTNfNDAzMDAxOTlfOTI4OTY2ODAzNjlfMF8z_b_Bdee65"
)


# ── 缺陷 1：.ts / .mp4 直连不是直播流 ──────────────────────────────────
def test_ts_direct_stream_is_not_live_playlist(monkeypatch):
    """`.ts` 直连（video/mp2t）判活 = 误判：那是点播/裸分片，不是直播流。

    修法方向：`.ts` / `.mp4` 这类**裸媒体**后缀不该走「HEAD 200 即放行」，
    要么判死，要么至少读 body 确认它是播放列表。
    """
    v, session = _patch(monkeypatch, {
        TS_URL: FakeResp(200, "video/mp2t", b"\x47\x40\x11\x10ftypisom"),
    })

    assert asyncio.run(v._check_url(TS_URL)) is False, (
        ".ts 直连被判活 —— 它是裸媒体文件，不是可播的直播流"
    )


def test_mp4_direct_stream_is_not_live_playlist(monkeypatch):
    """`.mp4` 直连同理。"""
    url = "http://example.invalid/live/stream.mp4"
    v, session = _patch(monkeypatch, {
        url: FakeResp(200, "video/mp4", b"\x00\x00\x00\x18ftypisom"),
    })

    assert asyncio.run(v._check_url(url)) is False


def test_real_playlist_with_ts_extension_still_alive(monkeypatch):
    """反向：后缀是 .ts 但 body 是合法 HLS 播放列表 → 仍判活。

    防的是「把 .ts 一刀切判死」—— 有的源确实用 .ts 后缀装 HLS 清单。
    """
    url = "http://example.invalid/live/playlist.ts"
    body = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    v, session = _patch(monkeypatch, {
        url: FakeResp(200, "text/plain", body),
    })

    assert asyncio.run(v._check_url(url)) is True


# ── 缺陷 2：YouTube 图片 CDN 不该判活 ─────────────────────────────────
def test_kwimgs_image_cdn_is_not_playable(monkeypatch):
    """YouTube 缩略图 CDN（kwimgs.com/upic/...）判活 = 误判。

    `PSEUDO_LIVE_KEYWORDS` 只拦 youtube.com / youtu.be，漏了 kwimgs.com。
    """
    v, session = _patch(monkeypatch, {
        KWIMGS_URL: FakeResp(200, "image/jpeg", b"\xff\xd8\xff\xe0"),
    })

    assert asyncio.run(v._check_url(KWIMGS_URL)) is False, (
        "YouTube 图片 CDN 被判活 —— 它是缩略图，不是播放列表"
    )


def test_kwimgs_domain_is_in_pseudo_live_keywords():
    """漂移守卫：`kwimgs.com` 必须留在伪直播关键词表里。

    防止后人「清理关键词」时把它删掉。
    """
    from src.validator import PSEUDO_LIVE_KEYWORDS

    assert any("kwimgs" in k for k in PSEUDO_LIVE_KEYWORDS), (
        "PSEUDO_LIVE_KEYWORDS 里必须有 kwimgs —— "
        "YouTube 静态资源 CDN 的 URL 会被判成可播频道"
    )


# ── 回归：正常直播流不能被误伤 ─────────────────────────────────────────
def test_normal_hls_playlist_still_alive(monkeypatch):
    """标准 HLS 播放列表必须仍然判活。"""
    url = "https://example.invalid/live/ok.m3u8"
    body = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    v, session = _patch(monkeypatch, {
        url: FakeResp(200, "application/vnd.apple.mpegurl", body),
    })

    assert asyncio.run(v._check_url(url)) is True


def test_mpegts_body_content_type_still_alive(monkeypatch):
    """Content-Type 是 mpegts 但 body 是 HLS 清单 → 判活。

    聚合源的 Content-Type 常被标错，body 签名才是准的。
    """
    url = "https://fast.hidns.vip/163189/rthk31"
    body = b"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nseg1.ts\n"
    v, session = _patch(monkeypatch, {
        url: FakeResp(200, "video/mp2t", body),
    })

    assert asyncio.run(v._check_url(url)) is True
