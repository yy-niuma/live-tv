"""tests/test_pipeline_snapshot.py

端到端（**完全离线**）快照测试，覆盖这一段流水线：

    List[Channel] → Grouper.group()（normalize + merge + categorize）
                  → Generator.generate_hk_and_all()（写 all_merged.m3u / hk_merged.m3u）

刻意切开的边界（为什么不覆盖更上下游）：
- `Fetcher.fetch_all()` 强依赖真实网络抓取（aiohttp GET 外部 m3u/yaml），本测试不调用它，
  也不 mock 它 —— 抓取与解析属于另一个测试单元。
- `Validator.validate()` 的 HEAD 请求同理，属于 tests/test_validator.py 的白名单短路路径。
- `src/main.py` 的 CLI 入口会串联 fetch→validate→group→generate 并读写 output/，
  这里也不调用，只测“Channel 列表之后”的纯逻辑 + 文件产出。

设计约束：
- fixture 全部内联；不依赖 conftest.py / pytest.ini。
- 不读仓库 config/alias.txt（注入固定别名），保证快照不受配置漂移影响。
"""
import re
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.fetcher import Channel  # noqa: E402
from src.generator import Generator, sort_key  # noqa: E402
from src.grouper import Grouper  # noqa: E402

EXTINF = "#EXTINF:-1"
_EXTGRP_RE = re.compile(r"^#EXTGRP:(?P<cat>.*) \((?P<n>\d+)\)$")


# ──────────────────────────────────────────────────────────────
#  fixture（内联）
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def make_grouper():
    """Grouper 工厂，但别名表被钉死为空（避免依赖 config/alias.txt 的当前内容）。"""

    def _make():
        g = Grouper()
        # _load_aliases() 在 _aliases 非空时直接返回，相当于“空别名表”
        g._aliases = {"__snapshot_noop_alias__": "__snapshot_noop_alias__"}
        return g

    return _make


@pytest.fixture()
def grouper(make_grouper):
    return make_grouper()


@pytest.fixture()
def sample_channels():
    """手工构造的频道样本，覆盖 CCTV / TVB / RTHK / 卫视 / 无法分类 + 脏数据 + 重复项。"""
    return [
        Channel(name="CCTV-1 综合 HD", url="http://example.invalid/cctv1.m3u8"),
        Channel(name="翡翠台 HD", url="http://example.invalid/jade_hd.m3u8"),
        Channel(name="翡翠台", url="http://hkdtmb.com/jade.m3u8"),  # 与上一条同归一化名
        Channel(name="港台电视31", url="http://example.invalid/rthk31.m3u8"),
        Channel(name="凤凰卫视资讯台", url="http://example.invalid/phoenix.m3u8"),
        Channel(name="自制频道XYZ", url="http://example.invalid/custom.m3u8"),
        Channel(
            name="Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36",
            url="http://example.invalid/dirty.m3u8",
        ),
    ]


def _parse(path):
    raw = Path(path).read_text(encoding="utf-8")
    lines = raw.split("\n")
    groups = []
    current = None
    for line in lines:
        if line.startswith("#EXTGRP:"):
            m = _EXTGRP_RE.match(line)
            current = {
                "cat": m.group("cat") if m else line,
                "declared": int(m.group("n")) if m else None,
                "extinf": [],
                "urls": [],
                "extra": [],
            }
            groups.append(current)
        elif line.startswith(EXTINF):
            current["extinf"].append(line)
        elif line.startswith("# ... and"):
            current["extra"].append(line)
        elif line.startswith("http"):
            current["urls"].append(line)
    return {"first_line": lines[0], "groups": groups, "raw": raw}


