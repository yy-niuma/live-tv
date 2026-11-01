#!/usr/bin/env python3
"""scripts/smoke_progress_log.py —— 冒烟：验证阶段进度日志是否真的会打。

只取 150 条真实 URL 跑一遍 validate()，确认：
1. `[验证进度]` 行会周期性出现（不卡死不报错）；
2. 批末 `[验证耗时]` 汇总和最慢 10 条会打；
3. 结果条数正常。

用途：改完 `Validator.validate()` 的进度/统计代码后，30 秒内验证没写崩，
不用花 20 分钟跑一次 CI 才发现日志里啥都没有。
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.fetcher import Channel  # noqa: E402
from src.validator import Validator  # noqa: E402


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="冒烟：验证阶段进度日志是否真的会打（取 N 条真实 URL 跑一遍）"
    )
    ap.add_argument("--limit", type=int, default=150, help="样本条数")
    ap.add_argument("--concurrency", type=int, default=40, help="并发数")
    args = ap.parse_args()

    path = ROOT / "config" / "stream_health.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("urls", raw)
    urls = [u for u in entries if isinstance(entries[u], dict)]
    random.Random(7).shuffle(urls)
    sample = urls[: args.limit]

    chans = [Channel(name=f"c{i}", url=u) for i, u in enumerate(sample)]
    print(f"本地验证 {len(chans)} 条（并发 {args.concurrency}）—— 观察进度日志")
    v = Validator(max_concurrent=args.concurrency)
    ok = asyncio.run(v.validate(chans))
    print(f"✓ 有效 {len(ok)}/{len(chans)} 条")
    assert len(ok) <= len(chans)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
