#!/usr/bin/env python3
"""分类准确度评测器 —— 用于改造前后对比。

用法:
    python scripts/eval_categorize.py                 # 跑内置反例/正例集
    python scripts/eval_categorize.py --snapshot A.tsv --snapshot B.tsv
                                            # 对比两份产物快照的分组漂移

数据集（随脚本维护在 scripts/categorize_dataset/）:
    known_bugs.tsv   已知误判样本 + 期望分类（改造后必须变对）
    known_good.tsv   必须保持正确的样本（改造后不能退化）
    current_snapshot.tsv  改造前的产物快照（分组\t频道名），用于看漂移

退出码: 0 = 全部通过; 1 = 有用例不达标
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


def load_tsv(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        rows.append((parts[0].strip(), parts[1].strip()))
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


def snapshot_diff(old_path: Path, new_path: Path) -> dict:
    """对比两份产物快照：哪些频道换了分组"""
    old = {}
    for line in old_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        grp, name = line.split("\t", 1)
        old[name] = grp
    new = {}
    for line in new_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        grp, name = line.split("\t", 1)
        new[name] = grp

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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(DATA))
    ap.add_argument("--snapshot", action="append", default=[],
                    help="产物快照 tsv，可给两次做漂移对比")
    args = ap.parse_args()

    data = Path(args.dataset)
    bugs = load_tsv(data / "known_bugs.tsv")
    good = load_tsv(data / "known_good.tsv")

    bp, bt, bf = eval_pairs(bugs)
    gp, gt, gf = eval_pairs(good)

    print(f"known_bugs  (误判修复集): {bp}/{bt} 通过")
    for name, exp, act, _ in bf:
        print(f"    FAIL {name!r}: 期望 {exp} / 实际 {act}")
    print(f"known_good  (不退化集): {gp}/{gt} 通过")
    for name, exp, act, _ in gf:
        print(f"    REGRESSION {name!r}: 期望 {exp} / 实际 {act}")

    total_pass, total = bp + gp, bt + gt
    print(f"\n合计: {total_pass}/{total}")

    if len(args.snapshot) >= 2:
        d = snapshot_diff(Path(args.snapshot[0]), Path(args.snapshot[1]))
        print(f"\n快照对比: 共同 {d['common']} 条，移组 {len(d['moved'])} 条，"
              f"新增 {len(d['added'])}，消失 {len(d['removed'])}")
        for (a, b), n in d["by_pair"].most_common(15):
            print(f"    {n:4}  {a}  →  {b}")

    ok = not bf and not gf
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
