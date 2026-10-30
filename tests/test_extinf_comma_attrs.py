"""EXTINF 属性写在时长逗号之后（畸形源）的解析回归测试。

真实来源：`qist-tvbox`（`https://raw.githubusercontent.com/qist/tvbox/master/list.m3u`）
里有 6 条这样的行：

    #EXTINF:-1,tvg-id="CCTV1" tvg-name="CCTV1" …
        tvg-logo="…" group-title="肥羊4K-8K",CCTV1-4K

`_EXTINF_RE` 的 `attributes` 是 `[^,]*`，遇到 `-1,` 只抓到空串，于是整串属性
被当成频道名进了产物（实测 hk_merged.m3u 里有 4 条带 `tvg-…` 的垃圾名）。
修复后属性会被拨回属性区、真名取最后一段。

这些用例全部离线，不联网。
"""
import pytest
from src.fetcher import Fetcher

MALFORMED = (
    "#EXTM3U\n"
    '#EXTINF:-1,tvg-id="CCTV1" tvg-name="CCTV1" '
    'tvg-logo="https://logo.example/CCTV1.png" group-title="肥羊4K-8K",CCTV1-4K\n'
    "http://example.com/cctv1.m3u8\n"
)

WELLFORMED = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="CCTV1" tvg-name="CCTV1" '
    'tvg-logo="https://logo.example/CCTV1.png" group-title="肥羊4K-8K",CCTV1-4K\n'
    "http://example.com/cctv1.m3u8\n"
)


def parse(text):
    return Fetcher().parse_m3u_text(text)


def test_malformed_line_yields_clean_name():
    """畸形行（属性在逗号后）不许把 tvg-… 属性串当成频道名。"""
    chans = parse(MALFORMED)
    assert len(chans) == 1
    ch = chans[0]
    assert ch.name == "CCTV1-4K"
    assert "tvg-" not in ch.name
    assert "group-title" not in ch.name


def test_malformed_line_recovers_attrs():
    """属性拨回后，id / logo / group 都要正常回收，不能因为畸形就丢。"""
    ch = parse(MALFORMED)[0]
    assert ch.id == "CCTV1"
    assert ch.logo == "https://logo.example/CCTV1.png"
    assert ch.group == "肥羊4K-8K"


def test_malformed_and_wellformed_parse_identically():
    """同一份内容的两种写法，解析结果必须逐字段相等。"""
    a = parse(MALFORMED)[0]
    b = parse(WELLFORMED)[0]
    assert (a.name, a.id, a.logo, a.group) == (b.name, b.id, b.logo, b.group)


def test_wellformed_line_unaffected():
    """正常行不受兜底逻辑影响（回归护栏）。"""
    ch = parse(WELLFORMED)[0]
    assert ch.name == "CCTV1-4K"
    assert ch.id == "CCTV1"
    assert ch.group == "肥羊4K-8K"


def test_name_containing_comma_is_preserved_when_no_attrs():
    """名字本身带逗号、但没有任何属性残留时，**不许**被截断。

    这是兜底逻辑最容易误伤的地方：判据必须是「名字里还有 attr=」，
    而不是「名字里有逗号」。
    """
    text = (
        "#EXTM3U\n"
        '#EXTINF:-1 group-title="综合",新闻, 财经\n'
        "http://example.com/news.m3u8\n"
    )
    ch = parse(text)[0]
    assert ch.name == "新闻, 财经"
    assert ch.group == "综合"


def test_attr_like_text_inside_name_after_comma_not_swallowed():
    """名字里出现 `group-title=` 字样但**没有逗号可分**时，保持原样。"""
    text = (
        "#EXTM3U\n"
        '#EXTINF:-1 group-title="A",某台 group-title=不是属性\n'
        "http://example.com/x.m3u8\n"
    )
    ch = parse(text)[0]
    # 没有第二个逗号，rpartition 的 head 为空 -> 不触发拨回
    assert ch.name == "某台 group-title=不是属性"


def test_malformed_without_id_still_clean():
    """畸形行但源里本来没有 tvg-id：名字干净、id 为空，不伪造。"""
    text = (
        "#EXTM3U\n"
        '#EXTINF:-1,tvg-name="某台" group-title="测试",某台\n'
        "http://example.com/x.m3u8\n"
    )
    ch = parse(text)[0]
    assert ch.name == "某台"
    assert ch.id == ""
    assert ch.group == "测试"


@pytest.mark.parametrize(
    "line,expect_name",
    [
        ('#EXTINF:-1,tvg-id="a" group-title="g",真名', "真名"),
        ('#EXTINF:-1, tvg-id="a" group-title="g",真名', "真名"),
        ('#EXTINF:0,tvg-id="a",真名', "真名"),
    ],
)
def test_parametrized_shapes(line, expect_name):
    text = f"#EXTM3U\n{line}\nhttp://example.com/x.m3u8\n"
    assert parse(text)[0].name == expect_name
