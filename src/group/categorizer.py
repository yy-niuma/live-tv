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
#  港澳台统一判定（categorize 与 is_hk_region 的**唯一**事实来源）
#  ------------------------------------------------------------------
#  设计契约：
#    _region_category(name, group) 返回某个港澳台分类名（或 None）
#    is_hk_region(...) <=> _region_category(...) is not None
#    categorize(...) 命中港澳台时返回的分类 == _region_category(...)
#  两张表各写一份是历史遗留 bug 的根源（categorize 认、is_hk_region 不认）。
# ──────────────────────────────────────────────────────────────
#  顺序敏感：TVBS 必须在 TVB 之前（tvbs 属于台湾 TVBS，不是 TVB）
HK_TW_MO_RULES = [
    ("🇹🇼 台湾", [
        r"\btvbs",                       # TVBS / TVBSNews / TVBS亚洲
        r"台视", r"台視", r"中视", r"中視", r"民视", r"民視",
        r"东森", r"東森", r"三立", r"华视", r"華視",
        r"大爱", r"大愛", r"公视", r"公視", r"非凡", r"中天",
        # (?<![a-z])…(?![a-z]) 而非 \b…\b：\b 在 CJK/数字边界不成立（PTS3 会漏）
        r"(?<![a-z])ttv(?![a-z])", r"(?<![a-z])ftv(?![a-z])",
        r"(?<![a-z])pts(?![a-z])", r"(?<![a-z])cna(?![a-z])",
        r"台湾", r"台灣",
    ]),
    ("📺 TVB", [
        # tvb 后不得紧跟拉丁字母（防 tvbrics / tvbrno 等假 TVB；tvbs 已在上面拦下）
        r"\btvb(?![a-z])",
        r"\btvb(?:plus|jade|pearl|j1|j2|x)(?![a-z])",   # 连写形态：TVBPlus/TVBJade...
        r"\bj2\b", r"\bj1\b",
        r"tvbanywhere",
        r"翡翠台", r"明珠台",
        r"无线电视", r"無線電視", r"无线新闻", r"無線新聞",
    ]),
    ("📺 ViuTV", [r"viutv", r"viu\s*tv", r"\bviu\s*6\b", r"\bviu6\b"]),
    ("📺 RTHK", [r"rthk", r"港台電視", r"港台电视", r"香港電台", r"香港电台"]),
    # 只做「前置否定」不做后置断言：\bhoy\b 在 CJK/数字后不成立（\w 含 CJK），
    # 会把 HOY资讯台 / HOY78 / HOYInfotainment 全部漏掉 —— 这三个都是真 HOY TV 频道。
    # 前置 (?<![a-z]) 用来挡 iHOY爱历史（历史纪录片频道，不是 HOY TV）。
    ("📺 HOY TV", [r"hoy\s*tv", r"hoytv", r"(?<![a-z])hoy"]),
    ("📺 Now TV", [
        # 繁体字形：財經/新聞 必须与简体并列（历史 bug：只写简体导致 Now財經 落兜底）
        r"now\s*tv", r"nowtv", r"now直播",
        r"now財經", r"now财经", r"now新聞", r"now新闻", r"nownews",
        r"\bnow\b[\s\-]*(?:sports|體育|体育|movies?|影|剧|劇|kids|hbo)",
    ]),
    ("📺 有线电视", [r"有线电视", r"有線電視", r"开电视", r"開電視",
                     r"cable\s*tv", r"cable_tv"]),
    ("🇲🇴 澳门", [
        r"澳门", r"澳門", r"澳視", r"澳视", r"澳广视", r"澳廣視",
        r"澳亚卫视", r"澳亞衛視", r"macau", r"\btdm\b",   # TDM = 澳门电台/电视（Teledifusão de Macau）
    ]),
]

