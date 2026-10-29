# live-tv · IPTV 直播源聚合

从 `config/sources.yaml` 配置的数据源（当前 **20 个，全部 enabled**）抓取 M3U / YAML 直播源，按 URL 去重、繁简归一、按频道名分类分组，最后生成两个 M3U 播放列表。

- 仓库：<https://github.com/yy-niuma/live-tv>
- 入口：`python -m src.main`（必须在**仓库根目录**执行，见「已知限制」#10）
- 授权：MIT，见 [LICENSE](LICENSE)

> 本文所有数字都是命令跑出来的，每条都在文末「数字核实」与 [`docs/getting-started.md`](docs/getting-started.md) 给了可复现命令。**产物数字每天都会变**，本文写的是仓库当前快照（`git log -1` = `074c677`，2026-10-29）。

> **关于审计报告**：本文引用的 `audit-c-engineering.md` / `work-plan.md` 是只读审计产出，**不入库**（见 `.gitignore`），只存在于本地磁盘。

本文与 [`docs/architecture.md`](docs/architecture.md)、[`docs/getting-started.md`](docs/getting-started.md) 一起在 2026-10-29 的工程整改批次里入库（`871e32d` 退出码、`5221621` CI、`7ff4be1` 依赖与工程配置、`3020583` 测试），**产物数字取自数据提交 `074c677`**。CI 与依赖锁定的规范说明见 [`docs/ci.md`](docs/ci.md)。

---

## 播放列表地址

| 文件 | 实测状态 | 地址 |
|---|---|---|
| `all_merged.m3u`（全球） | HTTP 200，257,714 bytes，与仓库内文件字节数一致 | <https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/all_merged.m3u> |
| `hk_merged.m3u`（港澳台） | HTTP 200，8,376 bytes，与仓库内文件字节数一致 | <https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/hk_merged.m3u> |

上面两个地址在 2026-10-29 实测可访问（`curl -o /dev/null -w '%{http_code} %{size_download}'` → `200 257714` / `200 8376`），返回的字节数与仓库里的文件完全一致，因此判定为**可用**。

> ⚠️ 旧文档里的 `raw.githubusercontent.com/yy-niuma/**iptv**/main/...` 已失效：实测 `http=404`。仓库真实名字是 `live-tv`（`git remote -v` → `https://github.com/yy-niuma/live-tv.git`）。

两个文件首行都声明了同一个 EPG：

```
#EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"
```

该 EPG 地址实测 HTTP 200（约 19.4 MB 的 XMLTV）。**具体覆盖哪些频道、能看几天节目单由该第三方服务决定，本仓库不做任何校验**，因此这里不承诺「支持 7 天预告」。

推荐播放器：VLC / PotPlayer / IPTV Smarters 等任意支持 M3U + x-tvg-url 的客户端。

---

## 频道数：三个数字，三种口径（重要）

`output/stats.json` 的合计、文件头部的 `# Total:`、文件里真实的 `#EXTINF` 条数，**三者互不相等**，这是设计内行为，不是抓取失败。

| 指标 | 数值 | 出处 |
|---|---:|---|
| `stats.json` 分组计数求和 | **8,371** | `python3 -c "import json;print(sum(json.load(open('output/stats.json')).values()))"` |
| `stats.json` 分组数 | 51 | `len(json.load(...))` |
| `all_merged.m3u` 首部 `# Total:` | 8,056 | `head -6 output/all_merged.m3u \| tail -1` |
| `all_merged.m3u` 实际 `#EXTINF` 条数 | **1,164** | `grep -c '^#EXTINF' output/all_merged.m3u` |
| `hk_merged.m3u` 实际 `#EXTINF` 条数 | **33** | `grep -c '^#EXTINF' output/hk_merged.m3u` |
| `hk_merged.m3u` 分组数 | 7 | `grep -c '^#EXTGRP' output/hk_merged.m3u` |
| 因 100/组上限被丢弃的条目 | 6,892 | 8,056 − 1,164（= 9 行 `# ... and N more` 之和） |
| 超过 100 条的分组数 | 9 | `grep -c '^# \.\.\. and' output/all_merged.m3u` |

