#!/usr/bin/env python3
"""Channel categorization and grouping logic."""
import re
from typing import Dict, List


# ──────────────────────────────────────────────────────────────
#  各省关键词（优先精确匹配）
# ──────────────────────────────────────────────────────────────
PROVINCE_KEYWORDS = {
    "📺 北京":          [r"北京卫视", r"北京科教", r"北京文艺", r"北京影视", r"北京财经", r"北京新闻", r"北京生活", r"北京青年", r"北京文艺频道"],
    "📺 上海":          [r"上海卫视", r"上海东方", r"上海新闻", r"上海都市", r"上海第一", r"上海艺术", r"上海生活", r"上海外语", r"上海综艺"],
    "📺 广东":          [r"广东卫视", r"广东珠江", r"广东新闻", r"广东体育", r"广东影视", r"广东综艺", r"广州卫视", r"广州新闻"],
    "📺 深圳":          [r"深圳卫视", r"深圳娱乐", r"深圳都市", r"深圳新闻", r"深圳公共", r"深圳财经"],
    "📺 浙江":          [r"浙江卫视", r"浙江新闻", r"浙江钱江", r"浙江经济", r"浙江教育", r"浙江影视", r"浙江民生", r"浙江体育"],
    "📺 江苏":          [r"江苏卫视", r"江苏新闻", r"江苏城市", r"江苏综艺", r"江苏影视", r"江苏体育", r"江苏教育", r"江苏公共"],
    "📺 湖南":          [r"湖南卫视", r"湖南新闻", r"湖南经视", r"湖南都市", r"湖南娱乐", r"湖南电视剧", r"湖南公共", r"湖南教育"],
    "📺 安徽":          [r"安徽卫视", r"安徽新闻", r"安徽经济", r"安徽综艺", r"安徽影视", r"安徽公共", r"安徽科教"],
    "📺 山东":          [r"山东卫视", r"山东新闻", r"山东齐鲁", r"山东体育", r"山东综艺", r"山东影视", r"山东公共", r"山东农科"],
    "📺 四川":          [r"四川卫视", r"四川新闻", r"四川经济", r"四川文旅", r"四川影视", r"四川综艺", r"四川公共", r"四川科教"],
    "📺 湖北":          [r"湖北卫视", r"湖北新闻", r"湖北经视", r"湖北综合", r"湖北影视", r"湖北教育", r"湖北公共", r"湖北垄上"],
    "📺 福建":          [r"福建卫视", r"福建东南", r"福建新闻", r"福建综合", r"福建经济", r"福建海峡", r"厦门卫视", r"厦门综合"],
    "📺 陕西":          [r"陕西卫视", r"陕西新闻", r"陕西都市", r"陕西文艺", r"陕西体育", r"陕西农林卫视", r"陕西音乐"],
    "📺 黑龙江":        [r"黑龙江卫视", r"黑龙江新闻", r"黑龙江都市", r"黑龙江文艺", r"黑龙江公共", r"黑龙江农业"],
    "📺 吉林":          [r"吉林卫视", r"吉林新闻", r"吉林都市", r"吉林乡村", r"吉林公共", r"吉林影视"],
    "📺 辽宁":          [r"辽宁卫视", r"辽宁新闻", r"辽宁都市", r"辽宁综合", r"辽宁经济", r"辽宁青少", r"辽宁体育"],
    "📺 河北":          [r"河北卫视", r"河北新闻", r"河北经济", r"河北都市", r"河北影视", r"河北公共", r"河北农民"],
    "📺 河南":          [r"河南卫视", r"河南新闻", r"河南都市", r"河南法治", r"河南公共", r"河南民生", r"河南乡村", r"河南经济"],
    "📺 江西":          [r"江西卫视", r"江西新闻", r"江西都市", r"江西经济", r"江西影视", r"江西公共", r"江西农业"],
    "📺 山西":          [r"山西卫视", r"山西新闻", r"山西黄河", r"山西公共", r"山西科教", r"山西文体"],
    "📺 内蒙古":        [r"内蒙古卫视", r"内蒙古新闻", r"内蒙古文体", r"内蒙古牧区"],
    "📺 宁夏":          [r"宁夏卫视", r"宁夏新闻", r"宁夏公共", r"宁夏经济", r"宁夏文旅"],
    "📺 青海":          [r"青海卫视", r"青海新闻", r"青海经济", r"青海综合"],
    "📺 甘肃":          [r"甘肃卫视", r"甘肃新闻", r"甘肃经济", r"甘肃文化", r"甘肃公共", r"甘肃都市"],
    "📺 新疆":          [r"新疆卫视", r"新疆新闻", r"新疆经济", r"新疆文体", r"新疆兵团"],
    "📺 西藏":          [r"西藏卫视", r"西藏新闻", r"西藏综合", r"西藏文化"],
    "📺 贵州":          [r"贵州卫视", r"贵州新闻", r"贵州综合", r"贵州经济", r"贵州公共", r"贵州影视"],
    "📺 云南":          [r"云南卫视", r"云南新闻", r"云南都市", r"云南经济", r"云南文旅", r"云南公共", r"云南娱乐"],
    "📺 广西":          [r"广西卫视", r"广西新闻", r"广西综合", r"广西综艺", r"广西都市", r"广西公共", r"广西资讯"],
    "📺 海南":          [r"海南卫视", r"海南新闻", r"海南综合", r"海南文旅", r"海南经济", r"海南公共"],
    "📺 重庆":          [r"重庆卫视", r"重庆新闻", r"重庆都市", r"重庆科教", r"重庆文体", r"重庆娱乐", r"重庆生活"],
    "📺 天津":          [r"天津卫视", r"天津新闻", r"天津文艺", r"天津科教", r"天津体育", r"天津都市", r"天津公共"],
}