# ──────────────────────────────────────────────────────────────
#  快照：Channel → 分组 → 生成
# ──────────────────────────────────────────────────────────────
def test_pipeline_produces_expected_structure(grouper, sample_channels, tmp_path):
    grouped = grouper.group(sample_channels)
    result = Generator().generate_hk_and_all(grouped, str(tmp_path))

    # ── 分组阶段：脏数据要到生成阶段才被丢弃；重复项在分组阶段已合并 ──
    assert sum(len(v) for v in grouped.values()) == 6  # 7 进，2 条“翡翠台”合并成 1
    assert len(grouped) == 5
    # 分组阶段脏名字仍在（只是被 strip_noise 改写），由 generator 的 is_clean_name 拦下
    names = [ch.name for chs in grouped.values() for ch in chs]
    assert any("chrome/" in n.lower() for n in names), names

    # ── 文件阶段 ──
    all_parsed = _parse(tmp_path / "all_merged.m3u")
    hk_parsed = _parse(tmp_path / "hk_merged.m3u")

    assert all_parsed["first_line"].startswith("#EXTM3U")
    assert hk_parsed["first_line"].startswith("#EXTM3U")

    assert len(all_parsed["groups"]) == 5
    assert sum(len(g["extinf"]) for g in all_parsed["groups"]) == 5
    assert all(not g["extra"] for g in all_parsed["groups"]), "样本量远小于 100，不应出现截断标记"

    # 每个分组：声明数 == 实际写入数，且 EXTINF 与 URL 一一对应
    for group in all_parsed["groups"]:
        assert group["declared"] == len(group["extinf"])
        assert len(group["urls"]) == len(group["extinf"])

    # 返回的摘要与实际文件内容一致
    assert result["all"]["channels"] == 5
    assert result["all"]["groups"] == 5

    # HK 子集：翡翠台 / RTHK 31 / 凤凰卫视资讯台
    assert result["hk"]["channels"] == 3
    assert result["hk"]["groups"] == 3


def test_pipeline_groups_are_ordered_by_category_priority(grouper, sample_channels, tmp_path):
    grouped = grouper.group(sample_channels)
    Generator().generate_hk_and_all(grouped, str(tmp_path))
    parsed = _parse(tmp_path / "all_merged.m3u")
    cats = [g["cat"] for g in parsed["groups"]]

    assert cats == sorted(cats, key=sort_key), f"分组顺序必须由 sort_key 决定，实际 {cats}"
    # 央视频道永远第一（CATEGORY_ORDER[0]）
    assert cats[0] == "📺 央视频道"


def test_pipeline_uses_normalized_names_and_dedupes(grouper, sample_channels, tmp_path):
    grouped = grouper.group(sample_channels)
    Generator().generate_hk_and_all(grouped, str(tmp_path))
    raw = (tmp_path / "all_merged.m3u").read_text(encoding="utf-8")

    # 归一化后的显示名：去掉了 HD 后缀、空格
    assert 'tvg-name="CCTV-1综合"' in raw
    assert 'tvg-name="翡翠台"' in raw
    assert "翡翠台 HD" not in raw
    # 港台电视31 → RTHK 31
    assert "RTHK 31" in raw
    # 两条翡翠台合并：hkdtmb（优先级 1）胜出，另一条 URL 不再作为独立条目出现
    assert "http://hkdtmb.com/jade.m3u8" in raw
    # 但合并时算出的备链必须真的输出到产物（failover），且只能以 #EXTBACKUP: 注释行出现：
    # 播放器不把它当频道，_parse / scripts 的 EXTINF 计数也不受影响（见下方独立性测试）
    assert "#EXTBACKUP:http://example.invalid/jade_hd.m3u8" in raw
    playable_urls = [line for line in raw.split("\n") if line.startswith("http")]
    assert "http://example.invalid/jade_hd.m3u8" not in playable_urls


def test_pipeline_drops_dirty_names_from_output(grouper, sample_channels, tmp_path):
    grouped = grouper.group(sample_channels)
    Generator().generate_hk_and_all(grouped, str(tmp_path))
    for name in ("all_merged.m3u", "hk_merged.m3u"):
        raw = (tmp_path / name).read_text(encoding="utf-8")
        assert "Mozilla/5.0" not in raw
        assert "dirty.m3u8" not in raw


