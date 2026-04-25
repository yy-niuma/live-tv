"""IPTV 主入口"""
import argparse
import asyncio
import json
import os
from pathlib import Path

from src.config import Config
from src.fetcher import Fetcher
from src.validator import Validator
from src.grouper import Grouper
from src.generator import Generator
from src.lib.cache import SimpleCache as Cache


async def run(config_dir: str = None, output_dir: str = None, use_cache: bool = True,
              skip_validation: bool = False, skip_fetch: bool = False, fetch_timeout: int = 90):
    """运行完整流程

    Args:
        skip_fetch: 跳过抓取步骤，使用缓存数据（无缓存则报错）
        fetch_timeout: 抓取超时秒数（默认90秒）
    """
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
    if skip_fetch:
        channels_data = cache.get(cache_key)
        if channels_data:
            from src.fetcher import Channel
            channels = [Channel(**d) for d in channels_data]
            print(f"  ✓ 跳过抓取，使用缓存: {len(channels)} 个频道")
        else:
            print("  ❌ 跳过抓取但无缓存数据，请先正常运行一次抓取")
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
                print(f"  ❌ 抓取超时（{fetch_timeout}s），请增加超时或使用 --skip-fetch 跳过")
                return None
            cache.set(cache_key, [ch.__dict__ for ch in channels])
    else:
        sources = config.sources
        print(f"  开始抓取 {len(sources)} 个数据源（超时 {fetch_timeout}s）...")
        fetcher = Fetcher(config)
        try:
            channels = await asyncio.wait_for(fetcher.fetch_all(), timeout=fetch_timeout)
        except asyncio.TimeoutError:
            print(f"  ❌ 抓取超时（{fetch_timeout}s），请增加超时或使用 --skip-fetch 跳过")
            return None

    print(f"  ✓ 抓取完成: 共 {len(channels)} 个频道")

    # 2. 验证
    print("\n[Step 2/4] 验证 URL...")
    if skip_validation:
        print("  ⚠ 跳过验证（--skip-validation）")
        valid_channels = channels
    else:
        validator = Validator(config)
        valid_channels = await validator.validate(channels)
        print(f"  ✓ 验证完成: {len(valid_channels)}/{len(channels)} 个有效")

    # 3. 分组
    print("\n[Step 3/4] 分组频道...")
    grouper = Grouper(config)
    grouped = grouper.group(valid_channels)

    # 统计各分组频道数
    top_groups = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    print(f"  ✓ 分组完成: 共 {len(grouped)} 个分组")
    print(f"  Top 5 分组:")
    for name, chs in top_groups:
        print(f"    - {name}: {len(chs)} 个频道")

    # 4. 生成
    print("\n[Step 4/4] 生成播放列表...")
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

    print("\n" + "=" * 60)
    print("完成！")
    print("=" * 60)

    return {
        "total": len(valid_channels),
        "groups": len(grouped),
        "hk_channels": result['hk']['channels'],
        "all_channels": result['all']['channels'],
        "output": str(output_dir),
        "stats": stats,
    }


def main():
    parser = argparse.ArgumentParser(description="IPTV 抓取、验证、分组、生成工具")
    parser.add_argument("--config", "-c", default=None, help="配置文件目录")
    parser.add_argument("--output", "-o", default=None, help="输出目录")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    parser.add_argument("--skip-validation", action="store_true", help="跳过 URL 验证")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="跳过抓取步骤，使用缓存数据（无缓存则报错）")
    parser.add_argument("--fetch-timeout", type=int, default=90,
                        help="抓取超时秒数（默认90秒）")
    args = parser.parse_args()

    result = asyncio.run(run(
        config_dir=args.config,
        output_dir=args.output,
        use_cache=not args.no_cache,
        skip_validation=args.skip_validation,
        skip_fetch=args.skip_fetch,
        fetch_timeout=args.fetch_timeout,
    ))

    if result is None:
        print("\n❌ 运行失败")
        return

    print(f"\n📊 总计:")
    print(f"   有效频道: {result['total']}")
    print(f"   分组数: {result['groups']}")
    print(f"   港澳台: {result['hk_channels']}")
    print(f"   全球: {result['all_channels']}")


if __name__ == "__main__":
    main()
