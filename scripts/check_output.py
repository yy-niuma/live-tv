#!/usr/bin/env python3
"""产物保险丝 —— 校验真实交付物，而不是生成器自报的计数器。

背景（2026-10-29 实测）：
    output/stats.json      总数 8450（51 个分组，**分组后、脏名过滤前**的计数）
    output/all_merged.m3u  EXTINF 实际 1168 条（Σmin(K,100)，ΣK=8168，隐藏 7000）
    output/hk_merged.m3u   EXTINF 实际 33 条（不截断）
旧版保险丝只读 stats.json，于是把 ``src/generator.py`` 里设计内的
``channels[:100]`` 误改成 ``channels[:1]`` 也能 PASS —— 统计照旧 8450，
交付物只剩 51 条。本版直接数 m3u，把这类失效变成红灯。

检查项：
  1. 统计底线：stats.json 频道总数 >= MIN_TOTAL_CHANNELS；港澳台计数 != 0。
  2. 交付物数量：all_merged.m3u / hk_merged.m3u 的 EXTINF 行数 >= 实测下限。
  3. 分组覆盖：stats.json 的每个分组在 all_merged.m3u 里至少有 1 条 EXTINF，
     且两个文件的分组集合必须一致（多出/缺少都报）。
  4. 头部一致：``# Total: N channels, M categories`` 的 N 必须等于该文件
     各 ``#EXTGRP:(K)`` 的 K 之和，M 必须等于分段数；N 不得超过 stats.json
     总数（m3u 是统计集合经 ``is_clean_name`` 过滤后的子集，只能更少）。
  5. 分组上限一致（核心）：每段 EXTINF 数必须等于 ``min(K, GROUP_CAP)``；
     K > GROUP_CAP 时必须存在 ``# ... and K-GROUP_CAP more`` 标记行，且剩余
     条数与之精确相等；K <= GROUP_CAP 时不得出现任何超额标记。
  6. 香港列表：不做上限截断，声明数必须等于实际数；总数不得超过统计港澳台数。

阈值依据（实测值 + 余量，勿凭感觉调）：
    MIN_TOTAL_EXTINF = 1000
        实测 1168 = 9 个超限分组各 100（=900）+ 其余 42 组共 268。
        取 1000 即要求小分组仍贡献 >=100（容忍其从 268 萎缩 -63%）。
        上限被改成 cap<82 时本条会红；改成 cap=1 时只剩约 277 条，红。
    MIN_HK_CHANNELS = 20
        实测 33；历史逐日 32/32/32/32/33（reports/audit-b-pipeline.md）。
        取 20 留 39% 余量，只防"香港列表被清空/砍半"，不防缓慢漂移。

已知未固定的事实（见 reports/，属 src 缺陷，本脚本不改 src）：
    stats.json 港澳台合计 44 而 hk_merged.m3u 只有 33。差额 11 = 12 条被
    ``is_hk_region()`` 漏判 - 1 条跨组捞回（华丽翡翠台，logo 判为 🇨🇳 中国源）。
    因此这里只断言"hk 列表 <= stats 港澳台"这条弱不变量。

用法：
    python scripts/check_output.py                       # 默认 output/stats.json
    python scripts/check_output.py path/to/stats.json     # m3u 取同目录兄弟文件
    python scripts/check_output.py stats.json --all-m3u a.m3u --hk-m3u h.m3u

退出码：
    0  全部检查通过
    1  任一检查失败（文件缺失、JSON 损坏、计数过小、分组缺失、上限不一致……）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── 阈值 / 常量 ────────────────────────────────────────────────
MIN_TOTAL_CHANNELS = 3000
MIN_TOTAL_EXTINF = 1000
MIN_HK_CHANNELS = 20
GROUP_CAP = 100

DEFAULT_STATS_PATH = Path("output/stats.json")
ALL_M3U_NAME = "all_merged.m3u"
HK_M3U_NAME = "hk_merged.m3u"

# stats.json 的 key 是分组名，港澳台相关分组目前是：
# 📺 TVB / 📺 ViuTV / 📺 RTHK / 📺 HOY TV / 📺 Now TV / 🇹🇼 台湾 / 🇲🇴 澳门
# 用子串匹配（小写比较）避免分组名微调后保险丝失灵。
HK_GROUP_KEYWORDS = ("tvb", "viutv", "rthk", "hoy", "now", "台湾", "澳门")

EXTINF_PREFIX = "#EXTINF"
EXTGRP_RE = re.compile(r"^#EXTGRP:(?P<name>.+) \((?P<declared>\d+)\)\s*$")
MORE_RE = re.compile(r"^#\s*\.\.\.\s*and\s+(?P<rest>\d+)\s+more\s*$")
HEADER_RE = re.compile(
    r"^#\s*Total:\s*(?P<total>\d+)\s*channels,\s*(?P<cats>\d+)\s*categories"
)


class OutputCheckError(Exception):
    """产物不满足底线条件（致命，后续检查无法继续）。"""


@dataclass
class Segment:
    """m3u 里一个 ``#EXTGRP:名称 (K)`` 分段。"""

    name: str
    declared: int
    line_no: int
    extinf: int = 0
    more: int | None = None
    more_line_no: int = 0


