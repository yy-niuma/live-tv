"""IPTV 主入口"""
import argparse
import asyncio
import json
import os  # noqa: F401 —— 历史遗留导入，pyproject 已记账，本 lane 不动
import sys
import time
from pathlib import Path

from src.config import Config
from src.fetcher import Fetcher
from src.validator import Validator
from src.grouper import Grouper
from src.generator import Generator
from src.lib.cache import SimpleCache as Cache
from src.lib import stream_health

# ---------------------------------------------------------------------------
# 验证阶段的默认并发 / 单条超时 —— 这两个数字是**实测出来的**，不是拍脑袋
# ---------------------------------------------------------------------------
#
# 背景：src/validator.py 的 `Validator(config=None, max_concurrent=20, timeout=10)`
# 默认值让一次完整流水线的验证阶段吃掉 ~30 分钟（19,506 条 / 20 并发 × 10s 超时），
# 而 CI 的 update job 是 timeout-minutes: 45 —— 验证一阶段就花掉三分之二预算，
# GitHub runner 网络通常还更差，超时被杀 = 当天产物不更新。所以并发必须从
# main.py 侧传参，validator.py 只负责接受参数。
#
# 实测数据（300 条真实 URL，取自 all_merged.m3u，timeout=10，每档多次交错跑）：
#     jobs=20  → 平均 295.0/300 可用，平均 17.5s   （基准）
#     jobs=30  → 平均 295.0/300 可用，平均 16.6s
#     jobs=40  → 平均 296.5/300 可用，平均 11.0s   ← 不丢可用条数且最快、方差小
#     jobs=60  → 平均 280.7/300 可用，平均 14.6s   ← 明显掉条（限流/连接打满）
#     jobs=120 → 297/300 可用，10.4s（单次样本，方差大）
#     jobs=150 → 292/300 可用，10.1s（开始掉）
# 结论：60 并发**不是**安全的提升 —— 会出现 236/300（78.7%）这种塌方run。
# 「不降低验证严格度」优先，所以默认取 40：可用条数不低于 20 并发，耗时约 1.6x 提升。
DEFAULT_VALIDATE_CONCURRENCY = 40

# 超时保持 10s：实测在 jobs=60 下把 timeout 降到 8s / 5s 会掉到 293 / 291 可用
# （相对 timeout=10 的 296~297）—— 那是把「慢但仍可用」的链路判死，
# 属于偷偷降低口径，不做。要提速只能动并发，不动超时。
DEFAULT_VALIDATE_TIMEOUT = 10


def _fmt_duration(seconds: float) -> str:
    """阶段耗时的统一格式，一律用秒（便于 CI 日志 grep 与 diff）。"""
    return f"{seconds:.1f}s"


def _print_stage_cost(stage: str, seconds: float) -> None:
    """阶段收尾时打印该阶段耗时。固定前缀便于 `grep 阶段耗时` 一眼找瓶颈。"""
    print(f"  ⏱ 阶段耗时[{stage}]: {_fmt_duration(seconds)}")


def _positive_int(text: str) -> int:
    """argparse type：只接受 >=1 的整数。

    并发 / 超时给 0 或负数不是「更快」，而是让 `asyncio.Semaphore(0)` 永久阻塞
    或者让超时立即触发 —— 两种都是静默跑出一种假的「验证通过/全部失败」。
    宁可在解析参数时就报错退出。
    """
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"需要整数，收到 {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"必须 >= 1，收到 {value}")
    return value


