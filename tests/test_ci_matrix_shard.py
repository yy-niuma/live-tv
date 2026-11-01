"""tests/test_ci_matrix_shard.py —— CI 矩阵分片的语义守卫。

为什么要分片
------------
验证阶段占整条流水线 99% 的时间（run #211 实测：抓取 8.8s / 验证 717.2s）。
单 job 内并发已被源站限流夹死（实测 160 掉条），唯一能线性压缩 wall clock
的是多 runner 并行：N 个 shard job 各验一份，最后一个 job 合并。

这个文件钉死三件事
------------------
1. **分片函数是稳定的** —— 同一 URL 永远落同一片。否则重跑单片、
   跨 run 对比都失去意义。
2. **分片是互斥且完备的** —— 每条 URL 恰好属于一片，不重不漏。
   漏一条 = 悄悄丢频道；重一条 = 重复探测。
3. **合并是并集且拒绝残缺** —— 少了一个分片文件必须失败退出，
   不能静默交付少 1/N 的产物。

分片规则为什么用 `sha1(url) % N` 而不是「轮转切片」
---------------------------------------------------
轮转切片（`urls[i::N]`）在**当前数据分布下**会把热 host 挤在同一片：
`stream1.freetv.fun` 有 1,199 条、`jmp2.uk` 有 1,179 条，且它们成块连续，
轮转后仍然会集中到少数几片 → 各片耗时严重不均，慢的那片决定总时长。
sha1 取模打散了 host 相关性，切片大小与耗时都更均衡。
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.merge_shard_urls import merge  # noqa: E402
from scripts.validate_shard import shard_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


# ── 分片函数 ──────────────────────────────────────────────────────────
def test_shard_of_is_stable():
    """同一 URL 反复调用必须得到同一片 —— 稳定性的底线。"""
    url = "http://example.com/live/1.m3u8"
    assert len({shard_of(url, 7) for _ in range(50)}) == 1


def test_shard_of_is_exclusive_and_complete():
    """每条 URL 恰好属于一片（0..N-1），不重不漏。"""
    urls = [f"http://h{i % 37}.example/live/{i}.m3u8" for i in range(500)]
    for n in (1, 2, 4, 8):
        buckets = Counter(shard_of(u, n) for u in urls)
        assert set(buckets) <= set(range(n)), f"出现了越界分片：{set(buckets)}"
        assert sum(buckets.values()) == len(urls), "分片丢条或重复"


def test_shard_distribution_is_balanced():
    """sha1 取模必须分布均匀 —— 倾斜会让慢片拖垮整体 wall clock。"""
    urls = [f"http://h{i % 41}.example/live/{i}.m3u8" for i in range(4000)]
    n = 4
    buckets = Counter(shard_of(u, n) for u in urls)
    expect = len(urls) / n
    for i in range(n):
        got = buckets.get(i, 0)
        # 允许 ±25% 的波动；轮转切片遇到热 host 集中会远远超出这个范围
        assert abs(got - expect) <= expect * 0.25, (
            f"分片 {i} 有 {got} 条，期望约 {expect:.0f} 条 —— 分布倾斜"
        )


# ── 合并 ──────────────────────────────────────────────────────────────
def _w(tmp_path: Path, name: str, urls) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(urls), encoding="utf-8")
    return p


def test_merge_is_union(tmp_path):
    a = _w(tmp_path, "a.json", ["http://x/1", "http://x/2"])
    b = _w(tmp_path, "b.json", ["http://x/2", "http://x/3"])
    assert merge([a, b]) == ["http://x/1", "http://x/2", "http://x/3"]


def test_merge_tolerates_empty_shard(tmp_path):
    """URL 总数少于片数时会出现空片 —— 这是合法的，不能报错。"""
    a = _w(tmp_path, "a.json", ["http://x/1"])
    b = _w(tmp_path, "b.json", [])
    assert merge([a, b], expected=2) == ["http://x/1"]


def test_merge_refuses_missing_shard(tmp_path):
    """声明 4 片却只给了 3 个文件 → 必须失败，不能静默交付残缺产物。"""
    a = _w(tmp_path, "a.json", ["http://x/1"])
    b = _w(tmp_path, "b.json", ["http://x/2"])
    c = _w(tmp_path, "c.json", ["http://x/3"])
    missing = tmp_path / "d.json"
    try:
        merge([a, b, c, missing], expected=4)
    except SystemExit as e:
        assert "缺失" in str(e)
    else:
        raise AssertionError("缺片时必须失败退出")


def test_merge_skips_non_string_entries(tmp_path):
    """脏数据（null / 数字）不能让合并崩，只能被丢掉。"""
    a = _w(tmp_path, "a.json", ["http://x/1", None, 42, ""])
    assert merge([a]) == ["http://x/1"]


# ── CLI 冒烟（参数契约） ──────────────────────────────────────────────
def test_cli_help_exits_zero():
    for script in ("validate_shard.py", "merge_shard_urls.py"):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"{script} --help 失败：{r.stderr[:400]}"