# ──────────────────────────────────────────────────────────────
#  Helper
# ──────────────────────────────────────────────────────────────
def _match(name_lower: str, group_lower: str, patterns: list) -> bool:
    """Return True if any pattern matches in name or group.
    
    Uses case-insensitive search. Note: Python's \\b word boundary treats
    CJK chars as \\w (word chars), so \\b fails at ASCII/CJK boundaries.
    Patterns should NOT use trailing \\b before possible CJK chars.
    """
    full = name_lower + " " + group_lower
    return any(re.search(p, full, re.IGNORECASE) for p in patterns)


def _excluded(name_lower: str, group_lower: str) -> bool:
    """Patterns that disqualify a channel from specialized categories.
    
    Note: \\b word boundaries don't work at ASCII/CJK boundaries (CJK is \\w).
    Patterns use simple substring matching instead.
    """
    # clang-format off
    exclude = [
        r"cctv", r"cetv",
        r"aljazeera", r"al jazeera",
        r"bbc", r"cnn",
        r"fox news",
        r"bloomberg", r"cnbc",
        r"16tv", r"16 tv",
        r"viutv", r"viu tv",
        r"tvb", r"翡翠台", r"明珠台", r"j2",
        r"rthk",
        r"hoy", r"hoytv",
        r"nowtv", r"now tv",
        r"cable", r"有线", r"开电视",
        r"凤凰", r"phoenix",
        r"star tv", r"startv",
        r"star movies", r"fox movies",
        r"hbo", r"cinemax", r"amc", r"paramount", r"mgm",
        r"channel v", r"channelv", r"mtv",
        r"nhk", r"tbs",
        r"disney", r"cartoon", r"nickelodeon",
        r"disney channel",
        r"espn", r"fox sports", r"beinsport", r"bein sport",
        r"african", r"africable",
        r"budapest", r"bogota", r"brasil", r"brazil",
        r"ktv",
        r"daystar",
    ]
    # clang-format on
    full = name_lower + " " + group_lower
    return any(re.search(p, full, re.IGNORECASE) for p in exclude)


