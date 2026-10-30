"""tests/test_normalize_dedup.py

离线回归：`src/group/normalize.py` 的繁简转换从「词组表」升级为「词组表 + 单字兜底」，
以及产物里的同台重复是否会因此减少、会不会把不同台误并成一台。

零网络、零外部依赖（不 import opencc，不发请求）；只读仓库里的
`output/*.m3u` 作为真实语料。
"""
import collections
import itertools
import pathlib
import re
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.group.normalize import (  # noqa: E402
    _TC_CHAR_SC,
    _TC_CHAR_TC,
    _TC_REPLACEMENTS,
    convert_tc_to_sc,
    normalize_channel_name,
)

ALIAS_FILE = _REPO / "config" / "alias.txt"
# 语料用**冻结的 fixture**，不要读 output/*.m3u。
# 教训：这套测试最初直接读 `output/hk_merged.m3u`，而产物每天会被流水线重生成
# （频道名在产物里已经是归一化后的样子、同台重复已经被合并掉）。一旦重生成，
# 「残留重复组数必须下降」的前提就消失了：old 和 new 都是 0，`0 < 0` 直接断言失败。
# 冻结成文件后，迁移前后对比始终跑在同一份真实语料上。
FIXTURES = _REPO / "tests" / "fixtures"
HK_NAMES_FILE = FIXTURES / "hk_channel_names_2026-10-30.txt"
ALL_NAMES_FILE = FIXTURES / "all_channel_names_2026-10-30.txt"

# 仍然保留活体产物路径，用于「当前产物没有残留重复」这条独立断言
HK_M3U = _REPO / "output" / "hk_merged.m3u"
ALL_M3U = _REPO / "output" / "all_merged.m3u"


# ──────────────────────────────────────────────────────────────
#  旧行为（基线）：只有词组表，没有单字兜底
# ──────────────────────────────────────────────────────────────
def _convert_old(text: str) -> str:
    """HEAD 版 convert_tc_to_sc 的等价实现：只跑词组表。"""
    for tc, sc in _TC_REPLACEMENTS:
        text = text.replace(tc, sc)
    return text


# 我在 config/alias.txt 里**新增**的条目（HEAD 里没有）。基线对比时要把它们摘掉，
# 否则「旧行为」会被新别名污染，测不出代码改动的效果。
_ALIASES_ADDED_BY_THIS_FIX = {"大爱二台", "TVBS新闻台", "三立台湾台"}


def _load_aliases(path: pathlib.Path | None = None, head: bool = False) -> dict:
    d = {}
    for line in (path or ALIAS_FILE).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sep = "->" if "->" in line else "="
        if sep not in line:
            continue
        k, _, v = line.partition(sep)
        if head and k.strip() in _ALIASES_ADDED_BY_THIS_FIX:
            continue
        d[k.strip()] = v.strip()
    return d


def _normalize_old(raw: str, aliases: dict) -> str:
    """HEAD 版归一化：词组表繁简 + 别名精确/大小写匹配（不含子串分支，基线够用）。"""
    from src.group.normalize import strip_noise

    t = _convert_old(strip_noise(raw)).strip()
    if t in aliases:
        return aliases[t]
    low = t.lower()
    for a, c in aliases.items():
        if a.lower() == low:
            return c
    return t


# ──────────────────────────────────────────────────────────────
#  「同一台」判定口径（口径 B）：去空格 + 去尾部「台/臺」+ 中文数字折叠为阿拉伯数字
#  这是**比较用**的口径，不参与产物命名，只用来数「产物里还有几组同名台」。
# ──────────────────────────────────────────────────────────────
_CN_DIGITS = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}


def dedupe_key(name: str) -> str:
    n = name.replace(" ", "")
    n = re.sub(r"[台臺]$", "", n)
    if n and n[-1] in _CN_DIGITS:
        n = n[:-1] + _CN_DIGITS[n[-1]]
    return n


