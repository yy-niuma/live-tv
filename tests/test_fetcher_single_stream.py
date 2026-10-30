"""tests/test_fetcher_single_stream.py —— 「单流直连」源的抓取支持。

背景（2026-10-30 调研）
------------------------
新增两个官方直连源，它们的 URL 本身**就是一个可播的 HLS 播放列表**，
不是「装着很多频道的清单」：

    https://live5.tdm.com.mo/ch5/info_ch5.live/playlist.m3u8
        #EXTM3U
        #EXT-X-STREAM-INF:...RESOLUTION=1920x1080
        chunklist_w1382731115.m3u8

    https://v3.mediacast.hk/webcast/bshdlive-pc/playlist.m3u8
        #EXTM3U
        #EXT-X-STREAM-INF:...RESOLUTION=1024x576
        chunklist_w768738166.m3u8

`parse_m3u_text` 只认 `#EXTINF` 行，遇到这种「没有 EXTINF、只有 STREAM-INF」
的 HLS 媒体/主播放列表会返回 0 条 —— 抓取器于是报「返回 0 个频道」，
源形同虚设（实测已复现）。

修法：抓取器遇到「解析出 0 条、但源本身是个 HLS 播放列表」时，
把源 URL 本身当成**一个频道**收下（频道名取自源配置）。
本文件钉死这个行为。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetcher import Fetcher  # noqa: E402


HLS_MASTER = (
    b"#EXTM3U\n"
    b"#EXT-X-VERSION:3\n"
    b'#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2914601,RESOLUTION=1920x1080\n'
    b"chunklist_w1382731115.m3u8\n"
)

HLS_MEDIA = (
    b"#EXTM3U\n"
    b"#EXT-X-VERSION:3\n"
    b"#EXT-X-TARGETDURATION:6\n"
    b"#EXTINF:6.006000,\nchunk1151562.ts\n"
)


class _FakeContent:
    def __init__(self, body):
        self._body = body

    async def read(self, limit=-1):
        return self._body if limit is None or limit < 0 else self._body[:limit]


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self.headers = {"Content-Type": "application/vnd.apple.mpegurl"}
        self.content = _FakeContent(body)

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def text(self):
        return self.content._body.decode("utf-8", "replace")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, body):
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, **kw):
        return _FakeResp(200, self._body)

    def head(self, url, **kw):
        return _FakeResp(200, self._body)


def _patch(monkeypatch, body):
    monkeypatch.setattr(
        "src.fetcher.aiohttp.ClientSession",
        lambda *a, **k: _FakeSession(body),
    )


def test_parse_hls_master_without_extinf_returns_zero():
    """前提：纯 HLS 主播放列表用 parse_m3u_text 解析确实是 0 条。

    这条测试是整个特性的「问题陈述」—— 如果哪天 parse_m3u_text 改成能解析
    HLS 播放列表了，这条会红，提示该特性可以简化。
    """
    f = Fetcher()
    assert f.parse_m3u_text(HLS_MASTER.decode()) == []


def test_single_stream_source_yields_one_channel(monkeypatch):
    """单流直连源必须被当成 1 个频道收下，而不是「返回 0 个频道」。"""
    _patch(monkeypatch, HLS_MASTER)
    f = Fetcher()
    src = {"name": "tdm-macau-official",
           "url": "https://live5.tdm.com.mo/ch5/info_ch5.live/playlist.m3u8",
           "priority": 1}
    chs = asyncio.run(f._fetch_source(src))
    assert len(chs) == 1, f"单流直连源应产出 1 个频道，实得 {len(chs)}"
    assert chs[0].url == src["url"], "频道 URL 必须就是源 URL 本身"
    assert chs[0].name, "频道必须有名字"


def test_single_stream_source_uses_configured_display_name(monkeypatch):
    """频道名应可由源配置指定（源名是内部标识，不适合当频道名）。"""
    _patch(monkeypatch, HLS_MASTER)
    f = Fetcher()
    src = {"name": "tdm-macau-official",
           "display_name": "澳门资讯",
           "url": "https://live5.tdm.com.mo/ch5/info_ch5.live/playlist.m3u8",
           "priority": 1}
    chs = asyncio.run(f._fetch_source(src))
    assert len(chs) == 1
    assert chs[0].name == "澳门资讯"


def test_single_stream_source_keeps_source_attribution(monkeypatch):
    """收下的频道要带 _source / _priority（后续合并与溯源依赖）。"""
    _patch(monkeypatch, HLS_MASTER)
    f = Fetcher()
    src = {"name": "bstv-hk-official",
           "display_name": "耀才财经台",
           "url": "https://v3.mediacast.hk/webcast/bshdlive-pc/playlist.m3u8",
           "priority": 1}
    chs = asyncio.run(f._fetch_source(src))
    assert chs[0].raw_attrs.get("_source") == "bstv-hk-official"
    assert chs[0].raw_attrs.get("_priority") == 1


def test_regular_m3u_source_is_not_turned_into_single_channel(monkeypatch):
    """普通清单源（有 #EXTINF）走原路径，不能被单流逻辑误伤。"""
    body = (
        b"#EXTM3U\n"
        b'#EXTINF:-1 tvg-name="\xe5\x8f\xb0A",\xe5\x8f\xb0A\n'
        b"http://example.com/a.m3u8\n"
        b'#EXTINF:-1 tvg-name="\xe5\x8f\xb0B",\xe5\x8f\xb0B\n'
        b"http://example.com/b.m3u8\n"
    )
    _patch(monkeypatch, body)
    f = Fetcher()
    src = {"name": "normal", "url": "http://example.com/list.m3u"}
    chs = asyncio.run(f._fetch_source(src))
    assert len(chs) == 2
    assert {c.name for c in chs} == {"台A", "台B"}


