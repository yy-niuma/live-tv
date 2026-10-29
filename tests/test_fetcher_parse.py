"""`Fetcher` 解析层的单元测试（纯函数，不发网络请求）。

背景：2026-10-29 发现 `config/sources.yaml` 里 8 个 `.md` 结尾的源
（`Free-TV/IPTV` 各区域列表 + 它的 fork `Harbin-byte/iptv`）**HTTP 200 但解析出 0 条**——
Free-TV 的 `.md` 是 markdown 表格，不是 m3u，而旧代码按后缀把所有非 `.yml` 都当 m3u 解析。
这里把「按内容嗅探」和「markdown 表格解析」钉成契约。
"""
import pytest

from src.fetcher import Fetcher


@pytest.fixture(scope="module")
def fetcher():
    return Fetcher()


# 真实内容取自 https://raw.githubusercontent.com/Free-TV/IPTV/master/lists/hong_kong.md
FREE_TV_HK_MD = """<h1>Hong Kong</h1>

* https://en.wikipedia.org/wiki/List_of_television_stations_in_Hong_Kong

| #   | Channel        | Link  | Logo | EPG id |
|:---:|:--------------:|:-----:|:----:|:------:|
| 31  | RTHK TV 31 | [>](https://rthktv31-live.akamaized.net/hls/live/2036818/RTHKTV31/master.m3u8) | <img height="20" src="https://i.imgur.com/kf818kM.png"/> | RTHKTV31.hk |
| 32  | RTHK TV 32 | [>](https://rthktv32-live.akamaized.net/hls/live/2036819/RTHKTV32/master.m3u8) | <img height="20" src="https://i.imgur.com/MXLuUoU.png"/> | RTHKTV32.hk |
| 77  | HOY TV Ⓖ | [>](https://hoytv-live-stream.hoy.tv/ch78/index-fhd.m3u8) | <img height="20" src="https://i.imgur.com/NfVZPTT.png"/> | HKIBC.hk |
| 83  | TVB News Channel | [>](https://tvp22.sky4k.top/index1.php) | <img height="20" src="https://i.imgur.com/Gwij0Fj.png"/> | TVBNewsChannel.hk |
"""

# 真实内容取自 .../lists/china.md（截取）
FREE_TV_CN_MD = """| #   | Channel | Link | Logo | EPG id |
|:---:|:-------:|:----:|:----:|:------:|
| 1   | CCTV-1 综合 Ⓢ | [>](https://cctv1.example/live.m3u8) | <img src="https://i.imgur.com/cctv1.png"/> | CCTV1.cn |
| 2   | CCTV-2 财经 | [>](https://cctv2.example/live.m3u8) |  | CCTV2.cn |
"""

M3U_TEXT = """#EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml"
#EXTINF:-1 tvg-name="翡翠台" tvg-logo="https://x/1.png" group-title="TVB",翡翠台
https://example.com/jade.m3u8
#EXTINF:-1 tvg-logo="https://x/2.png" group-title="TVB",明珠台
https://example.com/pearl.m3u8
"""

FREE_IPTV_YAML = """
streams:
  - name: 翡翠台
    url: https://example.com/jade.m3u8
    logo: https://x/1.png
    group: TVB
"""


# ── markdown 表格 ──────────────────────────────────────────────


def test_markdown_table_parses_hong_kong_list(fetcher):
    """Free-TV 的 hk 列表：4 行数据行，全部应被解析出来。"""
    chans = fetcher.parse_markdown_table(FREE_TV_HK_MD)
    assert len(chans) == 4
    names = [c.name for c in chans]
    assert names == ["RTHK TV 31", "RTHK TV 32", "HOY TV", "TVB News Channel"]
    assert chans[0].url == (
        "https://rthktv31-live.akamaized.net/hls/live/2036818/RTHKTV31/master.m3u8"
    )
    assert chans[0].logo == "https://i.imgur.com/kf818kM.png"


def test_markdown_table_strips_source_markers(fetcher):
    """名字尾部的 Ⓖ/Ⓢ 等是「geoblocked / subscription」标记，不该进频道名。"""
    chans = fetcher.parse_markdown_table(FREE_TV_HK_MD)
    hoy = next(c for c in chans if "HOY" in c.name)
    assert hoy.name == "HOY TV"
    assert "Ⓖ" not in hoy.name

    cn = fetcher.parse_markdown_table(FREE_TV_CN_MD)
    assert cn[0].name == "CCTV-1 综合"  # 去掉尾部 Ⓢ


def test_markdown_table_skips_header_and_separator(fetcher):
    """表头 `| # | Channel |` 和分隔行 `|:---:|` 不能被当成频道。"""
    chans = fetcher.parse_markdown_table(FREE_TV_CN_MD)
    assert len(chans) == 2
    assert all(c.name not in ("#", "Channel", "Link") for c in chans)


