"""`src/main.py` 流水线编排层的离线测试（本 lane 独占）。

覆盖点（全部**不发任何网络请求**）：
  1. CLI 参数：默认值、解析、`_positive_int` 拒绝 0/负数、--help 里出现新选项
  2. `run()` 把并发/超时**透传给 Validator**（stub 记录 kwargs），且不碰 validator.py
  3. 各阶段耗时输出格式：四个阶段各一行 + 最终总耗时
  4. `skip-fetch` 无缓存时早退返回 None（且不触发抓取）
  5. `main()` 把 CLI 参数接到 `run()`，返回 None 时退出码 1

约束：
- 不依赖 conftest 的任何 fixture（本文件自带 helper），因为 conftest 属隐式共享面。
- 不写真文件到仓库：output 一律用 tmp_path；Cache / stream_health 用桩替换，
  避免读到 src/.cache 与 config/stream_health.json 造成结果随仓库状态漂移。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import main as main_mod  # noqa: E402
from src.fetcher import Channel  # noqa: E402

# 阶段耗时行的固定格式：`  ⏱ 阶段耗时[抓取]: 12.3s`
STAGE_COST_RE = re.compile(r"^  ⏱ 阶段耗时\[(?P<stage>[^\]]+)\]: (?P<sec>\d+\.\d)s$")
TOTAL_COST_RE = re.compile(r"^⏱ 总耗时: (?P<sec>\d+\.\d)s$")


# ---------------------------------------------------------------------------
# helpers（不依赖 conftest）
# ---------------------------------------------------------------------------
class _FakeCache:
    """内存缓存桩：`payload=None` 表示「没有缓存」。"""

    def __init__(self, payload=None, **_kwargs):
        self.payload = payload
        self.sets: list[tuple[str, object]] = []

    def get(self, _key, ttl=None):  # noqa: ARG002 — 保持与 SimpleCache 同签名
        return self.payload

    def set(self, key, value):
        self.sets.append((key, value))


def _cache_factory(payload):
    """返回一个「被调用时构造 _FakeCache」的工厂 —— run() 里是 `Cache()`。"""
    return lambda *_a, **_k: _FakeCache(payload)


class _FakeStreamHealth:
    """stream_health 桩：永远没有实测快照，避免读 config/stream_health.json。"""

    def __init__(self):
        self.calls: list[object] = []

    def load(self, path=None):
        self.calls.append(path)
        return {}


class _RecordingValidator:
    """替换 main.Validator：记录构造 kwargs，validate() 只留第一条。"""

    instances: list["_RecordingValidator"] = []

    def __init__(self, config=None, max_concurrent=20, timeout=10):
        self.config = config
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.seen = 0
        _RecordingValidator.instances.append(self)

    async def validate(self, channels):
        self.seen = len(channels)
        return list(channels[:1])


def _channel_rows():
    """缓存里的原始频道数据（4 条，覆盖香港/内地/台湾，便于真实 Grouper 分组）。"""
    return [
        {"name": "翡翠台", "url": "http://example.invalid/tvb1.m3u8",
         "logo": "", "group": ""},
        {"name": "CCTV1 综合", "url": "http://example.invalid/cctv1.m3u8",
         "logo": "", "group": ""},
        {"name": "中天新闻", "url": "http://example.invalid/ctitv.m3u8",
         "logo": "", "group": ""},
        {"name": "ViuTV", "url": "http://example.invalid/viutv.m3u8",
         "logo": "", "group": ""},
    ]


@pytest.fixture
def offline_pipeline(monkeypatch, tmp_path):
    """把网络/磁盘的隐式依赖打成桩，返回 (kwargs, stdout)。

    只替换 Cache 与 stream_health；Grouper / Generator 用**真实实现**，
    这样测的是真编排而不是四个空壳。
    """
    monkeypatch.setattr(main_mod, "Cache", _FakeCache)
    monkeypatch.setattr(main_mod, "stream_health", _FakeStreamHealth())
    _RecordingValidator.instances.clear()
    return {"output_dir": str(tmp_path / "out")}


# ---------------------------------------------------------------------------
# 1. CLI 参数
# ---------------------------------------------------------------------------
def test_cli_defaults():
    args = main_mod.build_parser().parse_args([])
    assert args.validate_concurrency == main_mod.DEFAULT_VALIDATE_CONCURRENCY == 40
    assert args.validate_timeout == main_mod.DEFAULT_VALIDATE_TIMEOUT == 10
    # 既有参数不能被这次改动挤掉默认值
    assert args.fetch_timeout == 90
    assert args.skip_validation is False
    assert args.skip_fetch is False
    assert args.no_cache is False
    assert args.config is None and args.output is None and args.health_file is None


def test_cli_overrides_validation_params():
    args = main_mod.build_parser().parse_args(
        ["--validate-concurrency", "60", "--validate-timeout", "7"]
    )
    assert (args.validate_concurrency, args.validate_timeout) == (60, 7)


@pytest.mark.parametrize("bad", ["0", "-1", "-40"])
def test_cli_rejects_non_positive_values(bad):
    """0 并发 = Semaphore(0) 永久阻塞；<=0 超时 = 立刻判死。都必须在解析期拒绝。"""
    with pytest.raises(SystemExit):
        main_mod.build_parser().parse_args(["--validate-concurrency", bad])
    with pytest.raises(SystemExit):
        main_mod.build_parser().parse_args(["--validate-timeout", bad])


def test_cli_rejects_non_integer():
    with pytest.raises(SystemExit):
        main_mod.build_parser().parse_args(["--validate-concurrency", "many"])


def test_help_lists_validation_options_with_defaults():
    text = main_mod.build_parser().format_help()
    assert "--validate-concurrency" in text
    assert "--validate-timeout" in text
    # 帮助文本要带上「为什么是 40」的实测结论，避免后人随手调回 20/调到 60
    assert f"默认 {main_mod.DEFAULT_VALIDATE_CONCURRENCY}" in text
    assert "limit" in text or "限流" in text


def test_fmt_duration_is_always_seconds():
    assert main_mod._fmt_duration(0) == "0.0s"
    assert main_mod._fmt_duration(17.94) == "17.9s"
    assert main_mod._fmt_duration(1812.4) == "1812.4s"


# ---------------------------------------------------------------------------
# 2. run() 把并发/超时透传给 Validator（不许改 validator.py 的默认值）
# ---------------------------------------------------------------------------
async def test_run_passes_concurrency_and_timeout_to_validator(
        monkeypatch, offline_pipeline):
    monkeypatch.setattr(main_mod, "Cache", _cache_factory(_channel_rows()))
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    result = await main_mod.run(validate_concurrency=40, validate_timeout=10,
                                **offline_pipeline)

    assert result is not None
    assert len(_RecordingValidator.instances) == 1
    made = _RecordingValidator.instances[0]
    assert made.max_concurrent == 40
    assert made.timeout == 10
    assert made.seen == 4  # 4 条全进去了，没有在半路被筛掉


async def test_run_takes_custom_concurrency(monkeypatch, offline_pipeline):
    monkeypatch.setattr(main_mod, "Cache", _cache_factory(_channel_rows()))
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    await main_mod.run(validate_concurrency=60, validate_timeout=5, **offline_pipeline)

    made = _RecordingValidator.instances[0]
    assert (made.max_concurrent, made.timeout) == (60, 5)


async def test_run_rejects_non_positive_params_before_doing_work(
        monkeypatch, offline_pipeline):
    monkeypatch.setattr(main_mod, "Cache", _cache_factory(_channel_rows()))
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    with pytest.raises(ValueError):
        await main_mod.run(validate_concurrency=0, **offline_pipeline)
    with pytest.raises(ValueError):
        await main_mod.run(validate_timeout=0, **offline_pipeline)
    assert _RecordingValidator.instances == []


# ---------------------------------------------------------------------------
# 3. 各阶段耗时输出 + 最终总耗时（真实 Grouper/Generator，离线）
# ---------------------------------------------------------------------------
async def test_stage_timings_printed_for_every_stage(
        monkeypatch, offline_pipeline, capsys):
    monkeypatch.setattr(main_mod, "Cache", _cache_factory(_channel_rows()))
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    result = await main_mod.run(**offline_pipeline)
    out = capsys.readouterr().out

    stage_lines = {}
    for line in out.splitlines():
        m = STAGE_COST_RE.match(line)
        if m:
            stage_lines[m.group("stage")] = float(m.group("sec"))

    assert set(stage_lines) == {"抓取", "验证", "分组", "生成"}
    assert all(v >= 0.0 for v in stage_lines.values())

    total_lines = [ln for ln in out.splitlines() if TOTAL_COST_RE.match(ln)]
    assert len(total_lines) == 1, out
    total_printed = float(TOTAL_COST_RE.match(total_lines[0]).group("sec"))

    # 返回值里的 timings 必须与打印一致，CI 之外的程序化消费者也拿得到
    timings = result["timings"]
    assert set(timings) == {"fetch", "validate", "group", "generate", "total"}
    assert timings["total"] == pytest.approx(total_printed, abs=0.06)
    # 总耗时不会小于任一阶段（单调时钟，容差 1 个打印精度）
    for stage in ("fetch", "validate", "group", "generate"):
        assert timings["total"] + 0.06 >= timings[stage]


async def test_pipeline_writes_outputs(monkeypatch, offline_pipeline, capsys):
    """真实 Grouper + Generator 跑通：产物落地、统计口径与返回值自洽。"""
    monkeypatch.setattr(main_mod, "Cache", _cache_factory(_channel_rows()))
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    result = await main_mod.run(**offline_pipeline)

    out_dir = Path(result["output"])
    assert (out_dir / "stats.json").is_file()
    assert (out_dir / "all_merged.m3u").is_file()
    assert (out_dir / "hk_merged.m3u").is_file()
    assert result["stats"] == result["stats"]  # dict
    assert sum(result["stats"].values()) == result["merged"]
    assert result["merged"] >= result["total"]  # 1 条验证通过，合并后不会凭空变少
    assert "⏱ 总耗时" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 4. 早退路径
# ---------------------------------------------------------------------------
async def test_skip_fetch_without_cache_returns_none(monkeypatch, offline_pipeline,
                                                     capsys):
    """无缓存 + --skip-fetch → 返回 None，且绝不进入验证阶段。"""
    monkeypatch.setattr(main_mod, "Cache", _cache_factory(None))
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    assert await main_mod.run(skip_fetch=True, **offline_pipeline) is None
    assert _RecordingValidator.instances == []
    captured = capsys.readouterr()
    assert "跳过抓取但无缓存" in captured.err
    # 早退时不该有阶段耗时行（没有跑完的阶段可报）
    assert "阶段耗时" not in captured.out


async def test_skip_fetch_with_cache_and_skip_validation(monkeypatch, offline_pipeline,
                                                         capsys):
    """两个 skip 组合：用缓存、不验证，直接分组生成。"""
    monkeypatch.setattr(main_mod, "Cache", _cache_factory(_channel_rows()))
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    result = await main_mod.run(skip_fetch=True, skip_validation=True,
                                **offline_pipeline)

    assert result is not None
    assert _RecordingValidator.instances == []  # 跳过验证 → Validator 根本没构造
    assert result["total"] == 4
    out = capsys.readouterr().out
    assert "跳过验证" in out
    assert "验证 " in out  # 阶段耗时行仍然打（接近 0s），日志格式不缺行
    assert STAGE_COST_RE.match(
        [ln for ln in out.splitlines() if "阶段耗时[验证]" in ln][0]
    )


async def test_skip_fetch_uses_cache_not_network(monkeypatch, offline_pipeline):
    """Fetcher 一旦被构造就是 bug：--skip-fetch 必须完全不碰它。"""

    class _BoomFetcher:
        def __init__(self, *_a, **_k):
            raise AssertionError("skip_fetch 不应构造 Fetcher")

    monkeypatch.setattr(main_mod, "Cache", _cache_factory(_channel_rows()))
    monkeypatch.setattr(main_mod, "Fetcher", _BoomFetcher)
    monkeypatch.setattr(main_mod, "Validator", _RecordingValidator)

    result = await main_mod.run(skip_fetch=True, **offline_pipeline)
    assert result is not None


# ---------------------------------------------------------------------------
# 5. main() ↔ run() 的接线
# ---------------------------------------------------------------------------
def _fake_result():
    return {
        "total": 3, "merged": 2, "groups": 1, "hk_channels": 1, "all_channels": 2,
        "output": "out", "stats": {"📺 TVB": 2},
        "timings": {"fetch": 1.0, "validate": 2.0, "group": 0.5, "generate": 0.5,
                    "total": 4.0},
    }


def test_main_wires_cli_args_into_run(monkeypatch, capsys):
    captured = {}

    def _spy_run(**kwargs):
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(main_mod, "run", _spy_run)
    # main() 里唯一一次 asyncio 调用就是 asyncio.run(run(...))；桩掉它即可离线
    monkeypatch.setattr(main_mod.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", [
        "src.main", "--validate-concurrency", "40", "--validate-timeout", "10",
        "--no-cache", "--skip-fetch", "--output", "/tmp/x",
    ])

    main_mod.main()

    assert captured["validate_concurrency"] == 40
    assert captured["validate_timeout"] == 10
    assert captured["use_cache"] is False
    assert captured["skip_fetch"] is True
    assert captured["output_dir"] == "/tmp/x"
    out = capsys.readouterr().out
    assert "分阶段耗时" in out
    assert TOTAL_COST_RE.match([ln for ln in out.splitlines() if "总耗时" in ln][0])


def test_main_exits_1_when_run_returns_none(monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "run", lambda **_kw: None)
    monkeypatch.setattr(main_mod.asyncio, "run", lambda coro: coro)
    monkeypatch.setattr(sys, "argv", ["src.main", "--skip-fetch"])

    with pytest.raises(SystemExit) as excinfo:
        main_mod.main()
    assert excinfo.value.code == 1
    assert "运行失败" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 6. 严格度不变：并发/超时可配，但判定口径一行都没动
# ---------------------------------------------------------------------------
def test_main_does_not_change_validator_judgement():
    """main.py 只允许「构造时传参」，不许自己判 URL 或绕过 Validator。"""
    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    # 不能出现「跳过验证但仍当有效」的替代路径
    assert "return_exceptions" not in src  # 那是 validator 的事，别在这儿复刻
    assert "whitelist" not in src  # 不许在白名单上做文章
    # 必须真的把两个参数传给 Validator
    assert "max_concurrent=validate_concurrency" in src
    assert "timeout=validate_timeout" in src
