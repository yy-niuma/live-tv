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
from scripts.plan_shards import build_matrix  # noqa: E402
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
    p.parent.mkdir(parents=True, exist_ok=True)
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
    a = _w(tmp_path, "shard-0/valid.json", ["http://x/1"])
    b = _w(tmp_path, "shard-1/valid.json", ["http://x/2"])
    c = _w(tmp_path, "shard-2/valid.json", ["http://x/3"])
    missing = tmp_path / "shard-3/valid.json"
    try:
        merge([a, b, c, missing], expected=4)
    except SystemExit as e:
        msg = str(e)
        assert "3" in msg, f"报错没有指出缺失的下标 3：{msg}"
        assert "期望 4" in msg, f"报错没有说明期望片数：{msg}"
    else:
        raise AssertionError("缺片时必须失败退出")


def test_missing_shard_error_names_the_indices(tmp_path):
    """报错必须指出**具体缺哪几片**（run #219 实测教训）。

    早先版本报「缺失：[]」—— 因为 shell glob 只会展开实际存在的文件，
    「缺失的文件」这个列表天然是空的，运维看日志完全不知道缺了什么。
    现在要从 `shard-N` 目录名反推下标，报「缺分片下标 [8, 9, ...]」。
    """
    paths = []
    for i in range(8):
        p = tmp_path / f"shard-{i}" / "valid.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps([f"http://x/{i}"]), encoding="utf-8")
        paths.append(p)
    missing = tmp_path / "shard-8" / "valid.json"
    missing.parent.mkdir(parents=True)
    try:
        merge(paths + [missing], expected=16)
    except SystemExit as e:
        msg = str(e)
        assert "8" in msg and "15" in msg, f"报错没有指出缺失下标：{msg}"
    else:
        raise AssertionError("缺片时必须失败退出")


def test_merge_skips_non_string_entries(tmp_path):
    """脏数据（null / 数字）不能让合并崩，只能被丢掉。"""
    a = _w(tmp_path, "a.json", ["http://x/1", None, 42, ""])
    assert merge([a]) == ["http://x/1"]


# ── CLI 冒烟（参数契约） ──────────────────────────────────────────────
def test_cli_help_exits_zero():
    for script in ("validate_shard.py", "merge_shard_urls.py", "plan_shards.py"):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"{script} --help 失败：{r.stderr[:400]}"


# ── 矩阵生成（plan job 的逻辑） ───────────────────────────────────────
def test_build_matrix_length_matches_count():
    """动态矩阵长度必须精确等于分片数 —— 这是「超出范围的片不被创建」的前提。"""
    for n in (1, 2, 4, 8, 16):
        assert len(build_matrix(n)) == n
        assert build_matrix(n) == list(range(n))


def test_build_matrix_rejects_out_of_range():
    """越界分片数必须抛错，不能默默生成错矩阵。"""
    for bad in (0, -1, 17, 100):
        try:
            build_matrix(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"分片数 {bad} 应该被拒绝")


def test_plan_shards_cli_writes_matrix(tmp_path):
    """CLI 必须写出 JSON 数组并输出可被 workflow 解析的两行。"""
    out = tmp_path / "shards.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "plan_shards.py"),
         "--count", "4", "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[:400]
    assert json.loads(out.read_text()) == [0, 1, 2, 3]
    assert "count=4" in r.stdout
    assert "shards=[0, 1, 2, 3]" in r.stdout


def test_plan_shards_cli_rejects_bad_count(tmp_path):
    out = tmp_path / "shards.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "plan_shards.py"),
         "--count", "99", "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "越界分片数必须非零退出"


def test_workflow_default_shard_count_is_8():
    """默认分片数锁 8（实测决策：16 片边际收益只有 37% 但 runner 用量翻倍）。

    这是**成本/收益的平衡点**，不是随手填的：
    - 1 片 → 12m55s
    - 8 片 → 5m20s（runner ×8）
    - 16 片 → 3m22s（runner ×16，边际只快 37%）

    默认值改成别的数会直接影响每天的 runner 用量，所以要钉住。
    """
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "update.yml").read_text())
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert inputs["shard_count"]["default"] == "8", (
        f"默认分片数被改成 {inputs['shard_count']['default']} —— "
        "8 是实测的性价比平衡点，改动要重新算 runner 用量"
    )


def test_merged_valid_json_must_not_land_in_output_dir():
    """中间产物不能落在 `output/` 里（run #231 实测教训）。

    `output/` 是**发布目录**：里面的文件会被 manifest 记录、随提交推给订阅者。
    `merged_valid.json`（合并后的有效 URL 列表）是中间产物，
    早先版本把它写在 `output/` 里，结果被当成正式产物提交进了仓库。
    """
    import yaml

    wf_text = (ROOT / ".github" / "workflows" / "update.yml").read_text()
    assert "output/merged_valid.json" not in wf_text, (
        "merged_valid.json 是中间产物，不能写进发布目录 output/"
    )
    # 同时确认它确实被写到了某个地方（别改成不生成了）
    assert "--out merged_valid.json" in wf_text, (
        "合并步骤的输出路径不见了 —— 分片模式会拿不到 URL 集合"
    )
    # 消费的路径也要跟着改
    assert "--valid-urls-file merged_valid.json" in wf_text, (
        "main.py 的消费路径没有跟着改，会读不到合并结果"
    )
    # workflow 必须能解析
    yaml.safe_load(wf_text)

def test_github_output_format_keeps_the_name(tmp_path):
    """GITHUB_OUTPUT 必须是 `name=value` —— **名字不能丢**（run #226 实测）。

    早先 workflow 里写 `grep '^count=' out | cut -d= -f2- >> $GITHUB_OUTPUT`，
    `count=16` 被削成 `16`，GitHub 解析时直接报「Invalid format '16'」，
    整个 plan job 失败 —— 一次只差一个 `-f2-` 的改动就白跑一轮 CI。

    正确做法：脚本用 `--github-output` **直接写**文件，格式由脚本保证。
    """
    out = tmp_path / "shards.json"
    gh = tmp_path / "gh_output.txt"
    gh.write_text("", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "plan_shards.py"),
         "--count", "4", "--out", str(out), "--github-output", str(gh)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr[:400]
    content = gh.read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert "count=4" in lines, f"GITHUB_OUTPUT 缺 count=4：{lines}"
    assert "shards=[0, 1, 2, 3]" in lines, f"GITHUB_OUTPUT 缺 shards：{lines}"
    # 每行都必须有 '='，且名字部分不能为空
    for ln in lines:
        assert "=" in ln, f"GITHUB_OUTPUT 的行没有 '='：{ln!r}"
        name, _, _val = ln.partition("=")
        assert name.strip(), f"GITHUB_OUTPUT 的行丢了名字：{ln!r}"
