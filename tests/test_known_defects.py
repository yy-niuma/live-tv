"""已知缺陷登记表（xfail 守卫）。

规则：
- 这里只登记「跑真实代码确认过、当前确实错」的行为。每条断言写的是**应有的行为**，
  所以现在会失败 → xfail；将来 src/ 修好后会变 XPASS → strict=True 直接报红，
  强制维护者回来删掉这条（否则护栏会一直装作缺陷还在）。
- 每条 reason 写清：现象 + 根因（已用真实调用/源码位置确认）+ 修好后该怎么做。
- 不放 autouse fixture、不联网：全部是纯函数调用。
"""
import pytest

# ────────────────────────────────────────────────────────────────
#  缺陷组 1：港区判定自相矛盾
#  categorize() 判成 📺 TVB / 📺 HOY TV / 🇲🇴 澳门 / 🇹🇼 台湾，
#  但同名的 is_hk_region() 却返回 False —— 结果这些频道不会进 hk_merged.m3u。
# ────────────────────────────────────────────────────────────────


def test_bare_tvb_name_is_hk_region(classify):
    cat, hk = classify("TVB")
    assert cat == "📺 TVB"
    assert hk is True


@pytest.mark.parametrize("name", ["TVB Jade", "TVB Pearl"])
def test_spaced_tvb_english_name_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "📺 TVB"
    assert hk is True


# 回归护栏：HOY 分支曾用 r"\bhoy\b"，而 \b 在 CJK / 数字边界不成立（Python 的 \w 含 CJK），
# 于是 HOY资讯台 / HOY78 / HOYInfotainment 三个真频道全部漏掉、落进「🌐 国际」兜底。
# 现在用 r"(?<![a-z])hoy"（只做前置否定），三个都恢复，且 iHOY爱历史 仍被挡在外面。
@pytest.mark.parametrize(
    "name",
    ["HOY", "HOY TV", "HOYTV", "HOY 77台", "HOY78", "HOY资讯台", "HOYInfotainment"],
)
def test_hoy_family_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "📺 HOY TV"
    assert hk is True


def test_ihoy_history_channel_is_not_hoy_tv(classify):
    """iHOY 爱历史 是历史纪录片频道，名字里带 hoy 但不是 HOY TV —— 不能被前置否定放过。

    它真正的产出路径是 **logo**：`gitee.com/suxuang/.../IHOT爱历史.png` 命中
    `LOGO_REGION_PATTERNS` 的 `gitee.com/suxuang` → `🇨🇳 中国源`。
    所以这里同时钉两个口径，顺便记录「logo 会改变结果」：
    """
    cat, hk = classify("iHOY爱历史", "IHOT频道")
    assert cat == "🌐 国际", f"不传 logo 应为兜底的国际，实际 {cat!r}"
    assert hk is False

    logo = "https://gitee.com/suxuang/logo/raw/master/mylogo/IHOT爱历史.png"
    cat_logo, hk_logo = classify("iHOY爱历史", "IHOT频道", logo)
    assert cat_logo != "📺 HOY TV", "iHOY 被误判成 HOY TV"
    assert cat_logo == "🇨🇳 中国源", f"带 gitee logo 应为中国源，实际 {cat_logo!r}"
    assert hk_logo is False


@pytest.mark.parametrize("name", ["Macau TV", "MACAU TV"])
def test_macau_ascii_name_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "🇲🇴 澳门"
    assert hk is True


@pytest.mark.parametrize("name", ["TTV", "PTS", "CNA 中央社"])
def test_taiwan_ascii_callsign_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "🇹🇼 台湾"
    assert hk is True


@pytest.mark.parametrize("name", ["非凡商业台", "东森财经新闻"])
def test_taiwan_sub_channel_names_are_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "🇹🇼 台湾"
    assert hk is True


# ────────────────────────────────────────────────────────────────
#  缺陷组 2：分类结果本身错（不是自相矛盾，但明显不合理）
# ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["港台电视31", "港台电视32"])
def test_rthk_simplified_name_is_rthk(classify, name):
    cat, _hk = classify(name)
    assert cat == "📺 RTHK"


# 裁决记录（2026-10-29）：本条原先登记为「东方卫视 应归 📺 上海」。
# 但东方卫视是上海广播电视台的上星频道，归 📡 卫视频道 才是对的（📺 上海 应留给本地地面频道）。
# 分组逻辑重构后它稳定落在 📡 卫视频道，故从"缺陷守卫"改为"正向回归守卫"。
@pytest.mark.parametrize("name", ["东方卫视", "东方卫视 HD"])
def test_dongfang_weishi_is_satellite(classify, name):
    cat, _hk = classify(name)
    assert cat == "📡 卫视频道"
