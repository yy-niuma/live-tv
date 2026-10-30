"""tests/test_tvg_id.py

`tvg-id`（EPG 绑定键）的端到端契约测试：解析层 → 生成层。

背景：每个产物 m3u 头部都声明了 `x-tvg-url="https://epg.pw/xmltv/epg_HK.xml..."`，
但解析层 `_ATTR_RE` 只认 tvg-name / tvg-logo / tvg-chnid / group-title / attribute，
生成层 `build_extinf` 也只输出这三个属性 —— 播放器拿到了 EPG 地址却没有绑定键，
节目表实际绑不上（实测 output/hk_merged.m3u 里 tvg-id 出现 0 次，tvg-name 81 次）。

本文件钉住的契约：
1. 带 `tvg-id` 的 m3u 行能被解析出来，值原样保留（含 `@SD` 这类后缀）；
2. 源里没有 tvg-id 时 `Channel.id` 是空串，**绝不**用频道名伪造；
3. `build_extinf` 有 id 时写 `tvg-id="..."` 且排在 tvg-name 之前；
4. 没有 id 时 EXTINF 里不出现 `tvg-id=`（连 `tvg-id=""` 都不写）；
5. 原有 tvg-name / tvg-logo / group-title 的解析与输出不退化；
6. markdown 表格 / YAML 分支不凭空造 id。

完全离线：所有输入都是字符串字面量，产物写 pytest 的 tmp_path，无网络。
"""
import re
import sys
from pathlib import Path

import pytest

# 让 `import src.*` 在单独运行本文件时也能工作
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.fetcher import Channel, Fetcher  # noqa: E402
from src.generator import Generator, build_extinf  # noqa: E402

# iptv-org 的 streams/hk.m3u 实际形态（tvg-id 形如 CelestialMovies.hk@SD）
M3U_WITH_ID = (
    '#EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"\n'
    '#EXTINF:-1 tvg-id="CelestialMovies.hk@SD" tvg-name="天映頻道" '
    'tvg-logo="https://logo.example/celestial.png" group-title="電影",天映頻道\n'
    "https://example.invalid/celestial.m3u8\n"
    '#EXTINF:-1 tvg-id="RTHKTV31.hk" tvg-name="港台电视31" '
    'tvg-logo="https://logo.example/rthk31.png" group-title="港台",港台电视31\n'
    "https://example.invalid/rthk31.m3u8\n"
)

M3U_WITHOUT_ID = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-name="自制频道XYZ" tvg-logo="https://logo.example/xyz.png" '
    'group-title="其他",自制频道XYZ\n'
    "https://example.invalid/xyz.m3u8\n"
    '#EXTINF:-1 group-title="其他",无属性频道\n'
    "https://example.invalid/plain.m3u8\n"
)

M3U_MIXED = (
    "#EXTM3U\n"
    '#EXTINF:-1 tvg-id="TVBJade.hk" tvg-name="翡翠台",翡翠台\n'
    "https://example.invalid/jade.m3u8\n"
    '#EXTINF:-1 tvg-name="明珠台",明珠台\n'
    "https://example.invalid/pearl.m3u8\n"
)


@pytest.fixture(scope="module")
def fetcher():
    return Fetcher()


def _attrs_of(line: str) -> dict:
    """从一条 EXTINF 里按出现顺序取属性，用于断言顺序/取值。"""
    pairs = re.findall(r'(?P<k>[A-Za-z0-9-]+)="(?P<v>[^"]*)"', line)
    return dict(pairs)


# ──────────────────────────────────────────────────────────────
#  解析层：tvg-id 要被捕获
# ──────────────────────────────────────────────────────────────
def test_parse_m3u_captures_tvg_id(fetcher):
    chans = fetcher.parse_m3u_text(M3U_WITH_ID)
    assert [c.id for c in chans] == ["CelestialMovies.hk@SD", "RTHKTV31.hk"]


def test_parse_m3u_keeps_id_suffix_at_sd(fetcher):
    """`@SD` 这类画质后缀是 id 的一部分，不能被剥掉/规范化。"""
    chans = fetcher.parse_m3u_text(M3U_WITH_ID)
    assert chans[0].id == "CelestialMovies.hk@SD"
    assert chans[0].id.endswith("@SD")


def test_parse_m3u_without_tvg_id_gives_empty_string(fetcher):
    chans = fetcher.parse_m3u_text(M3U_WITHOUT_ID)
    assert [c.id for c in chans] == ["", ""]