@dataclass
class Playlist:
    """解析后的 m3u 交付物。"""

    path: Path
    header_total: int | None = None
    header_categories: int | None = None
    header_line_no: int = 0
    segments: list[Segment] = field(default_factory=list)
    orphan_extinf: int = 0

    @property
    def declared_total(self) -> int:
        return sum(seg.declared for seg in self.segments)

    @property
    def extinf_total(self) -> int:
        return sum(seg.extinf for seg in self.segments)

    @property
    def hidden_total(self) -> int:
        """被 GROUP_CAP 截断隐藏的条数 = ΣK - Σmin(K, cap)。"""
        return sum(max(0, seg.declared - GROUP_CAP) for seg in self.segments)


# ── stats.json ────────────────────────────────────────────────
def load_stats(path: Path = DEFAULT_STATS_PATH) -> dict[str, int]:
    """读取并解析 stats.json，任何异常都转成 OutputCheckError。"""
    if not path.exists():
        raise OutputCheckError(f"找不到产物统计文件: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OutputCheckError(f"{path} 无法解析为 JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise OutputCheckError(
            f"{path} 顶层应为对象（分组名 → 频道数），实际是 {type(raw).__name__}"
        )

    stats: dict[str, int] = {}
    for group, count in raw.items():
        if isinstance(count, bool) or not isinstance(count, int):
            raise OutputCheckError(f"{path} 中分组 {group!r} 的计数不是整数: {count!r}")
        if count < 0:
            raise OutputCheckError(f"{path} 中分组 {group!r} 的计数为负数: {count}")
        stats[str(group)] = count
    if not stats:
        raise OutputCheckError(f"{path} 是空对象（没有任何分组）")
    return stats


def is_hk_group(group: str) -> bool:
    lowered = group.lower()
    return any(keyword in lowered for keyword in HK_GROUP_KEYWORDS)


def summarize(stats: dict[str, int]) -> tuple[int, int]:
    """返回 (频道总数, 港澳台频道数)。"""
    total = sum(stats.values())
    hk = sum(n for group, n in stats.items() if is_hk_group(group))
    return total, hk


def check_stats(stats: dict[str, int], min_total: int = MIN_TOTAL_CHANNELS) -> list[str]:
    """统计底线（旧版两项检查）。返回失败原因列表，空列表表示通过。"""
    total, hk = summarize(stats)
    failures: list[str] = []
    if total < min_total:
        failures.append(f"stats 频道总数异常: {total} < {min_total}（差 {min_total - total}）")
    if hk == 0:
        failures.append("stats 港澳台频道数为 0（港澳台列表被清空？）")
    return failures


# ── m3u 解析 ──────────────────────────────────────────────────
def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise OutputCheckError(f"找不到产物文件: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OutputCheckError(f"{path} 无法按 UTF-8 读取: {exc}") from exc
    return text.splitlines()


def count_extinf(path: Path) -> int:
    """独立数字节级交付物：统计以 ``#EXTINF`` 开头的行数。"""
    return sum(1 for line in _read_lines(path) if line.startswith(EXTINF_PREFIX))


def parse_segments(path: Path) -> list[Segment]:
    """按 ``#EXTGRP:名称 (K)`` 切段，统计每段 EXTINF 与超额标记行。"""
    return parse_playlist(path).segments


def parse_playlist(path: Path) -> Playlist:
    """解析 m3u：头部 ``# Total:``、每个分段的声明数/实际数/超额标记。"""
    lines = _read_lines(path)
    playlist = Playlist(path=path)
    current: Segment | None = None

    for lineno, line in enumerate(lines, start=1):
        if playlist.header_total is None:
            header = HEADER_RE.match(line)
            if header:
                playlist.header_total = int(header.group("total"))
                playlist.header_categories = int(header.group("cats"))
                playlist.header_line_no = lineno
                continue

        group = EXTGRP_RE.match(line)
        if group:
            current = Segment(
                name=group.group("name"), declared=int(group.group("declared")), line_no=lineno
            )
            playlist.segments.append(current)
            continue

        if line.startswith(EXTINF_PREFIX):
            if current is None:
                playlist.orphan_extinf += 1
            else:
                current.extinf += 1
            continue

        if current is not None:
            more = MORE_RE.match(line)
            if more:
                current.more = int(more.group("rest"))
                current.more_line_no = lineno

    return playlist


# ── 各项检查 ──────────────────────────────────────────────────
def check_header(playlist: Playlist, stats_total: int | None = None) -> list[str]:
    """头部 ``# Total:`` 必须等于自身分段声明之和；不得超过 stats 总数。"""
    name = playlist.path.name
    if not playlist.segments:
        return [f"{name} 里没有任何 #EXTGRP 分段（产物为空或被写坏）"]

    failures: list[str] = []
    declared = playlist.declared_total
    segments = len(playlist.segments)
    header_total = playlist.header_total
    header_cats = playlist.header_categories

    if header_total is None or header_cats is None:
        failures.append(
            f"{name} 缺少 '# Total: N channels, M categories' 头部行"
            f"（各 #EXTGRP 声明合计 {declared}，{segments} 个分段）"
        )
        return failures

    if header_total != declared:
        failures.append(
            f"{name}:{playlist.header_line_no} 头部 '# Total: {header_total} channels'"
            f" 与文件内容不符：各 #EXTGRP 声明合计 {declared}"
            f"（差 {header_total - declared:+d}）"
        )
    if header_cats != segments:
        failures.append(
            f"{name}:{playlist.header_line_no} 头部声称 {header_cats} 个分类，"
            f"实际有 {segments} 个 #EXTGRP 分段（差 {header_cats - segments:+d}）"
        )
    if stats_total is not None and header_total > stats_total:
        failures.append(
            f"{name}:{playlist.header_line_no} 头部声称 {header_total} 个频道，"
            f"超过 stats.json 总数 {stats_total}"
            f"（多 {header_total - stats_total}）：m3u 是统计集合的子集，不可能更多"
        )
    return failures


def check_cap_consistency(segments: list[Segment], cap: int = GROUP_CAP) -> list[str]:
    """核心：每段 EXTINF 数 == min(K, cap)，超额标记必须存在且等于 K - cap。"""
    failures: list[str] = []
    for seg in segments:
        expected = min(seg.declared, cap)
        if seg.extinf != expected:
            failures.append(
                f"分组 {seg.name!r}（#EXTGRP 第 {seg.line_no} 行）声明 {seg.declared} 条，"
                f"实际 EXTINF {seg.extinf} 条，应为 min({seg.declared}, {cap}) = {expected}"
                f"（差 {seg.extinf - expected:+d}）"
            )

        if seg.declared > cap:
            want_more = seg.declared - cap
            if seg.more is None:
                failures.append(
                    f"分组 {seg.name!r} 声明 {seg.declared} > 上限 {cap}，"
                    f"但缺少 '# ... and {want_more} more' 超额标记行"
                )
            elif seg.more != want_more:
                failures.append(
                    f"分组 {seg.name!r} 超额标记写 '{seg.more} more'，"
                    f"应为 '{want_more} more'"
                    f"（{seg.declared} - {cap}，差 {seg.more - want_more:+d}）"
                )
        elif seg.more is not None:
            failures.append(
                f"分组 {seg.name!r} 声明 {seg.declared} 未超上限 {cap}，"
                f"却出现超额标记 '{seg.more} more'（第 {seg.more_line_no} 行）"
            )
    return failures


def check_declared_exact(segments: list[Segment], label: str) -> list[str]:
    """不截断的列表：每段声明数必须等于实际 EXTINF 数，且不得有超额标记。"""
    failures: list[str] = []
    for seg in segments:
        if seg.extinf != seg.declared:
            failures.append(
                f"{label} 分组 {seg.name!r}（第 {seg.line_no} 行）声明 {seg.declared} 条，"
                f"实际 EXTINF {seg.extinf} 条（差 {seg.extinf - seg.declared:+d}）"
            )
        if seg.more is not None:
            failures.append(
                f"{label} 分组 {seg.name!r} 不应截断，却出现超额标记 '{seg.more} more'"
                f"（第 {seg.more_line_no} 行）"
            )
    return failures


def check_group_coverage(stats: dict[str, int], segments: list[Segment]) -> list[str]:
    """stats 的每个分组在 all_merged.m3u 里必须至少有 1 条 EXTINF。"""
    failures: list[str] = []
    by_name: dict[str, list[Segment]] = {}
    for seg in segments:
        by_name.setdefault(seg.name, []).append(seg)

    for group, count in sorted(stats.items()):
        found = by_name.get(group)
        if not found:
            failures.append(
                f"stats.json 分组 {group!r}（{count} 个频道）在 all_merged.m3u 里没有对应分段"
            )
            continue
        actual = sum(seg.extinf for seg in found)
        if actual == 0:
            failures.append(
                f"stats.json 分组 {group!r}（{count} 个频道）在 all_merged.m3u 里 0 条 EXTINF"
                f"（声明 {sum(seg.declared for seg in found)} 条）"
            )

    extra = sorted(name for name in by_name if name not in stats)
    for name in extra:
        failures.append(
            f"all_merged.m3u 有 stats.json 里不存在的分组 {name!r}"
            f"（{sum(seg.extinf for seg in by_name[name])} 条 EXTINF）：两份产物不同源"
        )
    return failures


def check_delivery_size(playlist: Playlist, extinf_count: int, minimum: int) -> list[str]:
    """交付物真实条数下限。"""
    name = playlist.path.name
    if extinf_count < minimum:
        return [
            f"{name} 只有 {extinf_count} 条 EXTINF，低于下限 {minimum}"
            f"（差 {minimum - extinf_count}）：交付物被截断或产物被写坏"
        ]
    return []


def check_orphan_extinf(playlist: Playlist) -> list[str]:
    """EXTINF 不得出现在任何 #EXTGRP 分段之外。"""
    if playlist.orphan_extinf:
        return [
            f"{playlist.path.name} 有 {playlist.orphan_extinf} 条 EXTINF 位于所有"
            f" #EXTGRP 分段之外"
        ]
    return []


def check_hk_subset(playlist: Playlist, hk_stats: int) -> list[str]:
    """hk_merged 是 stats 港澳台集合的子集，只能更少。"""
    actual = playlist.extinf_total
    if actual > hk_stats:
        return [
            f"{playlist.path.name} 有 {actual} 条 EXTINF，超过 stats.json 港澳台合计 {hk_stats}"
            f"（多 {actual - hk_stats}）：违反子集关系"
        ]
    return []


# ── 编排 ──────────────────────────────────────────────────────
def build_paths(
    stats_path: Path, all_m3u: str | None, hk_m3u: str | None
) -> tuple[Path, Path]:
    base = stats_path.parent
    return (
        Path(all_m3u) if all_m3u else base / ALL_M3U_NAME,
        Path(hk_m3u) if hk_m3u else base / HK_M3U_NAME,
    )


def run_checks(stats_path: Path, all_path: Path, hk_path: Path) -> tuple[list[str], str]:
    """跑完全部检查，返回 (失败原因列表, 人读报告)。"""
    stats = load_stats(stats_path)
    all_pl = parse_playlist(all_path)
    hk_pl = parse_playlist(hk_path)
    all_extinf = count_extinf(all_path)
    hk_extinf = count_extinf(hk_path)

    total, hk_stats = summarize(stats)
    hk_groups = sorted(g for g in stats if is_hk_group(g))

    lines: list[str] = []
    lines.append(f"🧪 产物体检: {stats_path}")
    lines.append(f"   stats 频道总数: {total}")
    lines.append(f"   stats 分组数:   {len(stats)}")
    lines.append(f"   stats 港澳台:   {hk_stats}（{' / '.join(hk_groups) or '无匹配分组'}）")
    lines.append("")
    lines.append(f"📦 交付物: {all_path}")
    lines.append(f"   EXTINF 实际:    {all_extinf}（下限 {MIN_TOTAL_EXTINF}）")
    lines.append(
        f"   #EXTGRP 分段:   {len(all_pl.segments)}，声明合计 {all_pl.declared_total}，"
        f"文件内合计 {all_pl.extinf_total}，上限截断隐藏 {all_pl.hidden_total}"
    )
    lines.append(
        f"   与 stats 差:    {total - all_pl.declared_total}"
        f"（stats 记脏名过滤前的计数，正常应 >= 0）"
    )
    lines.append("")
    lines.append(f"🇭🇰 香港列表: {hk_path}")
    lines.append(f"   EXTINF 实际:    {hk_extinf}（下限 {MIN_HK_CHANNELS}）")
    lines.append(
        f"   #EXTGRP 分段:   {len(hk_pl.segments)}，声明合计 {hk_pl.declared_total}，"
        f"文件内合计 {hk_pl.extinf_total}"
    )
    lines.append(
        f"   与 stats 港澳台差: {hk_stats - hk_pl.declared_total}"
        f"（is_hk_region 召回缺口，见 reports/；此处只断言 <= 0 方向）"
    )
    lines.append("")

    failures: list[str] = []
    failures += check_stats(stats)
    failures += check_group_coverage(stats, all_pl.segments)
    failures += check_cap_consistency(all_pl.segments, cap=GROUP_CAP)
    failures += check_delivery_size(all_pl, all_extinf, MIN_TOTAL_EXTINF)
    failures += check_orphan_extinf(all_pl)
    failures += check_header(all_pl, stats_total=total)

    failures += check_declared_exact(hk_pl.segments, label="hk_merged.m3u")
    failures += check_delivery_size(hk_pl, hk_extinf, MIN_HK_CHANNELS)
    failures += check_orphan_extinf(hk_pl)
    failures += check_hk_subset(hk_pl, hk_stats)
    failures += check_header(hk_pl)

    return failures, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="产物保险丝：校验真实交付物")
    parser.add_argument(
        "stats", nargs="?", default=str(DEFAULT_STATS_PATH), help="stats.json 路径"
    )
    parser.add_argument("--all-m3u", default=None, help=f"默认取 stats 同目录 {ALL_M3U_NAME}")
    parser.add_argument("--hk-m3u", default=None, help=f"默认取 stats 同目录 {HK_M3U_NAME}")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    stats_path = Path(args.stats)
    all_path, hk_path = build_paths(stats_path, args.all_m3u, args.hk_m3u)

    try:
        failures, report = run_checks(stats_path, all_path, hk_path)
    except OutputCheckError as exc:
        print(f"❌ 产物体检失败: {exc}", file=sys.stderr)
        return 1

    print(report)
    sys.stdout.flush()  # 保证 CI 日志里报告先于下面的 stderr 错误行

    if failures:
        for reason in failures:
            print(f"❌ {reason}", file=sys.stderr)
        print(f"❌ 产物体检未通过（{len(failures)} 项），拒绝提交", file=sys.stderr)
        return 1

    print("✅ 产物体检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
