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


@pytest.mark.parametrize(
    "name",
    [
        "HOY 77台",
        pytest.param(
            "HOY资讯台",
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "现象：'HOY资讯台' 被判 '🌐 国际'、is_hk_region 为 False，而 'HOY 77台' / 'HOY' 都正确。"
                    "根因：类型词判定（「资讯」命中 📰 新闻财经 品牌词）先于港区品牌判定执行，"
                    "'HOY资讯台' 在走到 HOY 品牌分支之前就被 🌐 国际 兜底吃掉。"
                    "修法：把本地品牌判定（HOY/TVB/RTHK/ViuTV/Now）提到类型词判定之前；修好后移除本标记。"
                ),
            ),
        ),
    ],
)
def test_hoy_bare_marker_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "📺 HOY TV"
    assert hk is True


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
