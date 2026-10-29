# live-tv · IPTV 直播源聚合

从 `config/sources.yaml` 配置的数据源（当前 **20 个，全部 enabled**）抓取 M3U / YAML 直播源，按 URL 去重、繁简归一、按频道名分类分组，最后生成两个 M3U 播放列表。

- 仓库：<https://github.com/yy-niuma/live-tv>
- 入口：`python -m src.main`（必须在**仓库根目录**执行，见「已知限制」#10）
- 授权：仓库内 [LICENSE](LICENSE) 为 MIT。**但这是 2026-10-29 补齐时新建的** ——
  在此之前全仓零许可证线索（无 `LICENSE`/`COPYING`/`NOTICE` 文件、`pyproject.toml` 无 `license` 字段、
  无 `setup.py`/`setup.cfg`、源码无 `SPDX`/`Copyright` 头、`git log --grep=licen` 无相关提交）。
  **著作权人与许可证选择须由 owner 确认**；若 owner 选别的许可证，直接替换该文件即可。

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
   # src/generator.py:181-186
   # ALL 播放列表每个分组最多 100 个
   for ch in channels[:100]:
       ...
   if len(channels) > 100:
       all_lines.append(f"# ... and {len(channels) - 100} more")
   ```

   当前有 9 个分组超过 100 条，被丢弃 6,892 条，于是文件里留下 9 行 `# ... and N more`（293 + 427 + 562 + 581 + 246 + 869 + 172 + 168 + **3574** = 6,892）。

4. **33** = `hk_merged.m3u` **没有** 100 条上限（`src/generator.py:131-141` 是完整写出），它只收 `is_hk_region()` 判定为港澳台的子集，所以量级完全不同。

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

> 验证阶段是纯网络等待（并发 20、单条超时 10 秒），逐条 HEAD 请求上万个 URL，是整条流水线最慢的一步；只想看产物结构时加 `--skip-validation`。本机实测一次 `--no-cache --skip-validation` 的完整运行：启动 10:50、产物写入 10:54，约 4 分钟；抓取阶段（20 源并发，含 3 个失败源各重试 3 次）在启动后一分钟内结束，时间几乎全花在「合并同名频道 + 分类」上。验证阶段耗时随远端响应变化很大，审计报告 `audit-c-engineering.md` §2.6 有按吞吐外推的实测表（本文未复测该阶段）。

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
| `output/all_merged.m3u` | 全球列表，按固定分类顺序排列（顺序表见 `src/generator.py:19-63`），**每分组最多 100 条**，超限处有 `# ... and N more` 注释 |
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

## 分组逻辑

分组 = `src/group/categorizer.py` 的 `categorize(name, group)`，港澳台切分 = 同文件的 `is_hk_region()`。
**2026-10-29 做过一次重构**，两者改为共用同一套 `HK_TW_MO_RULES` / `_region_category()`，不再各维护一份关键词表。

### 重构前后对比（可复现）

评测集 `scripts/categorize_dataset/`（`known_bugs.tsv` 24 条已知错判 + `known_good.tsv` 27 条不能退化的正确判定）：

```
python scripts/eval_categorize.py
# 重构前：known_bugs 5/24，known_good 27/27，合计 32/51 → RESULT: FAIL
# 重构后：known_bugs 23/24，known_good 27/27，合计 50/51 → 剩 1 条已知残留
```

同一份 **13,470 条真实频道名语料**上跑 `is_hk_region()`，重构前后：

| 指标 | 重构前 | 重构后 |
|---|---:|---:|
| `is_hk_region()` 判为港澳台的频道数 | 92 | **141**（丢失 0 条，新增 49 条） |
| `categorize()` 产出的分组数 | 50 | 51 |
| `📡 卫视频道` 桶大小 | 603 | **37** |
| `🇨🇳 中国源` 桶大小 | 0（该组不存在） | 272 |

`📡 卫视频道` 从 603 掉到 37 是最大的单点收益：原规则里有个**没有词边界**的 `r"atv"`，把 `AricaTV` / `BarazaTV` / `AndorraTV` / `AgriculturaTV` 这类西语、葡语、意语频道全吸进了「卫视频道」（实测 98/1,164 = 8.4% 的产物条目受影响）。现在改成 `\batv\b`。

