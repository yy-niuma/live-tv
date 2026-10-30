"""`scripts/eval_categorize.py` 的离线单元测试。

- 数据集用仓库自带的 `scripts/categorize_dataset/`（本地文件）或 `tmp_path` 里现造的 tsv。
- `categorize()` 在需要确定性结果的用例里被替换成查表假实现，
  这样「评测器本身算得对不对」与「分类器当前准不准」两件事被分开测 ——
  否则分类器一改动，评测器的测试就跟着红，测什么就说不清了。
- fixture 全部内联，不依赖 `tests/conftest.py`。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "eval_categorize.py"


def _load_script():
    """按路径加载脚本模块；关掉字节码缓存，避免测试往 scripts/__pycache__ 写文件。"""
    spec = importlib.util.spec_from_file_location("eval_categorize_ut", SCRIPT)
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
def ev():
    return _load_script()


def fake_categorize(mapping: dict[str, str], seen: list | None = None):
    def _categorize(name, group="", logo=""):
        if seen is not None:
            seen.append((name, group, logo))
        return mapping.get(name, "❓ 未知")

    return _categorize


def make_tsv(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def make_dataset(base: Path, bugs: str = "", good: str = "") -> Path:
    make_tsv(base / "known_bugs.tsv", "# name\t期望分类\t原因\n" + bugs)
    make_tsv(base / "known_good.tsv", "# name\t期望分类\t备注\n" + good)
    return base


# ── load_tsv ───────────────────────────────────────────────────────────
def test_load_tsv_parses_two_columns(ev, tmp_path):
    path = make_tsv(
        tmp_path / "d.tsv",
        "# name\t期望\n"
        "\n"
        "CCTV5 体育\t📺 央视频道\n"
        " 广东卫视 \t 📺 广东 \n",
    )

    assert ev.load_tsv(path) == [
        ("CCTV5 体育", "📺 央视频道"),
        ("广东卫视", "📺 广东"),
    ]


def test_load_tsv_skips_short_and_empty_cell_lines(ev, tmp_path):
    path = make_tsv(
        tmp_path / "d.tsv",
        "只有一列\n"
        "\t只有期望\n"
        "只有名字\t\n"
        "正常\t🌐 国际\n",
    )

    assert ev.load_tsv(path) == [("正常", "🌐 国际")]


def test_load_tsv_only_comment_header_returns_empty(ev, tmp_path):
    path = make_tsv(tmp_path / "d.tsv", "# name\t期望\n")

    assert ev.load_tsv(path) == []


def test_load_tsv_empty_file_returns_empty(ev, tmp_path):
    assert ev.load_tsv(make_tsv(tmp_path / "d.tsv", "")) == []


def test_load_tsv_missing_file_raises(ev, tmp_path):
    """缺文件必须抛，不能安静返回 []：否则「数据集丢了」会变成「0 个用例全过」。"""
    with pytest.raises(FileNotFoundError):
        ev.load_tsv(tmp_path / "nope.tsv")


def test_load_tsv_repo_dataset_is_readable(ev):
    bugs = ev.load_tsv(ev.DATA / "known_bugs.tsv")
    good = ev.load_tsv(ev.DATA / "known_good.tsv")

    assert len(bugs) >= 20
    assert len(good) >= 20
    assert all(name and expected for name, expected in bugs + good)


def test_dataset_files_constant_matches_shipped_dataset(ev):
    for fname in ev.DATASET_FILES:
        assert (ev.DATA / fname).is_file(), fname
    assert (ev.DATA / "current_snapshot.tsv").is_file()


# ── eval_pairs ─────────────────────────────────────────────────────────
def test_eval_pairs_all_pass(ev, monkeypatch):
    monkeypatch.setattr(
        ev, "categorize", fake_categorize({"CCTV5 体育": "📺 央视频道"})
    )

    passed, total, failures = ev.eval_pairs([("CCTV5 体育", "📺 央视频道")])

    assert (passed, total, failures) == (1, 1, [])


def test_eval_pairs_reports_mismatch(ev, monkeypatch):
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "🌐 国际"}))

    passed, total, failures = ev.eval_pairs([("A", "📺 卫视频道")])

    assert passed == 0
    assert total == 1
    assert failures == [("A", "📺 卫视频道", "🌐 国际", "")]


def test_eval_pairs_empty_input(ev):
    assert ev.eval_pairs([]) == (0, 0, [])


def test_eval_pairs_counts_mixed(ev, monkeypatch):
    monkeypatch.setattr(
        ev, "categorize", fake_categorize({"A": "1", "B": "9", "C": "3"})
    )

    passed, total, failures = ev.eval_pairs([("A", "1"), ("B", "2"), ("C", "3")])

    assert (passed, total) == (2, 3)
    assert [f[0] for f in failures] == ["B"]


def test_eval_pairs_calls_categorize_with_blank_group(ev, monkeypatch):
    seen: list = []
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "1"}, seen=seen))

    ev.eval_pairs([("A", "1")])

    assert seen == [("A", "", "")]
    assert len(seen[0]) == 3


# ── read_snapshot / snapshot_diff ──────────────────────────────────────
def test_read_snapshot_parses_group_name_pairs(ev, tmp_path):
    path = make_tsv(
        tmp_path / "s.tsv",
        "📺 央视频道\tCCTV1\n\n🇹🇼 台湾\t中视\n",
    )

    assert ev.read_snapshot(path) == {"CCTV1": "📺 央视频道", "中视": "🇹🇼 台湾"}


def test_read_snapshot_skips_malformed_lines(ev, tmp_path):
    path = make_tsv(
        tmp_path / "s.tsv",
        "没有制表符的坏行\n"
        "📺 央视频道\t\n"
        "📺 央视频道\tCCTV1\n",
    )

    assert ev.read_snapshot(path) == {"CCTV1": "📺 央视频道"}


def test_read_snapshot_keeps_group_with_tabs_in_name(ev, tmp_path):
    path = make_tsv(tmp_path / "s.tsv", "📺 央视频道\t奇怪\t名字\n")

    assert ev.read_snapshot(path) == {"奇怪\t名字": "📺 央视频道"}


def test_snapshot_diff_identical(ev, tmp_path):
    a = make_tsv(tmp_path / "a.tsv", "📺 央视频道\tCCTV1\n🌐 国际\tBBC\n")
    b = make_tsv(tmp_path / "b.tsv", "📺 央视频道\tCCTV1\n🌐 国际\tBBC\n")

    d = ev.snapshot_diff(a, b)

    assert d["common"] == 2
    assert d["moved"] == {}
    assert d["added"] == []
    assert d["removed"] == []
    assert not d["by_pair"]


def test_snapshot_diff_detects_move_add_remove(ev, tmp_path):
    a = make_tsv(tmp_path / "a.tsv", "🌐 国际\tBBC\n🌐 国际\tCNN\n📺 旧组\t老频道\n")
    b = make_tsv(tmp_path / "b.tsv", "📺 卫视频道\tBBC\n🌐 国际\tCNN\n📺 新组\t新频道\n")

    d = ev.snapshot_diff(a, b)

    assert d["common"] == 2
    assert d["moved"] == {"BBC": ("🌐 国际", "📺 卫视频道")}
    assert d["added"] == ["新频道"]
    assert d["removed"] == ["老频道"]
    assert d["by_pair"] == {("🌐 国际", "📺 卫视频道"): 1}


def test_snapshot_diff_groups_moves_by_pair(ev, tmp_path):
    a = make_tsv(tmp_path / "a.tsv", "🌐 国际\tA\n🌐 国际\tB\n")
    b = make_tsv(tmp_path / "b.tsv", "📺 TVB\tA\n📺 TVB\tB\n")

    d = ev.snapshot_diff(a, b)

    assert d["by_pair"][("🌐 国际", "📺 TVB")] == 2


def test_snapshot_diff_missing_file_raises(ev, tmp_path):
    a = make_tsv(tmp_path / "a.tsv", "📺 央视频道\tCCTV1\n")

    with pytest.raises(FileNotFoundError):
        ev.snapshot_diff(a, tmp_path / "nope.tsv")


# ── report ─────────────────────────────────────────────────────────────
def test_report_all_pass(ev, monkeypatch, capsys):
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "1"}))

    ok, summary = ev.report([("A", "1")], [])

    out = capsys.readouterr().out
    assert ok is True
    assert summary == "1/1"
    assert "known_bugs  (误判修复集): 1/1 通过" in out
    assert "合计: 1/1" in out


def test_report_prints_fail_and_regression(ev, monkeypatch, capsys):
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "错", "B": "错"}))

    ok, summary = ev.report([("A", "对")], [("B", "对")])

    out = capsys.readouterr().out
    assert ok is False
    assert summary == "0/2"
    assert "FAIL 'A'" in out
    assert "REGRESSION 'B'" in out


# ── main 退出码 ─────────────────────────────────────────────────────────
def test_main_repo_dataset_returns_0_or_1(ev, capsys):
    rc = ev.main([])

    out = capsys.readouterr().out
    assert rc in (0, 1)  # 现状是 1（known_bugs 里仍有未修复样本），不是崩溃
    assert "known_bugs" in out
    assert "known_good" in out
    assert "合计: " in out
    assert "RESULT: " in out


def test_main_all_pass_exits_0(ev, monkeypatch, tmp_path, capsys):
    ds = make_dataset(tmp_path / "ds", bugs="A\t🌐 国际\n", good="B\t📺 央视频道\n")
    monkeypatch.setattr(
        ev, "categorize", fake_categorize({"A": "🌐 国际", "B": "📺 央视频道"})
    )

    rc = ev.main(["--dataset", str(ds)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "RESULT: PASS (2/2)" in out


def test_main_failure_exits_1(ev, monkeypatch, tmp_path, capsys):
    ds = make_dataset(tmp_path / "ds", bugs="A\t📺 纪录片\n")
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "🌐 国际"}))

    rc = ev.main(["--dataset", str(ds)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL 'A'" in out
    assert "RESULT: FAIL" in out


def test_main_missing_dataset_exits_2(ev, tmp_path, capsys):
    rc = ev.main(["--dataset", str(tmp_path / "nope")])

    assert rc == 2
    assert "读不到数据集" in capsys.readouterr().err


def test_main_partial_dataset_exits_2(ev, tmp_path, capsys):
    ds = tmp_path / "ds"
    make_tsv(ds / "known_bugs.tsv", "A\t🌐 国际\n")  # 缺 known_good.tsv

    rc = ev.main(["--dataset", str(ds)])

    assert rc == 2
    assert "读不到数据集" in capsys.readouterr().err


def test_main_empty_dataset_exits_2_not_0(ev, tmp_path, capsys):
    """空数据集必须是 2：0/0「全过」是这套工具最容易骗人的假绿。"""
    ds = make_dataset(tmp_path / "ds")

    rc = ev.main(["--dataset", str(ds)])

    captured = capsys.readouterr()
    assert rc == 2
    assert "数据集为空" in captured.err
    assert "EMPTY" in captured.out


def test_main_dataset_path_is_a_file_exits_2(ev, tmp_path, capsys):
    f = make_tsv(tmp_path / "notadir.txt", "x\n")

    rc = ev.main(["--dataset", str(f)])

    assert rc == 2
    assert "读不到数据集" in capsys.readouterr().err


def test_main_snapshot_pair_prints_diff(ev, monkeypatch, tmp_path, capsys):
    ds = make_dataset(tmp_path / "ds", bugs="A\t🌐 国际\n")
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "🌐 国际"}))
    a = make_tsv(tmp_path / "a.tsv", "🌐 国际\tBBC\n🌐 国际\tCNN\n")
    b = make_tsv(tmp_path / "b.tsv", "📺 卫视频道\tBBC\n🌐 国际\tCNN\n")

    rc = ev.main(["--dataset", str(ds), "--snapshot", str(a), "--snapshot", str(b)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "快照对比: 共同 2 条，移组 1 条，新增 0，消失 0" in out
    assert "🌐 国际  →  📺 卫视频道" in out


def test_main_single_snapshot_does_not_diff(ev, monkeypatch, tmp_path, capsys):
    ds = make_dataset(tmp_path / "ds", bugs="A\t🌐 国际\n")
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "🌐 国际"}))
    a = make_tsv(tmp_path / "a.tsv", "🌐 国际\tBBC\n")

    ev.main(["--dataset", str(ds), "--snapshot", str(a)])

    assert "快照对比" not in capsys.readouterr().out


def test_main_unreadable_snapshot_does_not_crash(ev, monkeypatch, tmp_path, capsys):
    ds = make_dataset(tmp_path / "ds", bugs="A\t🌐 国际\n")
    monkeypatch.setattr(ev, "categorize", fake_categorize({"A": "🌐 国际"}))

    rc = ev.main(["--dataset", str(ds), "--snapshot",
                  str(tmp_path / "gone1.tsv"), "--snapshot",
                  str(tmp_path / "gone2.tsv")])

    captured = capsys.readouterr()
    assert rc == 0
    assert "跳过对比" in captured.err


def test_main_help_exits_zero(ev):
    with pytest.raises(SystemExit) as ei:
        ev.main(["--help"])

    assert ei.value.code == 0
