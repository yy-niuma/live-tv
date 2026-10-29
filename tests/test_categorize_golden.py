"""分类器 golden 表：把「当前代码在真实频道名上的行为」钉住，作为重构护栏。

表的来源：
  1. 每条期望值都是先用真实代码跑出来的（见 reports/ 与提交说明中的原始输出），
     不是照抄注释/文档。
  2. 跑完后逐条人工判断「这个输出合理吗」：
     - 合理 → 写进本文件做硬断言；
     - 明显不合理/自相矛盾 → 不写进本文件，改放 tests/test_known_defects.py 用 xfail 登记。
  3. 因此本文件全绿 == 分类行为没有被（无意）改变；单条失败就是行为变更告警。

每行断言两件事：
  - categorize(name, group) 返回的 group
  - is_hk_region(name, group, cat) 的布尔值（调用关系与 src/generator.py 生产路径一致）
"""
import re
from collections import Counter

import pytest

from src.generator import CATEGORY_ORDER

# ---------------------------------------------------------------- 表构造
# pytest 会把非 ASCII 的 id 转义成 \uXXXX（失败列表里完全不可读），
# 所以 id 用「分组 slug + 序号 + 名字里的 ASCII 片段」，原始中文名仍作为参数
# 出现在断言消息里，失败时两者都能看到。
_GROUP_SLUG = {
    "📺 TVB": "tvb",
    "📺 ViuTV": "viutv",
    "📺 RTHK": "rthk",
    "📺 HOY TV": "hoy",
    "📺 Now TV": "now",
    "📺 有线电视": "cable",
    "📡 卫视频道": "sat",
    "🇲🇴 澳门": "mo",
    "🇹🇼 台湾": "tw",
    "📺 央视频道": "cctv",
    "📺 北京": "bj", "📺 上海": "sh", "📺 广东": "gd", "📺 深圳": "sz",
    "📺 浙江": "zj", "📺 江苏": "js", "📺 湖南": "hn", "📺 安徽": "ah",
    "📺 山东": "sd", "📺 四川": "sc", "📺 湖北": "hub", "📺 福建": "fj",
    "📺 陕西": "shx", "📺 黑龙江": "hlj", "📺 吉林": "jl", "📺 辽宁": "ln",
    "📺 河北": "heb", "📺 河南": "hen", "📺 江西": "jx", "📺 山西": "sxi",
    "📺 内蒙古": "nmg", "📺 宁夏": "nx", "📺 青海": "qh", "📺 甘肃": "gs",
    "📺 新疆": "xj", "📺 西藏": "xz", "📺 贵州": "gz", "📺 云南": "yn",
    "📺 广西": "gx", "📺 海南": "hai", "📺 重庆": "cq", "📺 天津": "tj",
    "⚽ 体育频道": "sports",
    "🎬 电影频道": "movie",
    "🎵 音乐频道": "music",
    "📰 新闻财经": "news",
    "🧸 儿童频道": "kids",
    "📺 纪录片": "doc",
    "🎭 综艺频道": "variety",
    "🌐 国际频道": "intl",
}

_SEEN: Counter = Counter()


def _case(name: str, expected_group: str, expected_hk: bool, group: str = ""):
    """一条 golden case（id 形如 tw-03-tvbs-asia）。"""
    slug = _GROUP_SLUG[expected_group]
    _SEEN[slug] += 1
    ascii_hint = re.sub(r"[^A-Za-z0-9+]+", "-", name).strip("-").lower()
    case_id = f"{slug}-{_SEEN[slug]:02d}"
    if ascii_hint:
        case_id += f"-{ascii_hint}"
    return pytest.param(name, group, expected_group, expected_hk, id=case_id)