# 仅影响「是否港澳台地域」、不决定分类的频道族：
#   凤凰/星空 是香港持牌的境外中文卫视 —— 地域属港，但内容定位是「卫视频道/电影频道」。
#   这类频道必须进 hk_merged，分类却由 categorize 的卫视/电影块决定。
_REGION_EXTRA = [
    r"凤凰卫视", r"鳳凰衛視", r"凤凰香港台", r"phoenix",
    r"星空卫视", r"星空衛視",
    r"\bstar\s*tv\b", r"\bstartv\b",   # 加边界：DaystarTV/HmongStarTV 不是星空卫视
]

# 名字里带港台品牌词、但实为海外分台的（沿用旧版排除表的关键项）
_REGION_NAME_VETO = [
    r"\bright\s*now\s*tv\b",      # Right Now TV（美国），命中裸 nowtv
    r"winnipeg", r"edmonton", r"ontario", r"british columbia", r"\bcanadian?\b",
]

# 这些分组里的频道即便名字带港澳台字样也不判为港澳台（央视/国际新闻等）
_REGION_GROUP_VETO = ("央视频道", "央视新闻", "国际频道", "国际新闻", "国际台")


def _region_extra(name: str, group: str) -> bool:
    """仅地域判定（不决定分类）的港澳台频道：凤凰卫视/星空卫视 等。"""
    full = (name or "").lower() + " " + (group or "").lower()
    return any(re.search(p, full, re.IGNORECASE) for p in _REGION_EXTRA)


def _region_category(name: str, group: str) -> str | None:
    """港澳台统一判定：返回港澳台分类名，或 None。"""
    name_lower = (name or "").lower()
    group_lower = (group or "").lower()
    full = name_lower + " " + group_lower
    # 央视/国际新闻分组整体否决（保持原有语义：央视频道组里没有港澳台）
    if any(v in (group or "").lower() for v in _REGION_GROUP_VETO):
        return None
    if any(re.search(p, full, re.IGNORECASE) for p in _REGION_NAME_VETO):
        return None
    for cat, patterns in HK_TW_MO_RULES:
        for p in patterns:
            if re.search(p, full, re.IGNORECASE):
                return cat
    return None


# ──────────────────────────────────────────────────────────────
#  省级关键词（拼音/英文写法，补中文表覆盖不到的名字）
# ──────────────────────────────────────────────────────────────
PROVINCE_LATIN = {
    "📺 北京": [r"beijing"], "📺 上海": [r"shanghai"], "📺 广东": [r"guangdong"],
    "📺 深圳": [r"shenzhen"], "📺 浙江": [r"zhejiang"], "📺 江苏": [r"jiangsu"],
    "📺 湖南": [r"hunan"], "📺 安徽": [r"anhui"], "📺 山东": [r"shandong"],
    "📺 四川": [r"sichuan"], "📺 湖北": [r"hubei"], "📺 福建": [r"fujian"],
    "📺 陕西": [r"shaanxi"], "📺 黑龙江": [r"heilongjiang"], "📺 吉林": [r"jilin"],
    "📺 辽宁": [r"liaoning"], "📺 河北": [r"hebei"], "📺 河南": [r"henan"],
    "📺 江西": [r"jiangxi"], "📺 山西": [r"shanxi"], "📺 内蒙古": [r"neimenggu", r"inner\s*mongolia"],
    "📺 宁夏": [r"ningxia"], "📺 青海": [r"qinghai"], "📺 甘肃": [r"gansu"],
    "📺 新疆": [r"xinjiang"], "📺 西藏": [r"xizang", r"tibet"],
    "📺 贵州": [r"guizhou"], "📺 云南": [r"yunnan"], "📺 广西": [r"guangxi"],
    "📺 海南": [r"hainan"], "📺 重庆": [r"chongqing"], "📺 天津": [r"tianjin"],
}

# 地市级/县市级中文台特征后缀（命中即判 🇨🇳 中国源，而不是掉进国际兜底）
CJK_CITY_SUFFIX = (
    "新闻综合", "综合频道", "新闻频道", "新闻台", "电视台", "广播电视台",
    "公共频道", "经济频道", "都市频道", "生活频道", "科教频道", "文旅频道",
    "民生频道", "法制频道", "法治频道", "少儿频道", "文体频道", "影视文艺",
    "综合", "资讯",
)

