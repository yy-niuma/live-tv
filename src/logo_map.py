#!/usr/bin/env python3
"""Logo mapping for IPTV channels - tvg-logo injection."""
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent.resolve()

# EPG CDN - primary logo source (already used by many sources in the project)
EPG_LOGO_CDN = "https://epg.112114.xyz/logo/"

# Fallback CDN (i.imgur.com style from iptv-org)
IMGUR_CDN = "https://i.imgur.com"

# =============================================================================
# Logo Mapping: normalized channel name (lowercase, stripped) -> logo URL
# Priority: EPG CDN > Imgur fallback
# =============================================================================

LOGO_MAP = {
    # ========== TVB ==========
    "翡翠台":        EPG_LOGO_CDN + "翡翠台.png",
    "tvb翡翠台":     EPG_LOGO_CDN + "TVB翡翠台.png",
    "jade":          EPG_LOGO_CDN + "翡翠台.png",
    "jade tvb":      EPG_LOGO_CDN + "翡翠台.png",
    "tvb jade":      EPG_LOGO_CDN + "翡翠台.png",
    "明珠台":        EPG_LOGO_CDN + "明珠台.png",
    "tvb明珠台":     EPG_LOGO_CDN + "TVB明珠台.png",
    "pearl":         EPG_LOGO_CDN + "明珠台.png",
    "pearl tvb":     EPG_LOGO_CDN + "明珠台.png",
    "tvb pearl":     EPG_LOGO_CDN + "明珠台.png",
    "j2":            EPG_LOGO_CDN + "J2.png",
    "j2 tvb":        EPG_LOGO_CDN + "J2.png",
    "tvb j2":        EPG_LOGO_CDN + "J2.png",
    "tvb news":      EPG_LOGO_CDN + "TVB新闻.png",
    "tvb新闻台":     EPG_LOGO_CDN + "TVB新闻.png",
    "tvb电视剧台":   EPG_LOGO_CDN + "TVB电视剧.png",
    "tvb经典台":     EPG_LOGO_CDN + "TVB经典台.png",
    "tvb星河台":     EPG_LOGO_CDN + "TVB星河台.png",
    "tvb finance":   EPG_LOGO_CDN + "TVB财经.png",

    # ========== ViuTV ==========
    "viutv":         EPG_LOGO_CDN + "ViuTV.png",
    "viu tv":        EPG_LOGO_CDN + "ViuTV.png",
    "viutv6":        EPG_LOGO_CDN + "ViuTV6.png",
    "viu tv6":       EPG_LOGO_CDN + "ViuTV6.png",
    "viu":           EPG_LOGO_CDN + "ViuTV.png",
    "viutv":         EPG_LOGO_CDN + "ViuTV.png",
    "viutv直播":     EPG_LOGO_CDN + "ViuTV.png",
    "viutv综合台":   EPG_LOGO_CDN + "ViuTV.png",

    # ========== RTHK ==========
    "rthk 31":       EPG_LOGO_CDN + "RTHK%2031.png",
    "rthk 32":       EPG_LOGO_CDN + "RTHK%2032.png",
    "rthk 33":       EPG_LOGO_CDN + "RTHK%2033.png",
    "rthk 34":       EPG_LOGO_CDN + "RTHK%2034.png",
    "rthk 35":       EPG_LOGO_CDN + "RTHK%2035.png",
    "rthk tv 31":    EPG_LOGO_CDN + "RTHK%2031.png",
    "rthk tv 32":    EPG_LOGO_CDN + "RTHK%2032.png",
    "rthk tv 33":    EPG_LOGO_CDN + "RTHK%2033.png",
    "rthk tv":       EPG_LOGO_CDN + "RTHK.png",
    "rthk31":        EPG_LOGO_CDN + "RTHK%2031.png",
    "rthk32":        EPG_LOGO_CDN + "RTHK%2032.png",
    "rthk33":        EPG_LOGO_CDN + "RTHK%2033.png",
    "港台电视31":    EPG_LOGO_CDN + "RTHK%2031.png",
    "港台电视32":    EPG_LOGO_CDN + "RTHK%2032.png",
    "港台电视33":    EPG_LOGO_CDN + "RTHK%2033.png",
    "rthk":          EPG_LOGO_CDN + "RTHK.png",
    "香港电台":      EPG_LOGO_CDN + "RTHK.png",

    # ========== HOY TV ==========
    "hoy tv":        EPG_LOGO_CDN + "HOY%20TV.png",
    "hoytv":         EPG_LOGO_CDN + "HOY%20TV.png",
    "hooy":          EPG_LOGO_CDN + "HOY%20TV.png",
    "hooy tv":       EPG_LOGO_CDN + "HOY%20TV.png",
    "hoy":           EPG_LOGO_CDN + "HOY%20TV.png",
    "hooytv":        EPG_LOGO_CDN + "HOY%20TV.png",

    # ========== Now TV ==========
    "now tv":        EPG_LOGO_CDN + "NOW%20TV.png",
    "nowtv":         EPG_LOGO_CDN + "NOW%20TV.png",
    "now news":      EPG_LOGO_CDN + "NOW%20NEWS.png",
    "now直播台":     EPG_LOGO_CDN + "NOW%20TV.png",
    "now财经":       EPG_LOGO_CDN + "NOW%20%E8%B4%8F%E7%BB%8F.png",
    "now":            EPG_LOGO_CDN + "NOW%20TV.png",

    # ========== 有线电视 / Cable ==========
    "有线电视":      EPG_LOGO_CDN + "有线电视.png",
    "cable tv":      EPG_LOGO_CDN + "有线电视.png",
    "cable news":    EPG_LOGO_CDN + "有线新闻.png",
    "开电视":        EPG_LOGO_CDN + "有线电视.png",
    "hk cable":      EPG_LOGO_CDN + "有线电视.png",

    # ========== 凤凰卫视 ==========
    "凤凰卫视":      EPG_LOGO_CDN + "凤凰卫视.png",
    "凤凰香港":      EPG_LOGO_CDN + "凤凰香港.png",
    "凤凰资讯":      EPG_LOGO_CDN + "凤凰资讯.png",
    "凤凰中文台":    EPG_LOGO_CDN + "凤凰卫视.png",
    "phoenix tv":    EPG_LOGO_CDN + "凤凰卫视.png",
    "phoenix":        EPG_LOGO_CDN + "凤凰卫视.png",

    # ========== TVBS (Taiwan) ==========
    "tvbs":          EPG_LOGO_CDN + "TVBS.png",
    "tvbs新闻":      EPG_LOGO_CDN + "TVBS%E6%96%B0%E8%81%9E.png",
    "tvbs新聞":      EPG_LOGO_CDN + "TVBS%E6%96%B0%E8%81%9E.png",
    "tvbs新闻台":    EPG_LOGO_CDN + "TVBS%E6%96%B0%E8%81%9E.png",
    "tvbs亚洲":      EPG_LOGO_CDN + "TVBS%E4%BA%9E%E6%B4%B2.png",
    "tvbs閩南":      EPG_LOGO_CDN + "TVBS%E9%96%86%E5%8D%97.png",
    "tvbs综合台":    EPG_LOGO_CDN + "TVBS%E7%BB%BC%E5%90%88.png",
    "tvbs戏剧台":    EPG_LOGO_CDN + "TVBS%E6%88%8F%E5%8A%87.png",
    "tvbs东方台":    EPG_LOGO_CDN + "TVBS%E6%9D%B1%E6%96%B9.png",

    # ========== Taiwan Channels ==========
    "台视":          EPG_LOGO_CDN + "台视.png",
    "中视":          EPG_LOGO_CDN + "中视.png",
    "华视":          EPG_LOGO_CDN + "华视.png",
    "民视":          EPG_LOGO_CDN + "民视.png",
    "东森":          EPG_LOGO_CDN + "东森.png",
    "東森":          EPG_LOGO_CDN + "东森.png",
    "东森美洲卫视":  EPG_LOGO_CDN + "东森.png",
    "東森美洲衛視":  EPG_LOGO_CDN + "东森.png",
    "东森超视":      EPG_LOGO_CDN + "东森%E8%B6%85%E8%A6%96.png",
    "东森超视34":    EPG_LOGO_CDN + "东森%E8%B6%85%E8%A6%96.png",
    "东森新闻":      EPG_LOGO_CDN + "东森%E6%96%B0%E8%81%9E.png",
    "三立":          EPG_LOGO_CDN + "三立.png",
    "三立新闻":      EPG_LOGO_CDN + "三立%E6%96%B0%E8%81%9E.png",
    "三立新聞":      EPG_LOGO_CDN + "三立%E6%96%B0%E8%81%9E.png",
    "三立綜合":      EPG_LOGO_CDN + "三立%E7%BB%BC%E5%90%88.png",
    "三立综合":      EPG_LOGO_CDN + "三立%E7%BB%BC%E5%90%88.png",
    "三立台湾台":    EPG_LOGO_CDN + "三立.png",
    "set三立":       EPG_LOGO_CDN + "三立.png",
    "set三立戏剧":   EPG_LOGO_CDN + "三立%E5%8A%87%E5%8A%87.png",
    "非凡":          EPG_LOGO_CDN + "非凡.png",
    "大爱":          EPG_LOGO_CDN + "大爱.png",
    "大爱电视台":    EPG_LOGO_CDN + "大爱.png",
    "公视":          EPG_LOGO_CDN + "公视.png",
    "公共电视":      EPG_LOGO_CDN + "公视.png",
    "客家":          EPG_LOGO_CDN + "客家.png",
    "客家电视台":    EPG_LOGO_CDN + "客家.png",
    "原住民":        EPG_LOGO_CDN + "原住民.png",
    "原住民电视台":  EPG_LOGO_CDN + "原住民.png",
    "台视新闻":      EPG_LOGO_CDN + "台视%E6%96%B0%E8%81%9E.png",
    "中视新闻":      EPG_LOGO_CDN + "中视%E6%96%B0%E8%81%9E.png",
    "华视新闻":      EPG_LOGO_CDN + "华视%E6%96%B0%E8%81%9E.png",
    "民视新闻台":    EPG_LOGO_CDN + "民视%E6%96%B0%E8%81%9E.png",

    # ========== Macau ==========
    "澳门":          EPG_LOGO_CDN + "澳门.png",
    "澳視":          EPG_LOGO_CDN + "澳视.png",
    "澳广视":        EPG_LOGO_CDN + "澳广视.png",
    "macau":         EPG_LOGO_CDN + "澳门.png",

    # ========== News Channels ==========
    "cnn":           IMGUR_CDN + "/KNQYvax.png",
    "bbc world":     IMGUR_CDN + "/4SSHER2.png",
    "bbc news":      IMGUR_CDN + "/4SSHER2.png",
    "半岛电视台":    IMGUR_CDN + "/fpWlNuG.png",
    "al jazeera":    IMGUR_CDN + "/fpWlNuG.png",
    "dw":            IMGUR_CDN + "/TOTuWa5.png",
    "france 24":     IMGUR_CDN + "/TOTuWa5.png",

    # ========== Sports ==========
    "espn":          IMGUR_CDN + "/qOsMXWj.png",
    "fox sports":    IMGUR_CDN + "/qOsMXWj.png",
    "bein sport":    IMGUR_CDN + "/qOsMXWj.png",
    "supersport":    IMGUR_CDN + "/qOsMXWj.png",
    "体育台":        EPG_LOGO_CDN + "体育.png",

    # ========== Movie / Entertainment ==========
    "hbo":           IMGUR_CDN + "/E6RdZfK.png",
    "cinemax":       IMGUR_CDN + "/E6RdZfK.png",
    "star movies":   IMGUR_CDN + "/E6RdZfK.png",
    "fox movies":    IMGUR_CDN + "/E6RdZfK.png",
    "卫视电影台":    IMGUR_CDN + "/E6RdZfK.png",
    "cinema":        IMGUR_CDN + "/E6RdZfK.png",
    "电影台":        EPG_LOGO_CDN + "电影.png",
    "amc电影台":     IMGUR_CDN + "/E6RdZfK.png",
    "AMC電影台":     IMGUR_CDN + "/E6RdZfK.png",
    "amc":           IMGUR_CDN + "/E6RdZfK.png",
    "animax":        IMGUR_CDN + "/YwbjcsE.png",
    "animax_":       IMGUR_CDN + "/YwbjcsE.png",
    "ftv":           IMGUR_CDN + "/E6RdZfK.png",
    "时尚台ftv":     IMGUR_CDN + "/E6RdZfK.png",
    "g tv八大第1台":  EPG_LOGO_CDN + "八大.png",
    "g tv八大第1台hd": EPG_LOGO_CDN + "八大.png",
    "g tv八大戲劇hd": EPG_LOGO_CDN + "八大.png",
    "g tv八大综合台hd": EPG_LOGO_CDN + "八大.png",
    "八大第1台":      EPG_LOGO_CDN + "八大.png",
    "八大戲劇":       EPG_LOGO_CDN + "八大.png",
    "八大综合台":     EPG_LOGO_CDN + "八大.png",
    "hits电影频道":   IMGUR_CDN + "/E6RdZfK.png",
    "rock影综":      EPG_LOGO_CDN + "电影.png",

    # ========== Kids ==========
    "nick":          IMGUR_CDN + "/YwbjcsE.png",
    "nickelodeon":   IMGUR_CDN + "/YwbjcsE.png",
    "disney":        IMGUR_CDN + "/YwbjcsE.png",
    "disney channel": IMGUR_CDN + "/YwbjcsE.png",
    "卡通台":        EPG_LOGO_CDN + "儿童.png",
    "儿童台":        EPG_LOGO_CDN + "儿童.png",
    "动画台":        EPG_LOGO_CDN + "儿童.png",

    # ========== Documentary ==========
    "discovery":     IMGUR_CDN + "/TxfOCxi.png",
    "national geographic": IMGUR_CDN + "/TxfOCxi.png",
    "nat geo":       IMGUR_CDN + "/TxfOCxi.png",
    "history":       IMGUR_CDN + "/TxfOCxi.png",
    "动物频道":      EPG_LOGO_CDN + "动物.png",
    "国家地理":      IMGUR_CDN + "/TxfOCxi.png",
    "國家地理":      IMGUR_CDN + "/TxfOCxi.png",
    "nhk":           EPG_LOGO_CDN + "NHK.png",
    "nhk world":     EPG_LOGO_CDN + "NHK.png",
    "nhk_world":     EPG_LOGO_CDN + "NHK.png",

    # ========== Music ==========
    "channel v":     IMGUR_CDN + "/TxfOCxi.png",
    "mtv":           IMGUR_CDN + "/TxfOCxi.png",
    "音乐台":        EPG_LOGO_CDN + "音乐.png",

    # ========== Others ==========
    "星空":          EPG_LOGO_CDN + "星空.png",
    "star tv":       EPG_LOGO_CDN + "星空.png",
    "无线台":        EPG_LOGO_CDN + "无线.png",
}


