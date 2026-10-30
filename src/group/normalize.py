#!/usr/bin/env python3
"""Channel name normalization and merging."""
import re
from typing import Dict, List, Optional, Tuple

# -------------------------------------------------------------------
# 1. 繁简转换（常用词替换，非逐字）
# -------------------------------------------------------------------
_TC_REPLACEMENTS = [
    ("電視", "电视"), ("視頻", "视频"), ("頻道", "频道"),
    ("電台", "电台"), ("資訊", "资讯"), ("新聞", "新闻"),
    ("財經", "财经"), ("體育", "体育"), ("綜藝", "综艺"),
    ("戲劇", "戏剧"), ("電影", "电影"), ("娛樂", "娱乐"),
    ("記錄", "记录"), ("卡通", "卡通"), ("兒童", "儿童"),
    ("教育", "教育"), ("生活", "生活"), ("旅遊", "旅游"),
    ("音樂", "音乐"), ("綜合", "综合"), ("軍事", "军事"),
    ("農業", "农业"), ("社會", "社会"), ("法制", "法治"),
    ("華視", "华视"), ("中視", "中视"), ("民視", "民视"),
    ("台視", "台视"), ("公視", "公视"), ("高清", "高清"),
    ("無綫", "无线"), ("有綫", "有线"), ("衛視", "卫视"),
    ("鳳凰", "凤凰"), ("半島", "半岛"), ("澳廣", "澳广"),
    ("澳視", "澳视"), ("亞洲", "亚洲"), ("美洲", "美洲"),
    ("日本", "日本"), ("韓國", "韩国"), ("經典", "经典"),
    ("強檔", "强档"), ("家庭", "家庭"), ("簽名", "签名"),
    ("無限", "无限"), ("魅力", "魅力"), ("高球", "高球"),
    ("緯來", "纬来"), ("三立", "三立"), ("東森", "东森"),
    ("中天", "中天"), ("靖天", "靖天"), ("天映", "天映"),
    ("美亞", "美亚"), ("年代", "年代"), ("寰宇", "寰宇"),
    ("大愛", "大爱"), ("創世", "创世"), ("生命", "生命"),
    ("佛衛", "佛卫"), ("好消", "好消"), ("復興", "复兴"),
    ("人間", "人间"), ("育樂", "育乐"), ("烹飪", "烹饪"),
    ("時尚", "时尚"), ("家居", "家居"), ("汽車", "汽车"),
    ("科技", "科技"), ("探索", "探索"), ("地理", "地理"),
    ("動物", "动物"), ("野生", "野生"), ("自然", "自然"),
    ("歷史", "历史"), ("人文", "人文"), ("文化", "文化"),
    ("美食", "美食"), ("星球", "星球"), ("直播", "直播"),
    ("國際", "国际"), ("晨間", "晨间"), ("晚間", "晚间"),
    ("午間", "午间"), ("黃金", "黄金"), ("超視", "超视"),
    ("幼幼", "幼幼"), ("偶像", "偶像"), ("日韓", "日韩"),
    ("閩南", "闽南"), ("客家", "客家"), ("博斯", "博斯"),
    ("連續", "连续"), ("轉播", "转播"), ("重播", "重播"),
    ("首播", "首播"), ("海外", "海外"), ("測試", "测试"),
    ("備用", "备用"), ("官方", "官方"), ("鏡像", "镜像"),
    ("騰訊", "腾讯"), ("愛奇藝", "爱奇艺"), ("優酷", "优酷"),
    ("嗶哩", "哔哩"),
]