def residual_dup_groups(names, normalizer):
    """返回 {dedupe_key: [归一化名...]}，只保留归一化后仍然 >1 条的分组。

    >1 条 = 产物里仍会出现两条同台不同名的条目。
    """
    groups = collections.defaultdict(set)
    for raw in names:
        n = normalizer(raw)
        groups[dedupe_key(n)].add(n)
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def merge_pairs(names, normalizer):
    """在 dedupe_key 口径下“被判为同一台”的原始名对集合。"""
    groups = collections.defaultdict(set)
    for raw in names:
        groups[dedupe_key(normalizer(raw))].add(raw)
    return {
        (a, b)
        for v in groups.values()
        for a, b in itertools.combinations(sorted(v), 2)
    }


def _corpus():
    """冻结 fixture（真实产物快照）里的频道名，作为回归语料。"""
    names = []
    for p in (HK_NAMES_FILE, ALL_NAMES_FILE):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                names.append(line)
    return names


CORPUS = _corpus()
needs_corpus = pytest.mark.skipif(
    not CORPUS, reason="output/*.m3u 尚未生成，跳过真实语料回归"
)


# ──────────────────────────────────────────────────────────────
#  1. 单字兜底：三个原本转不了的繁体字
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 缺陷 1 的四个实测样本（灣 / 門 / 麗 三个字不在任何词组里）
        ("華麗翡翠台", "华丽翡翠台"),
        ("三立台灣台", "三立台湾台"),
        ("澳视澳門", "澳视澳门"),
        ("澳视衛星", "澳视卫星"),
        # 单字兜底顺带覆盖的其它语料字
        ("有線電視財經資訊台", "有线电视财经资讯台"),
        ("中天綜合", "中天综合"),
    ],
)
def test_char_fallback_converts_chars_missing_from_phrase_table(raw, expected):
    assert convert_tc_to_sc(raw) == expected


def test_the_three_missing_chars_were_really_unreachable_before():
    """证明这是结构性问题而不是手抖：舊逻辑对这三个字完全无能为力。"""
    for name in ("華麗翡翠台", "三立台灣台", "澳视澳門", "澳视衛星"):
        assert _convert_old(name) == name, "旧逻辑本应原样返回，否则本用例的前提不成立"
    assert convert_tc_to_sc("灣門麗") == "湾门丽"


# ──────────────────────────────────────────────────────────────
#  2. 词组级替换不许退化（单字兜底不能拆坏已写死的整词）
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("華視", "华视"),
        ("衛視", "卫视"),
        ("鳳凰衛視", "凤凰卫视"),
        ("東森新聞", "东森新闻"),
        ("音樂頻道", "音乐频道"),
        ("無綫電視", "无线电视"),
        ("澳廣視", "澳广视"),
        # 语义型整词：法制→法治 绝不能拆成 制→治
        ("法制頻道", "法治频道"),
    ],
)
def test_phrase_level_replacement_still_wins(raw, expected):
    assert convert_tc_to_sc(raw) == expected


def test_char_table_shape():
    assert len(_TC_CHAR_TC) == len(_TC_CHAR_SC)
    pairs = dict(zip(_TC_CHAR_TC, _TC_CHAR_SC))
    assert pairs["灣"] == "湾" and pairs["門"] == "门" and pairs["麗"] == "丽"
    # 每个繁体字都必须真的变成别的字（写成 t->t 就是死条目）
    assert all(tc != sc for tc, sc in pairs.items())
    # 简化结果不许再是繁体字本身（否则需要多跑一遍，说明表里有链）
    assert not (set(_TC_CHAR_SC) & set(_TC_CHAR_TC)), (
        "单字表里出现了 A→B 且 B 又要继续转换的链"
    )
    # 转换必须幂等
    for tc in _TC_CHAR_TC:
        assert convert_tc_to_sc(convert_tc_to_sc(tc)) == convert_tc_to_sc(tc)


def test_char_fallback_does_not_touch_latin_or_simplified():
    for name in ("CCTV-5 体育", "TVB 翡翠台", "RTHK 31", "HBO", "PTS3"):
        assert convert_tc_to_sc(name) == name


