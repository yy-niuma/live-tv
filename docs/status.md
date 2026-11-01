# 项目状态快照

> 本文是**某一天实测出来的数字**，会随时间漂移。
> README 只放结论性的一句话，完整快照在这里 —— 引用前请自己复核。

## 复核命令

```bash
# 启用源数
.venv/bin/python -c "
import yaml; d=yaml.safe_load(open('config/sources.yaml')); s=d.get('sources',d)
print(len(s),'配置 /',len([x for x in s if x.get('enabled',True)]),'启用')"

# 代码规模
find src -name '*.py' | wc -l ; find src -name '*.py' -exec cat {} + | wc -l

# 测试 / 静态检查 / 类型检查
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check src scripts
.venv/bin/python -m mypy src/

# 产物三个口径（远端最新提交）
git show origin/main:output/stats.json | python -c "import json,sys; d=json.load(sys.stdin); print(sum(d.values()), d.get('__total__'))"
git show origin/main:output/all_merged.m3u | grep -c '^#EXTINF'
git show origin/main:output/hk_merged.m3u | grep -c '^#EXTINF'

# 分组成员评测
.venv/bin/python scripts/eval_categorize.py
```

## 快照（2026-11-01）

| 项目 | 值 |
|---|---|
| 代码规模 | 4,066 行 / 15 个 `.py`；`src/validator.py` 845 行最大，`src/group/categorizer.py` 610 行是分类重心 |
| 数据源 | 配置 32 个，**启用 30 个**；停用 2 个（`freetv-fun` 域名停服 http=000、`Harbin-byte-iptv` 与 `free-tv-hk` 逐字节相同），原因写在 `config/sources.yaml` 行内注释 |
| 测试 | `pytest tests/` → **857 passed, 5 xfailed**（共收集 862 项） |
| 静态检查 | `ruff check src scripts` → All checks passed |
| 类型检查 | `mypy src/` → 20 errors（CI 里 `continue-on-error`，与基线同量） |
| 分组成员评测 | `scripts/eval_categorize.py` → **50/51**（唯一残留 `DetetivesMedicos`，脚本故意退 1） |
| 产物（远端最新） | `stats.json` 求和 9,340 / 52 组；`all` 1,381 条；`hk` **78** 条 |
| 逐源体检 | `scripts/check_sources.py` → 每个源都有产出，**0 个零产出** |

## 怎么读这些数字

- **`stats.json` 求和 ≠ 文件里的 `#EXTINF` 条数** —— 前者是分组前的计数，
  后者经过「每分组 100 条上限」截断。推导见
  [getting-started.md](getting-started.md) FAQ 1/2/3。
- **文件头 `# Total:` 也不是实际条数** —— 它是截断前的数。
- **仓库里的 `output/` 是上一次 CI 数据提交产的**，每天定时任务会覆盖。
  引用数字前先 `git show origin/main:output/...` 复核。

> ⚠️ 测分类时 **`logo` 参数不能省** —— `LOGO_REGION_PATTERNS` 靠 logo URL 片段判地区
> （`Astro` → 🇲🇾 马来西亚、`gitee.com/suxuang` → 🇨🇳 中国源）。
> 漏传会得出完全错误的结论。生产路径 `src/grouper.py` 传的是
> `categorize(name, group, logo)`。教训见
> [categorize-rework.md](categorize-rework.md) 的「统计口径出过的错」。

## 历史教训（值得保留的一段）

2026-10-29 修掉过一个「整条流水线看起来完全正常」的坑：此前 20 个源里
**11 个产出 0 条**，而总量仍有 18,285 条、`exit=0`、产物正常生成。
原因是 8 个 markdown 表格源被当成 m3u 解析（其中 1 个是重复 fork，已停用）、
2 个指向已死的 GitHub 代理、1 个源站停服。

**只看总量和退出码发现不了这类问题**，所以现在按**内容**嗅探三种格式，
0 条会打 WARNING，并有 `scripts/check_sources.py` 逐源体检。
全过程与证据见 [source-health.md](source-health.md)。

## CI 性能现状

| 配置 | 整条 wall clock | 有效条数 |
|---|---:|---:|
| 单 job 并发 40（历史基线） | 18 分钟 | 11,042 |
| 单 job 并发 80 | 12m55s | 11,042 |
| **8 片（当前默认）** | **4m08s** | 10,990 |

分片方式、耗时构成、瓶颈分析见 [ci.md](ci.md) §7–§8。
