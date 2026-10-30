"""tests/test_manifest.py

离线测试 `output/manifest.json` 的契约：它必须让订阅者在不下载 m3u 的情况下
判断「产物新旧 / 有没有被改坏」，所以每个字段都要能被独立复算。

覆盖：
- generated_at：ISO8601 且带时区，且是这次运行的时间
- files：sha256 是真文件内容的 sha256（测试自己用 hashlib 重算）、字节数、
          **实际写出**的频道数（不是 #EXTGRP 声明的截断前总数）、分段数
- groups：分组名 → 该组实际写出条数（= min(声明数, GROUP_CAP)），且按分类优先级排序
- tool_version：由 src 常量 + 现场取的 git 短 hash 组成，绝不写死 hash；
                取不到时退化成 "unknown"

设计约束：
- 完全离线，产物写 pytest 的 tmp_path。
- 不使用 conftest.py / pytest.ini 的任何 fixture（fixture 全部内联在这里）。
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import src as src_pkg  # noqa: E402
from src import generator as generator_mod  # noqa: E402
from src.fetcher import Channel  # noqa: E402
from src.generator import (  # noqa: E402
    GROUP_CAP,
    MANIFEST_NAME,
    Generator,
    sha256_of_file,
    sort_key,
    tool_version,
)

EXTINF = "#EXTINF"
_EXTGRP_RE = re.compile(r"^#EXTGRP:(?P<cat>.*) \((?P<n>\d+)\)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FULL_GIT_HASH_RE = re.compile(r"\b[0-9a-f]{40}\b")


# ──────────────────────────────────────────────────────────────
#  fixture（内联）
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def make_channel():
    def _make(name, url=None, group="", logo=""):
        return Channel(
            name=name,
            url=url if url is not None else f"http://example.invalid/{name}.m3u8",
            logo=logo,
            group=group,
        )

    return _make


@pytest.fixture()
def small_grouped(make_channel):
    """3 组 5 条（含一条带 2 个备链的频道），远小于上限。"""
    jade = make_channel("翡翠台", url="http://hkdtmb.com/jade.m3u8")
    jade._backup_urls = ["http://b.example/b.m3u8", "http://c.example/c.m3u8"]
    return {
        "📺 央视频道": [
            make_channel("CCTV-1 综合"),
            make_channel("CCTV-5 体育"),
        ],
        "📺 TVB": [jade],
        "📡 卫视频道": [make_channel("凤凰卫视资讯台")],
    }


@pytest.fixture()
def over_cap_grouped(make_channel):
    """单组 150 条：用于验证「声明数 ≠ 实际写出数」。"""
    return {"📺 央视频道": [make_channel(f"CCTV-5 体育 {i:03d}") for i in range(150)]}


def _read_manifest(tmp_path) -> dict:
    return json.loads((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))


def _segments(path):
    """独立切段：只看 #EXTGRP / #EXTINF，不用产品代码。"""
    segs = []
    for line in Path(path).read_text(encoding="utf-8").split("\n"):
        if line.startswith("#EXTGRP:"):
            m = _EXTGRP_RE.match(line)
            segs.append({"cat": m.group("cat"), "declared": int(m.group("n")), "extinf": 0})
        elif line.startswith(EXTINF):
            segs[-1]["extinf"] += 1
    return segs