# 纯中文名里出现这些词说明是「内容」而不是「地方台」，不做地市台推断
CONTENT_WORDS = (
    "卫视", "港澳", "剧", "影", "春晚", "儿童", "少儿", "动画", "动漫", "纪录",
    "音乐", "歌", "曲", "戏曲", "相声", "评书", "球", "赛", "游戏", "购物",
    "直播", "点播", "回看", "试看", "测试", "成人", "教育", "考研", "证券",
    "财经", "新闻", "综合", "生活", "文化", "旅行", "美食",   # 这些若单独出现按地市台处理，见下
)
# 与 CJK_CITY_SUFFIX 重叠的词从黑名单里剔除（上表末尾几项仅供 _looks_like_city 判断用）
_LOCAL_OK_WORDS = ("新闻", "综合", "生活", "文化", "财经", "教育")
CONTENT_WORDS_STRICT = tuple(w for w in CONTENT_WORDS if w not in _LOCAL_OK_WORDS)

# 中文 group-title → 分类（源里大量中文分组名，英文映射表覆盖不到）
# 只收「语义明确」的中文分组；綜合/新聞/綜藝/運動 这类在实测语料里被源站误标
# （group=綜合 下多为印度/中东频道），刻意不收，避免引入噪声。
GROUP_TITLE_ZH_MAPPING = {
    "电影": "🎬 电影频道",          # 简体 '电影' 组下实测全是 CHC/1905 这类真电影频道
    "地方频道": "🇨🇳 中国源",
    "直播中国": "🇨🇳 中国源",
    "春晚频道": "🎭 综艺频道",
    "咪咕赛事": "⚽ 体育频道",
    "点播电影": "🎬 电影频道",
    "戏曲频道": "🎭 综艺频道",
    "纪录频道": "📺 纪录片",
    "动画频道": "🧸 儿童频道",
    "🪁动画频道": "🧸 儿童频道",
}

# ──────────────────────────────────────────────────────────────
#  央视频道
# ──────────────────────────────────────────────────────────────
#  \b 在 CJK 前不成立（CJK 属 \w），历史 bug：cctv1综合 / cctv10科教 全掉进兜底。
# 这里用 (?![a-z]) 而不是 \b：数字后紧跟中文/符号都算命中，只挡拉丁字母后缀。
CCTV_RE = re.compile(
    r"\bcctv[\s\-_]*\+?\d{1,2}(?:plus|\+|k)?(?![a-z])"
    r"|\bcctv(?![a-z0-9])"
    r"|\bcgtn(?![a-z])",
    re.IGNORECASE,
)
CETV_RE = re.compile(r"\bcetv[\s\-_]*\d{0,2}(?![a-z])", re.IGNORECASE)

_CJK_ONLY_RE = re.compile(r"^[\u4e00-\u9fff]+$")
_CITY_SUFFIX_RE = re.compile("(?:" + "|".join(CJK_CITY_SUFFIX) + ")$")
_FOREIGN_REGION_RE = re.compile(r"卫视|港澳台|香港|台湾|台灣|澳门|澳門|日本|韩国|美國|美国")


def _looks_like_cn_local(name: str, group: str) -> bool:
    """判断中文地市/县市台（兜底桶污染源）。

    三级判据，命中任一即认为是地方台：
      1. 中文名以地市台特征后缀结尾（新闻综合/综合频道/电视台…）；
      2. 纯中文名、2-8 字、且不含「内容类」词（剧/影/春晚/动画…）；
      3. group 是「地方频道 / 直播中国」这类明确的地方台分组。
    刻意保守：含 卫视/港澳台/外国地区 的名字一律不做地方台推断。
    """
    n = (name or "").strip()
    if not n:
        return False
    if _FOREIGN_REGION_RE.search(n):
        return False
    if _CITY_SUFFIX_RE.search(n):
        return True
    g0 = (group or "").strip()
    if _CJK_ONLY_RE.match(n) and 2 <= len(n) <= 8:
        if not any(w in n for w in CONTENT_WORDS_STRICT):
            # group 已经指明了内容类型（动画频道/春晚频道…）时，交给映射表，不做地市台猜测
            if not g0 or (g0 not in GROUP_TITLE_ZH_MAPPING and g0 not in GROUP_TITLE_EN_MAPPING):
                return True
    g = group or ""
    if any(k in g for k in ("地方频道", "直播中国")):
        return True
    return False