GOLDEN_CASES = [
    # ── 香港：TVB ──────────────────────────────────────────────
    _case("TVB翡翠台", "📺 TVB", True),
    _case("TVB 翡翠台 FHD", "📺 TVB", True),
    _case("翡翠台 HD", "📺 TVB", True),
    _case("翡翠台(HD)", "📺 TVB", True),
    _case("明珠台 HD", "📺 TVB", True),
    _case("TVB Pearl 明珠台", "📺 TVB", True),
    _case("TVB J2", "📺 TVB", True),
    _case("J2", "📺 TVB", True),
    _case("TVB Plus", "📺 TVB", True),
    _case("TVB Plus 84", "📺 TVB", True),
    _case("TVB星河频道", "📺 TVB", True),
    _case("TVB无线新闻", "📺 TVB", True),
    _case("TVB生活台", "📺 TVB", True),
    # ── 香港：ViuTV ────────────────────────────────────────────
    _case("ViuTV", "📺 ViuTV", True),
    _case("ViuTV 99台", "📺 ViuTV", True),
    _case("ViuTV 99 FHD", "📺 ViuTV", True),
    _case("ViuTVsix 96", "📺 ViuTV", True),
    _case("Viu TV 99台", "📺 ViuTV", True),
    # ── 香港：RTHK ────────────────────────────────────────────
    _case("RTHK 31", "📺 RTHK", True),
    _case("RTHK 31 HD", "📺 RTHK", True),
    _case("RTHK 32 港台电视32", "📺 RTHK", True),
    _case("RTHK 33", "📺 RTHK", True),
    # ── 香港：HOY TV ──────────────────────────────────────────
    _case("HOY TV", "📺 HOY TV", True),
    _case("HOY TV 77 FHD", "📺 HOY TV", True),
    _case("HOY TV 76", "📺 HOY TV", True),
    _case("hoytv 78", "📺 HOY TV", True),
    # ── 香港：Now TV ──────────────────────────────────────────
    _case("Now TV 新闻台", "📺 Now TV", True),
    _case("Now TV 332", "📺 Now TV", True),
    _case("Now TV 333 新闻", "📺 Now TV", True),
    _case("Now财经", "📺 Now TV", True),
    _case("now直播", "📺 Now TV", True),
    # ── 香港：有线 / 开电视 ────────────────────────────────────
    _case("有线电视 10台", "📺 有线电视", True),
    _case("有线电视 财经台", "📺 有线电视", True),
    _case("开电视 77", "📺 有线电视", True),
    # ── 境外华语卫星（凤凰等）──────────────────────────────────
    _case("凤凰卫视中文台 HD", "📡 卫视频道", True),
    _case("凤凰卫视资讯台", "📡 卫视频道", True),
    _case("凤凰卫视香港台", "📡 卫视频道", True),
    _case("星空卫视", "📡 卫视频道", True),
    # ── 澳门 ──────────────────────────────────────────────────
    _case("澳视澳门 HD", "🇲🇴 澳门", True),
    _case("澳门卫视", "🇲🇴 澳门", True),
    _case("澳门电台", "🇲🇴 澳门", True),
    _case("TDM 澳门", "🇲🇴 澳门", True),
    _case("澳广视", "🇲🇴 澳门", True),
    _case("澳亚卫视", "🇲🇴 澳门", True),
    # ── 台湾 ──────────────────────────────────────────────────
    _case("台湾中视", "🇹🇼 台湾", True),
    _case("台视主频", "🇹🇼 台湾", True),
    _case("民视无线台", "🇹🇼 台湾", True),
    _case("民视新闻台", "🇹🇼 台湾", True),
    _case("东森新闻", "🇹🇼 台湾", True),
    _case("华视", "🇹🇼 台湾", True),
    _case("TVBS新闻", "🇹🇼 台湾", True),
    _case("TVBS Asia", "🇹🇼 台湾", True),
    _case("三立台湾台", "🇹🇼 台湾", True),
    _case("公视", "🇹🇼 台湾", True),
    _case("大爱电视台", "🇹🇼 台湾", True),
    _case("中视新闻台", "🇹🇼 台湾", True),
    # ── 内地：央视 ────────────────────────────────────────────
    _case("CCTV-1 综合", "📺 央视频道", False),
    _case("CCTV-2 财经", "📺 央视频道", False),
    _case("CCTV-5+ 体育", "📺 央视频道", False),
    _case("CCTV-6 电影", "📺 央视频道", False),
    _case("CCTV-9 纪录", "📺 央视频道", False),
    _case("CCTV-13 新闻", "📺 央视频道", False),
    _case("CCTV-17 农业", "📺 央视频道", False),
    _case("CCTV-4K", "📺 央视频道", False),
    _case("CCTV4 中文国际", "📺 央视频道", False),
    _case("CETV-1", "📺 央视频道", False),
    # ── 内地：省市（35 条，覆盖 35 个省级分组）──────────────────
    _case("北京卫视 HD", "📺 北京", False),
    _case("北京新闻频道", "📺 北京", False),
    _case("上海新闻综合", "📺 上海", False),
    _case("上海东方卫视", "📺 上海", False),
    _case("广东卫视", "📺 广东", False),
    _case("广东体育", "📺 广东", False),
    _case("深圳都市", "📺 深圳", False),
    _case("浙江钱江都市", "📺 浙江", False),
    _case("江苏综艺", "📺 江苏", False),
    _case("湖南经视", "📺 湖南", False),
    _case("安徽影视频道", "📺 安徽", False),
    _case("山东齐鲁", "📺 山东", False),
    _case("四川文旅", "📺 四川", False),
    _case("湖北经视", "📺 湖北", False),
    _case("福建海峡卫视", "📺 福建", False),
    _case("厦门卫视", "📺 福建", False),
    _case("陕西都市青春", "📺 陕西", False),
    _case("黑龙江农业", "📺 黑龙江", False),
    _case("吉林乡村", "📺 吉林", False),
    _case("辽宁青少", "📺 辽宁", False),
    _case("河北农民", "📺 河北", False),
    _case("河南民生", "📺 河南", False),
    _case("江西都市", "📺 江西", False),
    _case("山西黄河", "📺 山西", False),
    _case("内蒙古文体", "📺 内蒙古", False),
    _case("宁夏文旅", "📺 宁夏", False),
    _case("青海综合", "📺 青海", False),
    _case("甘肃文化影视频道", "📺 甘肃", False),
    _case("新疆兵团", "📺 新疆", False),
    _case("西藏文化", "📺 西藏", False),
    _case("贵州公共", "📺 贵州", False),
    _case("云南都市", "📺 云南", False),
    _case("广西综艺", "📺 广西", False),
    _case("海南文旅", "📺 海南", False),
    _case("重庆科教", "📺 重庆", False),
    _case("天津体育", "📺 天津", False),
    # ── 体育 ──────────────────────────────────────────────────
    _case("ESPN", "⚽ 体育频道", False),
    _case("ESPN2", "⚽ 体育频道", False),
    _case("Fox Sports 2", "⚽ 体育频道", False),
    _case("BeIN Sports 1", "⚽ 体育频道", False),
    _case("NBA", "⚽ 体育频道", False),
    _case("英超直播", "⚽ 体育频道", False),
    _case("高尔夫网球频道", "⚽ 体育频道", False),
    _case("体育频道", "⚽ 体育频道", False),
    _case("Alpha TV", "⚽ 体育频道", False, group="Sports"),
    # ── 电影 ──────────────────────────────────────────────────
    _case("HBO Asia", "🎬 电影频道", False),
    _case("Cinemax HD", "🎬 电影频道", False),
    _case("Star Movies HD", "🎬 电影频道", False),
    _case("Fox Movies", "🎬 电影频道", False),
    _case("Paramount Network", "🎬 电影频道", False),
    _case("卫视电影台", "🎬 电影频道", False),
    _case("凤凰电影台", "🎬 电影频道", False),
    _case("Beta TV", "🎬 电影频道", False, group="Movies"),
    # ── 音乐 ──────────────────────────────────────────────────
    _case("Channel V 音乐", "🎵 音乐频道", False),
    _case("MTV Live", "🎵 音乐频道", False),
    _case("华语音乐台", "🎵 音乐频道", False),
    _case("流行音乐频道", "🎵 音乐频道", False),
    _case("音乐频道", "🎵 音乐频道", False),
    # ── 新闻财经 ──────────────────────────────────────────────
    _case("Bloomberg TV", "📰 新闻财经", False),
    _case("CNBC Asia", "📰 新闻财经", False),
    _case("凤凰财经", "📰 新闻财经", False),
    _case("VOA 美国之音", "📰 新闻财经", False),
    _case("半岛新闻台", "📰 新闻财经", False),
    _case("Gamma TV", "📰 新闻财经", False, group="News"),
    # ── 儿童 ──────────────────────────────────────────────────
    _case("Cartoon Network", "🧸 儿童频道", False),
    _case("Disney Junior", "🧸 儿童频道", False),
    _case("Nick Jr", "🧸 儿童频道", False),
    _case("Baby TV", "🧸 儿童频道", False),
    _case("儿童频道", "🧸 儿童频道", False),
    _case("卡通频道", "🧸 儿童频道", False),
    _case("Delta TV", "🧸 儿童频道", False, group="Kids"),
    # ── 纪录片 ────────────────────────────────────────────────
    _case("Discovery Channel", "📺 纪录片", False),
    _case("National Geographic", "📺 纪录片", False),
    _case("History Channel", "📺 纪录片", False),
    _case("探索频道", "📺 纪录片", False),
    _case("地理频道", "📺 纪录片", False),
    _case("Epsilon TV", "📺 纪录片", False, group="Documentary"),
    # ── 综艺 ──────────────────────────────────────────────────
    _case("综艺频道", "🎭 综艺频道", False),
    _case("娱乐频道", "🎭 综艺频道", False),
    _case("电视剧场", "🎭 综艺频道", False),
    _case("曲艺频道", "🎭 综艺频道", False),
    # ── 国际 ──────────────────────────────────────────────────
    # 裁决（2026-10-29 分组逻辑重构）：BBC World News 是 24 小时新闻台，
    # 归 📰 新闻财经 比 🌐 国际频道 更准确，且与 scripts/categorize_dataset/known_bugs.tsv
    # 的要求一致，故按本文件自己的规则（"合理 → 写进本文件做硬断言"）改锚定值。
    # 遗留不一致：CNN 仍归 🌐 国际频道（"国际新闻品牌"规则只覆盖 bbc news / bbc world news），
    # 见 docs/categorize-improvement-proposal.md 的残留问题清单。
    _case("BBC World News", "📰 新闻财经", False),
    _case("CNN", "🌐 国际频道", False),
    _case("NHK World", "🌐 国际频道", False),
    _case("DW", "🌐 国际频道", False),
    _case("France 24", "🌐 国际频道", False),
    _case("Al Jazeera English", "🌐 国际频道", False),
    _case("德国之声", "🌐 国际频道", False),
    _case("日本频道", "🌐 国际频道", False),
]