# ──────────────────────────────────────────────────────────────
#  is_hk_region — 保留（其他模块仍用）
# ──────────────────────────────────────────────────────────────
def is_hk_region(name: str, group: str, cat: str = None) -> bool:
    """判断是否为港台地区频道 (HK/TW/MO)
    
    Args:
        name: channel name
        group: group-title from m3u
        cat: optional category (from categorize()) for exclusion
    """
    name_lower, group_lower = name.lower(), (group or "").lower()
    full_text = name_lower + " " + group_lower

    hk_exact = [
        r"hkdtmb", r"香港台", r"香港電視",
        r"tvb", r"翡翠台", r"明珠台", r"j2", r"j1",
        r"viutv", r"viu tv", r"viu6", r"viu 6",
        r"rthk", r"rthk tv", r"港台電視", r"港台电视", r"香港电台",
        r"hoy tv", r"hoytv",
        r"now tv", r"nowtv", r"now直播", r"now财经", r"nownews",
        r"有线电视", r"开电视", r"cable tv", r"cable_tv",
        r"凤凰卫视", r"phoenix tv",
        r"无线电视", r"无线新闻", r"星空卫视",
    ]
    tw_exact = [
        r"tvbs", r"tvbs新闻",
        r"台视主频", r"台視主頻",
        r"中视综合台", r"中視綜合台",
        r"民视无线台", r"民視無限",
        r"东森电视", r"東森電視", r"东森新闻", r"東森新聞",
        r"三立台湾台", r"三立台灣台",
        r"华视", r"華視", r"中视", r"中視", r"民视", r"民視",
        r"台视", r"台視", r"大爱", r"公视", r"公視",
        r"\\bttv\b", r"\\bftv\b", r"\\bpts\b", r"\\bcna\b",
    ]
    mo_exact = [r"澳门", r"澳視", r"\\bmacau\b", r"澳广视", r"澳亚卫视"]

    exclude = [
        r"\bcctv\b", r"\bcetv\b", r"教育台",
        r"\bcctv[_\- ]", r"\bcetv[_\- ]",
        r"\bbbc\b", r"\bcnn\b",
        r"\bal jazeera\b", r"\baljazeera\b", r"\bfrance 24\b",
        r"bloomberg", r"cnbc", r"euronews",
        r"16tv", r"16 tv",
        r"african", r"africable",
        r"budapest",
        r"bogota", r"brasil", r"brazil",
        r"\bktv\b",
        r"\bmtv\b", r"\bm tv\b",
        r"star tv", r"startv",
        r"daystar",
        r"café", r"cafe",
        r"国际频道", r"国际新闻",
        r"央视频道", r"央视新闻",
    ]

    for p in exclude:
        if re.search(p, full_text):
            return False

    # Explicitly reject CCTV/CETV (must check before positive matches)
    if re.search(r"\bcctv[\-_\s]?\d*\b", name_lower) or re.search(r"\bcetv[\-_\s]?\d*\b", name_lower):
        return False
    if "教育台" in name or "央视" in name:
        return False
    # Reject 央视频道 / 央视新闻
    if re.search(r"央视频道|央视新闻", full_text):
        return False
    # Reject non-HK group categories
    non_hk_groups = [
        "央视频道", "国际频道", "国际新闻", "新闻财经",
        "电影频道", "音乐频道", "儿童频道", "体育频道",
        "纪录片", "综艺频道", "地方频道",
        "欧洲", "北美", "拉丁美洲", "中东", "非洲", "大洋洲",
        "日本", "韩国", "亚洲（东南亚）", "亚洲（其他）", "印度",
        "🌐 国际",
    ]
    check_text = (group or "") + " " + (cat or "")
    if any(g in check_text for g in non_hk_groups):
        return False

    for p in hk_exact + tw_exact + mo_exact:
        if re.search(p, full_text):
            return True

    return False


