# live-tv · IPTV 直播源聚合

从 `config/sources.yaml` 配置的 **20 个数据源**（M3U / YAML 两种格式）抓取直播源，
按 URL 去重、繁名归一、同名合并、按频道名分类，最后生成两个 M3U 播放列表。

- 仓库：<https://github.com/yy-niuma/live-tv>
- 入口：`python -m src.main`（**必须在仓库根目录执行**，见 [`docs/known-issues.md`](docs/known-issues.md) #10）
- 定时任务：GitHub Actions 每天 UTC 00:00（北京时间 08:00）自动跑，见 [`docs/ci.md`](docs/ci.md)

---

## 播放列表地址

| 文件 | 内容 | 地址 |
|---|---|---|
| `all_merged.m3u` | 全球列表（每分组最多 100 条） | <https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/all_merged.m3u> |
| `hk_merged.m3u` | 港澳台列表（无条数上限） | <https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/hk_merged.m3u> |

两个文件首行都声明了同一个 EPG：

```
#EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"
```

> ⚠️ 旧文档里的 `yy-niuma/**iptv**` 已失效（实测 404），真实仓库名是 `live-tv`。

推荐播放器：VLC / PotPlayer / IPTV Smarters 等任意支持 M3U + `x-tvg-url` 的客户端。
**EPG 覆盖哪些频道、能看几天由该第三方服务决定，本仓库不校验也不承诺。**

---

## 快速开始

```bash
git clone https://github.com/yy-niuma/live-tv.git
cd live-tv

python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 完整流程：抓取 → 验证 → 分组 → 生成
python -m src.main --output ./output
```

> 验证阶段是纯网络等待（并发 20、单条超时 10 秒），逐条 HEAD 上万个 URL，是最慢的一步。
> 只想看产物结构时加 `--skip-validation`，一次完整运行约 4 分钟。
> 从零跑通、常见问题见 **[docs/getting-started.md](docs/getting-started.md)**。

### 命令行参数（`python -m src.main --help` 共 7 项，含 `-h`；下表是 6 个功能选项）

| 参数 | 说明 |
|---|---|
| `-c, --config CONFIG` | 配置文件目录，默认仓库内 `config/` |
| `-o, --output OUTPUT` | 输出目录，默认仓库内 `output/` |
| `--no-cache` | 禁用缓存（注意：这条路径**不写**缓存，见 known-issues #3） |
| `--skip-validation` | 跳过 URL 验证（保留全部抓到的频道） |
| `--skip-fetch` | 跳过抓取，读 `src/.cache/channels_raw.json`；无缓存则报错退出 |
| `--fetch-timeout SECOND` | 抓取阶段总超时，默认 `90` |

---

## 输出文件与「三个频道数」

| 文件 | 内容 |
|---|---|
| `output/all_merged.m3u` | 全球列表，按固定分类顺序排列，**每分组最多 100 条**，超限处有 `# ... and N more` |
| `output/hk_merged.m3u` | 港澳台列表（`is_hk_region()` 命中项），无条数上限 |
| `output/stats.json` | `{分组名: 频道数}`，**生成前**的分组计数 |

**`stats.json` 的合计、文件头的 `# Total:`、文件里真实的 `#EXTINF` 条数，三者互不相等**——
这是设计内行为，不是抓取失败：

| 指标 | 仓库当前快照 |
|---|---:|
| `stats.json` 求和 / 分组数 | 8,371 / 51 |
| `all_merged.m3u` 首部 `# Total:` | 8,056 |
| `all_merged.m3u` 实际 `#EXTINF` | **1,164** |
| `hk_merged.m3u` 实际 `#EXTINF` / 分组数 | **33** / 7 |

差值的来源：8,371 −（脏名过滤 315）= 8,056 →（每分组 100 条上限丢掉 6,892）= 1,164。
完整推导见 [`docs/getting-started.md`](docs/getting-started.md) FAQ 1/2/3。

> **给播放器订阅的是 1,164 + 33 条；8,371 只是统计口径。**
> 另外 `output/` 是上一次 CI 的数据提交产出的，**每次定时任务跑完这些数字都会变**，引用前请自己 `grep -c`。

---

## 数据流

```
config/sources.yaml (20 源)
      │  src/fetcher.py      并发抓取 + 按 URL 去重（M3U / YAML）
      ▼
   Channel[]
      │  src/validator.py    HEAD 请求（405 回退 GET）+ 代理域名拒绝 + CDN 白名单放行
      ▼
   Channel[]（有效）
      │  src/grouper.py      别名归一 + 繁简转换 + 同名合并 + 分类
      ▼
   {分组: Channel[]}
      │  src/generator.py    脏名过滤 → 港澳台切分 → 100/组截断 → 写 m3u
      ▼
output/all_merged.m3u · output/hk_merged.m3u · output/stats.json
```

模块职责、行数、每个模块的已知问题见 **[docs/architecture.md](docs/architecture.md)**。

---

## 当前状态