# ──────────────────────────────────────────────────────────────
#  3. 真实语料回归：重复组数前 -> 后，且不许误并
# ──────────────────────────────────────────────────────────────
@needs_corpus
def test_residual_duplicate_groups_shrink_on_the_hk_playlist():
    hk = [line.strip()
          for line in HK_NAMES_FILE.read_text(encoding="utf-8").splitlines()
          if line.strip()]
    head_aliases = _load_aliases(head=True)
    aliases = _load_aliases()

    old = residual_dup_groups(hk, lambda r: _normalize_old(r, head_aliases))
    new = residual_dup_groups(hk, lambda r: normalize_channel_name(r, aliases))

    # 口径 B：81 条 hk 里，「同台不同名」的残留组数必须下降
    assert len(old) > 0, f"冻结语料本身没有残留重复，测试前提失效：{old}"
    assert len(new) < len(old), f"重复组数没有下降：old={old} new={new}"
    assert len(new) == 0, f"仍残留同台重复：{new}"
    # 三立这一组就是 灣 没被转换造成的，修好之后必须消失
    assert "三立台湾" not in new


def test_current_hk_product_has_no_residual_duplicates():
    """活体产物检查：当前 output/hk_merged.m3u 里不该有「同台不同名」的残留。

    这条与上面的迁移断言分开：产物每天重生成，只断言**结果**（残留为 0），
    不断言「比起旧版下降」——后者依赖产物里还留着未归一化的名字，会随重生成失效。
    """
    if not HK_M3U.exists():
        pytest.skip("output/hk_merged.m3u 不存在")
    hk = [line.split(",", 1)[1].strip()
          for line in HK_M3U.read_text(encoding="utf-8").splitlines()
          if line.startswith("#EXTINF") and "," in line]
    if not hk:
        pytest.skip("hk_merged.m3u 为空")
    aliases = _load_aliases()
    new = residual_dup_groups(hk, lambda r: normalize_channel_name(r, aliases))
    assert not new, f"当前产物仍残留同台重复：{new}"


@needs_corpus
def test_new_merge_decisions_are_a_superset_of_the_old_ones():
    """新的正例集合 ⊇ 旧的正例集合：改动不许让原本能合并的条目漏掉。"""
    head_aliases = _load_aliases(head=True)
    aliases = _load_aliases()
    old_pos = merge_pairs(CORPUS, lambda r: _normalize_old(r, head_aliases))
    new_pos = merge_pairs(CORPUS, lambda r: normalize_channel_name(r, aliases))

    lost = old_pos - new_pos
    assert not lost, f"改动让原本能合并的条目变得合不上了：{sorted(lost)}"
    assert old_pos <= new_pos


# ──────────────────────────────────────────────────────────────
#  4b. 子串别名只做一次替换 —— 用精确别名绕过（有线新闻台）
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 繁体源里是「有線新聞台」（不含「电视」二字）
        ("有線新聞台", "有线电视新闻"),
        ("有线新闻台", "有线电视新闻"),
        # 已有的那条（含「电视」）必须继续生效，不能被新条盖掉
        ("有线电视新闻台", "有线电视新闻"),
        # 已经是目标名的保持不动
        ("有线电视新闻", "有线电视新闻"),
    ],
)
def test_cable_news_alias_is_reached(raw, expected):
    """`有线 -> 有线电视` 是子串别名，会把「有线新闻台」改写成「有线电视新闻台」，
    而 `normalize_channel_name` 的别名替换**只做一次就 return**，
    所以 `有线电视新闻台 -> 有线电视新闻` 这条永远轮不到，
    结果是产物里「有线电视新闻」和「有线电视新闻台」并存。
    修法是补一条精确别名 `有线新闻台 -> 有线电视新闻`（精确匹配优先于子串匹配）。
    """
    aliases = _load_aliases()
    assert normalize_channel_name(raw, aliases) == expected