# -------------------------------------------------------------------
# 1b. 单字兜底表（词组表没覆盖到的繁体字）
#
# 为什么需要它：_TC_REPLACEMENTS 是「词组表」，只有恰好写进表里的**整词**才会被
# 转换。某个繁体字只要没有正好落在某个词组里，就**永远**转不了——实测
# `華麗翡翠台` / `三立台灣台` / `澳视澳門` / `澳视衛星` 四个真实频道名原样穿过，
# 因为 麗 / 灣 / 門 三个字不在任何词组里（而 華視 / 衛視 恰好在，能转）。
# 语料 1434 条频道名里有 514 个不同汉字，其中只有 77 个被词组表覆盖。
#
# 表的来源（不引入运行时依赖，纯静态数据）：
#   1) 词组表里「等长且非语义换词」的那些对，逐字拆出来的 62 个字------------
#      （如 電視→电视 ⇒ 電→电、視→视）；`法制→法治` 这类整词换义的被排除，
#      不能拆成单字，否则「民主制」会被写成「民主治」。
#   2) 语料里实际出现、但词组表没覆盖的 7 个字：區灣紀臺話門麗。
#   3) 每个字都跟 OpenCC 的 TSCharacters（单字、且只有唯一简化形式）交叉核对，
#      69 个字**零分歧**。
#      https://github.com/BYVoid/OpenCC ≡
#      https://raw.githubusercontent.com/BYVoid/OpenCC/master/data/dictionary/TSCharacters.txt
# 刻意**不**追求覆盖全部繁体（那是 OpenCC 的活儿）：表只收本项目语料/词组表
# 实测用到的字，收窄到可审计的规模。
# -------------------------------------------------------------------
_TC_CHAR_TC = (
    "亞來備優兒創劇動區嗶國娛島廣強復愛戲時會東業樂檔歷測灣無簽紀經綜綫緯續聞臺興華藝"
    "衛視訊記試話財資車軍轉農連遊錄鏡門間閩際電韓頻飪騰體鳳麗黃"
    # 線 在 OpenCC 里是「线 缐」两个候选，但两者都是「线」的异体，取 线 安全；
    # 它出现在上一代源的「有線電視」写法里，词组表只收了异体 綫（無綫/有綫）。
    "線"
)
_TC_CHAR_SC = (
    "亚来备优儿创剧动区哔国娱岛广强复爱戏时会东业乐档历测湾无签纪经综线纬续闻台兴华艺"
    "卫视讯记试话财资车军转农连游录镜门间闽际电韩频饪腾体凤丽黄"
    "线"
)
assert len(_TC_CHAR_TC) == len(_TC_CHAR_SC), "单字兜底表两张表长度必须一致"

# str.translate 用的映射表，模块加载时构建一次（热路径上不再做 str.replace）
_TC_CHAR_TABLE = str.maketrans(_TC_CHAR_TC, _TC_CHAR_SC)

# 词组级按长度倒序，保证长词优先（避免短词先把长词拆坏）
_TC_REPLACEMENTS_SORTED = sorted(_TC_REPLACEMENTS, key=lambda p: -len(p[0]))


def convert_tc_to_sc(text: str) -> str:
    """将繁体中文转换为简体中文（两层：词组表优先，单字兜底）。

    顺序不能反：词组级替换先行，才不会把「華視」这类已经写死的整词拆成
    单字后被替换成别的字；单字兜底只处理词组表没碰到的残余繁体字。
    """
    # 第一层：词组表（长词优先）
    for tc, sc in _TC_REPLACEMENTS_SORTED:
        text = text.replace(tc, sc)
    # 第二层：单字兜底
    return text.translate(_TC_CHAR_TABLE)


# -------------------------------------------------------------------
# 2. 需要去除的冗余模式（正则，按顺序应用）
# -------------------------------------------------------------------
_STRIP_PATTERNS = [
    # 1. 线路/备用标记
    re.compile(r'\s*-\s*线路\d+.*'),               #  - 线路1（大陆线路）
    re.compile(r'\s*-\s*備用\d+.*'),               #  - 備用1
    # 2. 方括号/书名号内容
    re.compile(r'\s*【[^】]*】'),                  #  【蓝光1】【官方】
    re.compile(r'\[[^\]]*\]\s*'),                 #  [BD]、[HD]、[SD] 前缀
    # 3. 随机后缀（*28、*ee 等）
    re.compile(r'\*[a-zA-Z0-9]+\s*$'),                       #  *28、*ee 等
    # 4. 括号内容（线路、分辨率、地区等）
    re.compile(r'[\(（][^)）]*线路[^)）]*[\)）]'),  # （大陆线路）（香港线路）
    re.compile(r'[\(（][^)）]*高清[^)）]*[\)）]'),  # （高清）
    re.compile(r'[\(（][^)）]*720P[^)）]*[\)）]'),  # （720P）
    re.compile(r'[\(（][^)）]*1080P[^)）]*[\)）]'), # （1080P）
    re.compile(r'[\(（][^)）]*4K[^)）]*[\)）]'),    # （4K）
    re.compile(r'[\(（][^)）]*北美版[^)）]*[\)）]'),# （北美版）
    re.compile(r'[\(（][^)）]*大陆版[^)）]*[\)）]'),# （大陆版）
    re.compile(r'[\(（][^)）]*香港[^)）]*[\)）]'),  # （香港线路）
    re.compile(r'[\(（][^)）]*\d+K[^)）]*[\)）]'),  # （8K）等
    re.compile(r'\s*[\(（][^)）]*[\)）]'),          # 残留的空括号
    # 5. 尾部分辨率（无论有无 dash）
    re.compile(r'\s*[-–—·]?\s*(1080[Pp]|720[Pp]|480[Pp]|4K|8K|HD|SD|FHD|UHD|超清|高清)\s*$', re.IGNORECASE),
    # 6. backup/备用 后缀
    re.compile(r'\s*[-–—·]?\s*backup\s*$', re.IGNORECASE),
    # 7. 多余空格
    re.compile(r'\s+'),
]