### 从 8,371 到 1,164 的完整推导

1. **8,371** = 分组完成后 `stats.json` 记录的各分组计数之和（51 个分组）。`src/main.py:115` 写的是 `{g: len(chs) for g, chs in grouped.items()}`，即**生成文件之前**的计数。
2. **8,056** = 写入 `all_merged.m3u` 前先用 `is_clean_name()`（`src/generator.py:69`）丢掉名字脏掉的条目，8,371 − 8,056 = 315 条被过滤。这个 8,056 只写进了文件第 6 行的注释里。
3. **1,164** = `all_merged.m3u` 每个分组最多只写前 **100** 条：

   ```python
   # src/generator.py:167-172
   # ALL 播放列表每个分组最多 100 个
   for ch in channels[:100]:
       ...
   if len(channels) > 100:
       all_lines.append(f"# ... and {len(channels) - 100} more")
   ```

   当前有 9 个分组超过 100 条，被丢弃 6,892 条，于是文件里留下 9 行 `# ... and N more`（293 + 427 + 562 + 581 + 246 + 869 + 172 + 168 + **3574** = 6,892）。

4. **33** = `hk_merged.m3u` **没有** 100 条上限（`src/generator.py:144-149` 是完整写出），它只收 `is_hk_region()` 判定为港澳台的子集，所以量级完全不同。

**结论：给播放器订阅的是 1,164（全球）+ 33（港澳台）条；8,371 只是统计口径。** 100 条/组是刻意的体积控制，若要全量输出需要改 `generator.py`（属于行为变更，不在文档范围内）。

---

## 快速开始

```bash
git clone https://github.com/yy-niuma/live-tv.git
cd live-tv

python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 完整流程：抓取 → 验证 → 分组 → 生成（验证阶段最慢，见下）
python -m src.main --output ./output
```

产物写在 `output/`（`--output` 可改）。完整说明、常见问题见 **[docs/getting-started.md](docs/getting-started.md)**。

> 验证阶段是纯网络等待（并发 20、单条超时 10 秒），逐条 HEAD 请求上万个 URL，是整条流水线最慢的一步；只想看产物结构时加 `--skip-validation`。本机实测一次 `--no-cache --skip-validation` 的完整运行：启动 10:50、产物写入 10:54，约 4 分钟；抓取阶段（20 源并发，含 3 个失败源各重试 3 次）在启动后一分钟内结束，时间几乎全花在「合并同名频道 + 分类」上。验证阶段耗时随远端响应变化很大，本地审计报告 `audit-c-engineering.md` §2.6 有按吞吐外推的实测表（本文未复测该阶段）。

## 命令行参数

以 `python -m src.main --help` 实测输出为准：

| 参数 | 说明（源码 `src/main.py:136-145`） |
|---|---|
| `-h, --help` | 显示帮助 |
| `-c, --config CONFIG` | 配置文件目录，默认仓库内 `config/` |
| `-o, --output OUTPUT` | 输出目录，默认仓库内 `output/` |
| `--no-cache` | 禁用缓存（**注意：这条路径不写缓存**，见「已知限制」#3） |
| `--skip-validation` | 跳过 URL 验证（保留全部抓到的频道） |
| `--skip-fetch` | 跳过抓取，直接读 `src/.cache/channels_raw.json`；无缓存则报错退出 |
| `--fetch-timeout FETCH_TIMEOUT` | 抓取阶段总超时秒数，默认 `90` |

## 输出文件

