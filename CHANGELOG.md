# 变更记录

本文件按 `git log` 的**真实历史**整理，不编造条目。

> 本文引用的 `audit-c-engineering.md` / `work-plan.md` 是只读审计产出，**不入库**（见 `.gitignore`），只存在于本地磁盘。

## 怎么读这份 CHANGELOG（重要）

- 仓库**没有任何 git tag**（`git tag` → 空），也没有 `pyproject.toml` 的历史版本，唯一的版本号是 `src/__init__.py` 里的 `__version__ = "1.0.0"`，从首次提交起就没变过。所以**无法按版本号切分历史**，只能按提交类型切。
- 全部历史 **197 个提交**（`git log --oneline | wc -l`，截至 `a00e134`）：
  - **183 个（92.9%）**来自 `github-actions[bot]`，标题一律是 `Update IPTV <ISO 时间戳>`，**只改 `output/` 三个文件**。验证：`git log --author=github-actions --name-only --pretty=format:` 的唯一路径集合就是 `output/all_merged.m3u` / `output/hk_merged.m3u` / `output/stats.json`；且 `git rev-list --count --author=github-actions HEAD` = `git rev-list --count HEAD -- output/all_merged.m3u output/hk_merged.m3u output/stats.json` = **183**，两者严格相等。这些是数据产物提交，**不含任何功能变更**。
  - **14 个**提交人是 `yy-niuma`（本地 git 身份，`git shortlog -sn HEAD` → `183 github-actions[bot] / 14 yy-niuma`）。其中 **3 个**是 2026-04-25 的原始代码提交，**11 个**是 2026-10-29 的工程整改与分组重构批次（由 AI 助理在该身份下提交）。
- 结论先行：**代码在 2026-04-25 被整体写入一次，之后半年只有数据在变**，直到 2026-10-29 才有工程整改（1.1.0）与分组逻辑重构（1.2.0）。所以 1.0.0 + 1.1.0 + 1.2.0 三节合起来就是全部代码历史。

---

## [1.2.0] — 2026-10-29（分组逻辑重构）

对着「分组准确度低、有缺失、区分混乱」做的一次重构。**这是本项目第一次改动分类规则本身**，1.0.0 的规则表原样沿用了半年。

| 提交 | 类型 | 内容 |
|---|---|---|
| `a00e134` | `refactor(分组)` | 统一港澳台判定、给关键词加词边界、补兜底链、`CATEGORY_ORDER` 62→65、测试去 xfail、新增评测器 |
| 本提交 | `docs` | README 补「分组逻辑」章节与残留清单；`docs/architecture.md` §3.6 按 AST 实测重写；`docs/getting-started.md` 修正行号与港台量级；新增 `docs/categorize-bug-analysis.md`、`docs/categorize-improvement-proposal.md` |

### 修掉的三类根因

1. **裸子串误伤**：`📡 卫视频道` 里有条没有词边界的 `r"atv"`，把 `AricaTV` / `BarazaTV` / `AndorraTV` / `AgriculturaTV` 这类西语葡语频道全吸进来（实测 98/1,164 = 8.4% 的产物条目受影响）。同类还有 `tv5`（`XinjiangTV5` 被抢进国际频道）、`tbs`、`dw`、`nick`、`amc`。
2. **港澳台判定两套表打架**：`is_hk_region()` 的 `hk_exact`/`tw_exact`/`mo_exact` 里有若干正则写成双反斜杠（`r"\\bmacau\\b"` 实际匹配字面反斜杠 + b），永不命中 → `Macau TV` / `TTV` / `PTS` / `CNA 中央社` / `非凡商业台` / `东森财经新闻` / `港台电视31` 被判成港澳台却进不了 `hk_merged.m3u`。
3. **兜底链太弱**：`recategorize_others()` 末尾 `return "🌐 国际"` 把没命中的频道全倒进国际桶（实测该桶 100 条里 100 条是大陆地市台）；未知 group 还一律暂归「📺 TVB」。

### 量化结果

| 指标 | 重构前 | 重构后 |
|---|---:|---:|
| 评测集 `known_bugs` 通过 | 5/24 | **23/24** |
| 评测集 `known_good` 不退化 | 27/27 | 27/27 |
| `is_hk_region()` 判为港澳台（13,470 条语料） | 92 | **145**（丢失 0，新增 53；第一版 141，第二遍修 `\b` 边界再 +4） |
| `📡 卫视频道` 桶大小 | 603 | **37** |
| `🇨🇳 中国源` 桶大小 | 0 | 272 |
| `all_merged.m3u` #EXTINF（同日全新运行） | 1,378 | **1,706**（第一版 1,702，第二遍修 `\b` 边界 +4） |
| `hk_merged.m3u` #EXTINF（同日全新运行） | 58 | **107**（第一版 103，+4 = `HOY78`/`HOYInfotainment`/`HOY资讯台`/`PTS3`，消失 0） |
| `python -m pytest` | 283 passed / 23 xfailed | **305 passed / 7 xfailed** |