def test_non_playlist_response_still_yields_zero(monkeypatch):
    """源返回的既不是清单也不是 HLS 播放列表时，仍然是 0 条（不硬造频道）。"""
    body = b"<html><body>404 not found</body></html>"
    _patch(monkeypatch, body)
    f = Fetcher()
    src = {"name": "bad", "url": "http://example.com/nope"}
    chs = asyncio.run(f._fetch_source(src))
    assert len(chs) == 0


# ---------------------------------------------------------------------------
# 单流判据本身（直接调 _as_single_stream，不走抓取流程）
# ---------------------------------------------------------------------------
# 上一组测试走的是「抓取流程」，parse_m3u_text 会先把带 #EXTINF 的清单解析掉，
# 于是判据第 2/3 条即使被删掉也测不出来。这里直接测判据本身。


def test_single_stream_rejects_channel_list_with_tvg_name():
    """带 tvg-name 的频道清单不能被当成单流（它有 N 个频道，不是 1 个）。

    构造时要**同时**带 HLS 标记（#EXT-X-TARGETDURATION）——有些源会在
    频道清单里附 HLS 参数。只带 #EXTINF 的话会被「HLS 标记」那条判据
    拦下，测不出 tvg-name 这条判据是否有效。
    """
    f = Fetcher()
    body = (
        b"#EXTM3U\n"
        b"#EXT-X-TARGETDURATION:6\n"
        b'#EXTINF:-1 tvg-name="A",A\n'
        b"http://example.com/a.m3u8\n"
    )
    assert f._as_single_stream("http://example.com/list.m3u", body.decode(), {}) == []


def test_single_stream_rejects_non_hls_playlist():
    """没有 HLS 标记的 #EXTM3U（普通播放列表）不能被当成单流。"""
    f = Fetcher()
    body = b"#EXTM3U\n#EXTVLCOPT:network-caching=1000\nfoo.m3u8\n"
    assert f._as_single_stream("http://example.com/x.m3u", body.decode(), {}) == []


def test_single_stream_rejects_html():
    """HTML 不是播放列表。"""
    f = Fetcher()
    assert f._as_single_stream("http://example.com/x", "<html>404</html>", {}) == []


def test_single_stream_rejects_empty():
    """空 body 不是播放列表。"""
    f = Fetcher()
    assert f._as_single_stream("http://example.com/x", "", {}) == []
    assert f._as_single_stream("http://example.com/x", "   \n ", {}) == []


def test_single_stream_accepts_hls_master():
    """HLS 主播放列表 = 单流。"""
    f = Fetcher()
    body = HLS_MASTER.decode()
    chs = f._as_single_stream("http://example.com/live.m3u8", body, {"name": "src"})
    assert len(chs) == 1
    assert chs[0].url == "http://example.com/live.m3u8"


def test_single_stream_accepts_hls_media_playlist():
    """HLS 媒体播放列表（#EXTINF 是分片）= 单流。"""
    f = Fetcher()
    body = HLS_MEDIA.decode()
    chs = f._as_single_stream("http://example.com/live.m3u8", body, {"name": "src"})
    assert len(chs) == 1


def test_single_stream_prefers_display_name_over_source_name():
    """display_name 优先于源 name（源 name 是内部标识）。"""
    f = Fetcher()
    chs = f._as_single_stream(
        "http://example.com/live.m3u8", HLS_MASTER.decode(),
        {"name": "tdm-macau-official", "display_name": "澳门资讯"},
    )
    assert chs[0].name == "澳门资讯"


def test_single_stream_falls_back_to_source_name():
    """没有 display_name 时用源 name。"""
    f = Fetcher()
    chs = f._as_single_stream(
        "http://example.com/live.m3u8", HLS_MASTER.decode(),
        {"name": "some-source"},
    )
    assert chs[0].name == "some-source"


@pytest.mark.parametrize("body", [HLS_MASTER, HLS_MEDIA])
def test_hls_media_playlist_also_works(monkeypatch, body):
    """媒体播放列表（#EXTINF + .ts 分片）同样应当被认成单流。"""
    _patch(monkeypatch, body)
    f = Fetcher()
    src = {"name": "x", "url": "http://example.com/live.m3u8"}
    chs = asyncio.run(f._fetch_source(src))
    assert len(chs) == 1
    assert chs[0].url == "http://example.com/live.m3u8"