# ──────────────────────────────────────────────────────────────
#  is_hk_region — 保留（其他模块仍用）
# ──────────────────────────────────────────────────────────────
def is_hk_region(name: str, group: str, cat: str | None = None) -> bool:
    """判断是否为港台地区频道 (HK/TW/MO)

    与 categorize() 共用 HK_TW_MO_RULES，保证「分类为港澳台」<=>「进 hk_merged」。

    Args:
        name: channel name
        group: group-title from m3u
        cat: 兼容旧签名保留；判定不再依赖它（避免循环依赖）
    """
    return _region_category(name, group) is not None or _region_extra(name, group)


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
    """对「其他」分组中的未知频道进行二次分类（兜底链路）。

    顺序：Logo 地区 → 港澳台（与 categorize 共用表）→ 省级（中文/拼音/中文分组名）
          → 中文 group-title 映射 → 英文 group-title 映射 → 中国地市台 → 音乐 → 国际兜底
    """
    name_lower, group_lower = name.lower(), (group or "").lower()
    logo_lower = logo.lower() if logo else ""

    # ── 1. Logo URL 识别 ────────────────────────────────────
    if logo_lower:
        for pattern, logo_region in LOGO_REGION_PATTERNS:
            if pattern.lower() in logo_lower:
                return logo_region

    # ── 2. 港澳台（统一判定，不再重复一套关键词）──────────────
    region = _region_category(name, group)
    if region:
        return region

    # ── 3. 省级频道（中文表 + 拼音表 + 中文分组名「XX频道」）──
    for cat, patterns in PROVINCE_KEYWORDS.items():
        if _match(name_lower, group_lower, patterns):
            return cat
    for cat, patterns in PROVINCE_LATIN.items():
        if _match(name_lower, group_lower, patterns):
            return cat
    for cat in PROVINCE_KEYWORDS:
        short = cat.replace("📺 ", "").strip()
        if short and (short + "频道") in (group or ""):
            return cat


    # ── 4. 中文 group-title 映射（源站大量中文分组名，英文表覆盖不到）──
    g_raw = (group or "").strip()
    if g_raw:
        for cand in (g_raw, g_raw.lstrip("☘️🪁🌊 ").strip()):
            if cand in GROUP_TITLE_ZH_MAPPING:
                return GROUP_TITLE_ZH_MAPPING[cand]

    # ── 5. 英文 group-title 映射（iptv-org / 英文播放列表）────────
    if group_lower and group_lower != "others":
        if group_lower in GROUP_TITLE_EN_MAPPING:
            return GROUP_TITLE_EN_MAPPING[group_lower]
        first = group_lower.split(";")[0].strip()
        if first in GROUP_TITLE_EN_MAPPING:
            return GROUP_TITLE_EN_MAPPING[first]
        for key in GROUP_TITLE_EN_MAPPING:
            if key in group_lower and ";" in group_lower:
                return GROUP_TITLE_EN_MAPPING[key]

    # ── 6. 中国地市/县市台（兜底桶污染源，判据见 _looks_like_cn_local）──
    if _looks_like_cn_local(name, group):
        return "🇨🇳 中国源"

    # ── 7. 音乐（旧代码返回 '🎵 音乐'，与 categorize 的 '🎵 音乐频道' 不一致，已统一）──
    if any(k in group_lower for k in ("mtv", "music", "musique")):
        return "🎵 音乐频道"

    # ── 8. 默认：未能精确识别的频道 ─────────────────────────
    return "🌐 国际"