def normalize(name: str) -> str:
    """Normalize channel name for matching: lowercase, strip spaces/punctuation."""
    import re
    name = name.lower().strip()
    # Remove common EXTINF noise: channel number prefix like "1.", "001."
    name = re.sub(r'^[\d\-\.]+\s*', '', name)
    # Remove parenthetical suffix like "(1080p)", "(Geo-blocked)"
    name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
    # Remove punctuation except Chinese chars
    name = re.sub(r'[^\w\s\u4e00-\u9fff]', '', name)
    # Normalize spaces
    name = ' '.join(name.split())
    return name


def get_logo(channel_name: str) -> str | None:
    """Look up logo URL by channel name. Returns None if no match."""
    norm = normalize(channel_name)
    return LOGO_MAP.get(norm)


def get_logo_with_fallback(channel_name: str, existing_logo: str) -> str:
    """Get logo URL: use mapping if available, otherwise keep existing."""
    mapped = get_logo(channel_name)
    if mapped:
        return mapped
    return existing_logo if existing_logo else ""


# Auto-generate case-insensitive lookup dict
LOGO_MAP_CASE = {}
for k, v in LOGO_MAP.items():
    LOGO_MAP_CASE[k.lower()] = v


def get_logo_fuzzy(channel_name: str) -> str | None:
    """Fuzzy match: try exact, then prefix parts, then safe contains."""
    norm = normalize(channel_name)
    # Try exact normalized match
    if norm in LOGO_MAP_CASE:
        return LOGO_MAP_CASE[norm]
    # Try "name without suffix" match (progressively shorter prefixes)
    parts = norm.split()
    if parts:
        for i in range(len(parts), 0, -1):
            key = ' '.join(parts[:i])
            if key in LOGO_MAP_CASE:
                return LOGO_MAP_CASE[key]
    # Try safe contains match: key must be >= 5 chars to avoid false positives
    # (e.g., "jade" matching "al jadeed")
    for key, url in LOGO_MAP_CASE.items():
        if len(key) >= 5 and (key in norm or norm in key):
            return url
    return None