def test_parse_m3u_mixed_only_marks_the_ones_with_id(fetcher):
    chans = fetcher.parse_m3u_text(M3U_MIXED)
    assert chans[0].id == "TVBJade.hk"
    assert chans[1].id == ""


def test_does_not_fabricate_id_from_channel_name(fetcher):
    """没有 tvg-id 时不许拿频道名顶替 —— 查不到的 id 比没有更糟。"""
    chans = fetcher.parse_m3u_text(M3U_WITHOUT_ID)
    for ch in chans:
        assert ch.id == ""
        assert ch.name not in ch.id


def test_x_tvg_id_variant_is_also_captured(fetcher):
    """部分源把键写成 `x-tvg-id`；正则未锚定，`tvg-id` 子串同样命中。"""
    text = (
        "#EXTM3U\n"
        '#EXTINF:-1 x-tvg-id="Peacock.hk" tvg-name="Now 新聞",Now 新聞\n'
        "https://example.invalid/now.m3u8\n"
    )
    assert fetcher.parse_m3u_text(text)[0].id == "Peacock.hk"


# ──────────────────────────────────────────────────────────────
#  原有属性不退化
# ──────────────────────────────────────────────────────────────
def test_existing_attributes_still_parse_alongside_id(fetcher):
    chans = fetcher.parse_m3u_text(M3U_WITH_ID)
    first = chans[0]
    assert first.name == "天映頻道"
    assert first.logo == "https://logo.example/celestial.png"
    assert first.group == "電影"
    assert first.url == "https://example.invalid/celestial.m3u8"
    assert first.id == "CelestialMovies.hk@SD"


def test_attributes_still_parse_when_id_absent(fetcher):
    chans = fetcher.parse_m3u_text(M3U_WITHOUT_ID)
    assert chans[0].name == "自制频道XYZ"
    assert chans[0].logo == "https://logo.example/xyz.png"
    assert chans[0].group == "其他"
    assert chans[0].id == ""


def test_channel_id_is_stripped_and_defaults_empty():
    assert Channel(name="A台", url="https://e/1.m3u8").id == ""
    assert Channel(name="A台", url="https://e/1.m3u8", id="  X.hk  ").id == "X.hk"
    # 位置参数顺序未变：logo/group 仍按老位置生效
    ch = Channel("A台", "https://e/1.m3u8", "https://l/x.png", "分组")
    assert (ch.logo, ch.group, ch.id) == ("https://l/x.png", "分组", "")


def test_markdown_table_branch_leaves_id_empty(fetcher):
    md = (
        "| #   | Channel | Link | Logo | EPG id |\n"
        "|:---:|:-------:|:----:|:----:|:------:|\n"
        '| 31  | RTHK TV 31 | [>](https://e/rthk31/master.m3u8) | '
        '<img src="https://i.example/k.png"/> | RTHKTV31.hk |\n'
    )
    chans = fetcher.parse_markdown_table(md)
    assert len(chans) == 1
    assert chans[0].id == "", "markdown 分支不认 tvg-id，留空而不是瞎编"


def test_yaml_branch_leaves_id_empty(fetcher):
    text = (
        "streams:\n"
        "  - name: 翡翠台\n"
        "    url: https://e/jade.m3u8\n"
        "    logo: https://l/j.png\n"
        "    group: TVB\n"
    )
    chans = fetcher.parse_yaml_text(text)
    if not chans:  # pyyaml 未安装时该分支返回 []
        pytest.skip("pyyaml 不可用，YAML 分支被跳过")
    assert chans[0].id == ""


# ──────────────────────────────────────────────────────────────
#  生成层：EXTINF 要带 tvg-id
# ──────────────────────────────────────────────────────────────
def test_build_extinf_writes_tvg_id_with_correct_value():
    ch = Channel(
        name="天映頻道",
        url="https://e/c.m3u8",
        logo="https://l/c.png",
        group="電影",
        id="CelestialMovies.hk@SD",
    )
    line = build_extinf(ch, "電影")
    assert line.startswith("#EXTINF:-1 ")
    assert line.endswith(",天映頻道")
    assert 'tvg-id="CelestialMovies.hk@SD"' in line


def test_build_extinf_puts_tvg_id_before_tvg_name():
    """属性顺序与源的习惯一致：tvg-id 在 tvg-name 前面。"""
    ch = Channel(name="翡翠台", url="https://e/j.m3u8", id="TVBJade.hk")
    line = build_extinf(ch, "TVB")
    order = list(_attrs_of(line))
    assert order[0] == "tvg-id", f"tvg-id 应该是第一个属性，实际 {order}"
    assert order.index("tvg-id") < order.index("tvg-name")


