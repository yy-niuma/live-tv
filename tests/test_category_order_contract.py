"""`CATEGORY_ORDER` 与 `categorize()` 实际产出之间的契约测试。

`src/generator.py` 的 `CATEGORY_ORDER` 头上写着一条维护约定：

    本表必须与 src/group/categorizer.py 实际能产出的分类保持一一对应。
    历史问题：表里有 13 个分类 categorize() 从不产出（📺 其他、🇯🇵 日本…🌏 大洋洲），
    而实际产出的 🇨🇳 中国源 / 🇲🇾 马来西亚 / 🌐 国际 不在表内，排序落到最后一档。

这条历史问题正是这个文件要钉住的：`sort_key()` 对不在表内的分类返回 `(1, cat)`，
会**静默**把它们扔到所有已知分类后面。没有断言的话，新增分类忘了登记只会表现为
「产物里某组跑到最后」，不会报错。

本文件只读仓库内已有产物与数据集，不发网络请求。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.generator import CATEGORY_ORDER, KNOWN_CATEGORIES, sort_key

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "scripts" / "categorize_dataset"
SHIPPED_ALL = REPO_ROOT / "output" / "all_merged.m3u"
SHIPPED_HK = REPO_ROOT / "output" / "hk_merged.m3u"

# 「预留但当前不产出」的分组：categorize() 目前从不返回它们。
# 它们留在表里只为不破坏旧产物排序与既有 sort_key 断言。
# 一旦某个开始真的产出，下面的
# test_reserved_categories_are_still_never_produced 会失败，
# 提醒把这一行从「预留」挪进「在用」，并同步文档。
RESERVED_CATEGORIES = frozenset({
    "🇯🇵 日本", "🇰🇷 韩国", "🌏 亚洲（东南亚）", "🇮🇳 印度", "🌏 亚洲（其他）",
    "🌍 欧洲", "🇺🇸 北美", "🌎 拉丁美洲", "🌍 中东", "🌍 非洲", "🌏 大洋洲",
    "📺 其他",
})

_EXTGRP_RE = re.compile(r"^#EXTGRP:(?P<cat>.*) \((?P<n>\d+)\)$")


def _shipped_categories(path: Path) -> set[str]:
    """从产物里读实际写出的分组名。"""
    if not path.is_file():
        return set()
    cats = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _EXTGRP_RE.match(line)
        if m:
            cats.add(m.group("cat"))
    return cats


def _dataset_names(path: Path) -> list[str]:
    """读 `name \\t 期望分类 \\t 原因` 格式的数据集，返回频道名列表。"""
    if not path.is_file():
        return []
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line.split("\t")[0])
    return names


# ──────────────────────────────────────────────────────────────
#  表本身的自洽性
# ──────────────────────────────────────────────────────────────
def test_category_order_has_no_duplicates():
    """重复项会让 `.index()` 永远返回第一个下标，后一个形同虚设。"""
    dupes = {c for c in CATEGORY_ORDER if CATEGORY_ORDER.count(c) > 1}
    assert not dupes, f"CATEGORY_ORDER 有重复分组：{sorted(dupes)}"


def test_known_categories_is_exactly_category_order():
    assert KNOWN_CATEGORIES == frozenset(CATEGORY_ORDER)


def test_reserved_categories_are_declared_in_order_table():
    missing = RESERVED_CATEGORIES - set(CATEGORY_ORDER)
    assert not missing, f"这些分组被标为预留却不在 CATEGORY_ORDER 里：{sorted(missing)}"


def test_reserved_block_sits_at_the_tail_of_the_order_table():
    """预留分组必须都排在所有「在用」分组之后，否则它们插在中间会误导排序意图。"""
    in_use = [c for c in CATEGORY_ORDER if c not in RESERVED_CATEGORIES]
    last_in_use = max(CATEGORY_ORDER.index(c) for c in in_use)
    first_reserved = min(CATEGORY_ORDER.index(c) for c in RESERVED_CATEGORIES)
    assert last_in_use < first_reserved, (
        f"在用分组最大下标 {last_in_use} 没有早于预留分组最小下标 {first_reserved}"
    )


# ──────────────────────────────────────────────────────────────
#  产出 ⊆ 表（历史 bug 的正向断言）
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "shipped", [SHIPPED_ALL, SHIPPED_HK], ids=["all_merged", "hk_merged"]
)
def test_every_shipped_group_is_declared_in_category_order(shipped: Path):
    """仓库产物里出现过的每个分组都必须能在 CATEGORY_ORDER 找到。

    找不到就意味着 `sort_key()` 会给它 `(1, cat)`，被静默排到文件末尾。
    """
    cats = _shipped_categories(shipped)
    if not cats:
        pytest.skip(f"{shipped.name} 不存在或没有 #EXTGRP 行（可能是干净检出）")
    unknown = cats - set(CATEGORY_ORDER)
    assert not unknown, (
        f"{shipped.name} 里有 CATEGORY_ORDER 未登记的分组 {sorted(unknown)} —— "
        f"它们排序时会掉到所有已知分组之后（sort_key 走 (1, cat) 分支）"
    )


@pytest.mark.parametrize(
    "dataset", sorted(DATASET_DIR.glob("known_*.tsv")), ids=lambda p: p.name
)
def test_every_dataset_expected_group_is_declared(dataset: Path):
    """评测集里的期望分类也必须是表里存在的分组（防拼错 emoji/空格）。

    注意 `known_*.tsv` 的列序是 `频道名 \t 期望分类 \t 原因`，
    而 `current_snapshot.tsv` 是 `分组 \t 频道名` —— 两者 schema 不同，分开测。
    """
    lines = [ln for ln in dataset.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    expected = {ln.split("\t")[1] for ln in lines if len(ln.split("\t")) >= 2}
    unknown = expected - set(CATEGORY_ORDER)
    assert not unknown, f"{dataset.name} 用了未登记的分组：{sorted(unknown)}"


def test_snapshot_groups_are_all_declared():
    """`current_snapshot.tsv` 是「分组 \t 频道名」，第 0 列是真实产出过的分组。"""
    snap = DATASET_DIR / "current_snapshot.tsv"
    if not snap.is_file():
        pytest.skip("没有 current_snapshot.tsv")
    cats = {ln.split("\t")[0] for ln in snap.read_text(encoding="utf-8").splitlines()
            if ln.strip() and len(ln.split("\t")) >= 2}
    unknown = cats - set(CATEGORY_ORDER)
    assert not unknown, (
        f"产物快照里出现了 CATEGORY_ORDER 未登记的分组：{sorted(unknown)}"
    )


# ──────────────────────────────────────────────────────────────
#  预留分组仍然「不产出」——让「预留」这个标签保持诚实
# ──────────────────────────────────────────────────────────────
def test_reserved_categories_are_still_never_produced():
    """预留分组若开始被产出，说明产地识别/兜底逻辑变了，表里的注释与本文的清单都该更新。"""
    produced = set()
    for shipped in (SHIPPED_ALL, SHIPPED_HK):
        produced |= _shipped_categories(shipped)
    if not produced:
        pytest.skip("没有可读产物，无法判定")

    now_produced = produced & RESERVED_CATEGORIES
    assert not now_produced, (
        f"这些分组标着「预留但当前不产出」，但产物里已经出现了：{sorted(now_produced)}。"
        f"请把它们从 RESERVED_CATEGORIES 与 generator.py 的预留注释里挪走，"
        f"并在 docs/architecture.md §3.8 同步。"
    )


# ──────────────────────────────────────────────────────────────
#  兜底分支的行为：未登记分类不报错，但一定排在最后
# ──────────────────────────────────────────────────────────────
def test_unregistered_category_is_silently_sorted_to_tail():
    """记录现状：未登记分类**不会**抛错，只会掉到末尾。

    这正是需要上面那些断言的原因 —— 它不报错，只静默排错序。
    """
    unknown = "🆕 完全没登记过的分组"
    assert sort_key(unknown) == (1, unknown)
    assert sort_key(unknown) > max(sort_key(c) for c in CATEGORY_ORDER)
