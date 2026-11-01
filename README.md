# live-tv · IPTV 直播源聚合

从 `config/sources.yaml` 配置的 **30 个启用数据源**抓取直播源，按 URL 去重、繁名归一、同名合并、
按频道名分类，生成两个 M3U 播放列表。

仓库 <https://github.com/yy-niuma/live-tv> ·
入口 `python -m src.main`（**必须在仓库根目录执行**，见 [known-issues.md](docs/known-issues.md) §10） ·
[CI](docs/ci.md) 每天 UTC 00:00（北京时间 08:00）自动跑

## 订阅地址

| 文件 | 内容 | 地址 |
|---|---|---|
| `all_merged.m3u` | 全球列表（每分组最多 100 条） | <https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/all_merged.m3u> |
| `hk_merged.m3u` | 港澳台列表（无条数上限） | <https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/hk_merged.m3u> |

两个文件首行都声明同一个 EPG（播放器据此拉节目单）：
`#EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"`

推荐播放器：VLC / PotPlayer / IPTV Smarters 等任意支持 M3U + `x-tvg-url` 的客户端。
**EPG 覆盖哪些频道、能看几天由第三方服务决定，本仓库不校验也不承诺。**
（旧文档里的 `yy-niuma/iptv` 已实测 404，真实仓库名是 `live-tv`。）

## 快速开始

```bash
git clone https://github.com/yy-niuma/live-tv.git && cd live-tv
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main --output ./output   # 抓取 → 验证 → 分组 → 生成
```

> 验证阶段是纯网络等待（逐条探测上万个 URL），最慢的一步；只想看产物结构时加 `--skip-validation`。
> 从零跑通、全部命令行参数、常见问题见 **[docs/getting-started.md](docs/getting-started.md)**。

## 工作原理

```
config/sources.yaml (30 个启用源)
  │ src/fetcher.py    并发抓取 + 按 URL 去重（M3U / YAML / Markdown 表格）
  │ src/validator.py  HTTP 探测 + 代理域名拒绝 + CDN 白名单放行 + 熔断跳过已知死链
  │ src/grouper.py    编排；繁简/别名归一在 src/group/normalize.py，分类在 categorizer.py
  │ src/generator.py  脏名过滤 → 港澳台切分 → 100/组截断 → 写 m3u
  ▼
output/all_merged.m3u · output/hk_merged.m3u · output/stats.json
```

模块职责、行数、每模块的已知问题见 **[docs/architecture.md](docs/architecture.md)**。

三个值得知道的机制：**① 同名合并按「已实测可播 > 未知 > 已实测不可播」排序**，避免主 URL 全是死链
（[stream-health.md](docs/stream-health.md)）；**② 熔断器跳过连败多次的 URL**；
**③ `categorize()` 与 `is_hk_region()` 共用 `HK_TW_MO_RULES`**，不再各判各的。

## 产物与频道数

`output/` 里三个文件记的是**三个不同阶段的数字**，互不相等，这是设计内行为：

| 指标 | 含义 |
|---|---|
| `output/stats.json` 求和 | 分组统计（生成文件**之前**的计数） |
| `all_merged.m3u` 首部 `# Total:` | 脏名过滤后、截断前的数 |
| `all_merged.m3u` 实际 `#EXTINF` | **真正交付给播放器的条数**（受 100 条/组上限约束） |
| `hk_merged.m3u` 实际 `#EXTINF` | 港澳台交付条数（无上限） |

**给播放器订阅的是最后两个；`stats.json` 只是统计口径。** 完整推导见
[docs/getting-started.md](docs/getting-started.md) FAQ 1/2/3。
这些数字每天随源站存活情况漂移，写死的数字都只是当日快照 —— 当前实测值见
[docs/status.md](docs/status.md)。

## 已知限制

**每条的完整证据、影响与可复核命令在 [docs/known-issues.md](docs/known-issues.md)**，
下表只是速查目录（编号与该文一致）：

| # | 一句话 |
|---|---|
| 1 | 每分组 100 条上限（设计内，非缺陷） |
| 2 | 文件头 `# Total:` 不是实际条数 —— 三口径见上节 |
| 3 | `--skip-fetch` 在无缓存时必然失败（`--no-cache` 分支不写缓存） |
| 5 | 缓存目录落在 `src/.cache`，不在仓库根 |
| 6 | 验证器把部分异常当成「有效」（保守放行策略） |
| 7 | `strip_noise` 删除所有内部空格 |
| 9–10 | 测试覆盖的空白、可安装性（无 `pyproject.toml`/`setup.py`） |
| 11 | 正则未预编译（历史报告称慢 40×，**2026-11-02 复测已不复现**，实测 1,413 条/s） |
| 12 | 产物数字每天随源站漂移，写死的数字只是当日快照 |

> 第 4、8、13 条**已修复**（失败退出码 / 分类与港澳台判定不一致 / 两类非直播资源判活），
> 保留在文档里是为了防止回归。

分组侧另有 4 条残留（`DetetivesMedicos` / `ATV` / `CNNInternational` / `CHANNEL_REGION_PATTERNS` 死数据），
见 [docs/categorize-rework.md](docs/categorize-rework.md) §9。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | 本地从零跑通、命令行参数、9 条常见问题、三口径频道数推导 |
| [docs/architecture.md](docs/architecture.md) | 模块地图、数据流、每个模块的职责与已知问题 |
| [docs/status.md](docs/status.md) | 当前实测快照（代码规模 / 测试数 / 产物条数）+ 复核命令 |
| [docs/stream-health.md](docs/stream-health.md) | 实测可播快照机制：为什么需要、怎么用、与 CI 的关系 |
| [docs/known-issues.md](docs/known-issues.md) | 13 条限制的证据 + 数字核实命令（含已修条目） |
| [docs/ci.md](docs/ci.md) | GitHub Actions 定时任务、耗时构成、分片验证、权限规范 |
| [docs/source-health.md](docs/source-health.md) | 逐源体检：11 个零产出源的诊断与修复、格式嗅探、防复发 |
| [docs/source-discovery.md](docs/source-discovery.md) | 选源口径：60+ 候选的新颖度×可播率实测 |
| [docs/categorize-rework.md](docs/categorize-rework.md) | 分组逻辑重构全过程 + 全部实测数据 |
| [docs/categorize-bug-analysis.md](docs/categorize-bug-analysis.md) | 分组缺陷清单（19 条 D01–D19） |
| [docs/categorize-improvement-proposal.md](docs/categorize-improvement-proposal.md) | 重构方案、残留取舍、后续 TODO |
| [docs/categorize-baseline-findings.md](docs/categorize-baseline-findings.md) | 重构前的基线量化（7 类缺陷） |
| [docs/hk-tw-source-research-2026-10-31.md](docs/hk-tw-source-research-2026-10-31.md) | 港澳台源站专项调研 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |

`reports/`（审计报告）与 `.hermes/` 是本地产物，**不入库**，见 `.gitignore`。

## 免责声明与许可证

本项目只做**索引聚合**：所有频道 URL 来自公开第三方数据源，版权归各自广播者所有。
仅供个人学习研究，请勿用于商业用途。数据源可用性、内容合法性由使用者自行判断。

[LICENSE](LICENSE)（MIT）只覆盖本仓库的**代码与文档**，不覆盖 `output/` 里播放列表中的频道 URL
及其内容，也不覆盖 `config/sources.yaml` 列出的各数据源。
