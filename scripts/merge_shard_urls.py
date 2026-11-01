#!/usr/bin/env python3
"""scripts/merge_shard_urls.py —— 把 N 个分片的有效 URL 列表合成一份。

输入：若干 `valid.json`（每份是一个 URL 字符串数组，`validate_shard.py` 产出）。
输出：一份去重排序后的 JSON 数组，交给 `src.main --valid-urls-file` 消费。

为什么单独一个脚本而不是在 workflow 里内联 python
--------------------------------------------------
1. 可以本地测（`tests/test_merge_shard_urls.py` 锁住语义）；
2. workflow 里的内联代码改一次就没人测一次，这是这个仓库反复吃过的亏
   （见 docs/known-issues.md §13 的 check_sources.py 误报）。

语义
----
- **并集**：任何一片判定有效就算有效。分片是互斥切分，正常情况下不会
  重叠；万一重跑导致同一 URL 出现在两片里，并集也是安全的方向
  （不会因为某片漏跑而丢频道）。
- **空文件不报错**：URL 总数少于片数时会出现空片，这是合法的。
- **缺失文件报错**：片数声明了 4 片却只给了 3 个文件，说明某个 shard job
  失败了 —— 这时必须失败退出，否则会静默交付少掉 1/4 的产物。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def merge(paths: list[Path], expected: int | None = None) -> list[str]:
    """读入并合并分片结果。"""
    found = [p for p in paths if p.exists()]
    if expected is not None and len(found) != expected:
        missing = [str(p) for p in paths if not p.exists()]
        raise SystemExit(
            f"❌ 期望 {expected} 个分片文件，实际找到 {len(found)} 个；"
            f"缺失：{missing}\n"
            "某个 shard job 可能失败了 —— 拒绝继续，避免交付残缺产物。"
        )

    urls: set[str] = set()
    per_file: list[tuple[str, int]] = []
    for p in found:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"❌ {p}: 期望 JSON 数组，实际 {type(data).__name__}")
        per_file.append((str(p), len(data)))
        urls.update(u for u in data if isinstance(u, str) and u)

    for name, n in per_file:
        print(f"  {name}: {n} 条", flush=True)
    print(f"合并后去重: {len(urls)} 条", flush=True)
    return sorted(urls)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="合并 N 个分片的有效 URL 列表（并集去重）"
    )
    ap.add_argument("inputs", nargs="+", help="分片 valid.json 路径")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    ap.add_argument(
        "--expected",
        type=int,
        default=None,
        help="期望的分片数；数量不符则失败退出",
    )
    args = ap.parse_args()

    urls = merge([Path(p) for p in args.inputs], args.expected)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(urls, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"✓ 已写入 {out}（{len(urls)} 条）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