def strip_noise(name: str) -> str:
    """去除频道名中的冗余信息（线路、分辨率、地区等）"""
    result = name.strip()
    for pat in _STRIP_PATTERNS:
        result = pat.sub('', result)
    result = re.sub(r'\s+', ' ', result).strip()
    # 去除首尾的 - 、 · 等
    result = re.sub(r'^[\s\-–—·]+|[\s\-–—·]+$', '', result)
    return result


# -------------------------------------------------------------------
# 3. 核心标准化函数
# -------------------------------------------------------------------
def normalize_channel_name(name: str, aliases: Dict[str, str]) -> str:
    """
    标准化频道名称:
    1. 去除首尾空白
    2. 去除冗余信息（线路、分辨率、地区版本）
    3. 繁简转换
    4. 应用别名映射表
    """
    if not name:
        return name

    original = name
    name = name.strip()

    # 去除噪声
    name = strip_noise(name)

    # 繁简转换
    name = convert_tc_to_sc(name)

    # 去除首尾空白（繁简转换可能产生多余空格）
    name = name.strip()

    # 硬编码的特殊映射（RTHK 系列等，不在 alias.txt 的）
    _SPECIAL_MAPPING = {
        "港台电视31": "RTHK 31",
        "港台电视32": "RTHK 32",
        "港台电视33": "RTHK 33",
        # CCTV 系列（根据 Logo 标准化）
        "CCTV": "CCTV-4K",  # Logo 为 CCTV4K.png 的裸 CCTV
        # 去除重复词
        "CCTV-6 电影电影": "CCTV-6 电影",
    }
    if name in _SPECIAL_MAPPING:
        return _SPECIAL_MAPPING[name]

    # 应用别名映射（精确匹配 > 大小写不敏感匹配 > 子串匹配）
    if name in aliases:
        return aliases[name]

    name_lower = name.lower()
    for alias, canonical in aliases.items():
        if alias.lower() == name_lower:
            return canonical

    # 子串匹配：找最长匹配（只替换一次）
    # 但只在有明确边界（空格、括号、-、.、数字）时匹配，避免部分匹配
    def has_boundary(prefix: str) -> bool:
        """检查 alias 前一个字符是否是明确的边界"""
        if not prefix:
            return True  # alias 在字符串开头
        return bool(re.match(r'[\s\-–—·()（）\[\]【】\/\\\s\d\w]$', prefix))

    def is_boundary_after(suffix: str) -> bool:
        """检查 alias 后一个字符是否是明确的边界"""
        if not suffix:
            return True  # alias 在字符串结尾
        return bool(re.match(r'^[\s\-–—·()（）\[\]【】\/\\\s\d\w]', suffix))

    best_alias, best_canonical = None, None
    best_len = 0
    for alias, canonical in aliases.items():
        if alias not in name:
            continue
        # 找 alias 在 name 中的所有位置
        start = 0
        while True:
            idx = name.find(alias, start)
            if idx == -1:
                break
            prefix = name[:idx]
            suffix = name[idx + len(alias):]
            if has_boundary(prefix) and is_boundary_after(suffix):
                if len(alias) > best_len:
                    best_alias, best_canonical = alias, canonical
                    best_len = len(alias)
            start = idx + 1

    if best_alias:
        name = name.replace(best_alias, best_canonical, 1)

    # 兜底：别名替换可能把「台」叠加成「亚洲台台」（如 alias 的 TVBS亚洲 → TVBS 亚洲台
    # 命中已经以「台」结尾的名字）。频道名尾部的连续「台」永远只应保留一个。
    name = re.sub(r'台{2,}$', '台', name)

    return name