def test_markdown_table_tolerates_missing_logo(fetcher):
    """Logo 列为空的行走 _MD_LOGO_RE 不匹配，logo 应为空串而不是报错。"""
    chans = fetcher.parse_markdown_table(FREE_TV_CN_MD)
    cctv2 = next(c for c in chans if c.name == "CCTV-2 财经")
    assert cctv2.logo == ""


def test_markdown_table_group_is_empty(fetcher):
    """markdown 表格没有分组列，group 必须是空串，交给 categorizer 按名字判。"""
    for c in fetcher.parse_markdown_table(FREE_TV_HK_MD):
        assert c.group == ""


# ── 内容嗅探（这次修的核心）────────────────────────────────────


def test_parse_text_detects_m3u(fetcher):
    r = fetcher.parse_text(M3U_TEXT)
    assert r.format == "m3u"
    assert len(r.channels) == 2
    assert r.channels[0].name == "翡翠台"
    assert r.channels[0].group == "TVB"


def test_parse_text_detects_markdown(fetcher):
    r = fetcher.parse_text(FREE_TV_HK_MD)
    assert r.format == "markdown"
    assert len(r.channels) == 4


def test_parse_text_prefers_m3u_over_suffix(fetcher):
    """有仓库把 m3u 内容存成 .md —— 内容嗅探必须优先于后缀。"""
    r = fetcher.parse_text(M3U_TEXT)
    assert r.format == "m3u"


def test_parse_text_detects_yaml(fetcher):
    r = fetcher.parse_text(FREE_IPTV_YAML)
    assert r.format == "yaml"
    assert len(r.channels) == 1
    assert r.channels[0].name == "翡翠台"


def test_parse_text_returns_empty_for_garbage(fetcher):
    """纯 HTML / 空响应 -> format='empty'，不能假装解析成功。"""
    r = fetcher.parse_text("<html><body>not a playlist</body></html>")
    assert r.format == "empty"
    assert r.channels == []
    assert fetcher.parse_text("").format == "empty"


# ── 回归：旧行为不变 ──────────────────────────────────────────


def test_parse_m3u_text_keeps_existing_behaviour(fetcher):
    chans = fetcher.parse_m3u_text(M3U_TEXT)
    assert [c.name for c in chans] == ["翡翠台", "明珠台"]
    assert chans[1].logo == "https://x/2.png"


def test_parse_yaml_text_streams_format(fetcher):
    chans = fetcher.parse_yaml_text(FREE_IPTV_YAML)
    assert len(chans) == 1
    assert chans[0].url == "https://example.com/jade.m3u8"


def test_parse_yaml_text_list_format(fetcher):
    """Free-IPTV 的第二种形态：顶层是 list，用 title/file/category。"""
    text = """
- title: 翡翠台
  file: https://example.com/jade.m3u8
  category: TVB
"""
    chans = fetcher.parse_yaml_text(text)
    assert len(chans) == 1
    assert chans[0].name == "翡翠台"
    assert chans[0].group == "TVB"


# ── headers 透传（sources.yaml 里写了 headers 但旧代码从不使用）────


@pytest.mark.asyncio
async def test_headers_from_source_are_forwarded(monkeypatch):
    """`freetv-fun` 配了 User-Agent，旧 `_fetch_source()` 读都没读。"""
    fetcher = Fetcher()
    captured = {}

    async def fake_get_text(url, headers=None):
        captured["url"] = url
        captured["headers"] = headers
        return M3U_TEXT

    monkeypatch.setattr(fetcher, "_get_text", fake_get_text)

    source = {
        "name": "with-headers",
        "url": "https://example.com/x.m3u",
        "priority": 2,
        "headers": {"User-Agent": "Mozilla/5.0 test"},
    }
    chans = await fetcher._fetch_source(source)

    assert len(chans) == 2
    assert captured["headers"] == {"User-Agent": "Mozilla/5.0 test"}
    assert chans[0].raw_attrs["_source"] == "with-headers"
    assert chans[0].raw_attrs["_priority"] == 2


@pytest.mark.asyncio
async def test_zero_channel_source_is_not_an_exception(monkeypatch, capsys):
    """0 条时应打 WARNING（旧版是静默的），但不算异常、不重试。"""
    fetcher = Fetcher(max_retries=1)

    async def fake_get_text(url, headers=None):
        return "<html>nothing here</html>"

    monkeypatch.setattr(fetcher, "_get_text", fake_get_text)
    chans = await fetcher._fetch_source({"name": "dead", "url": "https://example.com/d"})

    assert chans == []
    out = capsys.readouterr().out
    assert "WARNING" in out and "dead" in out
