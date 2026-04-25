"""生成模块：生成 m3u 格式、EPG 支持"""
import os
import re
from datetime import datetime
from typing import Dict, Any, List

from src.logo_map import get_logo_fuzzy
from src.group.categorizer import is_hk_region as _is_hk_region


# EPG URL
EPG_URL = "https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"

# 分类排序顺序
CATEGORY_ORDER = [
    # 央视频道
    "📺 央视频道",
    # 各省频道
    "📺 北京", "📺 上海", "📺 广东", "📺 深圳", "📺 浙江", "📺 江苏",
    "📺 湖南", "📺 安徽", "📺 山东", "📺 四川", "📺 湖北",
    "📺 福建", "📺 陕西", "📺 黑龙江", "📺 吉林", "📺 辽宁",
    "📺 河北", "📺 河南", "📺 江西", "📺 山西", "📺 内蒙古",
    "📺 宁夏", "📺 青海", "📺 甘肃", "📺 新疆", "📺 西藏",
    "📺 贵州", "📺 云南", "📺 广西", "📺 海南", "📺 重庆",
    "📺 天津",
    # 卫视频道
    "📡 卫视频道",
    # 港澳台
    "📺 TVB", "📺 ViuTV", "📺 RTHK", "📺 HOY TV", "📺 Now TV",
    "📺 有线电视",
    "🇹🇼 台湾", "🇲🇴 澳门",
    # 电影
    "🎬 电影频道",
    # 音乐
    "🎵 音乐频道",
    # 国际（细分）
    "🇯🇵 日本", "🇰🇷 韩国", "🌏 亚洲（东南亚）", "🇮🇳 印度", "🌏 亚洲（其他）",
    "🌍 欧洲", "🇺🇸 北美", "🌎 拉丁美洲", "🌍 中东", "🌍 非洲", "🌏 大洋洲",
    "🌐 国际频道",
    # 新闻财经
    "📰 新闻财经",
    # 儿童
    "🧸 儿童频道",
    # 综艺
    "🎭 综艺频道",
    # 体育
    "⚽ 体育频道",
    # 纪录片
    "📺 纪录片",
    # 其他
    "📺 其他",
]


def sort_key(cat: str) -> tuple:
    """Sort key for category ordering."""
    try:
        return (0, CATEGORY_ORDER.index(cat))
    except ValueError:
        return (1, cat)


DIRTY_PATTERNS = [
    "chrome/", "chrome\\", "safari", "likegecko", "like gecko",
    "edg/", "edge/", "webkit",
    "group-title=\"#EXTGRP",  # 残留的分组标记
]

def is_clean_name(name: str) -> bool:
    """检查频道名是否干净（排除 M3U 解析失败的脏数据）"""
    if not name or len(name) < 2:
        return False
    n_lower = name.lower()
    # 过滤含浏览器标识的损坏名称
    if any(p in n_lower for p in DIRTY_PATTERNS):
        return False
    # 过滤 URL 残留（名称看起来像 URL）
    if "http" in n_lower and ("tvg-logo" in n_lower or ".png" in n_lower or ".jpg" in n_lower):
        return False
    return True


def build_extinf(ch: Any, group: str = "") -> str:
    """构建 EXTINF 行"""
    attrs = []

    if ch.name:
        attrs.append(f'tvg-name="{ch.name}"')
    logo = ch.logo if ch.logo else get_logo_fuzzy(ch.name)
    if logo:
        attrs.append(f'tvg-logo="{logo}"')
    if group:
        attrs.append(f'group-title="{group}"')

    attr_str = " ".join(attrs) if attrs else ""
    return f"#EXTINF:-1 {attr_str},{ch.name}"


class Generator:
    """m3u 播放列表生成器"""

    def __init__(self):
        pass

    def generate_hk_and_all(
        self, grouped: Dict[str, List], output_dir: str
    ) -> Dict[str, dict]:
        """生成 hk_merged.m3u 和 all_merged.m3u"""
        os.makedirs(output_dir, exist_ok=True)

        # 分离港台频道
        hk_grouped: Dict[str, List] = {}
        all_grouped: Dict[str, List] = {}

        for cat, channels in grouped.items():
            hk_channels = []
            all_channels = []

            for ch in channels:
                if not is_clean_name(ch.name):
                    continue  # 跳过脏数据（M3U 解析失败的条目）
                if _is_hk_region(ch.name, ch.group, cat):
                    hk_channels.append(ch)
                all_channels.append(ch)

            if hk_channels:
                hk_grouped[cat] = hk_channels
            if all_channels:
                all_grouped[cat] = all_channels

        total_hk = sum(len(v) for v in hk_grouped.values())
        total_all = sum(len(v) for v in all_grouped.values())

        # 生成 HK 播放列表
        hk_lines = [
            f'#EXTM3U x-tvg-url="{EPG_URL}"',
            '#EXTVLCOPT:network-caching=1000',
            '#EXTVLCOPT:live-cache=1000',
            '#EXTVLCOPT:ttl=5',
            f'#PLAYLIST:HK & TW IPTV {datetime.now().strftime("%Y-%m-%d")}',
            f'# Total: {total_hk} channels, {len(hk_grouped)} categories',
            '']

        for cat, channels in sorted(hk_grouped.items(), key=lambda x: sort_key(x[0])):
            hk_lines.append(f"#EXTGRP:{cat} ({len(channels)})")
            for ch in channels:
                hk_lines.append(build_extinf(ch, cat))
                hk_lines.append(ch.url)
            hk_lines.append('')

        hk_path = os.path.join(output_dir, "hk_merged.m3u")
        with open(hk_path, "w", encoding="utf-8") as f:
            f.write('\n'.join(hk_lines))

        # 生成 ALL 播放列表
        all_lines = [
            f'#EXTM3U x-tvg-url="{EPG_URL}"',
            '#EXTVLCOPT:network-caching=1000',
            '#EXTVLCOPT:live-cache=1000',
            '#EXTVLCOPT:ttl=5',
            f'#PLAYLIST:All IPTV {datetime.now().strftime("%Y-%m-%d")}',
            f'# Total: {total_all} channels, {len(all_grouped)} categories',
            '']

        for cat, channels in sorted(all_grouped.items(), key=lambda x: sort_key(x[0])):
            all_lines.append(f"#EXTGRP:{cat} ({len(channels)})")
            # ALL 播放列表每个分组最多 100 个
            for ch in channels[:100]:
                all_lines.append(build_extinf(ch, cat))
                all_lines.append(ch.url)
            if len(channels) > 100:
                all_lines.append(f"# ... and {len(channels) - 100} more")
            all_lines.append('')

        all_path = os.path.join(output_dir, "all_merged.m3u")
        with open(all_path, "w", encoding="utf-8") as f:
            f.write('\n'.join(all_lines))

        return {
            "hk": {"file": hk_path, "channels": total_hk, "groups": len(hk_grouped)},
            "all": {"file": all_path, "channels": total_all, "groups": len(all_grouped)}
        }