| 文件 | 内容 |
|---|---|
| `output/all_merged.m3u` | 全球列表，按固定分类顺序排列（顺序表见 `src/generator.py:15-52`），**每分组最多 100 条**，超限处有 `# ... and N more` 注释 |
| `output/hk_merged.m3u` | 港澳台列表（`is_hk_region()` 命中项），无条数上限 |
| `output/stats.json` | `{分组名: 频道数}`，**生成前的分组计数**，不等于 m3u 里的条目数 |

两个 m3u 都以 `#EXTM3U x-tvg-url=...` 开头，随后是 3 行 `#EXTVLCOPT`（`network-caching=1000` / `live-cache=1000` / `ttl=5`）、`#PLAYLIST:` 与 `# Total:` 注释行，再按分组输出 `#EXTGRP:<分类> (<条数>)` + `#EXTINF` + URL。

## 数据流

```
config/sources.yaml (20 源)
      │  src/fetcher.py      并发抓取 + 按 URL 去重（M3U / YAML 两种格式）
      ▼
   Channel[]
      │  src/validator.py    HEAD 请求（405 回退 GET）+ 代理域名拒绝 + CDN 白名单放行
      ▼
   Channel[]（有效）
      │  src/grouper.py      别名归一(config/alias.txt) + 繁简转换 + 同名合并 + 分类
      ▼
   {分组: Channel[]}
      │  src/generator.py    脏名过滤 → 港澳台切分 → 100/组截断 → 写 m3u
      ▼
output/all_merged.m3u · output/hk_merged.m3u · output/stats.json
```

模块职责、行数、每个模块的已知问题见 **[docs/architecture.md](docs/architecture.md)**。

## CI（定时任务）

`.github/workflows/update.yml` 用 `schedule: cron: "0 0 * * *"`（UTC 00:00 = 北京时间 08:00）在 GitHub Actions 上定时跑，Python 版本 `3.11`；已拆成 `check`（静态检查/类型/测试，`timeout-minutes: 10`）与 `update`（抓取 → 生成 → 产物体检 → 有变化才提交推送 → 上传 artifact，`timeout-minutes: 45`）两个 job，并显式声明了 `permissions` 与 `concurrency`。

CI 细节、超时预算、权限与失败通知的规范说明见 **[docs/ci.md](docs/ci.md)**；如两者冲突，**以仓库里的 workflow 文件为准**。

## 已知限制与缺陷

以下每条都有可复核证据（本机实测，或明确标注来源的报告实测）：

