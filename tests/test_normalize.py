"""tests/test_normalize.py

离线测试 `src.group.normalize`：名称清洗、繁简转换、别名应用、URL 优先级、
同名合并去重。

设计约束：
- 纯函数 + 内存 dict 数据，无网络、无文件。
- fixture 全部内联；不依赖 conftest.py / pytest.ini。
- 断言以源码实际行为为准；确认是缺陷的用 xfail(strict=True) 登记（见文件末尾）。
"""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.group.normalize import (  # noqa: E402
    convert_tc_to_sc,
    get_url_priority,
    merge_duplicate_channels,
    normalize_channel_name,
    normalize_channels,
    strip_noise,
)


# ──────────────────────────────────────────────────────────────
#  fixture（内联）
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def no_aliases():
    """空别名表：把 strip_noise/繁简的行为从 alias.txt 内容里隔离出来。"""
    return {}


@pytest.fixture()
def make_entry():
    """构造 normalize 系列函数吃的 dict 条目。"""

    def _make(name, url, normalized=None, **extra):
        entry = {"name": name, "url": url, "logo": "", "group": ""}
        if normalized is not None:
            entry["_normalized_name"] = normalized
        entry.update(extra)
        return entry

    return _make


# ──────────────────────────────────────────────────────────────
#  strip_noise：分辨率 / 高清 / 括号 / 线路 / 随机后缀
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("翡翠台 HD", "翡翠台"),
        ("翡翠台 FHD", "翡翠台"),
        ("翡翠台 4K", "翡翠台"),
        ("翡翠台 UHD", "翡翠台"),
        ("翡翠台 1080P", "翡翠台"),
        ("翡翠台 720p", "翡翠台"),
        ("CCTV-5 高清", "CCTV-5"),
        ("CCTV1 4K", "CCTV1"),
        ("CCTV1-超清", "CCTV1"),
        ("频道名称（高清）", "频道名称"),
        ("凤凰卫视（香港线路）", "凤凰卫视"),
        ("凤凰卫视 - 线路1（大陆线路）", "凤凰卫视"),
        ("CCTV5（1080P）", "CCTV5"),
        ("TVB翡翠台*28", "TVB翡翠台"),
        ("J2 backup", "J2"),
        ("tvb jade Backup", "tvbjade"),
    ],
)
def test_strip_noise_removes_resolution_and_route_markers(raw, expected):
    assert strip_noise(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TVB 翡翠台 [HD]", "TVB翡翠台"),
        ("【蓝光1】凤凰卫视", "凤凰卫视"),
        ("  BBC World   News  ", "BBCWorldNews"),
        ("\t凤凰卫视\t", "凤凰卫视"),
    ],
)
def test_strip_noise_removes_brackets_and_collapses_spaces(raw, expected):
    """注意：源码把所有空白全部删掉（不只是合并），因此 'TVB 翡翠台' → 'TVB翡翠台'。"""
    assert strip_noise(raw) == expected


def test_strip_noise_is_idempotent_on_clean_names():
    assert strip_noise("翡翠台") == "翡翠台"
    assert strip_noise(strip_noise("翡翠台 HD")) == "翡翠台"


# ──────────────────────────────────────────────────────────────
#  繁简转换 + 名称归一化
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("東森新聞", "东森新闻"),
        ("鳳凰衛視", "凤凰卫视"),
        ("翡翠台", "翡翠台"),  # 已经是简体
        ("音樂頻道", "音乐频道"),
    ],
)
def test_convert_tc_to_sc(raw, expected):
    assert convert_tc_to_sc(raw) == expected


def test_normalize_empty_and_blank_returns_input_untouched(no_aliases):
    assert normalize_channel_name("", no_aliases) == ""
    assert normalize_channel_name("   ", no_aliases) == ""


def test_normalize_strips_noise_and_converts(no_aliases):
    assert normalize_channel_name("東森新聞 HD", no_aliases) == "东森新闻"
    assert normalize_channel_name("翡翠台 HD", no_aliases) == "翡翠台"


def test_normalize_special_mapping_for_rthk(no_aliases):
    assert normalize_channel_name("港台电视31", no_aliases) == "RTHK 31"


def test_normalize_applies_exact_alias():
    aliases = {"翡翠台": "TVB 翡翠台"}
    assert normalize_channel_name("翡翠台", aliases) == "TVB 翡翠台"


def test_normalize_applies_alias_after_noise_stripping():
    aliases = {"凤凰资讯": "凤凰资讯台"}
    assert normalize_channel_name("凤凰资讯 HD", aliases) == "凤凰资讯台"


def test_normalize_applies_alias_case_insensitively():
    aliases = {"jade": "TVB 翡翠台"}
    assert normalize_channel_name("JADE", aliases) == "TVB 翡翠台"


def test_space_removal_merges_raw_names_that_differ_only_by_spaces(no_aliases):
    """现象登记：所有空格被删除，因此 '翡翠 台' 与 '翡翠台' 归一化成同一个名字。

    对“同一台的不同写法”这是想要的去重效果，但它同时意味着任何仅靠空格区分的
    两个名字都会撞名（源码没有保留分隔符）。
    """
    assert normalize_channel_name("翡翠 台", no_aliases) == "翡翠台"
    assert normalize_channel_name("翡翠台", no_aliases) == "翡翠台"
    assert normalize_channel_name("TVB J2", no_aliases) == "TVBJ2"


# ──────────────────────────────────────────────────────────────
#  URL 优先级
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://hkdtmb.com/live/1.m3u8", 1),
        ("http://viutv.com/x.m3u8", 1),
        ("http://115.238.1.1/x.m3u8", 1),
        ("https://jdshipin.com/x.m3u8", 2),
        ("https://163189.xyz/x.m3u8", 2),
        ("https://example.invalid/x.m3u8", 3),
        ("", 3),
    ],
)
def test_get_url_priority(url, expected):
    assert get_url_priority(url) == expected