# ──────────────────────────────────────────────────────────────
#  categorize — 完全重写
# ──────────────────────────────────────────────────────────────
def categorize(name: str, group: str, logo: str = "") -> str:
    """分类频道，返回分组名称（按新规范）"""

    name_lower, group_lower = name.lower(), (group or "").lower()
    full_text = name_lower + " " + group_lower

    # ── 1. 央视频道 ──────────────────────────────────────────
    #  用 CCTV_RE / CETV_RE：不再依赖 \b（\b 在「数字+中文」边界不成立，
    #  历史 bug：cctv1综合 / cctv10科教 / cctv5plus 全部漏判）。
    if CCTV_RE.search(full_text):
        return "📺 央视频道"
    if CETV_RE.search(full_text) or "教育台" in full_text:
        return "📺 央视频道"
    # 源站已经明确标成「央视频道」分组：世界地理/兵器科技 这类无 cctv 字样的央视专业频道靠这条兜住
    if "央视频道" in (group or "") or "央视" in name:
        return "📺 央视频道"

    # ── 2. 各省频道（中文表 + 拼音表）─────────────────────────
    for cat, patterns in PROVINCE_KEYWORDS.items():
        if _match(name_lower, group_lower, patterns):
            return cat
    for cat, patterns in PROVINCE_LATIN.items():
        if _match(name_lower, group_lower, patterns):
            return cat
    for cat in PROVINCE_KEYWORDS:
        short = cat.replace("📺 ", "").strip()
        if short and (short + "频道") in (group or ""):
            return cat

    # ── 3. 港澳台（与 is_hk_region 共用 HK_TW_MO_RULES，唯一事实来源）──
    region = _region_category(name, group)
    if region:
        return region

    # ── 4. 卫视频道（境外/境外中文）──────────────────────────
    #  凤凰/星空 属于「境外卫视」而非港澳台本地台：分类为卫视，且 is_hk_region=False，
    #  两边口径一致（历史 bug：is_hk_region 认凤凰卫视、categorize 不认）。
    overseas_satellite = [
        r"凤凰卫视", r"鳳凰衛視", r"phoenix",
        r"星空卫视", r"星空衛視", r"\bstar\s*tv\b", r"\bstartv\b",
        r"凤凰香港台",
        r"法国中文", r"法国电视",
        r"中文电视", r"中文台",
        r"亚洲电视", r"亞洲電視", r"\batv\b",     # \batv\b：不再误伤 AricaTV/DunyaTV/Catv
        r"卫视中文",
        r"卫视(?!电影|電影|体育|體育)",   # 兜住无省份关键词的境内卫视；但不抢卫视电影/体育
    ]
    if _match(name_lower, group_lower, overseas_satellite):
        return "📡 卫视频道"

    # ── 5. 电影频道 ───────────────────────────────────────────
    movie_kw = [
        # 品牌词：必须带边界（实测 NHBollyGold/KhushbooBangla 被裸 'hbo' 误伤、
        # IAmChannel/IslamChannel 被裸 'amc' 误伤）
        r"\bhbo(?![a-z])", r"\bcinemax(?![a-z])", r"\bamc(?![a-z])",
        r"\bparamount\b", r"\bmgm(?![a-z])",
        r"star movies", r"fox movies",
        r"cinema",                       # cinema 不加 \b：PlutoTVCinemaItaliano 这类是真影院台
        r"电影频道", r"电影台", r"好莱坞电影",
        r"fx movie", r"fxmovie",
        r"好莱坞", r"影视", r"影城",
        r"movie",                        # 英文 movie：内容词，高召回优先，不加边界
        r"凤凰电影", r"卫视电影",
    ]
    if _match(name_lower, group_lower, movie_kw):
        return "🎬 电影频道"

    # ── 6. 音乐频道 ───────────────────────────────────────────
    music_kw = [
        r"channel v", r"channelv",
        r"\bmtv(?![a-z])", r"m tv",
        r"音乐电视", r"音乐频道", r"音乐台",
        r"vmv", r"v mv",
        r"华语音乐", r"中文音乐", r"流行音乐",
    ]
    if _match(name_lower, group_lower, music_kw):
        return "🎵 音乐频道"

    # ── 7. 国际新闻品牌（必须先于「国际频道」宽桶：BBC World News 属新闻，不是泛国际）──
    #  只收「品牌+国际/世界版」的确定写法；地区版（CNN Portugal / CNN Brasil）留在国际频道。
    news_strong = [
        r"\bcnn\s+(?:international|intl)\b",
        r"\bbbc\s+(?:world\s*news|world|news)\b",
    ]
    if _match(name_lower, group_lower, news_strong):
        return "📰 新闻财经"

    # ── 8. 国际频道 ───────────────────────────────────────────
    intl_kw = [
        r"bbc", r"cnn", r"al jazeera", r"aljazeera",
        r"\bnhk\b",
        # tbs 已移除：TBS（Turner）是美国综合娱乐网，不该被「国际频道」宽桶捕获
        r"france 24", r"france24",
        r"\bdw\b", r"(?<![a-z])trt(?![a-z])", r"\btv5\b", r"tv5monde",
        # tv5 加边界：VTV5TayNamBo / XinjiangTV5 / SuperTV55 不再被误判
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

    # ── 9. 新闻财经 ──────────────────────────────────────────
    news_kw = [
        r"bloomberg", r"cnbc",
        r"财经", r"金融", r"证券",
        r"新闻频道", r"新闻台",
        # \bcnn\b 漏掉 CNNInternational（"CNN"+"I" 之间无 \b）—— 这正是历史上
        # 「CNN 落 🌐 国际频道、BBC World News 落 📰 新闻财经」不一致的根因。
        r"(?<![a-z])cnn(?![a-z])", r"(?<![a-z])bbc[\s\-]*news",
        r"半岛新闻", r"半岛电视台",
        r"euronews",
        r"香港新闻", r"香港财经",
        r"凤凰财经", r"凤凰新闻",
        r"(?<![a-z])voa(?![a-z])", r"美国之音",
    ]
    if _match(name_lower, group_lower, news_kw):
        return "📰 新闻财经"

    # ── 10. 儿童频道 ─────────────────────────────────────────
    kids_kw = [
        r"cartoon network", r"cartoon",
        r"disney channel", r"disney",
        r"\bnick(?:elodeon|jr|toons)?(?![a-z])",
        r"kids",                        # Discovery Kids / Kids TV 不再因为「无 kids 规则」掉到纪录片
        r"少儿频道", r"儿童频道", r"少儿台",
        r"儿童动画", r"动漫频道", r"卡通频道",
        r"baby tv", r"babytv",
        r"boomerang",
        r"儿童电影", r"动画电影",
    ]
    if _match(name_lower, group_lower, kids_kw):
        return "🧸 儿童频道"

    # ── 11. 综艺频道 ─────────────────────────────────────────
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

    # ── 12. 体育频道 ─────────────────────────────────────────
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
        r"\bnba\b", r"\bcba\b",          # 加边界：ATNBangla / CBCTelevisionCBAT-DT 不再误判
        r"欧冠", r"英超", r"意甲", r"西甲", r"德甲", r"法甲",
        r"中超", r"亚冠",
        r"奥运", r"体育赛事",
    ]
    if _match(name_lower, group_lower, sport_kw):
        return "⚽ 体育频道"

    # ── 13. 纪录片 ───────────────────────────────────────────
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

    # ── 14. 中国地市/县市台（兜底桶最大污染源：6829 条「🌐 国际」里绝大多数是它）──
    if _looks_like_cn_local(name, group):
        return "🇨🇳 中国源"

    # ── 15. 未能分类 → 其他（二次分类）─────────────────────────
    return recategorize_others(name, group, logo)
