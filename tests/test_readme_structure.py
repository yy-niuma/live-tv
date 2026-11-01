"""tests/test_readme_structure.py —— README 的内容边界守卫。

为什么需要这个测试
------------------
README 一旦开始「长」，就会把专题内容（分组重构全过程、逐源体检诊断、
实测快照机制）都吸进去，最后变成 250 行、读者找不到订阅地址。

这个测试钉住三件事：
1. **README 必须短** —— 超过行数上限就红，逼着内容回流到 `docs/`；
2. **订阅地址必须在 README 里** —— 这是 99% 读者的唯一目的，不能被挪走；
3. **README 引用的每个文档都必须存在** —— 防死链。

⚠️ 只约束 README 的**篇幅与入口**，不约束它必须包含哪些具体数字 ——
数字每天漂移，写进测试反而会天天红。数字统一放 `docs/status.md`。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# README 的行数上限。给它留了余量，但远低于原来的 249 行 ——
# 超过就说明专题内容又漏进来了。
MAX_LINES = 130

# 订阅者最关心的东西，必须留在 README
MUST_APPEAR = [
    "all_merged.m3u",
    "hk_merged.m3u",
    "raw.githubusercontent.com/yy-niuma/live-tv",
    "python -m src.main",
]


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_readme_exists_and_is_short():
    """README 超过行数上限就红 —— 专题内容该回流到 docs/。"""
    lines = _readme_text().splitlines()
    assert len(lines) <= MAX_LINES, (
        f"README 有 {len(lines)} 行，超过上限 {MAX_LINES} —— "
        "专题内容（分组重构、逐源体检、快照机制、实测数字）应挪到 docs/ 下"
    )


def test_subscription_urls_are_in_readme():
    """订阅地址是读者唯一的目的地，不能被精简掉。"""
    text = _readme_text()
    for needle in MUST_APPEAR:
        assert needle in text, f"README 里找不到「{needle}」"


def test_all_doc_links_exist():
    """README 里的每个相对链接都必须指向真实文件（防死链）。"""
    text = _readme_text()
    links = re.findall(r"\]\(([^)#][^)]*)\)", text)
    checked = 0
    for link in links:
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        target = (ROOT / link.split("#")[0]).resolve()
        assert target.exists(), f"README 里的链接指向不存在的文件：{link}"
        checked += 1
    assert checked >= 10, f"README 的相对链接只有 {checked} 个，文档索引可能丢了"


def test_doc_index_covers_every_doc_file():
    """`docs/` 下每个文档都必须在 README 的索引里被提到。

    新增文档却忘了加索引 = 没人找得到它。
    """
    text = _readme_text()
    docs = sorted(p.name for p in (ROOT / "docs").glob("*.md"))
    missing = [d for d in docs if d not in text]
    assert not missing, f"这些文档没进 README 索引：{missing}"


def test_topic_documents_exist():
    """被精简掉的三块内容，各有落点。"""
    for name in ("status.md", "stream-health.md"):
        assert (ROOT / "docs" / name).exists(), f"docs/{name} 不存在"
