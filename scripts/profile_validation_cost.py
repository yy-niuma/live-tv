#!/usr/bin/env python3
"""scripts/profile_validation_cost.py —— 验证阶段的耗时到底花在哪。

为什么需要这个脚本
------------------
2026-11-01 我用 `stream_health.json` 的分布反推了一次：

    8,949 条死链 × 10s ÷ 并发 80 = 1,119s
    CI 实测验证                    1,070s     ← 「几乎完全吻合」

据此判定「验证阶段全部耗时都在等死链超时」，并实现了分级超时
（`Validator._timeout_for`，已知死链用 4s）。但端到端 A/B 只快了不到 20%，
说明那个反推**是巧合，不是事实**。

反推错在哪：它假设「死链都会耗满超时」。实际上死链的失败方式差别很大 ——
connection refused / DNS 失败是**毫秒级**返回的，只有「包被丢弃」才是耗满超时。
而活链也不一定快：有些源站响应本身就要好几秒。

本脚本直接量，不反推：
1. 从健康快照取 `n` 条，按 ok/alive 分组；
2. 逐条单独计时（用一个较大的并发池，但**每条独立计时**）；
3. 输出活链 / 死链各自的耗时分布（p50 / p90 / mean）和总耗时贡献；
4. 再按 `bad_count` 分组输出，用于验证分级超时到底能省多少。

用法：
    .venv/bin/python scripts/profile_validation_cost.py --limit 400
    .venv/bin/python scripts/profile_validation_cost.py --limit 400 --urls 40

⚠️ 必须在**没有别的网络任务**跑的时候测，否则 DNS 争用会把数据搞脏
（见 docs/ci.md §7.2.2）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.validator import Validator  # noqa: E402


def load_sample(limit: int, jobs: int, seed: int = 42):
    """按「活/死」分层抽样，保证两组都有足够样本。"""
    import random

    path = ROOT / "config" / "stream_health.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("urls", raw)

    alive: list[tuple[str, int]] = []
    dead: list[tuple[str, int]] = []
    for url, v in entries.items():
        if not isinstance(v, dict):
            continue
        rec = (url, v.get("bad_count", 0) or 0)
        (alive if v.get("ok") else dead).append(rec)

    rnd = random.Random(seed)
    rnd.shuffle(alive)
    rnd.shuffle(dead)
    # 各取一半，尽量贴近「活/死各约一半」的真实构成
    half = limit // 2
    sample = alive[:half] + dead[: half + (limit - 2 * half)]
    rnd.shuffle(sample)
    return sample


async def time_one(
    v: Validator, url: str, outer: asyncio.Semaphore
) -> tuple[bool, float]:
    """在**外层** semaphore 内计时 —— 只量请求本身，不含排队时间。

    ⚠️ 第一版把计时放在了外层 semaphore 外面，结果 dt 里混进了「排队等名额」
    的时间：400 条样本 sum/40 = 86s，而墙钟只有 27s —— 自相矛盾，
    说明每条的 dt 被背书得离谱。凡是「并行度 > 1 又要逐条计时」的基准，
    计时点必须在并发闸门**之后**。
    """
    async with outer:
        t0 = time.monotonic()
        try:
            ok = await v._check_url(url)
        except Exception:
            ok = False
        return ok, time.monotonic() - t0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400, help="样本条数（活死各半）")
    ap.add_argument("--urls", type=int, default=40, help="并发池大小")
    ap.add_argument("--timeout", type=int, default=10, help="完整超时（秒）")
    args = ap.parse_args()

    sample = load_sample(args.limit, args.urls)
    print(f"样本 {len(sample)} 条（活/死分层抽样），并发池 {args.urls}，"
          f"完整超时 {args.timeout}s\n")

    v = Validator()
    v.timeout = args.timeout
    # 内部 semaphore 放开（避免二次限流干扰计时），并发闸门只留外层一个
    v._semaphore = asyncio.Semaphore(100000)
    outer = asyncio.Semaphore(args.urls)

    t_start = time.monotonic()
    results = await asyncio.gather(*[time_one(v, u, outer) for u, _ in sample])
    wall = time.monotonic() - t_start

    buckets: dict[str, list[float]] = defaultdict(list)
    bad_buckets: dict[int, list[float]] = defaultdict(list)
    for (url, bad), (ok, dt) in zip(sample, results):
        buckets["活" if ok else "死"].append(dt)
        bad_buckets[bad].append(dt)

    def stats(xs: list[float]) -> str:
        if not xs:
            return "—"
        xs = sorted(xs)
        p = lambda q: xs[min(len(xs) - 1, int(len(xs) * q))]  # noqa: E731
        return (f"n={len(xs):4d}  mean={statistics.fmean(xs):5.2f}s  "
                f"p50={p(.5):5.2f}s  p90={p(.9):5.2f}s  max={xs[-1]:5.2f}s")

    print("=" * 78)
    print(f"墙钟总耗时 {wall:.1f}s（并发池 {args.urls}）\n")
    for k in ("活", "死"):
        xs = buckets[k]
        share = sum(xs) / max(1e-9, sum(buckets["活"] + buckets["死"])) * 100
        print(f"{k}链：{stats(xs)}")
        print(f"      串行耗时占比 {share:5.1f}%  "
              f"（{sum(xs):.0f}s 串行）\n")

    print("-" * 78)
    print("按 bad_count 分组（分级超时只对 >=2 生效）：")
    for bad in sorted(bad_buckets):
        xs = bad_buckets[bad]
        saved = 0.0
        if bad >= 2:
            # 串行意义下，每条最多能从完整超时省到短超时
            saved = sum(max(0.0, min(x, args.timeout) - 4.0) for x in xs)
        print(f"  bad={bad}: {stats(xs)}")
        if bad >= 2:
            print(f"           分级超时理论可省 {saved:.0f}s 串行 "
                  f"→ {saved / args.urls:.0f}s 墙钟（并发 {args.urls}）")

    print("\n" + "=" * 78)
    print("结论提示：哪个分组「串行耗时占比」最大，提速就该从哪里下手。")
    print("若「死链」占比不高、且 p90 远小于超时 → 分级超时收益有限，")
    print("真正的杠杆是并发（但要看掉条）或减少总条数。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
