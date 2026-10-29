"""`config/alias.txt` 的「X 与 X台 是同一频道」契约。

背景：2026-10-29 把 6 个新源入库后，`hk_merged.m3u` 里出现 31 组近似重名，
其中 25 个纯粹是尾部多/少一个「台」（`东森新闻` / `东森新闻台`）。中文频道名的
「台」是通用后缀，不统一就会在产物里出现两条同名频道。

这些用例钉住两件事：
1. 该合的必须合（`东森新闻台` → `东森新闻`）；
2. 不该合的**不许**合（`PTS` vs `PTS3`、`澳门有线CH1` vs `CH3`、`HOY TV` vs `HOY77台TV`
   是真的不同频道，别为了减少重复用户把不同频道并掉）。
"""
from pathlib import Path

import pytest
from src.group.normalize import merge_duplicate_channels, normalize_channel_name
from src.grouper import Grouper

ALIAS_FILE = Path(__file__).resolve().parent.parent / "config" / "alias.txt"


@pytest.fixture(scope="module")
def aliases() -> dict:
    return Grouper()._load_aliases()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 东森系列
        ("东森新闻台", "东森新闻"),
        # 繁体也应命中（顺序：strip_noise → 繁简 → alias）
        ("東森新聞台", "东森新闻"),
        ("东森综合台", "东森综合"),
        ("东森幼幼台", "东森幼幼"),
        # 三立系列
        ("三立新闻台", "三立新闻"),
        ("三立都会台", "三立都会"),
        ("三立戏剧台", "三立戏剧"),
        # 中天 / 中视 / 台视 / 民视
        ("中天新闻台", "中天新闻"),
        ("中天娱乐台", "中天娱乐"),
        ("中视菁采台", "中视菁采"),
        ("台视新闻台", "台视新闻"),
        ("民视新闻台", "民视新闻"),
        # 香港
        ("无线新闻台", "无线新闻"),
        ("有线电视新闻台", "有线电视新闻"),
        # RTHK 三种写法收敛到一个
        ("RTHK31", "RTHK 31"),
        ("RTHKTV31", "RTHK 31"),
        ("港台电视31", "RTHK 31"),
        # 大小写
        ("ftv", "FTV"),
    ],
)
def test_trailing_tai_is_merged(aliases, raw, expected):
    assert normalize_channel_name(raw, aliases) == expected, (
        f"{raw!r} 应规范化为 {expected!r}，否则产物里会出现两条同名频道"
    )


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("PTS", "PTS3"),                  # 公视 vs 公视3台
        ("HOY TV", "HOY77台TV"),           # 主频 vs 77 台写法
        ("澳门有线CH1", "澳门有线CH3"),
        ("Viu6", "ViuTV"),
        ("TVB J2", "TVBJ1"),
        ("大爱1台", "大爱2"),               # 大爱一台 vs 二台
    ],
)
def test_distinct_channels_are_not_merged(aliases, a, b):
    """防过度合并：这些名字去掉尾部「台」后仍有差异，或本来就是不同频道。"""
    assert normalize_channel_name(a, aliases) != normalize_channel_name(b, aliases), (
        f"{a!r} 与 {b!r} 是不同频道，不该被合并"
    )


def test_alias_file_has_no_duplicate_keys_with_conflicting_targets():
    keys: dict[str, str] = {}
    conflicts = []
    for line in ALIAS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sep = "->" if "->" in line else "="
        if sep not in line:
            continue
        k, _, v = line.partition(sep)
        k, v = k.strip(), v.strip()
        if k in keys and keys[k] != v:
            conflicts.append((k, keys[k], v))
        keys[k] = v
    assert not conflicts, f"alias.txt 里同一个原名映射到两个不同目标：{conflicts}"


def test_merge_collapses_tai_variants(aliases):
    """端到端：同名（合并后）只留一条 + 最多 2 个备用 URL。"""
    names = ["东森新闻", "东森新闻台", "東森新聞台"]
    chans = []
    for i, n in enumerate(names):
        chans.append(
            {
                "name": n,
                "url": f"https://example.com/{i}.m3u8",
                "_normalized_name": normalize_channel_name(n, aliases),
            }
        )
    merged = merge_duplicate_channels(chans)
    assert len(merged) == 1, f"三条应合并成 1 条，实际 {len(merged)} 条"
    assert len(merged[0]["_backup_urls"]) == 2
