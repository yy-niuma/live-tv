"""tests/test_generator.py

离线测试 `src.generator`：模块级纯函数（sort_key / is_clean_name / build_extinf）
与 `Generator.generate_hk_and_all` 的输出契约。

设计约束：
- 完全离线：不触发网络，输出写入 pytest 的 tmp_path。
- 不使用 conftest.py / pytest.ini 提供的任何东西：fixture 全部内联在本文件。
- 断言依据是源码实际行为（src/generator.py），不是猜测。
"""
import re
import sys
from pathlib import Path

import pytest

# 让 `import src.*` 在没有 conftest.py 的情况下也能工作
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.fetcher import Channel  # noqa: E402
from src.generator import (  # noqa: E402
    CATEGORY_ORDER,
    Generator,
    build_extinf,
    is_clean_name,
    sort_key,
)

EXTINF = "#EXTINF:-1"
_EXTGRP_RE = re.compile(r"^#EXTGRP:(?P<cat>.*) \((?P<n>\d+)\)$")


# ──────────────────────────────────────────────────────────────
#  fixture（内联，不依赖 conftest.py）
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def make_channel():
    """构造 Channel 的小工厂，默认给一个不会真的被访问的 URL。"""

    def _make(name: str, url: str = None, logo: str = "", group: str = "") -> Channel:
        return Channel(
            name=name,
            url=url if url is not None else f"http://example.invalid/{name}.m3u8",
            logo=logo,
            group=group,
        )

    return _make


@pytest.fixture()
def parse_playlist():
    """把生成的 m3u 解析成结构，便于断言条数/分组/超额标记。

    返回 {"first_line": str, "header_lines": [...], "groups": [...], "raw": str}
    每个 group: {"declared": int|None, "cat": str, "extinf": [...], "urls": [...], "extra": [...]}
    """

    def _parse(path) -> dict:
        raw = Path(path).read_text(encoding="utf-8")
        lines = raw.split("\n")
        groups = []
        header_lines = []
        current = None
        for line in lines:
            if line.startswith("#EXTGRP:"):
                m = _EXTGRP_RE.match(line)
                current = {
                    "declared": int(m.group("n")) if m else None,
                    "cat": m.group("cat") if m else line,
                    "extinf": [],
                    "urls": [],
                    "extra": [],
                }
                groups.append(current)
            elif line.startswith(EXTINF):
                assert current is not None, f"EXTINF 出现在任何 #EXTGRP 之前: {line!r}"
                current["extinf"].append(line)
            elif line.startswith("# ... and"):
                assert current is not None
                current["extra"].append(line)
            elif line.startswith("http"):
                assert current is not None
                current["urls"].append(line)
            elif current is None and line.strip():
                header_lines.append(line)
        return {"first_line": lines[0], "header_lines": header_lines, "groups": groups, "raw": raw}

    return _parse


@pytest.fixture()
def grouped_150_plus_hk(make_channel):
    """150 条同分组（央视频道，非港台）+ 3 条港台频道。"""
    big = [
        make_channel(f"CCTV-5 体育 {i:03d}", url=f"http://example.invalid/cctv5_{i:03d}.m3u8")
        for i in range(150)
    ]
    hk = [
        make_channel(f"翡翠台 备用{i}", url=f"http://example.invalid/jade_{i}.m3u8")
        for i in range(1, 4)
    ]
    return {"📺 央视频道": big, "📺 TVB": hk}


# ──────────────────────────────────────────────────────────────
#  sort_key
# ──────────────────────────────────────────────────────────────
def test_sort_key_known_category_is_zero_prefixed_index():
    for cat in ["📺 央视频道", "📡 卫视频道", "📺 TVB", "📰 新闻财经"]:
        assert sort_key(cat) == (0, CATEGORY_ORDER.index(cat))


def test_sort_key_unknown_category_sorts_after_all_known_ones():
    unknown = "🆕 源码里没有的分组"
    assert sort_key(unknown) == (1, unknown)
    # 已知分组一律排在未知分组之前，即使未知分组名字更“靠前”
    assert max(sort_key(c) for c in CATEGORY_ORDER) < sort_key(unknown)
    mixed = ["🆕 未知", "📺 其他", "📺 央视频道"]
    assert sorted(mixed, key=sort_key) == ["📺 央视频道", "📺 其他", "🆕 未知"]


def test_sort_key_unknown_categories_sort_alphabetically_by_name():
    assert sorted(["🆕 b组", "🆕 a组"], key=sort_key) == ["🆕 a组", "🆕 b组"]