# -------------------------------------------------------------------
# 4. URL 优先级
# -------------------------------------------------------------------
def get_url_priority(url: str) -> int:
    """
    返回 URL 的优先级（数字越小优先级越高）
    1 = HK CDN (最佳)
    2 = 国内 CDN
    3 = 普通 URL
    """
    if not url:
        return 3

    # HK CDN（最优）
    hk_patterns = [
        'hkdtmb.com',
        'tdm.com.mo',
        'viutv.com',
        'now.com',
        'tvb.com',
        'rthk.hk',
        'hkcable.com.hk',
        'cable-tvc.com',
        '115.238.', '61.238.', '116.199.',
        '202.181.', '203.186.', '1.32.', '42.2.',
        '122.152.', '8.138.',
        'fm1077.serv00.net',
        'aktv.top',
        'jiduo.me',
    ]

    # 国内 CDN（次优）
    cn_cdn_patterns = [
        'jdshipin.com',
        '163189.xyz',
    ]

    for p in hk_patterns:
        if p in url:
            return 1

    for p in cn_cdn_patterns:
        if p in url:
            return 2

    return 3


# -------------------------------------------------------------------
# 5. 频道合并
# -------------------------------------------------------------------
def merge_duplicate_channels(
    channels: List[dict],
    health: Optional[Dict[str, bool]] = None,
) -> List[dict]:
    """
    合并同名频道，保留最佳 URL。

    策略:
    - 按标准化后的名称分组
    - 每组最多保留 3 个 URL（1 个最优 + 2 个备用）
    - 优先级: **已实测可播 > 未知 > 已实测不可播**，同档内 HK CDN > 国内 CDN > 普通 URL

    参数 `health` 是 `{url: bool}` 的实测快照（见 `src/lib/stream_health.py`）。
    传 `None` / `{}` 时行为与旧版完全一致 —— 只按 CDN 白名单和 URL 优先级挑。
    为什么要这个参数：2026-10-29 实测到「只做同名去重」会让可播条数从 77 掉到 53，
    因为白名单里已死链的 URL 会压过实测可播的 URL。
    """
    try:
        from src.lib.whitelist import is_hk_cdn_whitelisted
    except ImportError:
        # 回退：不做 CDN 白名单检查
        def is_hk_cdn_whitelisted(url):
            return False

    # 按标准化名称分组
    groups: Dict[str, List[dict]] = {}
    for ch in channels:
        normalized = ch.get("_normalized_name", "")
        if not normalized:
            continue
        if normalized not in groups:
            groups[normalized] = []
        groups[normalized].append(ch)

    merged = []

    for norm_name, chs in groups.items():
        # 排序键：实测可播(0) > 未知(1) > 实测不可播(2)，同档内 whitelist > HK CDN > CN CDN > 普通
        def sort_key(c):
            url = c["url"]
            known_good = 1
            if health:
                hit = health.get(url)
                if hit is True:
                    known_good = 0
                elif hit is False:
                    known_good = 2
            if is_hk_cdn_whitelisted(url):
                return (known_good, 0, 0)
            return (known_good, 1, get_url_priority(url))

        sorted_chs = sorted(chs, key=sort_key)

        # 选最优的作为主频道
        best = sorted_chs[0]

        # 构建合并后的频道
        merged_ch = best.copy()
        # 使用标准化后的规范名称显示
        merged_ch["name"] = norm_name
        merged_ch["tvg_name"] = norm_name
        merged_ch["_backup_urls"] = []

        # 最多 2 个备用 URL（不同的）
        seen_urls = {best["url"]}
        for c in sorted_chs[1:]:
            if len(merged_ch["_backup_urls"]) >= 2:
                break
            if c["url"] not in seen_urls:
                merged_ch["_backup_urls"].append(c["url"])
                seen_urls.add(c["url"])

        merged.append(merged_ch)

    return merged


# -------------------------------------------------------------------
# 6. 批量标准化+合并
# -------------------------------------------------------------------
def normalize_channels(
    channels: List[dict],
    aliases: Dict[str, str],
    health: Optional[Dict[str, bool]] = None,
) -> List[dict]:
    """
    对频道列表进行标准化和合并。
    - 标准化频道名称
    - 合并同名频道
    - 返回合并后的列表
    """
    # 1. 标准化每个频道的名称（跳过已计算过的）
    for ch in channels:
        if "_normalized_name" not in ch:
            raw_name = ch.get("tvg_name", "") or ch.get("name", "")
            ch["_normalized_name"] = normalize_channel_name(raw_name, aliases)

    # 2. 合并同名频道
    merged = merge_duplicate_channels(channels, health=health)

    return merged