# ──────────────────────────────────────────────────────────────
#  基本结构
# ──────────────────────────────────────────────────────────────
def test_manifest_is_written_next_to_the_playlists(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    path = tmp_path / MANIFEST_NAME
    assert path.is_file()
    assert MANIFEST_NAME == "manifest.json"
    assert isinstance(_read_manifest(tmp_path), dict)


def test_manifest_has_all_required_top_level_keys(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)
    assert set(manifest) >= {"generated_at", "tool_version", "files", "groups"}
    assert isinstance(manifest["files"], dict)
    assert isinstance(manifest["groups"], dict)


def test_manifest_covers_both_playlist_files(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)
    assert set(manifest["files"]) == {"all_merged.m3u", "hk_merged.m3u"}
    for name, info in manifest["files"].items():
        assert (tmp_path / name).is_file()
        assert set(info) >= {"sha256", "bytes", "channels", "groups"}


# ──────────────────────────────────────────────────────────────
#  generated_at
# ──────────────────────────────────────────────────────────────
def test_generated_at_is_iso8601_with_timezone(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    raw = _read_manifest(tmp_path)["generated_at"]

    assert isinstance(raw, str)
    parsed = datetime.fromisoformat(raw)  # 解析失败即抛，ISO8601 的硬校验
    assert parsed.tzinfo is not None, f"generated_at 必须带时区: {raw!r}"
    assert parsed.utcoffset() is not None
    assert re.search(r"(Z|[+-]\d{2}:\d{2})$", raw), f"时区偏移必须显式写出: {raw!r}"


def test_generated_at_is_the_time_of_this_run(small_grouped, tmp_path):
    before = datetime.now().astimezone() - timedelta(seconds=5)
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    after = datetime.now().astimezone() + timedelta(seconds=5)
    parsed = datetime.fromisoformat(_read_manifest(tmp_path)["generated_at"])
    assert before <= parsed <= after, f"{parsed} 不在 [{before}, {after}] 内"


# ──────────────────────────────────────────────────────────────
#  files[*].sha256 / bytes
# ──────────────────────────────────────────────────────────────
def test_sha256_is_the_hash_of_the_real_file_bytes(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)

    for name, info in manifest["files"].items():
        actual = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        assert info["sha256"] == actual, f"{name} 的 sha256 与文件内容不符"
        assert _SHA256_RE.match(info["sha256"]), "必须是 64 位小写十六进制"


def test_sha256_helper_reads_bytes_not_text(small_grouped, tmp_path):
    """独立复算一遍：任何 BOM/换行层面的差异都要能被 sha256 抓到。"""
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    target = tmp_path / "all_merged.m3u"
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    assert sha256_of_file(str(target)) == expected


def test_bytes_match_the_file_size(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)
    for name, info in manifest["files"].items():
        assert info["bytes"] == (tmp_path / name).stat().st_size
        assert info["bytes"] > 0


def test_manifest_reports_actual_written_channel_counts(over_cap_grouped, tmp_path):
    """本组 150 条：file 级 channels 必须是真正写出的 100，而不是声明的 150。"""
    Generator().generate_hk_and_all(over_cap_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)

    segs = _segments(tmp_path / "all_merged.m3u")
    assert segs[0]["declared"] == 150
    assert segs[0]["extinf"] == GROUP_CAP
    assert manifest["files"]["all_merged.m3u"]["channels"] == GROUP_CAP
    assert manifest["files"]["all_merged.m3u"]["groups"] == 1


def test_manifest_channel_counts_match_a_dumb_extinf_count(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)

    for name, info in manifest["files"].items():
        raw = (tmp_path / name).read_text(encoding="utf-8")
        extinf = sum(1 for line in raw.split("\n") if line.startswith(EXTINF))
        assert info["channels"] == extinf, f"{name}: manifest 计数与文件实际条数不符"
        assert info["groups"] == len(_segments(tmp_path / name))


# ──────────────────────────────────────────────────────────────
#  groups：分组名 → 该组实际写出条数
# ──────────────────────────────────────────────────────────────
def test_groups_map_matches_extgrp_and_truncation(over_cap_grouped, make_channel, tmp_path):
    grouped = dict(over_cap_grouped)
    grouped["📺 TVB"] = [make_channel("翡翠台")]
    Generator().generate_hk_and_all(grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)

    segs = {s["cat"]: s for s in _segments(tmp_path / "all_merged.m3u")}
    assert set(manifest["groups"]) == set(segs), "groups 的键必须等于 all_merged 的每个分段"
    for cat, seg in segs.items():
        assert manifest["groups"][cat] == seg["extinf"]
        assert manifest["groups"][cat] == min(seg["declared"], GROUP_CAP)
    assert sum(manifest["groups"].values()) == manifest["files"]["all_merged.m3u"]["channels"]


def test_groups_map_is_ordered_by_category_priority(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    keys = list(_read_manifest(tmp_path)["groups"])
    assert keys == sorted(keys, key=sort_key), "groups 的键顺序应与 m3u 分段顺序一致"


def test_groups_file_points_at_all_merged(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)
    # groups 是 all_merged 的口径；hk 只有零星几组，别让订阅者猜
    assert manifest.get("groups_file", "all_merged.m3u") == "all_merged.m3u"


# ──────────────────────────────────────────────────────────────
#  tool_version：常量 + 现场取的 git hash，不写死
# ──────────────────────────────────────────────────────────────
def test_manifest_tool_version_matches_the_helper(small_grouped, tmp_path):
    Generator().generate_hk_and_all(small_grouped, str(tmp_path))
    manifest = _read_manifest(tmp_path)
    assert isinstance(manifest["tool_version"], str) and manifest["tool_version"]
    assert manifest["tool_version"] == tool_version()
    assert not _FULL_GIT_HASH_RE.search(manifest["tool_version"]), "只写短 hash，不内嵌 40 位全 hash"


def test_tool_version_takes_the_git_hash_live(monkeypatch):
    """把 git 取 hash 的结果换掉，版本号必须跟着变 —— 证明 hash 不是写死的。"""
    monkeypatch.setattr(generator_mod, "_git_short_commit", lambda repo_root=None: "abc1234")
    monkeypatch.setattr(src_pkg, "__version__", "9.9.9")
    assert tool_version() == "9.9.9+gitabc1234"


def test_tool_version_falls_back_to_the_src_constant_without_git(monkeypatch):
    monkeypatch.setattr(generator_mod, "_git_short_commit", lambda repo_root=None: "")
    monkeypatch.setattr(src_pkg, "__version__", "1.2.3")
    assert tool_version() == "1.2.3"


def test_tool_version_is_unknown_when_nothing_is_available(monkeypatch):
    monkeypatch.setattr(generator_mod, "_git_short_commit", lambda repo_root=None: "")
    monkeypatch.setattr(src_pkg, "__version__", "")
    assert tool_version() == "unknown"


def test_git_short_commit_is_empty_for_a_non_repo_directory(tmp_path):
    """取不到 git 时必须安静返回空串（不许抛异常把整次生成打断）。"""
    bogus = tmp_path / "not_a_repo"
    bogus.mkdir()
    assert generator_mod._git_short_commit(bogus) == ""


# ──────────────────────────────────────────────────────────────
#  覆盖写入 / 与产物同步
# ──────────────────────────────────────────────────────────────
def test_manifest_is_rewritten_when_the_playlist_changes(tmp_path, make_channel):
    out = tmp_path / "out"
    Generator().generate_hk_and_all({"📺 央视频道": [make_channel("CCTV-1 综合")]}, str(out))
    first = _read_manifest(out)

    Generator().generate_hk_and_all(
        {"📺 央视频道": [make_channel("CCTV-1 综合"), make_channel("CCTV-5 体育")]}, str(out)
    )
    second = _read_manifest(out)

    assert first["files"]["all_merged.m3u"]["sha256"] != second["files"]["all_merged.m3u"]["sha256"]
    assert second["files"]["all_merged.m3u"]["channels"] == 2
    assert second["files"]["all_merged.m3u"]["sha256"] == hashlib.sha256(
        (out / "all_merged.m3u").read_bytes()
    ).hexdigest()


def test_manifest_of_identical_input_is_byte_identical_except_timestamp(tmp_path, make_channel):
    """同输入两次生成：m3u 与 manifest 的 sha256 段落必须一致（B 的确定性可被订阅者验证）。"""
    chans = [make_channel("CCTV-1 综合"), make_channel("翡翠台"), make_channel("凤凰卫视资讯台")]
    out1, out2 = tmp_path / "r1", tmp_path / "r2"
    Generator().generate_hk_and_all({"📺 央视频道": chans[:1], "📺 TVB": chans[1:]}, str(out1))
    Generator().generate_hk_and_all({"📺 央视频道": chans[:1], "📺 TVB": chans[1:]}, str(out2))

    m1, m2 = _read_manifest(out1), _read_manifest(out2)
    assert m1["files"] == m2["files"]
    assert m1["groups"] == m2["groups"]
    assert m1["tool_version"] == m2["tool_version"]