### 已知残留（未修，如实登记）

- `DetetivesMedicos` 仍判 `🌐 国际`，期望 `📺 纪录片`（评测集唯一不达标项，故 `eval_categorize.py` 退出码 1）。
- `ATV`（亚洲电视，香港）分类 `📡 卫视频道`、`is_hk_region('ATV')=False` → 不进 `hk_merged.m3u`。
- ~~`HOY资讯台` 被判 `🌐 国际`~~ —— 已修。**更正：这是本版重构自己引入的回归，不是既有缺陷。**
  原 `r"\bhoy\b"` 在 CJK / 数字边界不成立（`\w` 含 CJK），连 `HOY78`、`HOYInfotainment` 一起击落；
  改 `r"(?<![a-z])hoy"` 后三条全恢复，`iHOY爱历史` 仍排除。同步把原来的错误 xfail 说明
  （「类型词判定先于品牌判定」）删掉，换成 7 条正向回归护栏。
- `CNN` 归 `🌐 国际频道` 但 `BBC World News` 归 `📰 新闻财经` —— 国际新闻品牌规则目前只覆盖 BBC。
- `CATEGORY_ORDER` 里仍有 11 个「预留但 `categorize()` 从不产出」的分类（`🇯🇵 日本`…`🌏 大洋洲`、`📺 其他`），保留是为不破坏 `sort_key` 断言，见 `tests/test_generator.py`。

详细缺陷分析与方案见 [`docs/categorize-bug-analysis.md`](docs/categorize-bug-analysis.md)、[`docs/categorize-improvement-proposal.md`](docs/categorize-improvement-proposal.md)。

⚠️ 版本号仍是 `src/__init__.py` 的 `1.0.0`，仓库仍无 tag —— `1.2.0` 这个标题只是给这批提交一个可引用的名字。

---

## [1.1.0] — 2026-10-29（工程整改批次）

5 个提交，全部落在数据提交 `074c677` 之上。这一批**不动分类规则、不改产物口径**（`src/` 只有退出码那一处改动，100 条/组上限原样保留）；分类规则本身在随后的 1.2.0 里才改。

| 提交 | 类型 | 内容 |
|---|---|---|
| `871e32d` | `fix(主流程)` | 失败写 stderr + `raise SystemExit(1)`，退出码由 0 变 1（CI 终于能感知失败） |
| `5221621` | `ci` | 拆 `check`（ruff + mypy + pytest，10 min）/ `update`（抓取→生成→产物体检→推送，45 min）；显式 `permissions` 与 `concurrency`；变更检测从 `git diff --stat \| grep "0 files changed"`（永假）改为 `git status --porcelain`；接入 dependabot；新增 `scripts/check_output.py` 产物保险丝 |
| `7ff4be1` | `build(依赖)` | `requirements.txt` 从 4 条下界改为 11 个精确 pin 的传递闭包，删掉 2 个零引用依赖；新增 dev 依赖与 `pyproject.toml`（`requires-python = ">=3.11"`、ruff/mypy 配置）、`pytest.ini`；`.gitignore` 补缓存目录 |
| `3020583` | `test` | 306 例回归基线（当时 `283 passed, 23 xfailed`，1.4s；分组重构后为 `305 passed, 7 xfailed`，312 例），含 golden 分类表与「已知缺陷契约」xfail |
| 本文所在提交 | `docs` | 重写 README；新增 `CHANGELOG.md`、`LICENSE`(MIT)、`docs/architecture.md`、`docs/getting-started.md` |

设计与依据见 `docs/ci.md` 与审计报告 `audit-c-engineering.md`。

⚠️ 版本号仍是 `src/__init__.py` 的 `1.0.0`，仓库仍无 tag —— `1.1.0` 这个标题只是给这批提交一个可引用的名字，不代表已打 tag。

---

## [1.0.0] — 2026-04-25

一个 commit 就是全部代码：`feat: IPTV M3U 播放列表聚合工具 — 全面重构版`（`1f7265f`）。当天随后两个 commit 是修复与 CI。

### 新增（`1f7265f`）

