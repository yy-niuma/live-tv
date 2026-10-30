"""逐源体检：报告每个数据源实际抓到多少频道。

## 为什么需要它

`python -m src.main` 只打印总量（「抓取 16,991 条」），**单源静默失效看不出来**。
2026-10-29 实测：20 个源里 11 个产出 0 条 —— 其中 8 个是 markdown 表格被当成 m3u 解析
（HTTP 200 + 0 条 + 无警告），2 个是 GitHub 代理域名挂了，1 个是源站停服。
总量仍有 18,285 条，整条流水线「看起来完全正常」。

本脚本逐源打印频道数与判定格式，把 `0 条` 标红。

## 历史记录（--history）

单次快照只能看到「现在是不是 0」，看不出「哪个源在缓慢衰减」（比如 800 → 600 → 400）。
所以每次运行把每个源的本次结果追加一行 JSONL：

    {"ts": "2026-10-30T12:00:00+08:00", "name": "...", "channels": 812,
     "status": "ok"}

`status` 三态：`ok`（> 0 条）/ `dead`（0 条且无异常）/ `error`（抓取或解析抛异常）。
默认写到 `config/sources_history.jsonl`（机器相关、时效性强，已进 .gitignore）。

**防膨胀策略**：文件只保留最近 `--history-limit` 行（默认 2000），超出时从头部丢弃。
20 个源 × 2000 行 ≈ 100 次运行，约为 3 个月的日更趋势，单行 ~90 字节 → 上限约 180 KB。
`--history-limit 0` 表示不限（不建议接 cron）。

写入是旁路：读历史时跳过损坏行（非 JSON 或非对象），不因为历史文件脏了就中断体检；
写历史失败只打 WARNING 到 stderr，**不改变体检退出码** —— 历史不该让健康检查变成假红。

## 用法

    .venv/bin/python scripts/check_sources.py
    .venv/bin/python scripts/check_sources.py --json sources.json
    .venv/bin/python scripts/check_sources.py --history /tmp/h.jsonl --history-limit 500
    .venv/bin/python scripts/check_sources.py --no-history

## 退出码

    0  每个启用的源都抓到了 > 0 条
    1  存在 0 条的源（这是健康检查失败，不是崩溃）
    2  配置文件读不到 / 读坏了（不存在、YAML 语法错、结构不是 mapping）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402
from src.fetcher import Fetcher  # noqa: E402

DEFAULT_HISTORY_LIMIT = 2000
DEFAULT_HISTORY_NAME = "sources_history.jsonl"


class SourceConfigError(Exception):
    """sources.yaml 存在但读坏了（YAML 语法错 / 结构不是 mapping）。"""


def default_history_path() -> Path:
    """默认历史文件：仓库内 config/，与 cwd 无关（cron 从任意目录跑都能落对地方）。"""
    return ROOT / "config" / DEFAULT_HISTORY_NAME


def resolve_history_path(path: Path | None) -> Path:
    """`--history` 的解析规则：缺省用仓库内默认路径，相对路径按 cwd 展开。"""
    if path is None:
        return default_history_path()
    return path if path.is_absolute() else Path.cwd() / path


def sources_yaml_path(config_dir: Path | None = None) -> Path:
    """配置目录里的 sources.yaml 路径（仅为报错信息与测试可注入）。"""
    base = Path(config_dir) if config_dir is not None else ROOT / "config"
    return base / "sources.yaml"


def load_sources(config_dir: Path | None = None) -> list[dict]:
    """读启用中的数据源。

    文件不存在 / 没有启用源 → 返回 `[]`（由调用方判为「读不到配置」）。
    文件存在但坏了 → 抛 `SourceConfigError`，让调用方给一行可读报错而不是 traceback。
    """
    try:
        cfg = Config()
        if config_dir is not None:
            # Config 的 sources 是惰性属性，首次访问前改 config_dir 是安全的；
            # 这样既能注入临时配置目录，也不用给 Config 的隐式 Optional 签名加忽略。
            cfg.config_dir = Path(config_dir)
        return list(cfg.sources)
    except (yaml.YAMLError, OSError, AttributeError, TypeError) as exc:
        raise SourceConfigError(f"{type(exc).__name__}: {exc}") from exc


def row_status(row: dict) -> str:
    """把一行体检结果压成三态，供历史记录做趋势判断。"""
    if row.get("error"):
        return "error"
    return "ok" if row.get("channels") else "dead"


async def probe_source(fetcher: Fetcher, src: dict) -> dict:
    """抓一个源并数条数。任何异常都收敛成 `error` 字段，绝不外抛。

    外抛会让「一个源挂掉」升级成「整次体检没结果」，这正好是静默失效的反面错误。
    """
    name = src.get("name", "?")
    url = src.get("url", "")
    try:
        text = await fetcher._get_text(url, headers=src.get("headers") or None)
        result = fetcher.parse_text(text)
        count, fmt, err = len(result.channels), result.format, ""
    except Exception as exc:  # noqa: BLE001
        count, fmt, err = 0, "-", f"{type(exc).__name__}: {exc}"[:90]
    return {
        "name": name,
        "url": url,
        "priority": src.get("priority"),
        "channels": count,
        "format": fmt,
        "error": err,
    }


async def probe_all(sources: list[dict], concurrency: int) -> list[dict]:
    """顺序遍历数据源（并发度由 fetcher 的信号量管），返回逐源结果。"""
    fetcher = Fetcher(max_concurrent=concurrency, max_retries=1)
    # `_fetch_source()` 依赖 `self._semaphore`，而它只在 `fetch_all()` 里初始化。
    # 直接调 `_get_text()` 会拿到 None 并抛
    # "'NoneType' object does not support the asynchronous context manager protocol"。
    # （`_get_text()` 现在会惰性补一个，这里显式建仍然更清楚。）
    fetcher._semaphore = asyncio.Semaphore(concurrency)
    return [await probe_source(fetcher, src) for src in sources]


def print_report(rows: list[dict]) -> tuple[int, list[str]]:
    """打印表格与汇总，返回 (合计条数, 零产出源名列表)。"""
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
    return total, dead


def read_history(path: Path) -> list[str]:
    """读历史文件里**有效**的行（损坏行丢弃，避免脏行把行数上限吃掉）。"""
    if not path.exists():
        return []
    kept: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            kept.append(line)
    return kept


def append_history(
    path: Path,
    rows: list[dict],
    *,
    ts: str | None = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> int:
    """把本次逐源结果追加到 JSONL，返回写完后的总行数。

    `limit` > 0 时只保留最近 `limit` 行（从头部丢）；`limit` <= 0 表示不限。
    先写 `.tmp` 再 `replace()`，避免中途被打断留下半截文件（CI 被 timeout 杀掉很常见）。
    """
    stamp = ts or datetime.now().astimezone().isoformat(timespec="seconds")
    new_lines = [
        json.dumps(
            {
                "ts": stamp,
                "name": r["name"],
                "channels": r["channels"],
                "status": row_status(r),
            },
            ensure_ascii=False,
        )
        for r in rows
    ]
    combined = read_history(path) + new_lines
    if limit > 0 and len(combined) > limit:
        combined = combined[-limit:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(combined) + "\n", encoding="utf-8")
    tmp.replace(path)
    return len(combined)


async def audit(
    json_path: Path | None = None,
    concurrency: int = 6,
    *,
    config_dir: Path | None = None,
    history_path: Path | None = None,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
) -> int:
    """跑一次体检，返回退出码。`history_path=None` 表示不写历史。"""
    cfg_path = sources_yaml_path(config_dir)
    try:
        sources = load_sources(config_dir)
    except SourceConfigError as exc:
        print(f"读不到数据源配置：{cfg_path}（{exc}）", file=sys.stderr)
        return 2
    if not sources:
        detail = "" if cfg_path.exists() else "（文件不存在）"
        print(f"读不到数据源配置：{cfg_path}{detail}", file=sys.stderr)
        return 2

    rows = await probe_all(sources, concurrency)
    total, dead = print_report(rows)

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

    if history_path is not None:
        try:
            kept = append_history(history_path, rows, limit=history_limit)
        except OSError as exc:
            # 历史是旁路产物：写不了也要让体检结论出来（不能让磁盘问题伪装成源故障）
            print(f"⚠️ 历史写入失败（不影响体检结论）：{exc}", file=sys.stderr)
        else:
            print(f"历史已追加 {len(rows)} 行到 {history_path}（现共 {kept} 行）")

    return 1 if dead else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="逐源体检：每个 IPTV 数据源实际抓到了多少频道"
    )
    ap.add_argument("--json", type=Path, default=None, help="把逐源结果写成 JSON")
    ap.add_argument("--jobs", type=int, default=6, help="并发数（默认 6）")
    ap.add_argument(
        "--config-dir", type=Path, default=None, help="配置目录（默认仓库内 config/）"
    )
    ap.add_argument(
        "--history",
        type=Path,
        default=None,
        help=f"历史 JSONL 路径（默认 config/{DEFAULT_HISTORY_NAME}）",
    )
    ap.add_argument("--no-history", action="store_true", help="不写历史记录")
    ap.add_argument(
        "--history-limit",
        type=int,
        default=DEFAULT_HISTORY_LIMIT,
        help=f"历史最多保留多少行（默认 {DEFAULT_HISTORY_LIMIT}；0 = 不限）",
    )
    args = ap.parse_args(argv)

    history = None if args.no_history else resolve_history_path(args.history)
    return asyncio.run(
        audit(
            args.json,
            args.jobs,
            config_dir=args.config_dir,
            history_path=history,
            history_limit=args.history_limit,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