同批修掉的裸子串还有 `tv5` / `tbs` / `dw` / `nick` / `amc`（`XinjiangTV5` 曾被 `tv5` 抢进「国际频道」）。**刻意没加词边界的**：`movie` / `cinema` / `kids` / `影视` / `影城` —— 这些是内容词，加边界会丢真命中。

### 端到端产物变化（同一天两次全新运行，`--no-cache --skip-validation`）

| 产物 | 重构前 | 重构后 |
|---|---:|---:|
| 抓取到手 | 16,901 | 16,994 |
| 同名合并后 | 12,505 | 12,578 |
| `stats.json` 求和 | 12,505 | 12,578 |
| `all_merged.m3u` 的 `#EXTINF` | 1,378 | **1,702** |
| `hk_merged.m3u` 的 `#EXTINF` | 58 | **103** |
| `hk_merged.m3u` 分组数 | 7 | 9 |

`hk_merged` 从 58 涨到 103（+78%）就是港台判定修好的直接结果：原先 `Macau TV` / `TTV` / `PTS` / `CNA 中央社` / `非凡商业台` / `东森财经新闻` / `港台电视31` 这些被判成港澳台却进不了港澳台列表。

> **产物快照警示**：仓库里现有的 `output/` 是**重构前**的分类器生成的（数据提交 `074c677`），所以本文前面引用的 `8,371 / 8,056 / 1,164 / 33` 都还是旧分布。下一次 CI 定时任务跑完后分组分布会变，届时的 `#EXTINF` 条数也会变。**不要拿旧快照对照新代码判断对错。**

缺陷清单见 [`docs/categorize-bug-analysis.md`](docs/categorize-bug-analysis.md)，重构方案、残留问题与后续 TODO 见 [`docs/categorize-improvement-proposal.md`](docs/categorize-improvement-proposal.md)。

### 第二遍修正：`\b` 在 CJK / 数字边界失效（同类缺陷的批量清理）

重构第一版把 `\bxxx\b` 当作词边界通解，但 **Python 的 `\w` 含 CJK，所以 `\b` 在「拉丁字母 + 中文」和「字母 + 数字」之间不成立**。
重构里已经为央视用了 `(?![a-z])` 而不是 `\b`，却没把这个结论推广到其他分支，于是留下同一类缺陷。

实测方式：从 `corpus.tsv`（13,470 条真实频道）里筛出「含 target 但 `\b` 尾部断言失败」的条目。

| target | 被 `\b` 击落 | 真实频道样例 | 处理 |
|---|---:|---|---|
| `hoy` | 3 | `HOY资讯台` / `HOY78` / `HOYInfotainment` | ✅ 改 `(?<![a-z])hoy` |
| `pts` | 1 | `PTS3`（公视 3 台） | ✅ 改 `(?<![a-z])pts(?![a-z])` |
| `trt` | 3 | `TRT1` / `TRT2` / `TRT3` | ✅ 改 `(?<![a-z])trt(?![a-z])` |
| `ttv` / `ftv` / `cna` | 各 0~3 | `TTVNews` / `FTVNews` / `CNAInternational` | 改了正则，但语料里这几条仍被更早分支命中，**实测 0 变动** |
| `cnn` / `voa` | 2 / 1 | `A2CNN` / `VOA美国之音` | 改了正则，**实测 0 变动**（均被更早分支吃掉） |
| `atv` / `tv5` / `now` / `nhk` / `dw` | 7 / 19 / 10 / 5 / 6 | `ATVAlanya`（土耳其台）/ `TV52` / `Now14` / `NHKWorld` / `DWEnglish` | ❌ **不动**：改宽会把土耳其 ATV、阿尔巴尼亚 TV52、印度 Now 误收 |

第二遍改动前后对比（`HEAD` vs 工作区，同一份 13,470 条语料）：

```
总变动 7 条 / 13470
  🌐 国际      -> 📺 HOY TV     3   (HOY78 / HOYInfotainment / HOY资讯台)
  🌐 国际      -> 🇹🇼 台湾        1   (PTS3)
  🌐 国际      -> 🌐 国际频道     3   (TRT1 / TRT2 / TRT3，从兜底进宽桶)

hk 覆盖：141 -> 145，丢失 0，新增 4
```