# ──────────────────────────────────────────────────────────────
#  英文 group-title → 中文分组映射（iptv-org / 英文播放列表用）
# ──────────────────────────────────────────────────────────────
GROUP_TITLE_EN_MAPPING = {
    # 新闻财经
    "news":         "📰 新闻财经",
    "business":     "📰 新闻财经",
    "weather":      "📰 新闻财经",
    # 电影
    "movies":       "🎬 电影频道",
    "classic":     "🎬 电影频道",
    # 电视剧/综艺
    "series":       "🎭 综艺频道",
    "entertainment": "🎭 综艺频道",
    "comedy":       "🎭 综艺频道",
    "cooking":      "🎭 综艺频道",
    # 音乐
    "music":        "🎵 音乐频道",
    # 体育
    "sports":       "⚽ 体育频道",
    "outdoor":      "⚽ 体育频道",
    "outdoor;sports": "⚽ 体育频道",
    # 儿童
    "kids":          "🧸 儿童频道",
    "animation":     "🧸 儿童频道",
    "animation;kids": "🧸 儿童频道",
    "family":        "🧸 儿童频道",
    # 纪录片/教育
    "documentary":   "📺 纪录片",
    "science":       "📺 纪录片",
    "education":     "📺 纪录片",
    "culture;education": "📺 纪录片",
    # 宗教（保持国际，不单独分类）
    "religious":     "🌐 国际",
    "general;religious": "🌐 国际",
    "music;religious": "🌐 国际",
    "kids;religious": "🌐 国际",
    # 无法分类的英文 group → 国际
    "general":       "🌐 国际",
    "undefined":     "🌐 国际",
    "general;public": "🌐 国际",
    "lifestyle":     "🌐 国际",
    "travel":        "🌐 国际",
    "auto":          "🌐 国际",
    "legislative":   "🌐 国际",
    "culture":       "🌐 国际",
    "general;news":  "🌐 国际",
    "news;public":   "🌐 国际",
    "culture;news":  "🌐 国际",
    "business;news": "🌐 国际",
    "entertainment;news": "🌐 国际",
    "documentary;news": "🌐 国际",
    "culture;entertainment": "🌐 国际",
    "culture;documentary": "🌐 国际",
    "entertainment;music": "🌐 国际",
    "entertainment;series": "🌐 国际",
    "family;movies": "🌐 国际",
    "education;kids": "🌐 国际",
    "education;science": "🌐 国际",
    "movies;series": "🌐 国际",
    "science;":      "🌐 国际",
}


# ──────────────────────────────────────────────────────────────
#  Logo URL 和频道名 → 国家/地区映射
# ──────────────────────────────────────────────────────────────
LOGO_REGION_PATTERNS = [
    # 中国源
    ("epg.112114.xyz/logo/TVB", "📺 TVB"),
    ("epg.112114.xyz/logo/翡翠台", "📺 TVB"),
    ("live.fanmingming.cn/tv/CH", "📺 央视频道"),
    ("gitee.com/suxuang", "🇨🇳 中国源"),
    # Astro 马来西亚
    ("ASTRO", "🇲🇾 马来西亚"),
    ("Astro", "🇲🇾 马来西亚"),
    # 澳大利亚
    ("Adelaide", "🇦🇺 澳大利亚"),
    ("Melbourne", "🇦🇺 澳大利亚"),
    ("Sydney", "🇦🇺 澳大利亚"),
]

CHANNEL_REGION_PATTERNS = [
    # Astro 马来西亚
    ("MOMOTV", "🇲🇾 马来西亚"),
    ("ASTROAOD", "🇲🇾 马来西亚"),
    # 澳大利亚
    ("Bold Adelaide", "🇦🇺 澳大利亚"),
    ("BoldAdelaide", "🇦🇺 澳大利亚"),
    # 荷兰
    ("AlmereTV", "🇳🇱 荷兰"),
    ("TwenteTV", "🇳🇱 荷兰"),
    # 宗教广播网
    ("3ABN", "🌐 宗教广播"),
    # 西班牙
    ("Televalencia", "🇪🇸 西班牙"),
    ("TeleValencia", "🇪🇸 西班牙"),
    # 意大利
    ("3Cat", "🇮🇹 意大利"),
    # 俄罗斯
    ("канал", "🇷🇺 俄罗斯"),
    # 北欧
    ("TV2", "🇳🇴 北欧"),
    # 非洲
    ("DSTV", "🌍 非洲"),
    ("Mnet", "🌍 非洲"),
    # 拉丁美洲 - 常见频道名模式
    ("TVCorrientes", "🌎 拉丁美洲"),
    ("TV Chile", "🌎 拉丁美洲"),
    ("Canal 13", "🌎 拉丁美洲"),
    ("Canal13", "🌎 拉丁美洲"),
    ("TV Brasil", "🌎 拉丁美洲"),
    ("TV Cultura", "🌎 拉丁美洲"),
    ("TV UNAM", "🌎 拉丁美洲"),
    ("VTV", "🌎 拉丁美洲"),
    # 波兰
    ("TVP", "🌍 欧洲"),
    ("Polsat", "🌍 欧洲"),
    ("TVN", "🌍 欧洲"),
]