1. **每分组 100 条上限**（`src/generator.py:168`，设计内）。交付量与 `stats.json` 永久不一致。
2. **文件头部 `# Total:` 不是实际条数**：8,056 是「截断前、脏名过滤后」的数，文件里只有 1,164 条。
3. **`--skip-fetch` 在无缓存时必然失败**：`--no-cache` 分支（`src/main.py:67-79`）不调用 `cache.set()`，所以「先 `--no-cache` 抓取、再 `--skip-fetch` 生成」的两步流程读不到缓存。实测 `python -m src.main --skip-fetch` 在 `[Step 1/4]` 就中止。HEAD 版与工作区版行为一致。
4. **失败退出码（`871e32d` 已修）**：现在「运行失败」会写 stderr 并 `raise SystemExit(1)`（实测 `EXIT=1`）；`871e32d` 之前的版本（含数据提交 `074c677`）只 `print` 后 `return`，退出码 0，CI 会把失败当成功。校验：`git show 871e32d:src/main.py | grep -c SystemExit` → `1`。
5. **缓存目录位置不对**：`src/lib/cache.py:13` 用 `Path(__file__).parent.parent / ".cache"`，实际落在 `src/.cache`（实测打印该路径）；`.gitignore` 已补 `src/.cache/`（`7ff4be1`），但缓存路径本身仍然算错，缓存不会落到仓库根的 `.cache/`。
6. **验证器把异常当成「有效」**：`src/validator.py:27` 的 `if valid` 对 `asyncio.gather(return_exceptions=True)` 返回的异常对象恒为真。实测 `http://[::1/list.m3u8`（`urlparse` 抛 `ValueError`）仍被保留。
7. **`strip_noise` 删除所有内部空格**：`src/group/normalize.py:84` 把 `\s+` 替换成空串，实测 `strip_noise("TVB 翡翠台")` → `"TVB翡翠台"`，下游 `logo_map` 只能靠额外分支打补丁。
8. **分类与港澳台过滤判定不一致**：`categorizer.py` 里有若干双反斜杠正则（如 `\\bmacau\\b`，正则表达的是字面反斜杠 + `b`），实测 `re.search(r"\\bmacau\\b", "Macau TV", re.I)` → `None`；于是 `categorize("Macau TV")` = `🇲🇴 澳门` 而 `is_hk_region("Macau TV")` = `False`，该类频道不进 `hk_merged.m3u`。
9. **测试覆盖**：`3020583` 起仓库里有 `tests/`（7 个文件，`python -m pytest` → `283 passed, 23 xfailed`，1.4s）。此前 186 个历史提交里没有任何测试。那 23 个 xfail 是**刻意固化的已知缺陷**（`tests/test_known_defects.py`），修好后去掉标记即变成契约测试。
10. **可安装性**：`python -m src.main` 是唯一入口，**必须在仓库根目录执行**，否则 `ModuleNotFoundError: No module named 'src'`（包名就是 `src`）。`pyproject.toml`（`7ff4be1`）只声明 `requires-python = ">=3.11"` 与 ruff/mypy 配置，**有意不写 `[build-system]`**，所以仍然不能 `pip install -e .`（原因见该文件开头的注释）。
11. **分组很慢**：`categorizer.py` 里几百个正则都以字符串形式传给 `re.search`，`re` 的 512 条内部缓存被反复冲掉，时间主要花在重新编译正则上（本地审计报告 `audit-c-engineering.md` §3.4 的 cProfile 实测：1,379 频道 40.2s，预编译后 1.0s，约 40×。**该 40× 是那份报告的实测值，本文档更新时未复测**）。
12. **数字每天漂移**：同一份代码在不同日期产出量差别很大。仓库快照是 `stats 8,371 / all 1,164 / hk 33`；2026-10-29 我实测的一次全新运行（`--no-cache --skip-validation`，抓到手 16,901 频道、同名合并后 12,505）得到 `stats 12,505 / 53 组`、`all_merged` 1,378 条、`hk_merged` 58 条。**任何写死的数字都只是当日快照**，引用前请自己跑 `grep -c`。

## 免责声明

本项目只做「索引聚合」：所有频道 URL 来自公开第三方数据源，版权归各自广播者所有。仅供个人学习研究，请勿用于商业用途。数据源可用性、内容合法性由使用者自行判断。

[LICENSE](LICENSE)（MIT）只覆盖本仓库的**代码与文档**；`output/` 里播放列表中的频道 URL 及其内容、以及 `config/sources.yaml` 列出的各数据源，各有其自身条款，不在本许可证授权范围内。

## 数字核实

```bash
git remote -v                                            # 仓库真实地址
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
  https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/all_merged.m3u   # 200 257714
python3 -c "import json;print(sum(json.load(open('output/stats.json')).values()))"  # 8371
python3 -c "import json;print(len(json.load(open('output/stats.json'))))"           # 51
grep -c '^#EXTINF' output/all_merged.m3u                 # 1164
grep -c '^#EXTINF' output/hk_merged.m3u                  # 33
grep -c '^#EXTGRP' output/hk_merged.m3u                  # 7
grep -c '^# \.\.\. and' output/all_merged.m3u            # 9
head -6 output/all_merged.m3u | tail -1                  # # Total: 8056 channels, 51 categories
python3 -c "import yaml;d=yaml.safe_load(open('config/sources.yaml'));print(len(d['sources']))"  # 20
python -m src.main --help                                # 参数表
```
