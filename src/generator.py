"""生成模块：生成 m3u 格式、EPG 支持"""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.logo_map import get_logo_fuzzy
from src.group.categorizer import is_hk_region as _is_hk_region


# EPG URL
EPG_URL = "https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"

# 产物 manifest 文件名（与两个 m3u 同目录）
MANIFEST_NAME = "manifest.json"

# ALL 播放列表每个分组最多写出多少条。
# 注意：**数值未改动**（历史上就是 `channels[:100]`），这里只是把散在写入逻辑
# 与 manifest 计数里的同一个字面量收成一个常量，避免两处漂移。
GROUP_CAP = 100

# 备选链路行的前缀（见 build_backup_lines 的说明）
BACKUP_TAG = "#EXTBACKUP:"

# 分类排序顺序
# 注意：本表必须与 src/group/categorizer.py 实际能产出的分类保持一一对应。
# 历史问题：表里有 13 个分类 categorize() 从不产出（📺 其他、🇯🇵 日本…🌏 大洋洲），
# 而实际产出的 🇨🇳 中国源 / 🇲🇾 马来西亚 / 🌐 国际 不在表内，排序落到最后一档。
# 维护约定：新增分类时同时改这里 + tests 里的分类清单断言。
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
    # 中国地市/县市台 + 未细分的国内源
    "🇨🇳 中国源",
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
    # 国际（"国际频道" = 有明确国家/品牌标记的国际台；"国际" = 无 genre 的全球长尾）
    "🇲🇾 马来西亚",
    "🌐 国际频道",
    "🌐 国际",
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
    # ── 以下为「预留但当前不产出」的分组 ──────────────────────────────
    # categorize() 目前不会返回它们（实测 13470 条语料 0 命中）。保留是为了不破坏
    # 旧产物排序与 tests/test_generator.py 的 sort_key 断言；要么实现产地识别，要么连同
    # 测试一起删除（见 docs/categorize-improvement-proposal.md §2.3 TODO-3）。
    # 注意：`📺 有线电视` 不在此预留块内（它在上面港澳台那行），但它在语料上同样 0 命中；
    # 那是语料没覆盖到，不是产不出来 —— categorize("有线电视新闻", "") 实测返回它。
    "🇯🇵 日本", "🇰🇷 韩国", "🌏 亚洲（东南亚）", "🇮🇳 印度", "🌏 亚洲（其他）",
    "🌍 欧洲", "🇺🇸 北美", "🌎 拉丁美洲", "🌍 中东", "🌍 非洲", "🌏 大洋洲",
    "📺 其他",
]

# 分类全集，供生成端做一致性断言（见 docs/categorize-improvement-proposal.md §4）
KNOWN_CATEGORIES = frozenset(CATEGORY_ORDER)


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


def get_backup_urls(ch: Any) -> List[str]:
    """取出该频道可用的备选链路（已去空、去重、去主 URL、拒绝含换行的值）。

    `_backup_urls` 是 `src/group/normalize.py:merge_duplicate_channels()` 在合并
    同名频道时算出来的，`src/grouper.py` 把 merged dict 转回 Channel 时挂成动态属性
    （不改 Channel 字段，那属于采集层的文件）。这里对缺失/脏值一律宽容，坏一条
    备链只丢一条，不影响主链与产物结构。
    """
    raw = getattr(ch, "_backup_urls", None) or []
    if isinstance(raw, str):  # 防御：有人误传单个 URL
        raw = [raw]
    primary = (ch.url or "").strip()
    seen = {primary}
    out: List[str] = []
    for url in raw:
        if not isinstance(url, str):
            continue
        url = url.strip()
        if not url or url in seen:
            continue
        if "\n" in url or "\r" in url:
            # 一个坏 URL 能伪造出额外的行（进而被解析器当成新频道），必须拒
            continue
        seen.add(url)
        out.append(url)
    return out