`HOYInfotainment` / `PTS3` / `TRT1-3` 都从 `🌐 国际` 兜底桶里被捞了出来，且**没有一条被打到别处**。
`iHOY爱历史`（历史纪录片频道，名字带 hoy 但不是 HOY TV）被前置否定 `(?<![a-z])` 正确挡在外面，已加负向测试钉住。

### MTV 副作用（实测，接受不修）

重构把音乐桶的裸 `mtv` 换成 `\bmtv(?![a-z])`。实测 189 条含 `mtv` 的频道里：

- `🎵 音乐频道` 31 条 —— `MTV` / `MTVLive` / `MTVRocks` 之外的真音乐台
- `🎭 综艺频道` 55 条 —— 主要是 **group 字段本身就是 `Entertainment`** 的 MTV 真人秀（`MTVCatfish` / `MTVTeenMom` / `MTVRidiculousness` / `MTVTheHills` / `MTVJerseyShore` / `MTVDating`）
- `🌐 国际` 88 条 —— 绝大多数根本不是 MTV，是 `GEMTV` / `MetaFilmTV` / `AdriftTV` 这类名字里恰好含 `mtv` 的地方台，**边界修复正是为了把它们赶出去**

判断：55 条落综艺里，真人秀落综艺在语义上是对的；只有 `MTVRocks` / `MTVCLASSICS` 这两类纯音乐台落综艺是遗憾，
但它们的数据源 group 就是 `Entertainment`，跟随 group 是既定策略。**这里不做名字级特例**，登记为已知取舍。

**已知残留**（如实登记，未修）：
- `DetetivesMedicos` 仍判 `🌐 国际`，期望 `📺 纪录片`（评测集里唯一不达标项，脚本因此退出码 1）。
- `ATV`（亚洲电视，香港）分类为 `📡 卫视频道` 且 `is_hk_region('ATV')=False` → 不进 `hk_merged.m3u`。
- ~~`HOY资讯台` 被判 `🌐 国际`~~ —— **已修**，但这条要单独记：它本来**不是**既有缺陷，
  是本次重构用 `r"\bhoy\b"` 引入的**新回归**（`\b` 在 CJK / 数字边界不成立，Python 的 `\w` 含 CJK，
  于是 `HOY资讯台` / `HOY78` / `HOYInfotainment` 三个真频道一起漏掉）。改回 `r"(?<![a-z])hoy"` 后三条全部恢复，
  `iHOY爱历史`（历史纪录片频道）仍正确排除。细节见下方「分组逻辑」里的更正说明。
- `CNNInternational`（无空格连写）落 `🌐 国际频道`，而 `CNN International`（带空格）落 `📰 新闻财经`。
  新闻块**有** `cnn` 规则，所以不是「只覆盖 BBC」；实测把 `\bcnn\b` 改成 `(?<![a-z])cnn(?![a-z])` 后
  连写形态**仍然**落 `🌐 国际频道`，说明它更早被「国际频道」宽桶命中（很可能 `international` 关键词）。
  **确切分支未定位，未修**。

## 已知限制与缺陷

以下每条都有可复核证据（本机实测，或明确标注来源的报告实测）：