def test_sort_key_relative_order_matches_source_intent():
    """央视 → 地方(省) → 卫视 → 港台(TVB/台湾) → 类型(电影/新闻/其他)。"""
    yt = sort_key("📺 央视频道")
    local = sort_key("📺 北京")  # 省级/地方频道
    sat = sort_key("📡 卫视频道")
    hk = sort_key("📺 TVB")
    tw = sort_key("🇹🇼 台湾")
    movie = sort_key("🎬 电影频道")
    news = sort_key("📰 新闻财经")
    other = sort_key("📺 其他")

    assert yt < local < sat < hk < tw < movie < news < other


def test_sort_key_is_stable_across_all_declared_categories():
    keys = [sort_key(c) for c in CATEGORY_ORDER]
    assert keys == sorted(keys)  # CATEGORY_ORDER 自身就是升序的
    assert len(set(keys)) == len(keys)  # 无重复（index 唯一）


# ──────────────────────────────────────────────────────────────
#  is_clean_name
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "name",
    ["CCTV-1 综合", "翡翠台", "凤凰卫视资讯台", "RTHK 31", "测试频道 01", "HBO", "J2"],
)
def test_is_clean_name_accepts_normal_names(name):
    assert is_clean_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36",
        "Edge/18.1.2",
        "webkit",
        "Safari/605.1.15",
        "LikeGecko",
    ],
)
def test_is_clean_name_rejects_browser_noise(name):
    assert is_clean_name(name) is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "缺陷：DIRTY_PATTERNS 里的 'group-title=\"#EXTGRP' 含大写字母，而 is_clean_name 用 "
        "name.lower() 做子串比较，该规则永远不会命中（死规则）；源数据里残留的分组标记不会被拦下。"
    ),
)
def test_dirty_pattern_with_uppercase_is_not_dead():
    assert is_clean_name('group-title="#EXTGRP') is False


@pytest.mark.parametrize("name", ["", None, "A", "Z", "9"])
def test_is_clean_name_rejects_empty_none_and_too_short(name):
    assert is_clean_name(name) is False


@pytest.mark.parametrize(
    "name",
    ["http://cdn.example.com/logo.png", "see tvg-logo=http://x/y.jpg", "http://a/b.jpg channel"],
)
def test_is_clean_name_rejects_url_residue(name):
    assert is_clean_name(name) is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "缺陷：is_clean_name 只按 DIRTY_PATTERNS/URL 残留做黑名单，纯符号名（★★★ / *** / 【】）"
        "与纯空白名（'  '，len>=2 通过长度校验）都会被判定为 clean=True，"
        "脏数据会直接流进 m3u 输出。"
    ),
)
def test_is_clean_name_rejects_pure_symbol_and_whitespace_names():
    for name in ["★★★", "***", "!@#$%^&", "【】", "  "]:
        assert is_clean_name(name) is False, f"{name!r} 应当被判为脏名字"


# ──────────────────────────────────────────────────────────────
#  build_extinf
# ──────────────────────────────────────────────────────────────
def test_build_extinf_starts_with_extinf_and_carries_group_and_name(make_channel):
    line = build_extinf(make_channel("自制频道XYZ"), "📺 其他")
    assert line.startswith("#EXTINF:-1")
    assert 'group-title="📺 其他"' in line
    assert "自制频道XYZ" in line
    assert line.endswith(",自制频道XYZ")


def test_build_extinf_omits_logo_attribute_when_no_logo_is_known(make_channel):
    """logo 为空且 LOGO_MAP 查不到时，不应留下 tvg-logo="" 这种空属性。"""
    line = build_extinf(make_channel("自制频道XYZ", logo=""), "📺 其他")
    assert "tvg-logo" not in line
    assert 'tvg-logo=""' not in line


def test_build_extinf_falls_back_to_logo_map_when_channel_logo_missing(make_channel):
    """源码行为：logo 为空时会走 get_logo_fuzzy，已知频道仍会带上 logo。"""
    line = build_extinf(make_channel("翡翠台", logo=""), "📺 TVB")
    assert 'tvg-logo="https://epg.112114.xyz/logo/翡翠台.png"' in line


def test_build_extinf_keeps_explicit_logo(make_channel):
    line = build_extinf(make_channel("自制频道XYZ", logo="http://logo.example/x.png"), "📺 其他")
    assert 'tvg-logo="http://logo.example/x.png"' in line


def test_build_extinf_omits_group_attribute_when_group_empty(make_channel):
    line = build_extinf(make_channel("无分组频道Q"), "")
    assert line.startswith("#EXTINF:-1")
    assert "group-title" not in line
    assert line.endswith(",无分组频道Q")


# ──────────────────────────────────────────────────────────────
#  Generator.generate_hk_and_all
# ──────────────────────────────────────────────────────────────
def test_generate_creates_both_playlists(grouped_150_plus_hk, tmp_path):
    result = Generator().generate_hk_and_all(grouped_150_plus_hk, str(tmp_path))

    all_path = tmp_path / "all_merged.m3u"
    hk_path = tmp_path / "hk_merged.m3u"
    assert all_path.is_file()
    assert hk_path.is_file()
    assert Path(result["all"]["file"]) == all_path
    assert Path(result["hk"]["file"]) == hk_path


