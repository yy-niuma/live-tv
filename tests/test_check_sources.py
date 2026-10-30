"""`scripts/check_sources.py` 的离线单元测试。

两条硬约束（与控制器约定一致）：

1. **不发网络**：所有 `Fetcher._get_text` 调用都在本文件里被替换成假实现，
   任何一条测试真的出去发包都算这条测试写错了。
2. **fixture 全部内联**：不依赖 `tests/conftest.py`（那个文件归别的 lane）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_sources.py"


def _load_script():
    """按路径加载脚本模块（`scripts/` 不是包，不能 `import scripts.x`）。

    加载时关掉字节码缓存：否则 exec_module 会往 `scripts/__pycache__/` 写 .pyc，
    跑一次测试就把工作区弄脏（虽被 .gitignore 挡住，仍不该由测试产生）。
    """
    spec = importlib.util.spec_from_file_location("check_sources_ut", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = previous
    return mod


@pytest.fixture(scope="module")
def cs():
    return _load_script()


# ── 内联数据 ────────────────────────────────────────────────────────────
M3U_OK = """#EXTM3U
#EXTINF:-1 tvg-name="CCTV1" group-title="央视频道",CCTV1 综合
http://example.invalid/1.m3u8
#EXTINF:-1 group-title="卫视频道",湖南卫视
http://example.invalid/2.m3u8
"""

MD_OK = """| #   | Channel    | Link                                  |
|:---:|:----------:|:-------------------------------------:|
| 31  | RTHK TV 31 | [>](https://example.invalid/hk.m3u8) |
"""

YAML_OK = """streams:
  - name: CCTV1
    url: https://example.invalid/c1.m3u8
"""


def write_sources(cfg_dir: Path, sources: list[dict]) -> Path:
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "sources.yaml"
    path.write_text(
        yaml.safe_dump({"sources": sources}, allow_unicode=True), encoding="utf-8"
    )
    return path


def fake_get_text(table: dict[str, str], error_urls=frozenset(), calls=None):
    """把 `Fetcher._get_text` 换成查表：命中返回文本，`error_urls` 抛超时。"""

    async def _get_text(self, url, headers=None):
        if calls is not None:
            calls.append({"url": url, "headers": headers})
        if url in error_urls:
            raise TimeoutError(f"fake timeout: {url}")
        if url not in table:
            raise ConnectionError(f"no fake content registered for {url}")
        return table[url]

    return _get_text


def healthy_sources() -> list[dict]:
    return [
        {"name": "m3u源", "url": "https://a.invalid/a.m3u", "priority": 1},
        {"name": "md源", "url": "https://b.invalid/b.md", "priority": 2},
        {"name": "yaml源", "url": "https://c.invalid/c.yaml", "priority": 3},
    ]


HEALTHY_TABLE = {
    "https://a.invalid/a.m3u": M3U_OK,
    "https://b.invalid/b.md": MD_OK,
    "https://c.invalid/c.yaml": YAML_OK,
}


# ── row_status ─────────────────────────────────────────────────────────
def test_row_status_ok(cs):
    assert cs.row_status({"channels": 12, "error": ""}) == "ok"


def test_row_status_dead(cs):
    assert cs.row_status({"channels": 0, "error": ""}) == "dead"


def test_row_status_error_wins_over_count(cs):
    # 有异常就是 error，哪怕条数非 0（部分解析成功 + 报错，仍是可疑状态）
    assert cs.row_status({"channels": 5, "error": "RuntimeError: boom"}) == "error"


# ── probe_source ───────────────────────────────────────────────────────
async def test_probe_source_counts_channels_and_format(cs, monkeypatch):
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, healthy_sources()[0])

    assert row["name"] == "m3u源"
    assert row["channels"] == 2
    assert row["format"] == "m3u"
    assert row["error"] == ""
    assert row["priority"] == 1


async def test_probe_source_detects_markdown(cs, monkeypatch):
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, healthy_sources()[1])

    assert row["format"] == "markdown"
    assert row["channels"] == 1


async def test_probe_source_empty_text_is_zero_not_error(cs, monkeypatch):
    """静默归零的形态：HTTP 200 + 0 条 + 无异常。必须判 dead，不能算 error。"""
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text({"https://a.invalid/a.m3u": ""})
    )
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, healthy_sources()[0])

    assert row["channels"] == 0
    assert row["format"] == "empty"
    assert row["error"] == ""
    assert cs.row_status(row) == "dead"


async def test_probe_source_swallows_exception_into_error_field(cs, monkeypatch):
    url = "https://a.invalid/a.m3u"
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text({}, error_urls={url})
    )
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, healthy_sources()[0])

    assert row["channels"] == 0
    assert row["format"] == "-"
    assert row["error"].startswith("TimeoutError:")
    assert cs.row_status(row) == "error"


async def test_probe_source_forwards_headers(cs, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE, calls=calls)
    )
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)
    src = {"name": "带头源", "url": "https://a.invalid/a.m3u",
           "headers": {"User-Agent": "ua"}}

    await cs.probe_source(fetcher, src)

    assert calls[0]["headers"] == {"User-Agent": "ua"}


async def test_probe_source_missing_url_reports_error(cs, monkeypatch):
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))
    fetcher = cs.Fetcher(max_concurrent=1, max_retries=1)

    row = await cs.probe_source(fetcher, {"name": "空源"})

    assert row["url"] == ""
    assert row["channels"] == 0
    assert row["error"].startswith("ConnectionError:")


async def test_probe_all_one_row_per_source(cs, monkeypatch):
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))

    rows = await cs.probe_all(healthy_sources(), concurrency=2)

    assert [r["name"] for r in rows] == ["m3u源", "md源", "yaml源"]
    assert sum(r["channels"] for r in rows) == 4


async def test_probe_all_empty_source_list(cs):
    assert await cs.probe_all([], concurrency=1) == []


# ── print_report ───────────────────────────────────────────────────────
def test_print_report_totals_and_dead_list(cs, capsys):
    rows = [
        {"name": "好源", "url": "u1", "priority": 1, "channels": 3,
         "format": "m3u", "error": ""},
        {"name": "死源", "url": "u2", "priority": 2, "channels": 0,
         "format": "empty", "error": ""},
    ]

    total, dead = cs.print_report(rows)

    out = capsys.readouterr().out
    assert total == 3
    assert dead == ["死源"]
    assert "合计 3 条 / 2 个启用源" in out
    assert "零产出 1 个" in out


def test_print_report_all_healthy(cs, capsys):
    rows = [{"name": "好源", "url": "u1", "priority": 1, "channels": 9,
             "format": "m3u", "error": ""}]

    total, dead = cs.print_report(rows)

    assert (total, dead) == (9, [])
    assert "✅ 每个源都抓到了内容" in capsys.readouterr().out


# ── load_sources / 配置错误路径 ─────────────────────────────────────────
def test_load_sources_reads_enabled_only(cs, tmp_path):
    write_sources(
        tmp_path,
        [
            {"name": "开", "url": "https://a.invalid/a.m3u", "enabled": True},
            {"name": "关", "url": "https://b.invalid/b.m3u", "enabled": False},
        ],
    )

    sources = cs.load_sources(tmp_path)

    assert [s["name"] for s in sources] == ["开"]


def test_load_sources_missing_file_returns_empty(cs, tmp_path):
    assert cs.load_sources(tmp_path / "nope") == []


def test_load_sources_broken_yaml_raises_source_config_error(cs, tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "sources.yaml").write_text("sources: [unclosed\n", encoding="utf-8")

    with pytest.raises(cs.SourceConfigError) as ei:
        cs.load_sources(tmp_path)

    # yaml 把语法错误具体化成 ParserError（YAMLError 的子类），原名进消息便于定位
    assert "ParserError" in str(ei.value)


def test_load_sources_non_mapping_yaml_raises_source_config_error(cs, tmp_path):
    (tmp_path / "sources.yaml").write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(cs.SourceConfigError) as ei:
        cs.load_sources(tmp_path)

    assert "AttributeError" in str(ei.value)


# ── audit 退出码 ───────────────────────────────────────────────────────
async def test_audit_all_healthy_exit_0(cs, monkeypatch, tmp_path, capsys):
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, healthy_sources())
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))

    rc = await cs.audit(None, 2, config_dir=cfg_dir)

    assert rc == 0
    assert "✅" in capsys.readouterr().out


async def test_audit_dead_source_exit_1(cs, monkeypatch, tmp_path, capsys):
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, [{"name": "空源", "url": "https://a.invalid/a.m3u"}])
    monkeypatch.setattr(
        cs.Fetcher, "_get_text", fake_get_text({"https://a.invalid/a.m3u": ""})
    )

    rc = await cs.audit(None, 1, config_dir=cfg_dir)

    assert rc == 1
    assert "零产出 1 个" in capsys.readouterr().out


async def test_audit_error_source_also_exit_1(cs, monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, [{"name": "崩源", "url": "https://a.invalid/a.m3u"}])
    monkeypatch.setattr(
        cs.Fetcher,
        "_get_text",
        fake_get_text({}, error_urls={"https://a.invalid/a.m3u"}),
    )

    assert await cs.audit(None, 1, config_dir=cfg_dir) == 1


async def test_audit_missing_config_exit_2(cs, tmp_path, capsys):
    rc = await cs.audit(None, 1, config_dir=tmp_path / "missing")

    assert rc == 2
    err = capsys.readouterr().err
    assert "读不到数据源配置" in err
    assert "文件不存在" in err


async def test_audit_empty_sources_exit_2(cs, tmp_path, capsys):
    """文件在但一个启用的源都没有，也是「读不到配置」，不能当成「全部健康」。"""
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, [{"name": "关", "url": "u", "enabled": False}])

    assert await cs.audit(None, 1, config_dir=cfg_dir) == 2
    assert "读不到数据源配置" in capsys.readouterr().err


async def test_audit_broken_yaml_exit_2_without_traceback(cs, tmp_path, capsys):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "sources.yaml").write_text("sources: [oops\n", encoding="utf-8")

    rc = await cs.audit(None, 1, config_dir=cfg_dir)

    assert rc == 2
    err = capsys.readouterr().err
    assert "读不到数据源配置" in err
    assert "ParserError" in err


async def test_audit_writes_json(cs, monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, healthy_sources())
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))
    out = tmp_path / "sources.json"

    await cs.audit(out, 1, config_dir=cfg_dir)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["total"] == 4
    assert payload["dead"] == []
    assert len(payload["sources"]) == 3
    assert set(payload["sources"][0]) == {
        "name", "url", "priority", "channels", "format", "error"
    }


# ── 历史记录 ───────────────────────────────────────────────────────────
ROWS_FIXTURE = [
    {"name": "好源", "channels": 7, "error": ""},
    {"name": "死源", "channels": 0, "error": ""},
    {"name": "崩源", "channels": 0, "error": "TimeoutError: boom"},
]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def test_append_history_writes_one_line_per_source(cs, tmp_path):
    path = tmp_path / "h.jsonl"

    kept = cs.append_history(path, ROWS_FIXTURE, ts="2026-10-30T12:00:00+08:00")

    lines = read_jsonl(path)
    assert kept == 3
    assert len(lines) == 3
    assert lines[0] == {
        "ts": "2026-10-30T12:00:00+08:00",
        "name": "好源",
        "channels": 7,
        "status": "ok",
    }
    assert [ln["status"] for ln in lines] == ["ok", "dead", "error"]


def test_append_history_appends_without_clobbering(cs, tmp_path):
    path = tmp_path / "h.jsonl"
    cs.append_history(path, ROWS_FIXTURE[:1], ts="2026-10-30T12:00:00+08:00")
    cs.append_history(path, ROWS_FIXTURE[:1], ts="2026-10-31T12:00:00+08:00")

    lines = read_jsonl(path)
    assert [ln["ts"] for ln in lines] == [
        "2026-10-30T12:00:00+08:00",
        "2026-10-31T12:00:00+08:00",
    ]


def test_append_history_trims_to_most_recent_limit(cs, tmp_path):
    """防膨胀：只保留最近 N 行，从头部丢。"""
    path = tmp_path / "h.jsonl"
    for i in range(5):
        cs.append_history(path, [{"name": f"旧{i}", "channels": 1, "error": ""}],
                          ts="2026-10-01T00:00:00+08:00", limit=0)
    assert len(read_jsonl(path)) == 5

    kept = cs.append_history(
        path,
        [{"name": "新1", "channels": 1, "error": ""},
         {"name": "新2", "channels": 1, "error": ""}],
        ts="2026-10-30T00:00:00+08:00",
        limit=4,
    )

    lines = read_jsonl(path)
    assert kept == 4
    assert [ln["name"] for ln in lines] == ["旧3", "旧4", "新1", "新2"]


def test_append_history_limit_zero_means_unbounded(cs, tmp_path):
    path = tmp_path / "h.jsonl"
    for i in range(3):
        cs.append_history(path, [{"name": f"源{i}", "channels": 1, "error": ""}],
                          limit=0)

    assert len(read_jsonl(path)) == 3


def test_append_history_drops_corrupt_lines(cs, tmp_path):
    path = tmp_path / "h.jsonl"
    path.write_text('not json\n{"ts": "x", "name": "旧", "channels": 1}\n[1, 2]\n',
                    encoding="utf-8")

    kept = cs.append_history(path, [{"name": "新", "channels": 2, "error": ""}],
                             ts="2026-10-30T00:00:00+08:00", limit=0)

    names = [ln["name"] for ln in read_jsonl(path)]
    assert kept == 2
    assert names == ["旧", "新"]


def test_append_history_creates_parent_dirs(cs, tmp_path):
    path = tmp_path / "deep" / "nested" / "h.jsonl"

    cs.append_history(path, ROWS_FIXTURE[:1])

    assert path.exists()


def test_append_history_leaves_no_tmp_file(cs, tmp_path):
    path = tmp_path / "h.jsonl"

    cs.append_history(path, ROWS_FIXTURE[:1])

    assert not path.with_name(path.name + ".tmp").exists()


def test_append_history_survives_empty_rows(cs, tmp_path):
    path = tmp_path / "h.jsonl"

    assert cs.append_history(path, []) == 0
    assert read_jsonl(path) == []


def test_default_history_path_is_repo_config(cs):
    assert cs.default_history_path() == ROOT / "config" / "sources_history.jsonl"


def test_resolve_history_path_relative_uses_cwd(cs, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert cs.resolve_history_path(Path("h.jsonl")) == tmp_path / "h.jsonl"


def test_resolve_history_path_absolute_passthrough(cs, tmp_path):
    target = tmp_path / "h.jsonl"

    assert cs.resolve_history_path(target) == target


def test_resolve_history_path_default(cs):
    assert cs.resolve_history_path(None) == ROOT / "config" / "sources_history.jsonl"


async def test_audit_writes_history_on_each_run(cs, monkeypatch, tmp_path):
    """核心验收：跑两次 → 每个源各两行，且第二次在第一次之后追加。"""
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, healthy_sources()[:2])
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))
    history = tmp_path / "sources_history.jsonl"

    await cs.audit(None, 1, config_dir=cfg_dir, history_path=history)
    await cs.audit(None, 1, config_dir=cfg_dir, history_path=history)

    lines = read_jsonl(history)
    assert len(lines) == 4
    assert [ln["name"] for ln in lines] == ["m3u源", "md源", "m3u源", "md源"]
    assert all(ln["status"] == "ok" for ln in lines)
    assert all(ln["channels"] > 0 for ln in lines)


async def test_audit_history_honours_limit(cs, monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, healthy_sources()[:1])
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))
    history = tmp_path / "h.jsonl"

    for _ in range(4):
        await cs.audit(None, 1, config_dir=cfg_dir, history_path=history,
                       history_limit=2)

    assert len(read_jsonl(history)) == 2


async def test_audit_history_failure_does_not_change_exit_code(
    cs, monkeypatch, tmp_path, capsys
):
    """历史是旁路：写不进去只能 WARNING，不能让健康检查变成假红/假绿。"""
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, healthy_sources()[:1])
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))
    bogus = tmp_path / "history_dir"
    bogus.mkdir()

    rc = await cs.audit(None, 1, config_dir=cfg_dir, history_path=bogus)

    assert rc == 0
    assert "历史写入失败" in capsys.readouterr().err


async def test_audit_without_history_path_writes_nothing(cs, monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config"
    write_sources(cfg_dir, healthy_sources()[:1])
    monkeypatch.setattr(cs.Fetcher, "_get_text", fake_get_text(HEALTHY_TABLE))

    await cs.audit(None, 1, config_dir=cfg_dir, history_path=None)

    assert list(tmp_path.glob("*.jsonl")) == []


# ── main() 参数接线 ─────────────────────────────────────────────────────
def _recorder(seen: dict):
    async def fake_audit(json_path=None, concurrency=6, **kwargs):
        seen["json_path"] = json_path
        seen["concurrency"] = concurrency
        seen.update(kwargs)
        return 0

    return fake_audit


def test_main_wires_default_history_path(cs, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(cs, "audit", _recorder(seen))

    assert cs.main([]) == 0
    assert seen["history_path"] == ROOT / "config" / "sources_history.jsonl"
    assert seen["history_limit"] == cs.DEFAULT_HISTORY_LIMIT


def test_main_no_history_flag(cs, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(cs, "audit", _recorder(seen))

    assert cs.main(["--no-history"]) == 0
    assert seen["history_path"] is None


def test_main_explicit_history_path(cs, monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(cs, "audit", _recorder(seen))
    target = tmp_path / "custom.jsonl"

    assert cs.main(["--history", str(target), "--history-limit", "7"]) == 0
    assert seen["history_path"] == target
    assert seen["history_limit"] == 7


def test_main_relative_history_path_uses_cwd(cs, monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(cs, "audit", _recorder(seen))
    monkeypatch.chdir(tmp_path)

    cs.main(["--history", "rel.jsonl"])

    assert seen["history_path"] == tmp_path / "rel.jsonl"


def test_main_passes_config_dir(cs, monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(cs, "audit", _recorder(seen))

    cs.main(["--config-dir", str(tmp_path), "--no-history"])

    assert seen["config_dir"] == tmp_path


def test_main_passes_jobs_and_json(cs, monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(cs, "audit", _recorder(seen))
    out = tmp_path / "s.json"

    cs.main(["--json", str(out), "--jobs", "3", "--no-history"])

    assert seen["json_path"] == out
    assert seen["concurrency"] == 3


def test_main_help_exits_zero(cs):
    with pytest.raises(SystemExit) as ei:
        cs.main(["--help"])

    assert ei.value.code == 0


def test_main_rejects_unknown_flag(cs):
    with pytest.raises(SystemExit) as ei:
        cs.main(["--nope"])

    assert ei.value.code == 2
