"""`scripts/` 目录的通用约定测试（与具体脚本行为无关）。

守三件容易悄悄烂掉的事：

1. 每个脚本都能被 `python -m py_compile` 编译（语法/编码问题挡住，别等到 cron 才炸）。
2. 每个脚本 `--help` 都能干净退出（0），且在 stderr 上不吐 traceback ——
   一条 `import` 写坏或 argparse 拼错，会在「用 --help 看一眼」时立刻暴露。
3. 每个脚本都有模块 docstring：`scripts/` 是运维入口，没有 docstring 的脚本
   半年后没人知道该不该跑、退出码 1 是故障还是结论。

外加一条防回归：`config/sources_history.jsonl` 必须留在 `.gitignore` 里
（`check_sources.py` 默认会往那儿追加，误入库会把 CI 的 diff 变成噪音）。
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
GITIGNORE = ROOT / ".gitignore"

# 目录里另有 categorize_dataset/ 之类的数据目录，只取顶层 .py
SCRIPT_FILES = sorted(p for p in SCRIPTS_DIR.glob("*.py") if p.is_file())

# 期望至少覆盖的真实脚本数：少于这个数说明 glob 写错了，
# 「0 个脚本全过」是这类约定测试最典型的假绿。
MIN_EXPECTED_SCRIPTS = 4


def _run(args: list[str], *, cwd: Path, env_extra: dict | None = None):
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )


def test_scripts_dir_has_expected_scripts():
    names = {p.name for p in SCRIPT_FILES}

    assert len(SCRIPT_FILES) >= MIN_EXPECTED_SCRIPTS, names
    assert {"check_sources.py", "eval_categorize.py"} <= names


@pytest.mark.parametrize("path", SCRIPT_FILES, ids=lambda p: p.name)
def test_script_compiles_with_py_compile(path, tmp_path):
    # PYTHONPYCACHEPREFIX 把 .pyc 赶出 scripts/，否则测试本身会弄脏工作区
    proc = _run(
        [sys.executable, "-m", "py_compile", path.name],
        cwd=SCRIPTS_DIR,
        env_extra={"PYTHONPYCACHEPREFIX": str(tmp_path / "pycache")},
    )

    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr


@pytest.mark.parametrize("path", SCRIPT_FILES, ids=lambda p: p.name)
def test_script_help_exits_zero(path, tmp_path):
    proc = _run(
        [sys.executable, path.name, "--help"],
        cwd=SCRIPTS_DIR,
        env_extra={"PYTHONPYCACHEPREFIX": str(tmp_path / "pycache")},
    )

    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    # argparse 的 --help 输出 "usage:" 到 stdout；没有它说明没走 argparse（或提前崩了）
    assert "usage:" in proc.stdout.lower()


@pytest.mark.parametrize("path", SCRIPT_FILES, ids=lambda p: p.name)
def test_script_has_module_docstring(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    doc = ast.get_docstring(tree)

    assert doc, f"{path.name} 缺模块 docstring"
    first_line = doc.strip().splitlines()[0].strip()
    assert first_line, f"{path.name} 的 docstring 首行为空"


# ── .gitignore 契约 ─────────────────────────────────────────────────────
def test_gitignore_mentions_sources_history():
    lines = [ln.strip() for ln in GITIGNORE.read_text(encoding="utf-8").splitlines()]

    assert "config/sources_history.jsonl" in lines


def test_gitignore_keeps_pre_existing_stream_health_entry():
    """只许追加：既有的 stream_health.json 那行不能被顺手删掉。"""
    lines = [ln.strip() for ln in GITIGNORE.read_text(encoding="utf-8").splitlines()]

    assert "config/stream_health.json" in lines


@pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="需要 git 与 .git 目录才能验证真实忽略效果",
)
def test_sources_history_is_actually_ignored_by_git():
    proc = _run(
        ["git", "check-ignore", "-v", "config/sources_history.jsonl"], cwd=ROOT
    )

    assert proc.returncode == 0, proc.stderr
    assert "sources_history.jsonl" in proc.stdout