def test_cable_news_alias_entry_exists():
    """锁住那条精确别名：别在清理 alias.txt 时把它当冗余删掉。"""
    aliases = _load_aliases()
    assert aliases.get("有线新闻台") == "有线电视新闻"


def test_chained_alias_is_a_known_limitation():
    """记录仍存在的限制：别名替换是单趟的，链式映射不会自动解析。

    为什么不用「循环到不动点」来根治：实测 16371 个真实频道名里有 20 个会变，
    其中至少 6 个是**错的**、会误并不同台：
        [BD]cctv-8k  ->  CCTV  ->  CCTV-4K
        北京4K超清    ->  北京4K  ->  北京
        Capital TV HD HD -> CapitalTVHD -> CapitalTV
    所以链式归一必须做得很窄，现阶段用「补精确别名」逐例解决。
    """
    aliases = _load_aliases()
    # 靠精确别名解决了「有线」这一族
    assert normalize_channel_name("有線新聞台", aliases) == "有线电视新闻"
    # 反例：链式会产生错误合并，这里断言它**没有**发生
    assert normalize_channel_name("北京4K超清", aliases) != "北京"
    assert normalize_channel_name("[BD]cctv-8k", aliases) != "CCTV-4K"


@needs_corpus
def test_no_different_channels_are_merged_by_the_char_table():
    """安全网：新增的合并判定只能是「同一个台的不同字形写法」。

    判据（比白名单更强）：一对名字被判成同一台，当且仅当把它们各自做繁简转换、
    去掉空格之后**完全相等**——即差异纯粹来自字形/空格。任何靠别的字（数字、
    频道序号、地区词）造成的合并都算误并。
    """
    head_aliases = _load_aliases(head=True)
    aliases = _load_aliases()
    old_pos = merge_pairs(CORPUS, lambda r: _normalize_old(r, head_aliases))
    new_pos = merge_pairs(CORPUS, lambda r: normalize_channel_name(r, aliases))

    def same_after_script_fold(a: str, b: str) -> bool:
        fa = convert_tc_to_sc(a).replace(" ", "")
        fb = convert_tc_to_sc(b).replace(" ", "")
        return fa == fb

    unexpected = [
        p for p in sorted(new_pos - old_pos) if not same_after_script_fold(*p)
    ]
    assert not unexpected, f"单字兜底把不同台误并了：{unexpected}"


@needs_corpus
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("東森美洲", "東森美洲衛視"),      # 主频 vs 卫视频道
        ("TVBS", "TVBS 亚洲台"),
        ("大爱", "大爱1台"),
        ("大爱1台", "大爱2"),              # 一台 vs 二台
        ("中视", "中视新闻"),
        ("三立", "三立新闻"),
        ("民视", "民视台湾台"),
        ("PTS", "PTS3"),
    ],
)
def test_similar_looking_channels_stay_distinct(a, b):
    aliases = _load_aliases()
    assert dedupe_key(normalize_channel_name(a, aliases)) != dedupe_key(
        normalize_channel_name(b, aliases)
    ), f"{a!r} 与 {b!r} 是不同的台，被误并成一台了"


@needs_corpus
def test_each_char_in_the_fallback_table_is_safe_against_the_corpus():
    """逐字安全网：单独打开某一个字，不许让两条不同的归一化名撞成同一个。"""
    aliases = _load_aliases()
    old_names = {r: _normalize_old(r, aliases) for r in CORPUS}
    old_values = set(old_names.values())

    offenders = []
    for tc, sc in zip(_TC_CHAR_TC, _TC_CHAR_SC):
        for raw, old_norm in old_names.items():
            if tc not in old_norm:
                continue
            new_norm = old_norm.replace(tc, sc)
            if new_norm != old_norm and new_norm in old_values:
                offenders.append((tc, raw, old_norm, new_norm))

    # 唯一允许的撞名就是 灣→湾 让「三立台灣台」落到「三立台湾台」上
    unexpected = [o for o in offenders if o[0] != "灣"]
    assert not unexpected, f"这些单字会让不同频道撞名：{unexpected}"