- 四阶段流水线：抓取 → 验证 → 分组 → 生成（`src/main.py` 的 `run()`）。
- 多源抓取：`config/sources.yaml` 配置源，支持 M3U 与 YAML（Free-IPTV 格式）两种输入，按 URL 去重，单源失败重试 3 次（`src/fetcher.py`）。
- URL 验证：代理域名拒绝 + CDN 白名单放行 + HEAD/GET 探测（`src/validator.py`）。
- 频道名归一：词表级繁简转换（106 条替换规则）、噪声清理、`config/alias.txt` 别名映射、同名合并（主用 + 最多 2 个备用 URL）（`src/group/normalize.py`）。
- 分类：32 组省级关键词表 + 港澳台/国际/题材分类规则，`CATEGORY_ORDER` 固定 62 个分类的输出顺序（2026-10-29 重构后为 65 个）（`src/group/categorizer.py`、`src/generator.py`）。
- 输出：`all_merged.m3u`（全球，**每分组上限 100 条**）、`hk_merged.m3u`（港澳台，无上限）、`stats.json`（分组计数）。100 条上限从首个提交起就存在（`git show 1f7265f:src/generator.py | grep -n 'channels\[:100\]'` → `180:`）。
- EPG：两个 m3u 首行都写 `x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"`。
- 依赖：`requirements.txt` 4 条（`pyyaml`、`aiohttp`、`aiofiles`、`charset-normalizer`，只有下界）。

### 修复（`e0625e6`）

- `fix: 全面修复HK/TW/MO频道过滤逻辑（162→86频道）` —— 提交信息自己记了这次修复把港澳台列表从 162 条降到 86 条。这是历史上唯一一次与业务判定相关的修复；此后半年没有任何代码改动。

### 工程 / CI（`d7c6d6b`）

- `ci: 重写 GitHub Actions workflow` —— 建立每日定时任务（`cron: "0 0 * * *"`，从该提交起就是这个表达式），Python 3.11，流程为抓取 → 生成 → 检测变化 → 提交推送 → 上传 artifact。

### 已知遗留（1.0.0 起就有，1.1.0 只修了「零测试 / 无 pyproject / 依赖无 lock」三项）

- 每分组 100 条上限导致交付量与 `stats.json` 永久不一致（详见 README「频道数」）—— **仍未修，属于设计**。
- `validate()` 把异常当「有效」（`validator.py:27`）—— **仍未修**。
- `strip_noise()` 删除所有内部空格（`normalize.py:84`）—— **仍未修**。
- 缓存落在 `src/.cache/`（`lib/cache.py:13`）—— **仍未修**（只补了 `.gitignore`）。
- 零测试、无 `pyproject.toml`、依赖只有下界 —— **1.1.0 已修**（`3020583`、`7ff4be1`）。
- 双反斜杠正则永不匹配（`categorizer.py` 内 3 行）—— **仍未修**，`tests/test_known_defects.py` 里以 xfail 固化。

（以上均有本轮实测证据，见 `docs/architecture.md` §5 的问题索引表。）

---

## [数据快照] — 2026-04-25 → 2026-10-29

这半年**只有机器人每日提交产物**，共 183 次。按提交次数分月（`git log --format='%ad' --date=format:'%Y-%m' | sort | uniq -c`）：

| 月份 | 提交数 | 说明 |
|---|---:|---|
| 2026-04 | 9 | 3 个人类提交 + 6 次产物更新（首次产物提交 `73c672d`，2026-04-25 15:24 UTC） |
| 2026-05 | 27 | 仅产物 |
| 2026-06 | 30 | 仅产物 |
| 2026-07 | 31 | 仅产物 |
| 2026-08 | 31 | 仅产物 |
| 2026-09 | 29 | 仅产物 |
| 2026-10 | 29 | 仅产物（最后一次 `074c677`，2026-10-29 05:38 UTC） |

日均约 1 次，但**不是每天成功**：一个月有 27~31 次产物提交，说明个别日子没有产出（源全挂、CI 失败、或产物与前一天逐字节相同因而没提交）。这些日子没有任何记录留下——没有 issue、没有日志、没有告警。

期间产物量的波动（据 审计报告 `audit-c-engineering.md` §1.2 的全历史扫描，本条未复测）：`hk_merged.m3u` 的频道数在整个历史里最小 18、最大 39、最后一次 33，**从未接近提交信息里提到的 162**。

---

## 版本号说明

`src/__init__.py` 的 `__version__ = "1.0.0"` 从首个提交起未变，仓库也没有 tag 指向它，因此它只是一个字符串常量，不代表可引用的发布点；本文件里的 `1.1.0` 标题同理，只是给 2026-10-29 那批提交一个名字。要让版本号真正可用，需要给提交打 tag（如 `v1.1.0`）并同步 `pyproject.toml` 的 `version`。
