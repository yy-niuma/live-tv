# 变更记录

本文件按 `git log` 的**真实历史**整理，不编造条目。

> 本文引用的 `audit-c-engineering.md` / `work-plan.md` 是只读审计产出，**不入库**（见 `.gitignore`），只存在于本地磁盘。

## 怎么读这份 CHANGELOG（重要）

- 仓库**没有任何 git tag**（`git tag` → 空），也没有 `pyproject.toml` 的历史版本，唯一的版本号是 `src/__init__.py` 里的 `__version__ = "1.0.0"`，从首次提交起就没变过。所以**无法按版本号切分历史**，只能按提交类型切。
- 全部历史 **186 个提交**（`git log --oneline | wc -l`）：
  - **183 个**来自 `github-actions[bot]`，标题一律是 `Update IPTV <ISO 时间戳>`，**只改 `output/` 三个文件**（`git log --name-only --author=github-actions` 的唯一路径集合就是 `output/all_merged.m3u`、`output/hk_merged.m3u`、`output/stats.json`，各 183 次）。这些是数据产物提交，**不含任何功能变更**。
  - **3 个**来自人类（`git shortlog -sn --all` → `183 github-actions[bot] / 3 yy-niuma`），全部集中在 **2026-04-25 一天**。
- 结论先行：**代码在 2026-04-25 被整体写入一次，之后半年只有数据在变**，直到 2026-10-29 才有第一批工程整改提交（见 1.1.0）。所以 1.0.0 + 1.1.0 两节合起来就是全部代码历史。

---

## [1.1.0] — 2026-10-29（工程整改批次）

5 个提交，全部落在数据提交 `074c677` 之上。**不改分类规则、不改产物口径**（`src/` 只有退出码那一处改动，100 条/组上限原样保留）。

| 提交 | 类型 | 内容 |
|---|---|---|
| `871e32d` | `fix(主流程)` | 失败写 stderr + `raise SystemExit(1)`，退出码由 0 变 1（CI 终于能感知失败） |
| `5221621` | `ci` | 拆 `check`（ruff + mypy + pytest，10 min）/ `update`（抓取→生成→产物体检→推送，45 min）；显式 `permissions` 与 `concurrency`；变更检测从 `git diff --stat \| grep "0 files changed"`（永假）改为 `git status --porcelain`；接入 dependabot；新增 `scripts/check_output.py` 产物保险丝 |
| `7ff4be1` | `build(依赖)` | `requirements.txt` 从 4 条下界改为 11 个精确 pin 的传递闭包，删掉 2 个零引用依赖；新增 dev 依赖与 `pyproject.toml`（`requires-python = ">=3.11"`、ruff/mypy 配置）、`pytest.ini`；`.gitignore` 补缓存目录 |
| `3020583` | `test` | 306 例回归基线（`283 passed, 23 xfailed`，1.4s），含 golden 分类表与「已知缺陷契约」xfail |
| 本文所在提交 | `docs` | 重写 README；新增 `CHANGELOG.md`、`LICENSE`(MIT)、`docs/architecture.md`、`docs/getting-started.md` |

设计与依据见 `docs/ci.md` 与本地审计报告 `audit-c-engineering.md`。

⚠️ 版本号仍是 `src/__init__.py` 的 `1.0.0`，仓库仍无 tag —— `1.1.0` 这个标题只是给这批提交一个可引用的名字，不代表已打 tag。

---

## [1.0.0] — 2026-04-25

一个 commit 就是全部代码：`feat: IPTV M3U 播放列表聚合工具 — 全面重构版`（`1f7265f`）。当天随后两个 commit 是修复与 CI。

### 新增（`1f7265f`）

- 四阶段流水线：抓取 → 验证 → 分组 → 生成（`src/main.py` 的 `run()`）。
- 多源抓取：`config/sources.yaml` 配置源，支持 M3U 与 YAML（Free-IPTV 格式）两种输入，按 URL 去重，单源失败重试 3 次（`src/fetcher.py`）。
- URL 验证：代理域名拒绝 + CDN 白名单放行 + HEAD/GET 探测（`src/validator.py`）。
- 频道名归一：词表级繁简转换（106 条替换规则）、噪声清理、`config/alias.txt` 别名映射、同名合并（主用 + 最多 2 个备用 URL）（`src/group/normalize.py`）。
- 分类：32 组省级关键词表 + 港澳台/国际/题材分类规则，`CATEGORY_ORDER` 固定 62 个分类的输出顺序（`src/group/categorizer.py`、`src/generator.py`）。
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

期间产物量的波动（据 本地审计报告 `audit-c-engineering.md` §1.2 的全历史扫描，本条未复测）：`hk_merged.m3u` 的频道数在整个历史里最小 18、最大 39、最后一次 33，**从未接近提交信息里提到的 162**。

---

## 版本号说明

`src/__init__.py` 的 `__version__ = "1.0.0"` 从首个提交起未变，仓库也没有 tag 指向它，因此它只是一个字符串常量，不代表可引用的发布点；本文件里的 `1.1.0` 标题同理，只是给 2026-10-29 那批提交一个名字。要让版本号真正可用，需要给提交打 tag（如 `v1.1.0`）并同步 `pyproject.toml` 的 `version`。
