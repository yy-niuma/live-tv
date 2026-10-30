"""tests/test_check_output.py —— ``scripts/check_output.py`` 的回归测试。

本文件自带全部 fixture（stats.json 与 m3u 都在 ``tmp_path`` 里现造），
不依赖 ``tests/conftest.py`` 里的任何 fixture，也不读仓库的 ``output/``。

背景（2026-10-29 控制器实测产物，HEAD 6656715）
------------------------------------------------
脚本原来的「港澳台子集」断言按**分组名**汇总 stats（``HK_GROUP_KEYWORDS``
子串匹配，本次得 79），却拿 ``hk_merged.m3u`` 的**全部** EXTINF（81）去比。
两个口径不同源：

    ``hk_merged.m3u`` 是按每条频道的 ``is_hk_region()`` 逐条捞出来的；
    其中 ``📡 卫视频道``(3) 与 ``📺 有线电视``(3) 这两个分组不在
    ``HK_GROUP_KEYWORDS`` 里，于是 stats 口径少算 6 条，81 > 79 被误判成
    「违反子集关系」，脚本 EXIT=1 挡住了一份完全正常的产物。

真不变量是**逐组**比较 ``hk_merged[g] <= stats[g]``（实测 8 组全过：
卫视频道 3<=23、TVB 8<=8、ViuTV 1<=1、RTHK 3<=3、HOY TV 2<=2、
有线电视 3<=3、台湾 58<=62、澳门 3<=3）。「全量合计」口径降级为报告里
一行提示，不再是失败条件。

复现命令（仓库根执行；真实产物目录由控制器跑出来）
------------------------------------------------
    .venv/bin/python scripts/check_output.py \
        /home/hermes/.hermes/cache/scratch/livetv_ci_run/stats.json  # 修复后 EXIT=0
    .venv/bin/python -m pytest tests/test_check_output.py -p no:cacheprovider -q

修复前同一命令：``❌ hk_merged.m3u 有 81 条 EXTINF，超过 stats.json 港澳台合计
79（多 2）：违反子集关系`` + EXIT=1。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_output.py"


def _load_script() -> ModuleType:
    """按路径加载被测脚本（scripts/ 不是包，无需 sys.path 改造）。"""
    spec = importlib.util.spec_from_file_location(
        "check_output_under_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


co = _load_script()

# ── 真实产物口径（2026-10-29 控制器实测，勿凭感觉改） ──────────────
# stats.json 里这 8 个分组的计数
HK_STATS: dict[str, int] = {
    "📡 卫视频道": 23,
    "📺 TVB": 8,
    "📺 ViuTV": 1,
    "📺 RTHK": 3,
    "📺 HOY TV": 2,
    "📺 有线电视": 3,
    "🇹🇼 台湾": 62,
    "🇲🇴 澳门": 3,
}
# hk_merged.m3u 实测逐组 EXTINF 条数（合计 81）
HK_ACTUAL: dict[str, int] = {
    "📡 卫视频道": 3,
    "📺 TVB": 8,
    "📺 ViuTV": 1,
    "📺 RTHK": 3,
    "📺 HOY TV": 2,
    "📺 有线电视": 3,
    "🇹🇼 台湾": 58,
    "🇲🇴 澳门": 3,
}
# 填充分组：只为满足 MIN_TOTAL_CHANNELS(3000) / MIN_TOTAL_EXTINF(1000) 两条底线
FILLER_GROUPS: dict[str, int] = {f"🌐 填充{i:02d}": 300 for i in range(10)}


def _extinf_block(group: str, count: int) -> list[str]:
    lines: list[str] = []
    for i in range(count):
        lines.append(
            f'#EXTINF:-1 tvg-name="{group}-{i}" group-title="{group}",{group}-{i}'
        )
        lines.append(f"http://example.invalid/{i}.m3u8")
    return lines


def _write_m3u(
    path: Path,
    *,
    header: tuple[int, int] | None,
    segments: list[tuple[str, int, int]],
    more: dict[str, int] | None = None,
) -> Path:
    """写一份 m3u。

    ``segments`` 每项是 ``(分组名, #EXTGRP 声明数, 实际 EXTINF 条数)``，
    两者不等即模拟截断；``more`` 是分组 → ``# ... and N more`` 标记数。
    """
    lines = ["#EXTM3U", "#PLAYLIST:fixture"]
    if header is not None:
        lines.append(f"# Total: {header[0]} channels, {header[1]} categories")
    lines.append("")
    for group, declared, extinf in segments:
        lines.append(f"#EXTGRP:{group} ({declared})")
        lines.extend(_extinf_block(group, extinf))
        rest = (more or {}).get(group)
        if rest is not None:
            lines.append(f"# ... and {rest} more")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _default_all_segments() -> tuple[list[tuple[str, int, int]], dict[str, int]]:
    """all_merged.m3u 的默认分段：填充组被 100/组上限截断，港澳台组全量写出。"""
    segments: list[tuple[str, int, int]] = []
    more: dict[str, int] = {}
    for group, count in FILLER_GROUPS.items():
        segments.append((group, count, co.GROUP_CAP))
        more[group] = count - co.GROUP_CAP
    for group, count in HK_STATS.items():
        segments.append((group, count, count))
    return segments, more


def _write_all(
    tmp_path: Path,
    segments: list[tuple[str, int, int]],
    more: dict[str, int] | None = None,
    *,
    header_delta: int = 0,
) -> Path:
    declared_total = sum(seg[1] for seg in segments)
    return _write_m3u(
        tmp_path / "all_merged.m3u",
        header=(declared_total + header_delta, len(segments)),
        segments=segments,
        more=more,
    )


def _write_hk(
    tmp_path: Path,
    segments: list[tuple[str, int, int]],
    *,
    header_delta: int = 0,
) -> Path:
    declared_total = sum(seg[1] for seg in segments)
    return _write_m3u(
        tmp_path / "hk_merged.m3u",
        header=(declared_total + header_delta, len(segments)),
        segments=segments,
    )


def _write_stats(tmp_path: Path, stats: dict[str, int]) -> Path:
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def passing_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    """一份结构与真实产物同形、且应全部检查通过的 (stats, all_m3u, hk_m3u)。"""
    stats = dict(HK_STATS)
    stats.update(FILLER_GROUPS)
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    all_path = _write_all(tmp_path, all_segments, more)
    hk_segments = [(group, n, n) for group, n in HK_ACTUAL.items()]
    hk_path = _write_hk(tmp_path, hk_segments)
    return stats_path, all_path, hk_path


# ── (a) 真实数字：不得误报 ────────────────────────────────────
def test_real_hk_numbers_pass_end_to_end(passing_artifacts, capsys) -> None:
    """真实口径（hk 81 / stats 港澳台 79）必须通过，退出码 0。"""
    stats_path, _, _ = passing_artifacts
    assert co.main([str(stats_path)]) == 0
    out = capsys.readouterr()
    assert "❌" not in out.err
    assert "违反子集关系" not in out.err
    assert "✅ 产物体检通过" in out.out


def test_real_hk_numbers_report_keeps_total_hint(passing_artifacts, capsys) -> None:
    """全量合计口径（81 vs 79）保留为提示信息，而不是失败条件。"""
    stats_path, _, _ = passing_artifacts
    co.main([str(stats_path)])
    out = capsys.readouterr().out
    assert "stats 港澳台:   79" in out
    assert "81" in out  # hk 实际条数仍打印
    assert "⚠️" in out  # 合计口径提示行


def test_hk_subset_by_group_accepts_real_numbers(passing_artifacts) -> None:
    """逐组比较：8 个分组全部满足 hk[g] <= stats[g]，失败列表为空。"""
    stats_path, _, hk_path = passing_artifacts
    stats = co.load_stats(stats_path)
    playlist = co.parse_playlist(hk_path)
    failures, notes = co.check_hk_subset_by_group(playlist, stats)
    assert failures == []
    assert any("81" in note for note in notes)


def test_hk_group_absent_from_keywords_is_not_a_failure(passing_artifacts) -> None:
    """卫视频道 / 有线电视不在 HK_GROUP_KEYWORDS 里，但逐组比较不能因此报红。"""
    _, _, hk_path = passing_artifacts
    playlist = co.parse_playlist(hk_path)
    names = {seg.name for seg in playlist.segments}
    assert {"📡 卫视频道", "📺 有线电视"} <= names
    for name in ("📡 卫视频道", "📺 有线电视"):
        assert co.is_hk_group(name) is False  # 关键词口径确实漏掉它们
        assert HK_ACTUAL[name] <= HK_STATS[name]


# ── (b) 真违反子集关系必须报红 ────────────────────────────────
def test_group_overrun_turns_red(passing_artifacts, capsys) -> None:
    """台湾 63 > stats 62：必须报红，且指名分组与超出条数。"""
    stats_path, _, hk_path = passing_artifacts
    segments = [("📺 TVB", 8, 8), ("🇹🇼 台湾", 63, 63)]
    _write_hk(hk_path.parent, segments)
    assert co.main([str(stats_path)]) == 1
    err = capsys.readouterr().err
    assert "🇹🇼 台湾" in err
    assert "多 1" in err


def test_group_overrun_reports_exact_excess(passing_artifacts) -> None:
    """逐组失败信息必须写清「哪个分组 / 超出几条」。"""
    stats_path, _, hk_path = passing_artifacts
    stats = co.load_stats(stats_path)
    playlist = co.parse_playlist(hk_path)
    playlist.segments.append(
        co.Segment(name="📺 TVB", declared=3, line_no=999, extinf=3)
    )
    failures, _ = co.check_hk_subset_by_group(playlist, stats)
    assert len(failures) == 1
    assert "📺 TVB" in failures[0]
    assert "多 3" in failures[0]  # 8 + 3 = 11 > 8


def test_group_missing_in_stats_is_a_failure(passing_artifacts) -> None:
    """hk 里出现 stats 没有的分组 → 两份产物不同源，必须报红。"""
    stats_path, _, hk_path = passing_artifacts
    stats = co.load_stats(stats_path)
    playlist = co.parse_playlist(hk_path)
    playlist.segments.append(
        co.Segment(name="📺 幽灵分组", declared=2, line_no=999, extinf=2)
    )
    failures, _ = co.check_hk_subset_by_group(playlist, stats)
    assert len(failures) == 1
    assert "📺 幽灵分组" in failures[0]
    assert "stats.json" in failures[0]


def test_duplicate_segments_are_aggregated(passing_artifacts) -> None:
    """同名分段必须累加后再比较，不能逐段各自过关。"""
    stats_path, _, hk_path = passing_artifacts
    stats = co.load_stats(stats_path)
    playlist = co.parse_playlist(hk_path)
    playlist.segments.append(
        co.Segment(name="📺 TVB", declared=1, line_no=998, extinf=1)
    )
    failures, _ = co.check_hk_subset_by_group(playlist, stats)
    assert len(failures) == 1
    assert "多 1" in failures[0]


# ── (c) 其它检查项不得被破坏 ──────────────────────────────────
def test_header_mismatch_still_red(tmp_path: Path, capsys) -> None:
    stats = dict(HK_STATS)
    stats.update(FILLER_GROUPS)
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    _write_all(tmp_path, all_segments, more, header_delta=1)
    _write_hk(tmp_path, [(g, n, n) for g, n in HK_ACTUAL.items()])
    assert co.main([str(stats_path)]) == 1
    assert "头部 '# Total:" in capsys.readouterr().err


def test_cap_inconsistency_still_red(tmp_path: Path, capsys) -> None:
    stats = dict(HK_STATS)
    stats.update(FILLER_GROUPS)
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    first = all_segments[0]
    all_segments[0] = (first[0], first[1], co.GROUP_CAP - 1)  # 少写一条
    _write_all(tmp_path, all_segments, more)
    _write_hk(tmp_path, [(g, n, n) for g, n in HK_ACTUAL.items()])
    assert co.main([str(stats_path)]) == 1
    err = capsys.readouterr().err
    assert first[0] in err
    assert "应为 min(" in err


def test_missing_more_marker_still_red(tmp_path: Path, capsys) -> None:
    stats = dict(HK_STATS)
    stats.update(FILLER_GROUPS)
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    more.pop(all_segments[0][0])
    _write_all(tmp_path, all_segments, more)
    _write_hk(tmp_path, [(g, n, n) for g, n in HK_ACTUAL.items()])
    assert co.main([str(stats_path)]) == 1
    assert "more" in capsys.readouterr().err


def test_group_coverage_extra_group_still_red(tmp_path: Path, capsys) -> None:
    stats = dict(HK_STATS)
    stats.update(FILLER_GROUPS)
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    all_segments.append(("📺 幽灵分组", 1, 1))
    _write_all(tmp_path, all_segments, more)
    _write_hk(tmp_path, [(g, n, n) for g, n in HK_ACTUAL.items()])
    assert co.main([str(stats_path)]) == 1
    assert "不存在的分组" in capsys.readouterr().err


def test_group_coverage_missing_group_still_red(tmp_path: Path, capsys) -> None:
    stats = dict(HK_STATS)
    stats.update(FILLER_GROUPS)
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    all_segments = [seg for seg in all_segments if seg[0] != "🇲🇴 澳门"]
    _write_all(tmp_path, all_segments, more)
    _write_hk(tmp_path, [(g, n, n) for g, n in HK_ACTUAL.items()])
    assert co.main([str(stats_path)]) == 1
    assert "没有对应分段" in capsys.readouterr().err


def test_hk_declared_mismatch_still_red(tmp_path: Path, capsys) -> None:
    stats = dict(HK_STATS)
    stats.update(FILLER_GROUPS)
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    _write_all(tmp_path, all_segments, more)
    _write_hk(tmp_path, [("📺 TVB", 9, 8)])  # 声明 9 实际 8
    assert co.main([str(stats_path)]) == 1
    assert "hk_merged" in capsys.readouterr().err


def test_stats_dirty_name_slack_is_tolerated(tmp_path: Path, capsys) -> None:
    """stats 记脏名过滤前的计数，因此 stats 总数的差额只是报告，不是失败。"""
    stats = dict(HK_STATS)
    stats.update({g: count + 10 for g, count in FILLER_GROUPS.items()})
    stats_path = _write_stats(tmp_path, stats)
    all_segments, more = _default_all_segments()
    _write_all(tmp_path, all_segments, more)
    _write_hk(tmp_path, [(g, n, n) for g, n in HK_ACTUAL.items()])
    assert co.main([str(stats_path)]) == 0
    out = capsys.readouterr().out
    assert "与 stats 差" in out


def test_missing_stats_file_exits_one(tmp_path: Path, capsys) -> None:
    assert co.main([str(tmp_path / "nope.json")]) == 1
    assert "找不到产物统计文件" in capsys.readouterr().err