GOLDEN_ROWS = [(p.values[0], p.values[1], p.values[2], p.values[3]) for p in GOLDEN_CASES]


# ---------------------------------------------------------------- 断言


@pytest.mark.parametrize("name,group,expected_group,expected_hk", GOLDEN_CASES)
def test_golden_categorize(classify, name, group, expected_group, expected_hk):
    """单条频道名 → (group, is_hk_region) 的 golden 断言。"""
    actual_group, actual_hk = classify(name, group)
    assert actual_group == expected_group, (
        f"{name!r} (group={group!r}) 分组变了: {actual_group!r} != {expected_group!r}"
    )
    assert actual_hk is expected_hk, (
        f"{name!r} (group={group!r}) 港区判定变了: {actual_hk} != {expected_hk}"
    )


# ---------------------------------------------------------------- 表格自检


def test_golden_table_is_large_enough():
    """表不能被悄悄裁剪（护栏本身也要有护栏）。"""
    assert len(GOLDEN_CASES) >= 50, f"golden 表只剩 {len(GOLDEN_CASES)} 条"


def test_golden_names_are_unique():
    names = [name for name, _, _, _ in GOLDEN_ROWS]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"golden 表里有重复名（会让 id 冲突、覆盖不全）：{sorted(dupes)}"


def test_golden_expected_groups_are_real_categories():
    """期望值必须是 CATEGORY_ORDER 里真实存在的分组，防止拼错 emoji/空格。"""
    unknown = {g for _, _, g, _ in GOLDEN_ROWS if g not in CATEGORY_ORDER}
    assert not unknown, f"golden 表用了不存在的分组名：{sorted(unknown)}"


