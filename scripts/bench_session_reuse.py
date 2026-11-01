"""A/B 基准：验证阶段 session 复用的实测收益。

用法：
    .venv/bin/python scripts/bench_session_reuse.py --jobs 40 --limit 300

## 关键设计：A/B 两边跑**完全相同**的验证逻辑

第一次写这个脚本时踩过坑：旧实现用的是「简化版」（单次 GET + 只看 `#EXTM3U`），
新实现走的是完整 validator（代理黑名单 + CDN 白名单 + 熔断 + HEAD 回退 +
master 子流探测）。两边干的活不一样，测出来的「51 条判定不同 / 0.93x」
毫无意义 —— 那不是优化失败，是基准本身无效。

现在两边都走**同一个** `Validator`，唯一差别是 session 生命周期：

  A. 每 URL 新建 session（旧行为）
     —— monkeypatch `_session_scope`，让每次调用都临时建一个、用完关掉。
  B. 批次级 session（现行为）
     —— 原样。

所以判定结果**必须逐条一致**；不一致就是优化改了行为，必须报错。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aiohttp  # noqa: E402
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


@asynccontextmanager
async def _per_url_session_scope(self):
    """A 侧：每次调用都临时建一个 session（还原优化前的行为）。"""
    timeout = aiohttp.ClientTimeout(total=self.timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        yield session


async def run_both(
    urls: list[str], jobs: int, timeout: int
) -> tuple[list[bool], float, list[bool], float]:
    channels = [Channel(name=f"u{i}", url=u) for i, u in enumerate(urls)]

    # A：每 URL 新建 session
    validator_a = Validator(Config(), max_concurrent=jobs, timeout=timeout)
    validator_a._session_scope = _per_url_session_scope.__get__(validator_a)
    t0 = time.monotonic()
    valid_a = await validator_a.validate(channels)
    time_a = time.monotonic() - t0
    urls_a = {ch.url for ch in valid_a}

    # B：批次级 session
    validator_b = Validator(Config(), max_concurrent=jobs, timeout=timeout)
    t0 = time.monotonic()
    valid_b = await validator_b.validate(channels)
    time_b = time.monotonic() - t0
    urls_b = {ch.url for ch in valid_b}

    return (
        [u in urls_a for u in urls], time_a,
        [u in urls_b for u in urls], time_b,
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", type=Path, default=Path("/tmp/bench_urls.txt"))
    ap.add_argument("--jobs", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument(
        "--repeat", type=int, default=1,
        help="跑几轮取平均（网络抖动大时建议 >= 3）",
    )
    args = ap.parse_args()

    if not args.urls.is_file():
        print(f"找不到 URL 列表：{args.urls}", file=sys.stderr)
        return 2

    urls = load_urls(args.urls, args.limit)
    print(f"样本 {len(urls)} 条真实 URL，并发 {args.jobs}，超时 {args.timeout}s，"
          f"重复 {args.repeat} 轮")
    print("-" * 66)

    times_a: list[float] = []
    times_b: list[float] = []
    results_a: list[bool] = []
    results_b: list[bool] = []

    for i in range(args.repeat):
        ra, ta, rb, tb = await run_both(urls, args.jobs, args.timeout)
        times_a.append(ta)
        times_b.append(tb)
        results_a, results_b = ra, rb
        print(f"第 {i + 1}/{args.repeat} 轮："
              f"A(每URL新建) {ta:6.1f}s 可用 {sum(ra):3d} | "
              f"B(批次复用) {tb:6.1f}s 可用 {sum(rb):3d}")

    avg_a = sum(times_a) / len(times_a)
    avg_b = sum(times_b) / len(times_b)
    print("-" * 66)
    print(f"A 每 URL 新建 session：平均 {avg_a:6.1f}s")
    print(f"B 批次级 session    ：平均 {avg_b:6.1f}s")
    if avg_b > 0:
        print(f"提速：{avg_a / avg_b:.2f}x  （省 {avg_a - avg_b:.1f}s）")

    if results_a == results_b:
        print("✅ 判定结果逐条一致"
              "（同一套 validator 逻辑，唯一差别是 session 生命周期）")
        return 0
    diff = sum(1 for a, b in zip(results_a, results_b) if a != b)
    print(f"⚠️ 判定结果有 {diff} 条不同 —— 优化改变了行为，必须复查")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