# ──────────────────────────────────────────────────────────────
#  recategorize_others — 精简版：只做 logo/省级/HK台 匹配
#  所有无法精确匹配的频道统一归入 "🌐 国际"
# ──────────────────────────────────────────────────────────────
def recategorize_others(name: str, group: str, logo: str = "") -> str:
    """对"其他"分组中的未知频道进行二次分类。

    只保留：
    1. Logo URL 国家/地区识别（优先）
    2. 省级频道精确匹配（使用 PROVINCE_KEYWORDS）
    3. 港澳台频道（is_hk_region）

    其余全部归入 "🌐 国际"。
    """
    name_lower, group_lower = name.lower(), (group or "").lower()
    logo_lower = logo.lower() if logo else ""

    # ── 1. Logo URL 识别 ────────────────────────────────────
    if logo_lower:
        for pattern, region in LOGO_REGION_PATTERNS:
            if pattern.lower() in logo_lower:
                return region

    # ── 2. 省级频道（复用 PROVINCE_KEYWORDS）─────────────────
    for cat, patterns in PROVINCE_KEYWORDS.items():
        if _match(name_lower, group_lower, patterns):
            return cat

    # ── 3. 港澳台 ──────────────────────────────────────────
    if is_hk_region(name, group):
        return "🌐 国际"

    # ── 4. 英文 group-title 映射（iptv-org / 英文播放列表）────────
    if group_lower and group_lower != "others":
        # 精确匹配
        if group_lower in GROUP_TITLE_EN_MAPPING:
            return GROUP_TITLE_EN_MAPPING[group_lower]
        # 半精确匹配（取第一段，如 "Animation;Kids" → "animation"）
        first = group_lower.split(";")[0].strip()
        if first in GROUP_TITLE_EN_MAPPING:
            return GROUP_TITLE_EN_MAPPING[first]
        # 含分号的组合匹配
        for key in GROUP_TITLE_EN_MAPPING:
            if key in group_lower and ";" in group_lower:
                return GROUP_TITLE_EN_MAPPING[key]

    # ── 默认：未能精确识别的频道 ─────────────────────────────
    return "🌐 国际"


