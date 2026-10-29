"""逐源体检：报告每个数据源实际抓到多少频道。

## 为什么需要它

`python -m src.main` 只打印总量（「抓取 16,991 条」），**单源静默失效看不出来**。
2026-10-29 实测：20 个源里 11 个产出 0 条 —— 其中 8 个是 markdown 表格被当成 m3u 解析
（HTTP 200 + 0 条 + 无警告），2 个是 GitHub 代理域名挂了，1 个是源站停服。
总量仍有 18,285 条，整条流水线「看起来完全正常」。

本脚本逐源打印频道数与判定格式，把 `0 条` 标红。

## 用法

    .venv/bin/python scripts/check_sources.py
    .venv/bin/python scripts/check_sources.py --json sources.json

## 退出码

    0  每个启用的源都抓到了 > 0 条
    1  存在 0 条的源（这是健康检查失败，不是崩溃）
    2  配置文件读不到
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402
from src.fetcher import Fetcher  # noqa: E402


async def audit(json_path: Path | None, concurrency: int) -> int:
    cfg = Config()
    sources = cfg.sources
    if not sources:
        print(f"读不到数据源配置：{cfg.config_dir / 'sources.yaml'}", file=sys.stderr)
        return 2

    fetcher = Fetcher(config=cfg, max_concurrent=concurrency, max_retries=1)
    # `_fetch_source()` 依赖 `self._semaphore`，而它只在 `fetch_all()` 里初始化。
    # 直接调 `_fetch_source()` 会拿到 None 并抛
    # "'NoneType' object does not support the asynchronous context manager protocol"。
    fetcher._semaphore = asyncio.Semaphore(concurrency)

    rows = []
    for src in sources:
        name = src.get("name", "?")
        url = src.get("url", "")
        try:
            text = await fetcher._get_text(url, headers=src.get("headers") or None)
            result = fetcher.parse_text(text)
            count, fmt, err = len(result.channels), result.format, ""
        except Exception as exc:  # noqa: BLE001
            count, fmt, err = 0, "-", f"{type(exc).__name__}: {exc}"[:90]
        rows.append(
            {
                "name": name,
                "url": url,
                "priority": src.get("priority"),
                "channels": count,
                "format": fmt,
                "error": err,
            }
        )

    print("=" * 104)
    print(f"{'源':26} {'频道数':>7}  {'格式':9} {'优先级':>5}  url")
    print("=" * 104)
    for r in rows:
        flag = "🔴" if r["channels"] == 0 else "  "
        print(
            f"{flag}{r['name']:24} {r['channels']:>7}  {r['format']:9} "
            f"{r['priority']!s:>5}  {r['url'][:52]}"
        )
        if r["error"]:
            print(f"    └─ {r['error']}")

    total = sum(r["channels"] for r in rows)
    dead = [r["name"] for r in rows if r["channels"] == 0]
    print("=" * 104)
    print(f"合计 {total} 条 / {len(rows)} 个启用源")
    if dead:
        print(f"🔴 零产出 {len(dead)} 个：{dead}")
        print("   排查顺序：1) 直接 curl 看 http 码与内容前几行")
        print("             2) 看上面「格式」列 —— empty 说明 parse_text() 不认识它")
    else:
        print("✅ 每个源都抓到了内容")

    if json_path:
        json_path.write_text(
            json.dumps(
                {"total": total, "sources": rows, "dead": dead},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"逐源结果已写入 {json_path}")

    return 1 if dead else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="逐源体检：每个 IPTV 数据源实际抓到了多少频道"
    )
    ap.add_argument("--json", type=Path, default=None, help="把逐源结果写成 JSON")
    ap.add_argument("--jobs", type=int, default=6, help="并发数（默认 6）")
    args = ap.parse_args()
    return asyncio.run(audit(args.json, args.jobs))


if __name__ == "__main__":
    raise SystemExit(main())
