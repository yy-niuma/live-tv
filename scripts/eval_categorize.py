#!/usr/bin/env python3
"""分类准确度评测器 —— 用于改造前后对比。

用法:
    python scripts/eval_categorize.py                 # 跑内置反例/正例集
    python scripts/eval_categorize.py --snapshot A.tsv --snapshot B.tsv
                                            # 对比两份产物快照的分组漂移
    python scripts/eval_categorize.py --dataset /tmp/ds
                                            # 换一套数据集（目录里放同样三个 tsv）

数据集（随脚本维护在 scripts/categorize_dataset/）:
    known_bugs.tsv   已知误判样本 + 期望分类（改造后必须变对）
    known_good.tsv   必须保持正确的样本（改造后不能退化）
    current_snapshot.tsv  改造前的产物快照（分组\t频道名），用于看漂移

判定口径是**严格全等**：`categorize(name, "") == 期望分类`。没有「差不多对」，
因为分组名会直接写进 m3u 的 group-title，错一个就是错一个分组。

退出码:
    0 = 全部通过
    1 = 有用例不达标（这是评测结论，不是崩溃 —— 现状就是 1，见 known_bugs.tsv）
    2 = 数据集读不到 / 为空（空数据集必须报错：否则「0/0 全过」是假绿）
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "categorize_dataset"
sys.path.insert(0, str(ROOT))

from src.group.categorizer import categorize  # noqa: E402

DATASET_FILES = ("known_bugs.tsv", "known_good.tsv")


def load_tsv(path: Path) -> list[tuple[str, str]]:
    """读 `名称\t期望` 两列 tsv；`#` 注释、空行、列数不足的行全部跳过。

    文件不存在时抛 `FileNotFoundError`（由 main 转成退出码 2），不在这里吞掉 ——
    吞掉会让「数据集丢了」变成「0 个用例全过」。
    """
    rows: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name, expected = parts[0].strip(), parts[1].strip()
        if not name or not expected:
            continue
        rows.append((name, expected))
    return rows


def eval_pairs(
    rows: list[tuple[str, str]],
) -> tuple[int, int, list[tuple[str, str, str, str]]]:
    """返回 (通过数, 总数, 失败明细)"""
    passed = 0
    failures: list[tuple[str, str, str, str]] = []
    for name, expected in rows:
        actual = categorize(name, "")
        if actual == expected:
            passed += 1
        else:
            failures.append((name, expected, actual, ""))
    return passed, len(rows), failures


def read_snapshot(path: Path) -> dict[str, str]:
    """读 `分组\t频道名` 快照；没有制表符的坏行跳过（历史快照手工编辑过）。"""
    snap: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or "\t" not in line:
            continue
        grp, name = line.split("\t", 1)
        if not name.strip():
            continue
        snap[name] = grp
    return snap


def snapshot_diff(old_path: Path, new_path: Path) -> dict:
    """对比两份产物快照：哪些频道换了分组"""
    old = read_snapshot(old_path)
    new = read_snapshot(new_path)

    moved = {n: (old[n], new[n]) for n in old if n in new and old[n] != new[n]}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    by_pair = collections.Counter((a, b) for a, b in moved.values())
    return {
        "common": len(set(old) & set(new)),
        "moved": moved,
        "added": added,
        "removed": removed,
        "by_pair": by_pair,
    }


def report(
    bugs: list[tuple[str, str]], good: list[tuple[str, str]]
) -> tuple[bool, str]:
    """打印评测明细，返回 (是否全过, 文本摘要)。"""
    bp, bt, bf = eval_pairs(bugs)
    gp, gt, gf = eval_pairs(good)

    lines = [f"known_bugs  (误判修复集): {bp}/{bt} 通过"]
    for name, exp, act, _ in bf:
        lines.append(f"    FAIL {name!r}: 期望 {exp} / 实际 {act}")
    lines.append(f"known_good  (不退化集): {gp}/{gt} 通过")
    for name, exp, act, _ in gf:
        lines.append(f"    REGRESSION {name!r}: 期望 {exp} / 实际 {act}")

    total_pass, total = bp + gp, bt + gt
    lines.append(f"\n合计: {total_pass}/{total}")
    for line in lines:
        print(line)
    return (not bf and not gf), f"{total_pass}/{total}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="分类准确度评测：known_bugs 必须变对，known_good 不能退化"
    )
    ap.add_argument("--dataset", default=str(DATA), help="数据集目录")
    ap.add_argument(
        "--snapshot",
        action="append",
        default=[],
        help="产物快照 tsv，可给两次做漂移对比",
    )
    args = ap.parse_args(argv)

    data = Path(args.dataset)
    try:
        sets = {name: load_tsv(data / name) for name in DATASET_FILES}
    except FileNotFoundError as exc:
        print(f"读不到数据集：{exc.filename}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"读不到数据集：{exc}", file=sys.stderr)
        return 2

    bugs, good = sets["known_bugs.tsv"], sets["known_good.tsv"]
    ok, summary = report(bugs, good)

    if not (bugs or good):
        # 空数据集不给 0：「0/0 全过」是这套工具最危险的假绿
        print(f"\n数据集为空：{data}（{', '.join(DATASET_FILES)} 里没有可用行）"
              , file=sys.stderr)
        print("\nRESULT:", "EMPTY")
        return 2

    if len(args.snapshot) >= 2:
        try:
            d = snapshot_diff(Path(args.snapshot[0]), Path(args.snapshot[1]))
        except (FileNotFoundError, OSError) as exc:
            print(f"\n快照读不到，跳过对比：{exc}", file=sys.stderr)
        else:
            print(f"\n快照对比: 共同 {d['common']} 条，移组 {len(d['moved'])} 条，"
                  f"新增 {len(d['added'])}，消失 {len(d['removed'])}")
            for (a, b), n in d["by_pair"].most_common(15):
                print(f"    {n:4}  {a}  →  {b}")

    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} ({summary})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