1. **每分组 100 条上限**（`src/generator.py:182`，设计内）。交付量与 `stats.json` 永久不一致。
2. **文件头部 `# Total:` 不是实际条数**：8,056 是「截断前、脏名过滤后」的数，文件里只有 1,164 条。
3. **`--skip-fetch` 在无缓存时必然失败**：`--no-cache` 分支（`src/main.py:67-79`）不调用 `cache.set()`，所以「先 `--no-cache` 抓取、再 `--skip-fetch` 生成」的两步流程读不到缓存。实测 `python -m src.main --skip-fetch` 在 `[Step 1/4]` 就中止。HEAD 版与工作区版行为一致。
4. **失败退出码（`871e32d` 已修）**：现在「运行失败」会写 stderr 并 `raise SystemExit(1)`（实测 `EXIT=1`）；`871e32d` 之前的版本（含数据提交 `074c677`）只 `print` 后 `return`，退出码 0，CI 会把失败当成功。校验：`git show 871e32d:src/main.py | grep -c SystemExit` → `1`。
5. **缓存目录位置不对**：`src/lib/cache.py:13` 用 `Path(__file__).parent.parent / ".cache"`，实际落在 `src/.cache`（实测打印该路径）；`.gitignore` 已补 `src/.cache/`（`7ff4be1`），但缓存路径本身仍然算错，缓存不会落到仓库根的 `.cache/`。
6. **验证器把异常当成「有效」**：`src/validator.py:27` 的 `if valid` 对 `asyncio.gather(return_exceptions=True)` 返回的异常对象恒为真。实测 `http://[::1/list.m3u8`（`urlparse` 抛 `ValueError`）仍被保留。
7. **`strip_noise` 删除所有内部空格**：`src/group/normalize.py:84` 把 `\s+` 替换成空串，实测 `strip_noise("TVB 翡翠台")` → `"TVB翡翠台"`，下游 `logo_map` 只能靠额外分支打补丁。
8. ~~**分类与港澳台过滤判定不一致**~~ —— **已在 2026-10-29 的分组逻辑重构中修复**。原缺陷是 `categorizer.py` 的 `hk_exact`/`tw_exact`/`mo_exact` 三张表与 `categorize()` 各自维护一套关键词，其中若干正则写成双反斜杠（如 `\\bmacau\\b`，实际匹配字面反斜杠 + `b`）永不命中，于是 `categorize("Macau TV")` = `🇲🇴 澳门` 而 `is_hk_region("Macau TV")` = `False`。现在两者共用同一套 `HK_TW_MO_RULES` + `_region_category()`，实测 `is_hk_region("Macau TV")` → `True`、`is_hk_region("TTV")` → `True`。**残留**：`is_hk_region()` 的 `cat` 参数仍可绕过地区判定，调用方需保持一致（`src/generator.py:136` 已按生产路径传入 `cat`）。
9. **测试覆盖**：`3020583` 起仓库里有 `tests/`（7 个文件）。分组逻辑重构后 `python -m pytest` → **`305 passed, 7 xfailed`**（合计 312 例，0.9s）；重构前是 `283 passed, 23 xfailed` —— 差额主要是本次真正修好的缺陷（xfail 守卫按 `strict=True` 报 XPASS，删掉标记后转为正向回归测试）。此前 189 个历史提交里没有任何测试（`git rev-list --count 3020583^` → 189）。剩下 7 个 xfail 是**刻意固化的、仍然坏着的**已知缺陷（`tests/test_known_defects.py`），修好后去掉标记即变成契约测试。
10. **可安装性**：`python -m src.main` 是唯一入口，**必须在仓库根目录执行**，否则 `ModuleNotFoundError: No module named 'src'`（包名就是 `src`）。`pyproject.toml`（`7ff4be1`）只声明 `requires-python = ">=3.11"` 与 ruff/mypy 配置，**有意不写 `[build-system]`**，所以仍然不能 `pip install -e .`（原因见该文件开头的注释）。
11. **分组很慢**：`categorizer.py` 里几百个正则都以字符串形式传给 `re.search`，`re` 的 512 条内部缓存被反复冲掉，时间主要花在重新编译正则上（审计报告 `audit-c-engineering.md` §3.4 的 cProfile 实测：1,379 频道 40.2s，预编译后 1.0s，约 40×。**该 40× 是那份报告的实测值，本文档更新时未复测**）。
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
python -m src.main --help                                # 参数表（6 个选项）
.venv/bin/python -m ruff check src scripts               # All checks passed!
.venv/bin/python -m pytest                              # 305 passed, 7 xfailed
.venv/bin/python scripts/eval_categorize.py             # 50/51（退出码 1，见下）
```

`scripts/eval_categorize.py` 的退出码语义是「全部达标才 0」，当前有 1 条已知残留
（`DetetivesMedicos`），所以它**故意**退出 1；这个脚本没有接进 CI，接进去之前要么先修掉
那条残留、要么加个 `--allow-known-residuals` 开关。
