#!/usr/bin/env python3
"""scripts/validate_shard.py —— CI 矩阵分片：只验证全量频道中的**自己那一份**。

为什么要分片
------------
验证阶段占整条流水线 **99%** 的时间（run #211 实测：抓取 8.8s / 验证 717.2s）。
单个 job 里能动的只有并发，而并发被两头夹住：

- 全局并发再往上（160/240）会被源站限流 → 掉条，实测过；
- 单 job 的 wall clock 下限 = 串行总耗时 ÷ 并发，压不到「源站响应速度」以下。

唯一能线性压缩 wall clock 的办法是**多 runner 并行** —— 把 19,547 条 URL
切成 N 份，N 个 job 各验一份，最后一个 job 合并。N=4 时验证阶段
717s → 约 180s + 合并开销。

分片规则
--------
按 `sha1(url) % shard_count == shard_index` 切分，不用轮转切片：

- **稳定**：同一 URL 永远落在同一片，跨 run 可比、可重跑单片。
- **均衡**：sha1 分布均匀；实测按 host 轮转切片会因为热 host 集中而倾斜
  （`stream1.freetv.fun` 1,199 条会全挤在少数几片里）。

产物
----
只写一个 JSON：本片**验证有效**的 URL 列表。不写 stream_health 快照 ——
熔断冻结期 `min(24h, 60 × 2^bad_count)` 对 3 连败也才 8 分钟，
远小于 CI 跑批间隔，快照在 CI 场景里本来就几乎不生效，合并它只增加
竞态和复杂度（N 个 job 抢同一个文件）。

用法
----
    python -u scripts/validate_shard.py --shard-index 0 --shard-count 4 \\
        --validate-concurrency 80 --validate-timeout 10 --out-dir ./shard-0

CI 里由 `.github/workflows/update.yml` 的 `shard` job 调用，
`update` job 用 `--valid-urls-file` 消费合并结果。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402
from src.fetcher import Fetcher  # noqa: E402
from src.validator import Validator  # noqa: E402


def shard_of(url: str, shard_count: int) -> int:
    """稳定的分片函数：同一 URL 永远落同一片。"""
    digest = hashlib.sha1(url.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


async def amain() -> int:
    ap = argparse.ArgumentParser(
        description="CI 矩阵分片：只验证全量频道中的一个切片，输出有效 URL 列表"
    )
    ap.add_argument("--shard-index", type=int, required=True, help="本片下标（0 起）")
    ap.add_argument("--shard-count", type=int, required=True, help="总片数")
    ap.add_argument("--validate-concurrency", type=int, default=80, help="本片并发")
    ap.add_argument("--validate-timeout", type=int, default=10, help="单条超时秒数")
    ap.add_argument("--fetch-timeout", type=int, default=300, help="抓取超时秒数")
    ap.add_argument("--out-dir", default=None, help="产物目录（默认 ./shard-<index>）")
    ap.add_argument("--config", "-c", default=None, help="配置文件目录")
    args = ap.parse_args()

    if args.shard_count < 1:
        ap.error("--shard-count 必须 >= 1")
    if not 0 <= args.shard_index < args.shard_count:
        ap.error(
            f"--shard-index 必须在 0..{args.shard_count - 1} 之间，"
            f"收到 {args.shard_index}"
        )

    out_dir = Path(args.out_dir or f"./shard-{args.shard_index}")
    out_dir.mkdir(parents=True, exist_ok=True)

    config = Config(args.config)
    print(f"[shard {args.shard_index}/{args.shard_count}] 开始抓取…", flush=True)
    fetcher = Fetcher(config)
    try:
        channels = await asyncio.wait_for(
            fetcher.fetch_all(), timeout=args.fetch_timeout
        )
    except asyncio.TimeoutError:
        print(f"❌ 抓取超时（{args.fetch_timeout}s）", file=sys.stderr)
        return 1

    mine = [ch for ch in channels if shard_of(ch.url, args.shard_count) == args.shard_index]
    print(
        f"[shard {args.shard_index}/{args.shard_count}] "
        f"全量 {len(channels)} 条 → 本片 {len(mine)} 条",
        flush=True,
    )
    if not mine:
        # 空片是合法的（URL 总数少于片数），写空列表让合并侧不用特判
        (out_dir / "valid.json").write_text("[]", encoding="utf-8")
        print("[shard] 本片无 URL，已写空列表", flush=True)
        return 0

    validator = Validator(
        config,
        max_concurrent=args.validate_concurrency,
        timeout=args.validate_timeout,
    )
    valid = await validator.validate(mine)
    urls = sorted(ch.url for ch in valid)

    dest = out_dir / "valid.json"
    dest.write_text(json.dumps(urls, ensure_ascii=False, indent=0), encoding="utf-8")
    print(
        f"[shard {args.shard_index}/{args.shard_count}] "
        f"有效 {len(urls)}/{len(mine)} → {dest}",
        flush=True,
    )

    # 写 GitHub Actions 的 job summary / output，方便在 UI 上直接看
    summary = Path(out_dir / "summary.txt")
    summary.write_text(
        f"shard {args.shard_index}/{args.shard_count}: "
        f"{len(urls)}/{len(mine)} valid\n",
        encoding="utf-8",
    )
    step_summary = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(
                f"- shard {args.shard_index}/{args.shard_count}: "
                f"**{len(urls)}/{len(mine)}** valid\n"
            )
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
