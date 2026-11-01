"""并发档位实测：找出「不丢条」的最高并发数。

用法：
    .venv/bin/python scripts/bench_concurrency.py --limit 200 --repeat 2

## 为什么需要它

`src/main.py` 的文件头记着一组旧实测：并发 60 会因源站限流掉条
（300 条样本在 236~296 之间波动），所以默认取 40。

但那组数据是在**每 URL 新建 session** 的旧实现下测的 —— 那时每次请求都
重做 TCP + TLS 握手，源站看到的是「一堆短命连接」。改成批次级 session
（连接池复用）之后，源站看到的是「少量长连接」，限流行为可能不同。

所以并发档位必须**重新实测**，不能沿用旧结论。

## 判据

对每个并发档位：
  - **可用条数**：能不能与低并发基准（--baseline，默认 20）持平
    —— 掉了就是限流/连接打满导致误判死，是硬伤；
  - **耗时**：越短越好；
  - **误判率**：与基准比，判定不同的条数（应接近 0）。

「不降低验证严格度」优先 —— 任何档位只要掉条就淘汰，
哪怕它更快。选**可用条数持平前提下最快**的那档。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402
from src.fetcher import Channel  # noqa: E402
from src.validator import Validator  # noqa: E402


def load_urls(path: Path, limit: int) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("http"):
            urls.append(line)
        if len(urls) >= limit:
            break
    return urls


async def probe(urls: list[str], jobs: int, timeout: int) -> tuple[list[bool], float]:
    validator = Validator(Config(), max_concurrent=jobs, timeout=timeout)
    channels = [Channel(name=f"u{i}", url=u) for i, u in enumerate(urls)]
    t0 = time.monotonic()
    valid = await validator.validate(channels)
    elapsed = time.monotonic() - t0
    valid_urls = {ch.url for ch in valid}
    return [u in valid_urls for u in urls], elapsed


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", type=Path, default=Path("/tmp/bench150.txt"))
    ap.add_argument("--jobs", type=str, default="20,40,60,80,100,120,150")
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--baseline", type=int, default=20,
                    help="基准并发（低并发档，用作「不丢条」的参照）")
    args = ap.parse_args()

    if not args.urls.is_file():
        print(f"找不到 URL 列表：{args.urls}", file=sys.stderr)
        return 2

    urls = load_urls(args.urls, args.limit)
    levels = [int(x) for x in args.jobs.split(",") if x.strip()]
    print(f"样本 {len(urls)} 条真实 URL，超时 {args.timeout}s，"
          f"每档重复 {args.repeat} 轮")
    print("-" * 78)
    print(f"{'并发':>6} {'可用条数':>10} {'基准可用':>10} {'掉条':>6} "
          f"{'平均耗时(s)':>12} {'判定差异':>10}")

    results: dict[int, tuple[float, list[bool]]] = {}
    base_ok: int | None = None

    for jobs in levels:
        oks: list[int] = []
        times: list[float] = []
        last: list[bool] = []
        for _ in range(args.repeat):
            res, elapsed = await probe(urls, jobs, args.timeout)
            oks.append(sum(res))
            times.append(elapsed)
            last = res
        avg_t = sum(times) / len(times)
        avg_ok = sum(oks) / len(oks)
        results[jobs] = (avg_t, last)
        if jobs == args.baseline and base_ok is None:
            base_ok = int(avg_ok)

    if base_ok is None:
        base_ok = max(int(sum(r)) for _, r in results.values())

    for jobs in levels:
        avg_t, res = results[jobs]
        ok = sum(res)
        dropped = base_ok - ok
        diff = ""
        base_res = results.get(args.baseline, (0, None))[1]
        if base_res is not None and base_res is not res:
            diff = str(sum(1 for a, b in zip(base_res, res) if a != b))
        else:
            diff = "0"
        flag = "  ⚠️ 掉条" if dropped > 0 else ""
        print(f"{jobs:>6} {ok:>10} {base_ok:>10} {dropped:>6} "
              f"{avg_t:>12.1f} {diff:>10}{flag}")

    print("-" * 78)
    # 推荐：可用条数与基准持平（不低）的前提下，最快的档位
    safe = [j for j in levels if sum(results[j][1]) >= base_ok]
    if safe:
        best = min(safe, key=lambda j: results[j][0])
        print(f"✅ 推荐并发 = {best}（可用条数持平基准 {base_ok}，"
              f"耗时 {results[best][0]:.1f}s）")
        print(f"   对比当前默认 40：{results[40][0]:.1f}s → {results[best][0]:.1f}s "
              f"（{results[40][0] / results[best][0]:.2f}x）"
              if 40 in results else "")
    else:
        print("⚠️ 没有档位能持平基准 —— 需要复核样本或源站状态")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