def test_golden_hk_tw_mo_rows_are_also_hk_region(hk_tw_mo_groups):
    """地区型分组必须同时被 is_hk_region 认账，否则就是自相矛盾（应进 known_defects）。"""
    bad = sorted(
        {name for name, _, g, hk in GOLDEN_ROWS if g in hk_tw_mo_groups and not hk}
    )
    assert not bad, f"这些行 categorize 判成港台但 is_hk_region=False（应移入 xfail）：{bad}"


def test_golden_covers_required_regions():
    """香港运营商 / 港澳台 / 内地省市 / 8 大内容类型的覆盖下限。"""
    groups = {g for _, _, g, _ in GOLDEN_ROWS}
    required_hk_ops = {"📺 TVB", "📺 ViuTV", "📺 RTHK", "📺 HOY TV", "📺 Now TV", "📺 有线电视"}
    required_regions = {"🇲🇴 澳门", "🇹🇼 台湾", "📺 央视频道", "📡 卫视频道"}
    required_genres = {
        "⚽ 体育频道", "🎬 电影频道", "🎵 音乐频道", "📰 新闻财经",
        "🧸 儿童频道", "📺 纪录片", "🎭 综艺频道", "🌐 国际频道",
    }
    for label, need in (
        ("香港运营商", required_hk_ops),
        ("港澳台/内地", required_regions),
        ("内容类型", required_genres),
    ):
        missing = need - groups
        assert not missing, f"{label} 覆盖缺失：{sorted(missing)}"

    provinces = {g for g in groups if g.startswith("📺 ") and g not in required_hk_ops
                 and g not in ("📺 央视频道", "📺 纪录片")}
    assert len(provinces) >= 8, f"省级分组只覆盖了 {len(provinces)} 个：{sorted(provinces)}"


def test_keyword_matching_is_case_insensitive(classify):
    """_match 用 re.IGNORECASE：同一频道大小写不同不应改变结果。"""
    assert classify("viutv 99台") == classify("VIUTV 99台") == ("📺 ViuTV", True)
    assert classify("discovery channel") == classify("DISCOVERY CHANNEL") == ("📺 纪录片", False)


def test_group_only_english_mapping_does_not_leak_hk_region(classify):
    """纯英文 group 映射出的内容分组不应被算进港台播放列表。"""
    for group in ("Movies", "Kids", "News", "Sports", "Documentary"):
        _, hk = classify("Zeta TV", group)
        assert hk is False, f"group={group} 被判成港台频道"