# ──────────────────────────────────────────────────────────────
#  categorize — 完全重写
# ──────────────────────────────────────────────────────────────
def categorize(name: str, group: str, logo: str = "") -> str:
    """分类频道，返回分组名称（按新规范）"""

    name_lower, group_lower = name.lower(), (group or "").lower()
    full_text = name_lower + " " + group_lower

    # ── 1. 央视频道 ──────────────────────────────────────────
    if re.search(r"\bcctv[\-_ ]?(\d+|news|english|4k|8k|15|16|17)\b", full_text):
        return "📺 央视频道"
    if re.search(r"\bcetv[\-_ ]?(\d+|1|2|3|4)\b", full_text):
        return "📺 央视频道"
    if re.search(r"\bcetv\b", name_lower) or "教育台" in full_text:
        return "📺 央视频道"
    # 裸 CCTV 兜底（排除 BBC/ABC/CNN 等）
    if re.search(r"\bcctv\b", name_lower) and not any(
        kw in full_text for kw in ["bbc", "abc ", "cnn", "al jazeera", "ntv"]
    ):
        return "📺 央视频道"

    # ── 2. 各省频道 ──────────────────────────────────────────
    for cat, patterns in PROVINCE_KEYWORDS.items():
        if _match(name_lower, group_lower, patterns):
            return cat

    # ── 3. 卫视频道（境外/境外中文） ──────────────────────────
    overseas_satellite = [
        r"凤凰卫视", r"phoenix",
        r"星空卫视", r"star tv", r"startv",
        r"华视",           # 华视 (CTV Taiwan)
        r"法国中文", r"法国电视",
        r"中文电视", r"中文台",
        r"亚洲电视", r"atv",
        r"卫视中文",
    ]
    if _match(name_lower, group_lower, overseas_satellite):
        return "📡 卫视频道"

    # ── 4. 港澳台 ─────────────────────────────────────────────
    # TVB
    # TVB 精确匹配（TVB 后面必须跟空格/连字符/数字，或完全是 TVB）
    tvb_pattern = r"(^tvb($|[\s\-\d])|\btvb翡翠|\btvb明珠|\btvbjade|\btvbpearl|\btvb无线|\btvb星河|\btvb娱乐|\btvb生活|\btvbplus|\btvb经典|\btvb亚洲|\bj2\b|\bj1\b|\b翡翠台|\b明珠台)"
    if re.search(tvb_pattern, name_lower, re.IGNORECASE):
        return "📺 TVB"

    # ViuTV
    if _match(name_lower, group_lower, [r"viutv", r"viu tv", r"viu6", r"viu 6"]):
        return "📺 ViuTV"

    # RTHK
    if _match(name_lower, group_lower, [r"rthk", r"rthk tv", r"港台電視", r"香港電台", r"香港电台"]):
        return "📺 RTHK"

    # HOY TV
    if _match(name_lower, group_lower, [r"hoy tv", r"hoytv", r"hoy"]):
        return "📺 HOY TV"

    # Now TV
    if _match(name_lower, group_lower, [r"now tv", r"nowtv", r"now直播", r"now财经", r"nownews"]):
        return "📺 Now TV"

    # 有线电视
    if _match(name_lower, group_lower, [r"有线电视", r"开电视", r"cable tv", r"cable_tv"]):
        return "📺 有线电视"

    # 台湾
    tw_kw = [
        r"tvbs", r"tvbs新闻",
        r"台视", r"台視", r"台视主频", r"台視主頻",
        r"中视", r"中視", r"中视综合台", r"中視綜合台",
        r"民视", r"民視", r"民视无线台", r"民視無限",
        r"东森", r"東森", r"东森新闻", r"東森新聞",
        r"三立台湾", r"三立台灣",
        r"华视", r"華視",
        r"大爱", r"公视", r"公視",
        r"非凡", r"非視",
        r"\bttv\b", r"\bftv\b", r"\bpts\b", r"\bcna\b",
        r"台湾台", r"台灣台",
    ]
    if _match(name_lower, group_lower, tw_kw):
        return "🇹🇼 台湾"

    # 澳门
    if _match(name_lower, group_lower, [r"澳门", r"澳視", r"macau", r"澳广视", r"澳亚卫视"]):
        return "🇲🇴 澳门"

    # ── 5. 电影频道 ───────────────────────────────────────────
    movie_kw = [
        # 英文电影频道（不用\b，因为中文旁边不算boundary）
        r"hbo", r"cinemax", r"amc", r"paramount", r"mgm",
        r"star movies", r"fox movies",
        r"cinema",                       # cinema 不加\b，避免被 cinemax 意外匹配
        r"电影频道", r"电影台", r"好莱坞电影",
        r"fx movie", r"fxmovie",
        r"好莱坞", r"影视", r"影城",
        r"movie",                        # 英文 movie
        r"凤凰电影", r"卫视电影",
    ]
    if _match(name_lower, group_lower, movie_kw):
        return "🎬 电影频道"

    # ── 6. 音乐频道 ───────────────────────────────────────────
    music_kw = [
        r"channel v", r"channelv",
        r"mtv", r"m tv",
        r"音乐电视", r"音乐频道", r"音乐台",
        r"vmv", r"v mv",
        r"华语音乐", r"中文音乐", r"流行音乐",
    ]
    if _match(name_lower, group_lower, music_kw):
        return "🎵 音乐频道"

    # ── 7. 国际频道 ───────────────────────────────────────────
    intl_kw = [
        r"bbc", r"cnn", r"al jazeera", r"aljazeera",
        r"nhk", r"tbs",
        r"france 24", r"france24",
        r"dw", r"trt", r"tv5", r"tv5monde",
        r"澳大利亚", r"澳洲电视",
        r"德国电视", r"德国之声",
        r"意大利", r"西班牙电视",
        r"韩国频道", r"韩流", r"韩国广播",
        r"日本频道", r"日本电视",
        r"泰国频道", r"越南频道",
        r"印度频道", r"印度新闻",
        r"国际频道", r"海外频道",
    ]
    if _match(name_lower, group_lower, intl_kw):
        return "🌐 国际频道"

    # ── 8. 新闻财经 ──────────────────────────────────────────
    news_kw = [
        r"bloomberg", r"cnbc",
        r"财经", r"金融", r"证券",
        r"新闻频道", r"新闻台",
        r"cnn", r"bbc news",
        r"半岛新闻", r"半岛电视台",
        r"euronews",
        r"香港新闻", r"香港财经",
        r"凤凰财经", r"凤凰新闻",
        r"voa", r"美国之音",
    ]
    if _match(name_lower, group_lower, news_kw):
        return "📰 新闻财经"

    # ── 9. 儿童频道 ──────────────────────────────────────────
    kids_kw = [
        r"cartoon network", r"cartoon",
        r"disney channel", r"disney",
        r"nickelodeon", r"nick",
        r"少儿频道", r"儿童频道", r"少儿台",
        r"儿童动画", r"动漫频道", r"卡通频道",
        r"baby tv", r"babytv",
        r"boomerang",
        r"儿童电影", r"动画电影",
    ]
    if _match(name_lower, group_lower, kids_kw):
        return "🧸 儿童频道"

    # ── 10. 综艺频道 ──────────────────────────────────────────
    variety_kw = [
        r"综艺", r"综合台", r"综合频道",
        r"娱乐频道", r"娱乐台", r"娱乐节目",
        r"戏剧频道", r"戏剧台",
        r"电视剧", r"电视剧场",
        r"真人秀", r"综艺频道",
        r"曲艺", r"相声",
    ]
    if _match(name_lower, group_lower, variety_kw):
        return "🎭 综艺频道"

    # ── 11. 体育频道 ──────────────────────────────────────────
    sport_kw = [
        r"espn", r"espn2",
        r"fox sports", r"foxsports",
        r"beinsport", r"bein sport",
        r"体育频道", r"体育台",
        r"足球频道", r"足球台",
        r"篮球频道", r"篮球台",
        r"高尔夫", r"网球频道",
        r"赛车", r"搏击", r"格斗",
        r"直播频道", r"直播台",
        r"卫视体育", r"体育新闻",
        r"nba", r"cba",
        r"欧冠", r"英超", r"意甲", r"西甲", r"德甲", r"法甲",
        r"中超", r"亚冠",
        r"奥运", r"体育赛事",
    ]
    if _match(name_lower, group_lower, sport_kw):
        return "⚽ 体育频道"

    # ── 12. 纪录片 ────────────────────────────────────────────
    doc_kw = [
        r"discovery", r"national geographic", r"nat geo",
        r"地理频道", r"探索频道", r"探索",
        r"history channel", r"历史频道",
        r"动物频道", r"野生频道",
        r"science channel", r"科学频道",
        r"documentary", r"纪录片",
    ]
    if _match(name_lower, group_lower, doc_kw):
        return "📺 纪录片"

    # ── 13. 未能分类 → 其他（二次分类）─────────────────────────
    return recategorize_others(name, group, logo)