def test_generate_header_starts_with_extm3u(grouped_150_plus_hk, tmp_path, parse_playlist):
    Generator().generate_hk_and_all(grouped_150_plus_hk, str(tmp_path))
    for name in ("all_merged.m3u", "hk_merged.m3u"):
        parsed = parse_playlist(tmp_path / name)
        assert parsed["first_line"].startswith("#EXTM3U")
        assert any(line.startswith("#PLAYLIST:") for line in parsed["header_lines"])


def test_all_playlist_caps_each_group_at_100_entries(grouped_150_plus_hk, tmp_path, parse_playlist):
    Generator().generate_hk_and_all(grouped_150_plus_hk, str(tmp_path))
    parsed = parse_playlist(tmp_path / "all_merged.m3u")

    by_cat = {g["cat"]: g for g in parsed["groups"]}
    assert set(by_cat) == {"📺 央视频道", "📺 TVB"}

    big = by_cat["📺 央视频道"]
    assert len(big["extinf"]) == 100, "ALL 播放列表每个分组最多写 100 条 EXTINF"
    assert len(big["urls"]) == 100
    assert big["extra"] == ["# ... and 50 more"], "超额必须留一行 and N more 标记"

    small = by_cat["📺 TVB"]
    assert len(small["extinf"]) == 3
    assert small["extra"] == []


def test_extgrp_count_is_pretruncation_total(grouped_150_plus_hk, tmp_path, parse_playlist):
    """#EXTGRP:名称 (N) 的 N 是截断前的总数，不是实际写入的 EXTINF 条数。"""
    Generator().generate_hk_and_all(grouped_150_plus_hk, str(tmp_path))
    parsed = parse_playlist(tmp_path / "all_merged.m3u")
    big = next(g for g in parsed["groups"] if g["cat"] == "📺 央视频道")

    assert big["declared"] == 150
    assert len(big["extinf"]) == 100
    assert big["declared"] != len(big["extinf"])


def test_hk_playlist_is_not_truncated(make_channel, tmp_path, parse_playlist):
    """HK 列表没有 100 上限（源码只对 ALL 做 channels[:100]）——这是刻意的不对称。"""
    grouped = {
        "📺 TVB": [make_channel(f"翡翠台 {i:03d}", url=f"http://example.invalid/j{i}.m3u8") for i in range(150)]
    }
    Generator().generate_hk_and_all(grouped, str(tmp_path))
    parsed = parse_playlist(tmp_path / "hk_merged.m3u")

    (group,) = parsed["groups"]
    assert group["declared"] == 150
    assert len(group["extinf"]) == 150
    assert group["extra"] == []


def test_generate_summary_counts(grouped_150_plus_hk, tmp_path):
    result = Generator().generate_hk_and_all(grouped_150_plus_hk, str(tmp_path))
    assert result["all"]["channels"] == 153
    assert result["all"]["groups"] == 2
    assert result["hk"]["channels"] == 3
    assert result["hk"]["groups"] == 1


def test_dirty_channel_names_are_dropped_from_both_playlists(make_channel, tmp_path, parse_playlist):
    dirty = "Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36"
    grouped = {
        "📺 央视频道": [make_channel("CCTV-1 综合"), make_channel(dirty)],
        "📺 TVB": [make_channel("翡翠台"), make_channel("Edge/18.1")],
    }
    result = Generator().generate_hk_and_all(grouped, str(tmp_path))

    assert result["all"]["channels"] == 2
    assert result["hk"]["channels"] == 1
    for name in ("all_merged.m3u", "hk_merged.m3u"):
        raw = (tmp_path / name).read_text(encoding="utf-8")
        assert dirty not in raw
        assert "Edge/18.1" not in raw


def test_generate_orders_groups_by_sort_key(make_channel, tmp_path, parse_playlist):
    grouped = {
        "📺 其他": [make_channel("自制频道AAA")],
        "📺 央视频道": [make_channel("CCTV-1 综合")],
        "📡 卫视频道": [make_channel("凤凰卫视资讯台")],
    }
    Generator().generate_hk_and_all(grouped, str(tmp_path))
    parsed = parse_playlist(tmp_path / "all_merged.m3u")
    assert [g["cat"] for g in parsed["groups"]] == ["📺 央视频道", "📡 卫视频道", "📺 其他"]


def test_generate_creates_output_dir(make_channel, tmp_path):
    target = tmp_path / "nested" / "out"
    Generator().generate_hk_and_all({"📺 央视频道": [make_channel("CCTV-1 综合")]}, str(target))
    assert (target / "all_merged.m3u").is_file()
    assert (target / "hk_merged.m3u").is_file()