async def run(config_dir: str = None, output_dir: str = None, use_cache: bool = True,
              skip_validation: bool = False, skip_fetch: bool = False, fetch_timeout: int = 90,
              health_file: str = None,
              validate_concurrency: int = DEFAULT_VALIDATE_CONCURRENCY,
              validate_timeout: int = DEFAULT_VALIDATE_TIMEOUT):
    """运行完整流程

    Args:
        skip_fetch: 跳过抓取步骤，使用缓存数据（无缓存则报错）
        fetch_timeout: 抓取超时秒数（默认90秒）
        health_file: `{url: bool}` 实测可播快照（`check_streams.py --health-out` 的产物）。
            提供时合并同名频道会优先挑实测能播的链路；不提供则退化为只按 CDN 白名单排序。
            详见 src/lib/stream_health.py。
        validate_concurrency: 验证阶段并发数（默认 40，见文件头实测说明）。
            直接透传给 `Validator(max_concurrent=...)`；本模块不改 validator.py。
        validate_timeout: 验证阶段单条超时秒数（默认 10，见文件头实测说明）。

    Returns:
        dict / None。None 表示流水线提前退出（抓取失败或 skip-fetch 无缓存）。
        dict 里除原有统计外还有 `timings`（各阶段耗时秒数，含 `total`）。
    """
    # Semaphore(0) 会永久阻塞、timeout<=0 会立刻判死 —— 两个都是静默的假结果，
    # 所以即便调用方不走 CLI（直接 import run），也在入口处拦住。
    if validate_concurrency < 1:
        raise ValueError(f"validate_concurrency 必须 >= 1，收到 {validate_concurrency}")
    if validate_timeout < 1:
        raise ValueError(f"validate_timeout 必须 >= 1，收到 {validate_timeout}")

    pipeline_start = time.monotonic()
    timings: dict[str, float] = {}

    print("=" * 60)
    print("IPTV 抓取、验证、分组、生成工具")
    print("=" * 60)

    config = Config(config_dir)
    output_dir = Path(output_dir) if output_dir else Path(__file__).parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    cache = Cache()
    cache_key = "channels_raw"

    # 1. 抓取
    print("\n[Step 1/4] 抓取频道...")
    stage_start = time.monotonic()
    if skip_fetch:
        channels_data = cache.get(cache_key)
        if channels_data:
            from src.fetcher import Channel
            channels = [Channel(**d) for d in channels_data]
            print(f"  ✓ 跳过抓取，使用缓存: {len(channels)} 个频道")
        else:
            print("  ❌ 跳过抓取但无缓存数据，请先正常运行一次抓取", file=sys.stderr)
            return None
    elif use_cache:
        channels_data = cache.get(cache_key)
        if channels_data:
            print(f"  ✓ 使用缓存: {len(channels_data)} 个频道")
            from src.fetcher import Channel
            channels = [Channel(**d) for d in channels_data]
        else:
            sources = config.sources
            print(f"  开始抓取 {len(sources)} 个数据源（超时 {fetch_timeout}s）...")
            fetcher = Fetcher(config)
            try:
                channels = await asyncio.wait_for(fetcher.fetch_all(), timeout=fetch_timeout)
            except asyncio.TimeoutError:
                print(
                    f"  ❌ 抓取超时（{fetch_timeout}s），"
                    "请增加超时或使用 --skip-fetch 跳过",
                    file=sys.stderr,
                )
                return None
            cache.set(cache_key, [ch.__dict__ for ch in channels])
    else:
        sources = config.sources
        print(f"  开始抓取 {len(sources)} 个数据源（超时 {fetch_timeout}s）...")
        fetcher = Fetcher(config)
        try:
            channels = await asyncio.wait_for(fetcher.fetch_all(), timeout=fetch_timeout)
        except asyncio.TimeoutError:
            print(
                f"  ❌ 抓取超时（{fetch_timeout}s），"
                "请增加超时或使用 --skip-fetch 跳过",
                file=sys.stderr,
            )
            return None

    print(f"  ✓ 抓取完成: 共 {len(channels)} 个频道")
    timings["fetch"] = time.monotonic() - stage_start
    _print_stage_cost("抓取", timings["fetch"])

    # 2. 验证
    print(f"\n[Step 2/4] 验证 URL（并发 {validate_concurrency} / "
          f"单条超时 {validate_timeout}s）...")
    stage_start = time.monotonic()
    if skip_validation:
        print("  ⚠ 跳过验证（--skip-validation）")
        valid_channels = channels
    else:
        # 并发 / 超时只能从这一侧传参：src/validator.py 由图外的 lane 独占，
        # 不许改它的默认值。Validator 的构造签名是
        #   Validator(config=None, max_concurrent=20, timeout=10)
        validator = Validator(config, max_concurrent=validate_concurrency,
                              timeout=validate_timeout)
        valid_channels = await validator.validate(channels)
        print(f"  ✓ 验证完成: {len(valid_channels)}/{len(channels)} 个有效")
    timings["validate"] = time.monotonic() - stage_start
    _print_stage_cost("验证", timings["validate"])

    # 3. 分组
    print("\n[Step 3/4] 分组频道...")
    stage_start = time.monotonic()
    health = dict((stream_health.load(health_file) if health_file
                   else stream_health.load()) or {})
    # 本轮实测**覆盖**历史快照：快照是整轮跑完才落盘的，如果只用快照，合并时
    # 用的是上一轮的结论 —— 上一轮「还活着」的死链会压过本轮新验到的活源
    # （RTHK 31/32 就是被 `rthk.hk` 域的旧结论拖死的）。本轮通过验证的 URL
    # 一律记为可播，判定以最新观测为准。
    if valid_channels:
        health.update({ch.url: True for ch in valid_channels})
    if health:
        good = sum(1 for v in health.values() if v)
        print(f"[Health] 载入 {len(health)} 条实测结果（可播 {good} / 不可播 {len(health) - good}）")
    grouper = Grouper(config, health=health)
    grouped = grouper.group(valid_channels)

    # 统计各分组频道数
    top_groups = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    print(f"  ✓ 分组完成: 共 {len(grouped)} 个分组")
    print(f"  Top 5 分组:")
    for name, chs in top_groups:
        print(f"    - {name}: {len(chs)} 个频道")
    timings["group"] = time.monotonic() - stage_start
    _print_stage_cost("分组", timings["group"])

    # 4. 生成
    print("\n[Step 4/4] 生成播放列表...")
    stage_start = time.monotonic()
    generator = Generator()

    # 生成 hk_merged.m3u 和 all_merged.m3u
    result = generator.generate_hk_and_all(grouped, str(output_dir))
    print(f"  ✓ 港澳台: {result['hk']['channels']} 频道, {result['hk']['groups']} 分组")
    print(f"  ✓ 全球: {result['all']['channels']} 频道, {result['all']['groups']} 分组")

    # 统计
    stats = {g: len(chs) for g, chs in grouped.items()}
    stats_path = output_dir / "stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 统计已保存: {stats_path}")
    timings["generate"] = time.monotonic() - stage_start
    _print_stage_cost("生成", timings["generate"])

    timings["total"] = time.monotonic() - pipeline_start

    print("\n" + "=" * 60)
    print("完成！")
    print(f"⏱ 总耗时: {_fmt_duration(timings['total'])}")
    print("=" * 60)

    merged_total = sum(len(chs) for chs in grouped.values())
    return {
        # `total` 是「抓取去重后的唯一频道数」（未跳过验证时也等于验证通过的数）。
        # 注意它**不等于**分组后的条数：同名频道会被合并掉一批，
        # 所以再单独给出 `merged`。两个数字都别跟 m3u 里的 #EXTINF 条数直接对比
        # （生成阶段还有脏名过滤 + 每分组 100 条上限，见 docs/known-issues.md）。
        "total": len(valid_channels),
        "merged": merged_total,
        "groups": len(grouped),
        "hk_channels": result['hk']['channels'],
        "all_channels": result['all']['channels'],
        "output": str(output_dir),
        "stats": stats,
        # 各阶段耗时（秒）：fetch / validate / group / generate / total
        "timings": timings,
    }


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 解析器。

    单独抽成函数是为了让测试能直接断言参数默认值 / --help 文本，
    不用起子进程、更不用真的跑流水线（`main()` 里只有 asyncio.run）。
    """
    parser = argparse.ArgumentParser(description="IPTV 抓取、验证、分组、生成工具")
    parser.add_argument("--config", "-c", default=None, help="配置文件目录")
    parser.add_argument("--output", "-o", default=None, help="输出目录")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    parser.add_argument("--skip-validation", action="store_true", help="跳过 URL 验证")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="跳过抓取步骤，使用缓存数据（无缓存则报错）")
    parser.add_argument("--health-file", default=None,
                        help="实测可播快照 {url: bool}（check_streams.py --health-out 的产物）；"
                             "不传则读 config/stream_health.json（若存在）")
    parser.add_argument("--fetch-timeout", type=int, default=90,
                        help="抓取超时秒数（默认90秒）")
    parser.add_argument("--validate-concurrency", type=_positive_int,
                        default=DEFAULT_VALIDATE_CONCURRENCY,
                        help=f"验证阶段并发数（默认 {DEFAULT_VALIDATE_CONCURRENCY}）。"
                             "实测：40 与 20 并发的可用条数持平但快约 1.6x；"
                             "提到 60 会因源站限流掉条（300 条样本 236~296 波动），"
                             "所以别盲目往上加")
    parser.add_argument("--validate-timeout", type=_positive_int,
                        default=DEFAULT_VALIDATE_TIMEOUT,
                        help=f"验证阶段单条超时秒数（默认 {DEFAULT_VALIDATE_TIMEOUT}）。"
                             "实测调到 8/5 会把慢但仍可用的链路判死（可用条数 296→293/291），"
                             "所以不建议调低")
    return parser


def main():
    args = build_parser().parse_args()

    result = asyncio.run(run(
        config_dir=args.config,
        output_dir=args.output,
        use_cache=not args.no_cache,
        skip_validation=args.skip_validation,
        skip_fetch=args.skip_fetch,
        fetch_timeout=args.fetch_timeout,
        health_file=args.health_file,
        validate_concurrency=args.validate_concurrency,
        validate_timeout=args.validate_timeout,
    ))

    if result is None:
        print("\n❌ 运行失败", file=sys.stderr)
        raise SystemExit(1)

    timings = result.get("timings", {})
    print("\n📊 总计:")
    print(f"   抓取去重后: {result['total']} 个频道")
    print(f"   同名合并后: {result['merged']} 个频道（合并掉 {result['total'] - result['merged']} 个重名）")
    print(f"   分组数: {result['groups']}")
    print(f"   港澳台列表: {result['hk_channels']} 条")
    print(f"   全球列表: {result['all_channels']} 条")
    print(f"   分阶段耗时: 抓取 {_fmt_duration(timings.get('fetch', 0.0))} / "
          f"验证 {_fmt_duration(timings.get('validate', 0.0))} / "
          f"分组 {_fmt_duration(timings.get('group', 0.0))} / "
          f"生成 {_fmt_duration(timings.get('generate', 0.0))}")
    print(f"⏱ 总耗时: {_fmt_duration(timings.get('total', 0.0))}")


if __name__ == "__main__":
    main()