def test_build_extinf_omits_tvg_id_when_channel_has_none():
    ch = Channel(name="自制频道XYZ", url="https://e/x.m3u8")
    line = build_extinf(ch, "其他")
    assert "tvg-id" not in line
    assert 'tvg-id=""' not in line


def test_build_extinf_ignores_whitespace_only_id():
    ch = Channel(name="自制频道XYZ", url="https://e/x.m3u8", id="   ")
    assert "tvg-id" not in build_extinf(ch, "其他")


def test_build_extinf_legacy_attributes_unchanged():
    """tvg-name / tvg-logo / group-title 的原有输出不退化。"""
    ch = Channel(
        name="翡翠台", url="https://e/j.m3u8", logo="https://l/j.png", id="TVBJade.hk"
    )
    line = build_extinf(ch, "📺 TVB")
    attrs = _attrs_of(line)
    assert attrs["tvg-name"] == "翡翠台"
    assert attrs["tvg-logo"] == "https://l/j.png"
    assert attrs["group-title"] == "📺 TVB"
    assert attrs["tvg-id"] == "TVBJade.hk"
    # 没有 id 时其余三个属性的输出必须与旧行为逐字一致
    no_id = build_extinf(
        Channel(name="翡翠台", url="https://e/j.m3u8", logo="https://l/j.png"), "📺 TVB"
    )
    assert no_id == (
        '#EXTINF:-1 tvg-name="翡翠台" tvg-logo="https://l/j.png" '
        'group-title="📺 TVB",翡翠台'
    )


def test_extinf_round_trips_through_fetcher(fetcher):
    """生成的 EXTINF 能被自己的解析器读回，id 不丢 —— 产物可再消费。"""
    ch = Channel(
        name="港台电视31",
        url="https://e/r.m3u8",
        logo="https://l/r.png",
        group="港台",
        id="RTHKTV31.hk",
    )
    text = "#EXTM3U\n" + build_extinf(ch, "港台") + "\n" + ch.url + "\n"
    parsed = fetcher.parse_m3u_text(text)
    assert len(parsed) == 1
    assert parsed[0].id == "RTHKTV31.hk"
    assert parsed[0].name == "港台电视31"
    assert parsed[0].logo == "https://l/r.png"
    assert parsed[0].group == "港台"


# ──────────────────────────────────────────────────────────────
#  产物级：generate_hk_and_all 真的写出 tvg-id，且 EPG 头部不变
# ──────────────────────────────────────────────────────────────
def _playlist_body(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_generated_playlists_emit_tvg_id(tmp_path):
    grouped = {
        "📺 TVB": [
            Channel(name="翡翠台", url="https://e/jade.m3u8", id="TVBJade.hk"),
            Channel(name="明珠台", url="https://e/pearl.m3u8", id="TVBPearl.hk"),
            Channel(name="ViuTV", url="https://e/viu.m3u8"),  # 源里没有 tvg-id
        ]
    }
    Generator().generate_hk_and_all(grouped, str(tmp_path))

    for name in ("hk_merged.m3u", "all_merged.m3u"):
        body = _playlist_body(tmp_path / name)
        extinf = [ln for ln in body.splitlines() if ln.startswith("#EXTINF")]
        with_id = [ln for ln in extinf if 'tvg-id="' in ln]
        assert len(with_id) == 2, f"{name}: 应只有 2 条带 tvg-id，实际 {len(with_id)}"
        assert 'tvg-id="TVBJade.hk"' in body
        assert 'tvg-id="TVBPearl.hk"' in body
        assert 'tvg-id=""' not in body, "空 id 不许写成空属性"
        # 无 id 的那条 EXTINF 里不出现 tvg-id
        plain = [ln for ln in extinf if "ViuTV" in ln]
        assert plain and all("tvg-id" not in ln for ln in plain)


def test_generated_playlist_keeps_epg_url_header_unchanged(tmp_path):
    grouped = {
        "📺 TVB": [Channel(name="翡翠台", url="https://e/j.m3u8", id="TVBJade.hk")]
    }
    Generator().generate_hk_and_all(grouped, str(tmp_path))
    for name in ("hk_merged.m3u", "all_merged.m3u"):
        first = _playlist_body(tmp_path / name).splitlines()[0]
        assert first.startswith("#EXTM3U")
        assert "x-tvg-url=" in first
        assert "epg.pw/xmltv/epg_HK.xml" in first