def build_backup_lines(ch: Any) -> List[str]:
    """把备选链路渲染成注释行。

    为什么用 `#EXTBACKUP:` 注释行，而不是「同一频道多写一条 #EXTINF」：
      1. m3u 没有标准的「一条目多 URL」语法。多写 #EXTINF 会被所有播放器当成
         独立频道，同时让产物计数（tests 的 _parse、scripts/check_streams.py 的
         parse_m3u、scripts/check_output.py 的 EXTINF 计数）全部虚高。
      2. 以 `#` 开头的行是注释/未知指令：按 m3u 约定解析器只消费已知指令，
         其余跳过。于是「#EXTINF 紧跟主 URL」这条一一对应关系完好，播放器照旧
         播放主链，备链对它们是纯注释。
      3. 备链写在主 URL 的**下一行**，靠相邻性绑定到这个频道 —— 人和工具都能
         逐行读回做 failover，不需要另建索引。
    """
    return [f"{BACKUP_TAG}{url}" for url in get_backup_urls(ch)]


def channel_sort_key(ch: Any) -> tuple:
    """分组内频道的确定排序键：频道名为主键，URL 为次键。

    为什么要它：分组列表此前来自抓取/set 遍历顺序，同一份输入在不同进程里可能
    给出不同顺序（PYTHONHASHSEED / set 迭代序），产物 diff 充满噪音，也无法用
    sha256 判断「产物有没有真的变」。按 (name, url) 排序后，同输入 → 同输出，
    且截断（GROUP_CAP）挑走的那 100 条也是确定的。
    """
    return ((ch.name or ""), (ch.url or ""))


def build_extinf(ch: Any, group: str = "") -> str:
    """构建 EXTINF 行

    属性顺序沿用源里的习惯：tvg-id → tvg-name → tvg-logo → group-title。
    tvg-id 是 EPG 主键：产物头部已经声明了 x-tvg-url，没有这个键播放器就
    绑不上节目表。频道没有 id（源里本来就没有）时**不写** tvg-id 属性 ——
    写 `tvg-id=""` 会让部分播放器按空键去查，比缺省更糟。
    """
    attrs = []

    # 用 getattr 而不是 ch.id：build_extinf 是鸭子类型入参（测试/旧调用会传
    # 只有 name/url/logo/group 的轻量对象），缺属性时退化为「没有 id」
    tvg_id = getattr(ch, "id", "") or ""
    if isinstance(tvg_id, str) and tvg_id.strip():
        attrs.append(f'tvg-id="{tvg_id.strip()}"')
    if ch.name:
        attrs.append(f'tvg-name="{ch.name}"')
    logo = ch.logo if ch.logo else get_logo_fuzzy(ch.name)
    if logo:
        attrs.append(f'tvg-logo="{logo}"')
    if group:
        attrs.append(f'group-title="{group}"')

    attr_str = " ".join(attrs) if attrs else ""
    return f"#EXTINF:-1 {attr_str},{ch.name}"