| 项目 | 值 |
|---|---|
| 代码规模 | 2,200 行 / 14 个 `.py`（`categorizer.py` 684 行是重心） |
| 测试 | `pytest` → **323 passed, 7 xfailed**（330 例） |
| 静态检查 | `ruff check src scripts` → All checks passed |
| 类型检查 | `mypy src/` → 18 errors（CI 里 `continue-on-error`） |
| 分组成员评测 | `scripts/eval_categorize.py` → **50/51**（唯一残留 `DetetivesMedicos`，脚本故意退 1） |
| 最近一次全新运行 | 抓取 16,991 → 合并 12,578 → 53 组；`all` 1,706 条、`hk` 107 条 |
| 港澳台链接可用率 | `hk_merged` 107 条中 43 条可用 = **40.2%**（`scripts/check_streams.py`） |

> 「仓库快照」与「最近一次全新运行」数字不同，是因为仓库里的 `output/` 还是**上一次 CI 数据提交**
> 产的（重构前的分类器）。**不要拿旧快照对照新代码判断对错。**

---

## 分组逻辑

分组 = `src/group/categorizer.py` 的 `categorize(name, group, logo)`，
港澳台切分 = 同文件的 `is_hk_region()`。

**2026-10-29 做过一次重构**：两者改为共用同一套 `HK_TW_MO_RULES` + `_region_category()`，
不再各维护一份关键词表。结果：

- 评测集 **32/51 → 50/51**（`known_bugs` 5/24 → 23/24，`known_good` 27/27 不退化）
- 13,470 条真实语料上 `is_hk_region()` 命中 **92 → 145**（新增 53 / 丢失 0）
- `📡 卫视频道` 桶 **603 → 37**（原先没有词边界的 `r"atv"` 把 `AricaTV`/`AndorraTV` 等全吸进来）
- 13,470 条里 **1,891 条（14.0%）** 分类发生变化，分组集合本身零新增零消失

缺陷清单、机制隔离贡献、两次修正的全过程、以及统计口径出过的错，
都在 **[docs/categorize-rework.md](docs/categorize-rework.md)**。

> 测分类时 **`logo` 参数不能省** —— `LOGO_REGION_PATTERNS` 靠 logo URL 片段判地区
> （`Astro` → 🇲🇾 马来西亚、`gitee.com/suxuang` → 🇨🇳 中国源）。漏传会得出完全错误的结论。

---

## 已知限制

一句话清单，每条的可复核证据见 **[docs/known-issues.md](docs/known-issues.md)**：

1. 每分组 100 条上限（设计内），交付量与 `stats.json` 永久不一致
2. 文件头 `# Total:` 不是实际条数
3. `--no-cache` 不写缓存，所以 `--skip-fetch` 在其后必然失败
4. ~~失败退出码为 0~~ —— 已修（`871e32d`）
5. 缓存目录落在 `src/.cache` 而非仓库根
6. 验证器把 `asyncio` 异常对象当成「有效」
7. `strip_noise` 删除所有内部空格
8. ~~分类与港澳台过滤判定不一致~~ —— 已修（2026-10-29 重构）
9. 测试覆盖：323 passed / 7 xfailed；此前 189 个历史提交零测试
10. `python -m src.main` 必须在仓库根目录跑，且不能 `pip install -e .`
11. 分组很慢：几百个正则以字符串传给 `re.search`，缓存被反复冲掉
12. 产物数字每天漂移，任何写死的数字都只是当日快照

分组侧另有 4 条残留（`DetetivesMedicos` / `ATV` / `CNNInternational` / `CHANNEL_REGION_PATTERNS` 死数据），
见 [`docs/categorize-rework.md`](docs/categorize-rework.md) §9。

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/getting-started.md](docs/getting-started.md) | 本地从零跑通、9 条常见问题、三口径频道数推导 |
| [docs/architecture.md](docs/architecture.md) | 模块地图、数据流、每个模块的职责与已知问题 |
| [docs/categorize-rework.md](docs/categorize-rework.md) | 分组逻辑重构全过程 + 全部实测数据 |
| [docs/known-issues.md](docs/known-issues.md) | 12 条限制的证据 + 数字核实命令 |
| [docs/ci.md](docs/ci.md) | GitHub Actions 定时任务、超时预算、权限规范 |
| [docs/categorize-bug-analysis.md](docs/categorize-bug-analysis.md) | 分组缺陷清单（19 条 D01–D19） |
| [docs/categorize-improvement-proposal.md](docs/categorize-improvement-proposal.md) | 重构方案、残留取舍、后续 TODO |
| [docs/categorize-baseline-findings.md](docs/categorize-baseline-findings.md) | 重构前的基线量化（7 类缺陷） |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |

`reports/`（审计报告）与 `.hermes/` 是本地产物，**不入库**，见 `.gitignore`。

---

## 免责声明与许可证

本项目只做**索引聚合**：所有频道 URL 来自公开第三方数据源，版权归各自广播者所有。
仅供个人学习研究，请勿用于商业用途。数据源可用性、内容合法性由使用者自行判断。

[LICENSE](LICENSE)（MIT）只覆盖本仓库的**代码与文档**，不覆盖 `output/` 里播放列表中的频道 URL
及其内容，也不覆盖 `config/sources.yaml` 列出的各数据源。

> ⚠️ `LICENSE` 是 2026-10-29 补齐时**新建**的 —— 此前全仓零许可证线索（无 `LICENSE`/`COPYING`/`NOTICE`、
> `pyproject.toml` 无 `license` 字段、无 `setup.py`/`setup.cfg`、源码无 SPDX 头、`git log --grep=licen` 无相关提交）。
> **著作权人与许可证选择须由 owner 确认**；若 owner 选别的许可证，直接替换该文件即可。
