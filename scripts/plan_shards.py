#!/usr/bin/env python3
"""scripts/plan_shards.py —— 生成 CI 分片矩阵（GitHub Actions `plan` job 调用）。

为什么需要它
------------
GitHub Actions 的 **job 级 `if` 不能引用 `matrix` 上下文** —— job 级 if
在矩阵展开**之前**求值。所以「本片序号 < shard_count」这种条件写不进 job 级，
只能靠**动态矩阵**来控制实际创建几个 job。

早先版本把矩阵写死 8 片、用 step 级 if 跳过超出的片，结果（run #219 实测）：
- 超出的片照样**启动 runner**、跑完 checkout + 装依赖才跳过（白烧 runner）
- 16 片配置下 8 号以上没有 artifact，合并步骤直接失败

动态矩阵让「实际创建的 job 数」精确等于 `shard_count`。

用法
----
    python scripts/plan_shards.py --count 8 --out shards.json

输出
----
- `--out` 文件：JSON 数组 `[0, 1, ...]`，workflow 用它当矩阵
- stdout：`count=N` / `shards=[...]`，供 workflow 写进 `$GITHUB_OUTPUT`

范围
----
1~16 片。1 = 不分片（退回单 job 内验证）；超过 16 直接失败 ——
再多片的收益会被「每片固定开销」（checkout + 装依赖 + 抓取约 40s）摊薄，
而实测分片收益本身按 √ 衰减（见 docs/ci.md §8.5），收益已经很有限。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MIN_SHARDS = 1
MAX_SHARDS = 16


def build_matrix(count: int) -> list[int]:
    """返回分片下标列表；越界直接抛错。"""
    if not isinstance(count, int):
        raise ValueError(f"分片数必须是整数，收到 {count!r}")
    if count < MIN_SHARDS or count > MAX_SHARDS:
        raise ValueError(
            f"分片数必须在 {MIN_SHARDS}~{MAX_SHARDS} 之间，收到 {count}"
        )
    return list(range(count))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="生成分片矩阵（分片数 → 下标列表），供 CI 的 plan job 使用"
    )
    ap.add_argument("--count", type=int, required=True, help="分片数（1~16）")
    ap.add_argument("--out", required=True, help="输出的 JSON 数组路径")
    ap.add_argument(
        "--github-output",
        default=None,
        help="GitHub Actions 的 GITHUB_OUTPUT 文件路径；给了就往里写 job outputs",
    )
    args = ap.parse_args()

    try:
        shards = build_matrix(args.count)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(shards), encoding="utf-8")

    # ⚠️ 这里**直接写 GITHUB_OUTPUT 文件**，不要让 workflow 去 grep/cut。
    # 早先版本在 workflow 里写 `grep '^count=' ... | cut -d= -f2- >> $GITHUB_OUTPUT`，
    # 结果 `count=16` 被削成 `16` —— **丢掉了 output 的名字**，
    # GitHub 解析时直接报「Invalid format '16'」，整个 plan job 失败（run #226 实测）。
    # GITHUB_OUTPUT 的格式是 `name=value`，名字必须一起写进去。
    lines = [f"count={args.count}", f"shards={json.dumps(shards)}"]
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
    else:
        for line in lines:
            print(line)
    print(f"✓ 已写入 {out}（{len(shards)} 片）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