def sha256_of_file(path: str) -> str:
    """对**落盘后的文件**真算 sha256（64 位小写十六进制），不信任调用方传值。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_short_commit(repo_root: Optional[Path] = None) -> str:
    """当前工作树 HEAD 的短 hash。无 git / 非仓库 / 超时 / 无提交一律返回空串。"""
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        # 没装 git、不在仓库、超时 —— 版本号缺失不该让产物生成失败
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def tool_version(repo_root: Optional[Path] = None) -> str:
    """产物来源版本：`src.__version__` 常量 +（可用时）git 短 hash。

    刻意不写死任何 commit hash：hash 由 git 现场取，取不到就退回常量，
    常量也拿不到才写 "unknown"。
    """
    base = ""
    try:
        import src as _src_pkg

        base = str(getattr(_src_pkg, "__version__", "") or "").strip()
    except Exception:
        base = ""
    commit = _git_short_commit(repo_root)
    if commit:
        return f"{base}+git{commit}" if base else f"git{commit}"
    return base or "unknown"


def write_manifest(
    output_dir: str,
    files: Dict[str, Dict[str, Any]],
    group_counts: Dict[str, int],
    groups_file: str = "all_merged.m3u",
    repo_root: Optional[Path] = None,
) -> str:
    """写 `manifest.json`，供订阅者判断产物新旧/完整性。

    结构::

        {
          "generated_at": "2026-10-30T14:03:11+08:00",   # ISO8601，带时区
          "tool_version": "1.0.0+git6656715",             # 常量 + 现场取的 git 短 hash
          "groups_file": "all_merged.m3u",                # groups 描述的是哪个文件
          "files": {"all_merged.m3u": {"sha256", "bytes", "channels", "groups"}, ...},
          "groups": {"📺 TVB": 8, ...}                    # 分组名 → 该组实际写出条数
        }

    `channels` 是**真正写进文件**的条数（ALL 列表已受 GROUP_CAP 截断），
    `_EXTGRP:` 里声明的是截断前的总数 —— 两者故意不相等，见 tests。
    """
    payload_files: Dict[str, Dict[str, Any]] = {}
    for name, info in files.items():
        path = os.path.join(output_dir, name)
        payload_files[name] = {
            "sha256": sha256_of_file(path),
            "bytes": os.path.getsize(path),
            "channels": int(info.get("channels", 0)),
            "groups": int(info.get("groups", 0)),
        }

    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool_version": tool_version(repo_root),
        "groups_file": groups_file,
        "files": payload_files,
        "groups": {cat: int(group_counts[cat]) for cat in sorted(group_counts, key=sort_key)},
    }

    path = os.path.join(output_dir, MANIFEST_NAME)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    return path


class Generator:
    """m3u 播放列表生成器"""

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

            # 组内定序（name 主键、url 次键）：同输入 → 同输出，截断挑谁也是确定的
            if hk_channels:
                hk_grouped[cat] = sorted(hk_channels, key=channel_sort_key)
            if all_channels:
                all_grouped[cat] = sorted(all_channels, key=channel_sort_key)

        total_hk = sum(len(v) for v in hk_grouped.values())
        total_all = sum(len(v) for v in all_grouped.values())

        # 实际写出条数（ALL 列表受 GROUP_CAP 截断，HK 列表不截断）
        written_by_group = {
            cat: min(len(chs), GROUP_CAP) for cat, chs in all_grouped.items()
        }
        written_all = sum(written_by_group.values())
        written_hk = total_hk

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
                # 备链紧跟主 URL：计数不变、解析口径不变（以 # 开头的行是注释）
                hk_lines.extend(build_backup_lines(ch))
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
            # ALL 播放列表每个分组最多 GROUP_CAP 个
            for ch in channels[:GROUP_CAP]:
                all_lines.append(build_extinf(ch, cat))
                all_lines.append(ch.url)
                all_lines.extend(build_backup_lines(ch))
            if len(channels) > GROUP_CAP:
                all_lines.append(f"# ... and {len(channels) - GROUP_CAP} more")
            all_lines.append('')

        all_path = os.path.join(output_dir, "all_merged.m3u")
        with open(all_path, "w", encoding="utf-8") as f:
            f.write('\n'.join(all_lines))

        # 两个 m3u 都落盘后再写 manifest（sha256 必须是对最终文件真算出来的）
        write_manifest(
            output_dir,
            files={
                "all_merged.m3u": {"channels": written_all, "groups": len(all_grouped)},
                "hk_merged.m3u": {"channels": written_hk, "groups": len(hk_grouped)},
            },
            group_counts=written_by_group,
        )

        return {
            "hk": {"file": hk_path, "channels": total_hk, "groups": len(hk_grouped)},
            "all": {"file": all_path, "channels": total_all, "groups": len(all_grouped)}
        }
