"""对 hk_merged.m3u 里的每一条频道 URL 做可用性验证，输出逐条结果 + 汇总。

用途：收尾「hk_merged 新增条目播放可用性未验证」这项遗留。
直接复用 src/validator.py 的判定口径（代理域名拒绝 / CDN 白名单 / HEAD 优先），
所以结论与流水线 --skip-validation 之外的行为一致。

用法:
    .venv/bin/python scripts/check_streams.py output/hk_merged.m3u
    .venv/bin/python scripts/check_streams.py <m3u> --jobs 20 --json out.json

退出码（重要，接 cron / CI 时别误判）:
    0  全部可用
    1  **跑完了，但存在不可用条目** —— 这是本工具的设计行为，不是崩溃。
       探测"流能不能播"这件事本身就以"有死链"为常态，所以不能拿退出码当异常。
    2  解析不出任何频道（m3u 路径或格式错），这才是真错误。

    如果要把"死链过多"当失败条件，请自己读 --json 输出判定，
    例如 `ok / total < 0.5` 才算失败。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fetcher import Channel  # noqa: E402
from src.validator import Validator  # noqa: E402

EXTINF_NAME = re.compile(r",([^,]*)$")


def parse_m3u(path: Path) -> list[Channel]:
    """从 m3u 取出 (名称, 分组, URL) 三元组；跳过 # ... and N more 之类的注释行。"""
    channels: list[Channel] = []
    group = ""
    name = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#EXTGRP:"):
            # #EXTGRP:📺 TVB (14)  ->  📺 TVB
            group = re.sub(r"\s*\(\d+\)\s*$", "", line[len("#EXTGRP:"):])
        elif line.startswith("#EXTINF:"):
            m = EXTINF_NAME.search(line)
            name = (m.group(1).strip() if m else "")
            # 分组在 #EXTINF 的 group-title 里也有一份，优先用它
            gm = re.search(r'group-title="([^"]*)"', line)
            if gm:
                group = gm.group(1)
        elif line and not line.startswith("#"):
            channels.append(Channel(name=name, url=line, group=group, logo=""))
    return channels


async def run(channels: list[Channel], jobs: int, timeout: int) -> list[dict]:
    v = Validator(max_concurrent=jobs, timeout=timeout)
    v._semaphore = asyncio.Semaphore(jobs)

    async def one(ch: Channel) -> dict:
        try:
            ok = await v._validate_one(ch)
        except Exception as exc:  # noqa: BLE001 — 单条异常不该中断整批
            ok = False
            return {"name": ch.name, "group": ch.group, "url": ch.url,
                    "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"name": ch.name, "group": ch.group, "url": ch.url,
                "ok": bool(ok), "error": ""}

    return await asyncio.gather(*(one(ch) for ch in channels))


def main() -> int:
    ap = argparse.ArgumentParser(description="验证 m3u 里每条流 URL 的可达性")
    ap.add_argument("m3u", type=Path)
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--json", type=Path, default=None, help="把逐条结果写成 JSON")
    ap.add_argument("--only", default=None, help="只验证名字匹配该正则的频道")
    ap.add_argument("--quiet", action="store_true", help="只打汇总，不逐条")
    ap.add_argument("--max-bad-ratio", type=float, default=None,
                    help="不可用占比超过该值时以退出码 1 表示「超阈值」；"
                         "不传则退 1 仅表示「存在不可用条目」")
    args = ap.parse_args()

    if not args.m3u.is_file():
        print(f"文件不存在: {args.m3u}", file=sys.stderr)
        return 2

    channels = parse_m3u(args.m3u)
    if args.only:
        pat = re.compile(args.only, re.I)
        channels = [c for c in channels if pat.search(c.name)]
    if not channels:
        print("没有解析到任何频道，检查 m3u 路径/格式", file=sys.stderr)
        return 2

    print(f"待验证 {len(channels)} 条"
          f"（jobs={args.jobs} timeout={args.timeout}s）…", flush=True)
    results = asyncio.run(run(channels, args.jobs, args.timeout))

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    if not args.quiet:
        print(f"\n{'结果':<6} {'分组':<16} 频道名 / URL")
        print("-" * 100)
        for r in sorted(results, key=lambda x: (not x["ok"], x["group"], x["name"])):
            mark = "OK  " if r["ok"] else "FAIL"
            tail = r["url"] if not r["error"] else f"{r['url']}  [{r['error']}]"
            print(f"{mark:<6} {r['group'][:16]:<16} {r['name'][:28]:<28} {tail[:70]}")

    print(f"\n合计 {len(results)}  可用 {len(ok)}  不可用 {len(bad)}"
          f"  可用率 {len(ok) / len(results) * 100:.1f}%")
    if bad:
        print("\n不可用条目按分组统计：")
        by_group: dict[str, int] = {}
        for r in bad:
            key = r["group"] or "(无分组)"
            by_group[key] = by_group.get(key, 0) + 1
        for g, n in sorted(by_group.items(), key=lambda x: -x[1]):
            print(f"  {g:<20} {n}")

    if args.json:
        args.json.write_text(
            json.dumps({"source": str(args.m3u), "total": len(results),
                        "ok": len(ok), "bad": len(bad), "results": results},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n逐条结果已写入 {args.json}")
    if args.max_bad_ratio is None:
        return 0 if not bad else 1
    ratio = len(bad) / len(results)
    if ratio > args.max_bad_ratio:
        print(f"\n不可用占比 {ratio:.1%} 超过阈值 {args.max_bad_ratio:.1%}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
