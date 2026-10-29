"""本 lane（分类器 golden 测试）专用 fixture。

约定：
- 不放 autouse fixture（其它 lane 的测试会被迫继承，容易互相打架）。
- 不发网络请求：所有 fixture 都是纯本地。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 让 `import src.*` 在任意 cwd 下都可用（CI 里 pytest 从仓库根跑也一样）
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.group.categorizer import categorize, is_hk_region  # noqa: E402

# categorize() 返回的「地区型」分组：这些分组理应同时被 is_hk_region 认定为港台
HK_TW_MO_GROUPS = frozenset({
    "📺 TVB", "📺 ViuTV", "📺 RTHK", "📺 HOY TV", "📺 Now TV", "📺 有线电视",
    "🇹🇼 台湾", "🇲🇴 澳门",
})


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def classify():
    """返回 generator.py 生产路径用的同款判定函数。

    generator.Generator.generate_hk_and_all() 的做法是：
        cat = categorize(name, group, logo)
        hk  = is_hk_region(name, group, cat)
    这里复刻同一调用关系，避免测试和生产走两条不同路径。

    ⚠️ `logo` 不能省：`LOGO_REGION_PATTERNS` 靠 logo URL 里的片段判地区
    （`Astro` → 🇲🇾 马来西亚、`epg.112114.xyz/logo/TVB` → 📺 TVB、
    `gitee.com/suxuang` → 🇨🇳 中国源）。参数默认空串只为兼容既有只传
    (name, group) 的用例，不代表生产可以不传。
    """

    def _classify(name: str, group: str = "", logo: str = "") -> tuple[str, bool]:
        cat = categorize(name, group, logo)
        return cat, is_hk_region(name, group, cat)

    return _classify


@pytest.fixture(scope="session")
def hk_tw_mo_groups() -> frozenset:
    return HK_TW_MO_GROUPS
