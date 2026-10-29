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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：categorize('TVB') == '📺 TVB'，但 is_hk_region('TVB') 为 False，"
        "裸名 TVB 被排除出港区列表。根因：is_hk_region 的 hk_exact/tvb_kw_exact 只列了"
        "\\btvbjade\\b/\\btvbpearl\\b/... 连写品牌词，没有裸 'tvb' 精确匹配（tvb_pattern 里"
        "'^tvb($|[\\s\\-\\d])' 的分支只在 categorize 侧存在）。"
        "修法：is_hk_region 增加裸 'tvb' 精确匹配；修好后移除本标记。"
    ),
)
def test_bare_tvb_name_is_hk_region(classify):
    cat, hk = classify("TVB")
    assert cat == "📺 TVB"
    assert hk is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：'TVB Jade' 被判 '📺 TVB'，但 is_hk_region('TVB Jade') 为 False"
        "（空格分隔的官方英文台名被漏掉）。根因：hk_exact 只有连写 '\\btvbjade\\b'，"
        "不认 'TVB Jade'；而 categorize 的 tvb_pattern 有 '^tvb($|[\\s\\-\\d])' 兜住。"
        "修法：hk_exact/tvb_kw_exact 补 'tvb jade' / 'tvb pearl' 空格写法；修好后移除本标记。"
    ),
)
@pytest.mark.parametrize("name", ["TVB Jade", "TVB Pearl"])
def test_spaced_tvb_english_name_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "📺 TVB"
    assert hk is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：'HOY 77台' / 'HOY资讯台' 被判 '📺 HOY TV'，但 is_hk_region 为 False。"
        "根因：categorize 的 HOY 分支用裸 r'hoy'，is_hk_region 的 hk_exact 只列"
        "'hoy tv'/'hoytv'，两侧关键词集合不一致。"
        "修法：hk_exact 补裸 'hoy' 或统一两边关键词；修好后移除本标记。"
    ),
)
@pytest.mark.parametrize("name", ["HOY 77台", "HOY资讯台"])
def test_hoy_bare_marker_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "📺 HOY TV"
    assert hk is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：'Macau TV' / 'MACAU TV' 被判 '🇲🇴 澳门'，但 is_hk_region 返回 False。"
        "根因：src/group/categorizer.py:143 的 mo_exact 写成 r\"\\\\bmacau\\\\b\"（源码里是"
        "两个反斜杠的原始字符串），正则实际匹配的是字面文本 '\\bmacau\\b'，分支永不命中。"
        "修法：改成 r\"\\bmacau\\b\"；修好后移除本标记。"
    ),
)
@pytest.mark.parametrize("name", ["Macau TV", "MACAU TV"])
def test_macau_ascii_name_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "🇲🇴 澳门"
    assert hk is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：TTV / PTS / CNA 中央社 被判 '🇹🇼 台湾'，但 is_hk_region 返回 False。"
        "根因：src/group/categorizer.py:141 的 tw_exact 写成 r\"\\\\bttv\\\\b\" 等（双反斜杠"
        "原始字符串），正则匹配字面 '\\bttv\\b'，该分支永不命中；categorize 侧同名单反斜杠"
        "写法 r\"\\bttv\\b\" 是正常的，于是两边结论打架。"
        "修法：把 141 行的 \\\\b 改成 \\b；修好后移除本标记。"
    ),
)
@pytest.mark.parametrize("name", ["TTV", "PTS", "CNA 中央社"])
def test_taiwan_ascii_callsign_is_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "🇹🇼 台湾"
    assert hk is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：'非凡商业台' / '东森财经新闻' 被判 '🇹🇼 台湾'，但 is_hk_region 为 False。"
        "根因：is_hk_region 的 tw_exact 只列 '东森新闻/東森新聞'（不含东森财经）且完全没有"
        "'非凡'，而 categorize 的 tw_kw 用裸 '东森'/'非凡'。两侧关键词集合不一致。"
        "修法：tw_exact 补 '东森'/'非凡' 泛匹配或补齐子台名；修好后移除本标记。"
    ),
)
@pytest.mark.parametrize("name", ["非凡商业台", "东森财经新闻"])
def test_taiwan_sub_channel_names_are_hk_region(classify, name):
    cat, hk = classify(name)
    assert cat == "🇹🇼 台湾"
    assert hk is True


# ────────────────────────────────────────────────────────────────
#  缺陷组 2：分类结果本身错（不是自相矛盾，但明显不合理）
# ────────────────────────────────────────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：'港台电视31'（RTHK 31 的官方中文名）被判 '📺 TVB'。"
        "根因：categorize 的 RTHK 关键词只写了繁体 '港台電視'，简体 '港台电视' 不命中，"
        "于是落到末尾 recategorize_others，其 hk_kw 同时列了繁体+简体、兜底返回 '📺 TVB'。"
        "（注：真实流水线里 normalize.py 会把这两个名字硬映射成 'RTHK 31/32'，所以这个缺陷"
        "只在未归一化的输入上暴露。）"
        "修法：RTHK 分支补 '港台电视'；修好后移除本标记。"
    ),
)
@pytest.mark.parametrize("name", ["港台电视31", "港台电视32"])
def test_rthk_simplified_name_is_rthk(classify, name):
    cat, _hk = classify(name)
    assert cat == "📺 RTHK"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "现象：'东方卫视' / '东方卫视 HD' 被判 '🌐 国际'（上海台被扔进国际堆）。"
        "根因：PROVINCE_KEYWORDS['📺 上海'] 只列了 '上海东方'，没有裸 '东方卫视'；"
        "既不是境外卫视（overseas_satellite 无此词），也不命中任何类型词。"
        "修法：上海关键词补 '东方卫视'；修好后移除本标记。"
    ),
)
@pytest.mark.parametrize("name", ["东方卫视", "东方卫视 HD"])
def test_dongfang_weishi_is_shanghai(classify, name):
    cat, _hk = classify(name)
    assert cat == "📺 上海"