# ──────────────────────────────────────────────────────────────
#  合并去重
# ──────────────────────────────────────────────────────────────
def test_merge_same_name_different_urls_keeps_best_url_and_backups(make_entry):
    # 用同一 _normalized_name 模拟“不同原始写法已被归一化成同名”
    merged = merge_duplicate_channels(
        [
            make_entry("翡翠台", "https://example.invalid/a.m3u8", "翡翠台"),
            make_entry("翡翠台 HD", "http://hkdtmb.com/b.m3u8", "翡翠台"),
            make_entry("翡翠台 备用", "https://jdshipin.com/c.m3u8", "翡翠台"),
        ]
    )
    assert len(merged) == 1
    (entry,) = merged
    assert entry["name"] == "翡翠台"
    assert entry["tvg_name"] == "翡翠台"
    # HK CDN(优先级 1) 胜出
    assert entry["url"] == "http://hkdtmb.com/b.m3u8"
    # 两个备用按优先级排列
    assert entry["_backup_urls"] == [
        "https://jdshipin.com/c.m3u8",
        "https://example.invalid/a.m3u8",
    ]


def test_merge_same_url_same_name_is_deduplicated(make_entry):
    merged = merge_duplicate_channels(
        [
            make_entry("翡翠台", "http://example.invalid/a.m3u8", "翡翠台"),
            make_entry("翡翠台", "http://example.invalid/a.m3u8", "翡翠台"),
        ]
    )
    assert len(merged) == 1
    assert merged[0]["_backup_urls"] == []


def test_merge_same_url_different_names_keeps_both_entries(make_entry):
    """源码只按 _normalized_name 分组，不按 URL 去重：同 URL 不同名会保留两条。"""
    merged = merge_duplicate_channels(
        [
            make_entry("A台", "http://example.invalid/same.m3u8", "A台"),
            make_entry("B台", "http://example.invalid/same.m3u8", "B台"),
        ]
    )
    assert [e["name"] for e in merged] == ["A台", "B台"]
    assert [e["url"] for e in merged] == [
        "http://example.invalid/same.m3u8",
        "http://example.invalid/same.m3u8",
    ]


def test_merge_caps_backup_urls_at_two(make_entry):
    urls = [f"https://example.invalid/{i}.m3u8" for i in range(5)]
    merged = merge_duplicate_channels([make_entry("翡翠台", u, "翡翠台") for u in urls])
    assert len(merged) == 1
    assert len(merged[0]["_backup_urls"]) == 2


def test_merge_drops_entries_without_normalized_name(make_entry):
    """没有 _normalized_name 的条目会被静默丢弃（空名 = 未归一化）。"""
    merged = merge_duplicate_channels(
        [
            make_entry("翡翠台", "http://example.invalid/a.m3u8"),
            make_entry("明珠台", "http://example.invalid/b.m3u8", "明珠台"),
        ]
    )
    assert [e["name"] for e in merged] == ["明珠台"]


def test_normalize_channels_computes_name_then_merges(make_entry):
    out = normalize_channels(
        [
            make_entry("翡翠台 HD", "http://example.invalid/a.m3u8"),
            make_entry("翡翠台", "http://hkdtmb.com/b.m3u8"),
        ],
        {},
    )
    assert len(out) == 1
    assert out[0]["name"] == "翡翠台"
    assert out[0]["url"] == "http://hkdtmb.com/b.m3u8"
    assert out[0]["_backup_urls"] == ["http://example.invalid/a.m3u8"]


def test_normalize_channels_prefers_tvg_name_over_name(make_entry):
    out = normalize_channels([make_entry("显示名", "http://example.invalid/a.m3u8", tvg_name="翡翠台 HD")], {})
    assert out[0]["name"] == "翡翠台"


def test_normalize_channels_keeps_preexisting_normalized_name(make_entry):
    """已带 _normalized_name 的条目不会被重算（保留上游给定值）。"""
    out = normalize_channels([make_entry("脏名字 (Chrome/1.0)", "http://example.invalid/a.m3u8", "已归一化")], {})
    assert [e["name"] for e in out] == ["已归一化"]


# ──────────────────────────────────────────────────────────────
#  已确认的缺陷（xfail strict）
# ──────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason=(
        "缺陷：尾部模式里有 '超清|高清' 但没有 '超高清'，'CCTV 超高清' 被削掉 '高清' 后"
        "留下悬空的 '超' → 'CCTV超'，有意义的信息被吃掉且产生不存在于任何源的频道名。"
    ),
)
def test_ultra_hd_suffix_does_not_leave_dangling_char(no_aliases):
    assert normalize_channel_name("CCTV 超高清", no_aliases) == "CCTV超高清"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "缺陷：'CCTV-8K' 先去噪声变成 'CCTV'（4K 被当分辨率删掉），再命中 "
        "_SPECIAL_MAPPING['CCTV'] = 'CCTV-4K'，于是 8K 频道被改名成 4K 频道。"
    ),
)
def test_8k_channel_is_not_rewritten_to_4k(no_aliases):
    assert normalize_channel_name("CCTV-8K", no_aliases) == "CCTV-8K"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "缺陷：_SPECIAL_MAPPING 的键 'CCTV-6 电影电影' 带空格，但 strip_noise 已在别名查表前"
        "删掉所有空格，该键永远不可能命中 → 重复词 '电影电影' 从未被清理（死代码）。"
    ),
)
def test_duplicate_word_special_mapping_actually_fires(no_aliases):
    assert normalize_channel_name("CCTV-6 电影电影", no_aliases) == "CCTV-6电影"