def test_pipeline_is_deterministic_for_the_same_input(make_grouper, sample_channels, tmp_path):
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    Generator().generate_hk_and_all(make_grouper().group(sample_channels), str(out1))
    Generator().generate_hk_and_all(make_grouper().group(sample_channels), str(out2))

    def extinf_lines(path):
        return [g["extinf"] for g in _parse(path)["groups"]]

    assert extinf_lines(out1 / "all_merged.m3u") == extinf_lines(out2 / "all_merged.m3u")
    assert extinf_lines(out1 / "hk_merged.m3u") == extinf_lines(out2 / "hk_merged.m3u")


def test_pipeline_empty_input_writes_header_only_files(grouper, tmp_path):
    result = Generator().generate_hk_and_all(grouper.group([]), str(tmp_path))

    assert result == {
        "hk": {"file": str(tmp_path / "hk_merged.m3u"), "channels": 0, "groups": 0},
        "all": {"file": str(tmp_path / "all_merged.m3u"), "channels": 0, "groups": 0},
    }
    all_parsed = _parse(tmp_path / "all_merged.m3u")
    assert all_parsed["first_line"].startswith("#EXTM3U")
    assert all_parsed["groups"] == []


# ──────────────────────────────────────────────────────────────
#  failover：备链进产物，但不改变任何既有计数口径
# ──────────────────────────────────────────────────────────────
def test_backup_urls_reach_the_playlist_without_changing_counts(grouper, sample_channels, tmp_path):
    grouped = grouper.group(sample_channels)
    Generator().generate_hk_and_all(grouped, str(tmp_path))

    for name in ("all_merged.m3u", "hk_merged.m3u"):
        parsed = _parse(tmp_path / name)
        raw = parsed["raw"]
        assert "#EXTBACKUP:" in raw, f"{name} 应当带出备选链路"
        # 原来的不变量一条都不许变：声明数 == EXTINF 数 == 可播 URL 数
        for group in parsed["groups"]:
            assert group["declared"] == len(group["extinf"])
            assert len(group["urls"]) == len(group["extinf"])
        # 备链行一律以 # 开头（注释），绝不能被当成独立频道
        assert not any(line.startswith("http") for line in raw.split("\n") if "#EXTBACKUP:" in line)


def test_backup_lines_follow_their_primary_url(grouper, sample_channels, tmp_path):
    """备链靠「紧跟主 URL 的下一行」绑定到频道，顺序不能乱。"""
    Generator().generate_hk_and_all(grouper.group(sample_channels), str(tmp_path))
    lines = (tmp_path / "all_merged.m3u").read_text(encoding="utf-8").split("\n")

    idx = lines.index("http://hkdtmb.com/jade.m3u8")
    assert lines[idx + 1] == "#EXTBACKUP:http://example.invalid/jade_hd.m3u8"


# ──────────────────────────────────────────────────────────────
#  确定性：跨输入顺序也不变（不是只在同进程重复跑时一致）
# ──────────────────────────────────────────────────────────────
def test_output_is_identical_when_input_order_is_reversed(make_grouper, sample_channels, tmp_path):
    out1 = tmp_path / "forward"
    out2 = tmp_path / "reversed"
    Generator().generate_hk_and_all(make_grouper().group(list(sample_channels)), str(out1))
    Generator().generate_hk_and_all(make_grouper().group(list(reversed(sample_channels))), str(out2))

    for name in ("all_merged.m3u", "hk_merged.m3u"):
        a = (out1 / name).read_text(encoding="utf-8")
        b = (out2 / name).read_text(encoding="utf-8")
        assert a == b, f"{name} 的组内顺序仍依赖输入顺序"


def test_manifest_is_written_after_the_two_playlists(grouper, sample_channels, tmp_path):
    Generator().generate_hk_and_all(grouper.group(sample_channels), str(tmp_path))
    assert (tmp_path / "manifest.json").is_file()
