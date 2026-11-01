"""tests/test_check_sources_single_stream.py —— 体检脚本对「单流直连」源的口径。

背景（2026-11-01 实测复现）
----------------------------
`scripts/check_sources.py` 的 `probe_source()` 用 `fetcher.parse_text(text)` 解析，
而**主流程走的是 `Fetcher._fetch_source()`** —— 后者在解析出 0 条时会兜底调用
`_as_single_stream()`，把「源 URL 本身就是一条可播 HLS 流」收成一个频道。

两个路径不一致，导致体检把 5 个**活的**官方源报成 dead：

    tdm-macau-official  →  https://live5.tdm.com.mo/ch5/info_ch5.live/playlist.m3u8
    bstv-hk-official    →  https://v3.mediacast.hk/webcast/bshdlive-pc/playlist.m3u
    rthk31-hidns        →  https://fast.hidns.vip/163189/rthk31
    rthk32-hidns        →  https://fast.hidns.vip/163189/rthk32
    hoy78-hidns         →  https://fast.hidns.vip/163189/hoy78

实测证据（2026-11-01）：
    curl 探活        → 5/5 返回 HTTP 200 + `#EXTM3U`
    主流程 _fetch_source → 5/5 各抓到 1 条
    体检 parse_text  → 5/5 报 0 条 dead

这是「假警报」—— 比「静默失效」同样有害：人会据此把好源从 sources.yaml 里删掉。

修法：体检与主流程共用同一套解析口径（`_fetch_source`），不允许各走各的。
本文件钉死这个契约。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_sources.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_sources_ss_ut", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = previous
    return mod


@pytest.fixture(scope="module")
def cs():
    return _load_script()


# HLS master 播放列表：#EXTM3U + #EXT-X-STREAM-INF，**没有** #EXTINF。
# 这正是官方直连源（TDM / 明珠 / hidns）的真实形态。
HLS_MASTER = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2914601,RESOLUTION=1920x1080\n"
    "chunklist_w1382731115.m3u8\n"
)

SINGLE_STREAM_SRC = {
    "name": "tdm-macau-official",
    "url": "https://live5.tdm.com.mo/ch5/info_ch5.live/playlist.m3u8",
    "display_name": "澳視澳門台",
    "priority": 1,
}


def fake_get_text(table: dict[str, str], error_urls=frozenset(), calls=None):
    """把 `Fetcher._get_text` 换成查表（不发真实网络）。"""

    async def _get_text(self, url, headers=None):
        if calls is not None:
            calls.append({"url": url, "headers": headers})
        if url in error_urls:
            raise TimeoutError(f"fake timeout: {url}")
        if url not in table:
            raise ConnectionError(f"no fake content registered for {url}")
        return table[url]

    return _get_text


# ── RED：单流直连源不能被判 dead ────────────────────────────────────────
async def test_single_stream_source_is_not_reported_dead(cs, monkeypatch):
    """核心回归：HLS master 直连源必须报 1 条，不能报 0 条 dead。

    这条在修复前会失败（channels=0 / status=dead），
    修复后必须绿 —— 它就是当初 5 个官方源被误报的那个洞。
    """
    url = SINGLE_STREAM_SRC["url"]
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text({url: HLS_MASTER})
    )
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, SINGLE_STREAM_SRC)

    assert row["channels"] == 1, (
        f"单流直连源被报成 {row['channels']} 条 —— "
        "体检口径与主流程不一致，会导致好源被误弃"
    )
    assert row["error"] == ""
    assert cs.row_status(row) == "ok"


async def test_single_stream_source_uses_source_url_as_channel_url(cs, monkeypatch):
    """单流直连收下的频道，URL 必须是**源 URL 本身**（不是 master 里的子流）。"""
    url = SINGLE_STREAM_SRC["url"]
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text({url: HLS_MASTER})
    )
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, SINGLE_STREAM_SRC)

    assert row["format"] == "single_stream", (
        "单流直连要有独立的 format 标记，不能混进 m3u —— "
        "否则体检报告看不出这个源是哪种形态"
    )


async def test_health_check_and_main_flow_agree_on_single_stream(cs, monkeypatch):
    """漂移守卫：体检口径必须与主流程 `_fetch_source` 一致。

    这是本文件最关键的一条 —— 它防的不是「某个源报几条」，
    而是「体检与主流程各走各的解析路径」这个**结构性**缺陷。
    """
    url = SINGLE_STREAM_SRC["url"]
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text({url: HLS_MASTER})
    )
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, SINGLE_STREAM_SRC)
    main_channels = await fetcher._fetch_source(SINGLE_STREAM_SRC)

    assert row["channels"] == len(main_channels), (
        f"体检报 {row['channels']} 条、主流程抓到 {len(main_channels)} 条 —— "
        "两个口径已经漂移"
    )


# ── 反向：真死的源仍必须报 dead（别把修复做成「一律放行」）────────────
async def test_truly_empty_source_still_reported_dead(cs, monkeypatch):
    """修口径不能变成「一律放行」：空 body 仍必须判 dead。"""
    url = "https://a.invalid/a.m3u"
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text({url: ""}))
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, {"name": "空源", "url": url})

    assert row["channels"] == 0
    assert cs.row_status(row) == "dead"


async def test_html_error_page_still_reported_dead(cs, monkeypatch):
    """HTML 错误页不是播放列表，必须判 dead。

    （`_as_single_stream` 要求 body 以 `#EXTM3U` 开头。）
    """
    url = "https://a.invalid/a.m3u"
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text({url: "<html>404 not found</html>"})
    )
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, {"name": "错误页", "url": url})

    assert row["channels"] == 0
    assert cs.row_status(row) == "dead"


async def test_channel_list_with_tvg_name_is_not_single_stream(cs, monkeypatch):
    """带 tvg-name 的 EXTINF 是**频道清单**，不能被当成单流直连收下。"""
    url = "https://a.invalid/a.m3u"
    body = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:PROGRAM-ID=1\n"
        'child.m3u8\n'
        '#EXTINF:-1 tvg-name="RTHK TV 31",RTHK TV 31\n'
        "http://example.invalid/hk31.m3u8\n"
    )
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text({url: body}))
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, {"name": "清单源", "url": url})

    assert row["channels"] == 1
    assert row["format"] == "m3u"
