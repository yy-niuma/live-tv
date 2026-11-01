# 本地从零跑通

> 本文引用的 `audit-c-engineering.md` 是只读审计产出，**不入库**（见 `.gitignore`），只存在于本地磁盘。

目标：在一台干净机器上把 `live-tv` 跑通一次，看懂 `output/` 里三个文件，并能自己复算文档里的每个数字。

> 本文的命令与数字都在 2026-10-29 实跑验证过（Python 3.14.4 的 `.venv`，产物快照 = 数据提交 `074c677`）。**抓取结果每天不同**，你跑出来的频道数不会和下面一样，这正常；但「三个文件的条数关系」在任何一天都成立。

---

## 1. 前置条件

| 项 | 要求 | 依据 |
|---|---|---|
| Python | **>= 3.11** | `pyproject.toml` 的 `requires-python = ">=3.11"`（提交 `7ff4be1` 入库）；本机实测可用：3.11.15、3.13.5、3.14.4 |
| 网络 | 能直连外网 | 要访问 `config/sources.yaml` 里的 20 个数据源 + `epg.pw` 的 EPG |
| 依赖 | `requirements.txt` | `aiohttp`、`pyyaml` 等 11 个精确 pin（`==`）的包（提交 `7ff4be1`） |
| 磁盘 | 几十 MB | 一次完整运行的产物在 300 KB 量级 |

不需要数据库、不需要 API key、不需要任何账号。

## 2. 取代码

```bash
git clone https://github.com/yy-niuma/live-tv.git
cd live-tv
```

`cd` 这一步是硬要求：包名就叫 `src`，`python -m src.main` **只在仓库根目录可用**。在别处执行会得到：

```
Error while finding module specification for 'src.main' (ModuleNotFoundError: No module named 'src')
```

## 3. 装依赖

```bash
python3 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

确认装上了：

```bash
python -c "import aiohttp, yaml; print(aiohttp.__version__)"
```

## 4. 跑一次（先跑快的那个）

完整流程是四步：**抓取 → 验证 → 分组 → 生成**。验证阶段要对上万个 URL 逐个发 HEAD 请求，是最慢的一步；第一次跑建议先跳过它，确认整条链路通：

```bash
python -m src.main --no-cache --skip-validation --fetch-timeout 300 --output ./output
```

本机实测（`--no-cache --skip-validation`，用时约 4 分钟：抓取阶段在启动后一分钟内结束，剩下时间全在「合并同名频道 + 分类」）：

```
[Step 1/4] 抓取频道...
  开始抓取 20 个数据源（超时 300s）...
  → 正在抓取: sammy0101 ...
  ...
[Fetcher] sammy0101 attempt 3 failed: Cannot connect to host raw.gh.registry.cyou:443 ssl:default [No address associated with hostname]
[Fetcher] freetv-fun attempt 3 failed: 403, message='Forbidden', url='https://t.freetv.fun/m3u/playlist.m3u'
  ✓ 抓取完成: 共 16901 个频道

[Step 2/4] 验证 URL...
  ⚠ 跳过验证（--skip-validation）

[Step 3/4] 分组频道...
[Grouper] 开始分组，共 16901 个频道
[Grouper] 合并同名频道...
[Grouper] 合并后剩余 12505 个频道
[Grouper] 分组完成，共 53 个分组
  Top 5 分组:
    - 🌐 国际: 6101 个频道
    - 🎭 综艺频道: 1279 个频道

[Step 4/4] 生成播放列表...
  ✓ 港澳台: 58 频道, 10 分组
  ✓ 全球: 11928 频道, 53 分组
  ✓ 统计已保存: .../output/stats.json
```

再跑「完整版」（含验证，慢）：

```bash
python -m src.main --no-cache --fetch-timeout 300 --output ./output
```

其它常用组合：

```bash
python -m src.main --help                      # 看全部参数
python -m src.main --output /tmp/iptv          # 产物写到别处，不动仓库里的 output/
python -m src.main --skip-fetch                 # 有缓存时跳过抓取（见下面 FAQ #4）
```

## 5. 看产物

```bash
ls -l output/
# all_merged.m3u  hk_merged.m3u  stats.json

head -6 output/all_merged.m3u
# #EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"
# #EXTVLCOPT:network-caching=1000
# #EXTVLCOPT:live-cache=1000
# #EXTVLCOPT:ttl=5
# #PLAYLIST:All IPTV 2026-10-29
# # Total: 8056 channels, 51 categories      ← 注意：这不是文件里的真实条数！

grep -c '^#EXTINF' output/all_merged.m3u     # 仓库快照: 1164
grep -c '^#EXTINF' output/hk_merged.m3u      # 仓库快照: 33
python3 -c "import json;d=json.load(open('output/stats.json'));print(len(d), sum(d.values()))"
# 51 8371
```

我用同一份代码在 2026-10-29 全新跑出来的三个数字是 `12505`（stats 求和）/ `1378`（all_merged 条数）/ `58`（hk_merged 条数）——和仓库快照的 `8371 / 1164 / 33` 完全不同，因为当天抓到的源不一样。**所以不要相信任何写死的数字，包括这份文档。**

用播放器验证：把 `output/all_merged.m3u` 直接拖进 VLC（媒体 → 打开文件），能出列表即产物格式正确。

## 6. 命令行参数

`python -m src.main --help` 共 11 项（含 `-h`），即 10 个功能选项 —— 下表按 `--help` 的顺序：

| 参数 | 说明 |
|---|---|
| `--config, -c CONFIG` | 配置文件目录 |
| `--output, -o OUTPUT` | 输出目录 |
| `--no-cache` | 禁用缓存（注意：这条路径**不写**缓存，见 [known-issues.md](known-issues.md) §3） |
| `--skip-validation` | 跳过 URL 验证（保留全部抓到的频道） |
| `--valid-urls-file PATH` | 从该 JSON 文件读取已验证有效的 URL 列表并跳过验证 —— **CI 分片合并用**，本地别用 |
| `--skip-fetch` | 跳过抓取，使用缓存数据；无缓存则报错退出 |
| `--health-file PATH` | 实测可播快照 `{url: bool}`（`check_streams.py --health-out` 的产物）；不传则读 `config/stream_health.json`（若存在）。机制见 [stream-health.md](stream-health.md) |
| `--fetch-timeout SECOND` | 抓取超时秒数，默认 `90` |
| `--validate-concurrency N` | 验证阶段并发数，默认 `80`。实测 20~150 全部档位可用条数持平、不掉条，80 最快；再往上可能被源站限流。见 [ci.md](ci.md) §7 |
| `--validate-timeout N` | 验证阶段单条超时秒数，默认 `10`。实测调到 8/5 会把慢但仍可用的链路判死（可用条数 296→293/291），**不建议调低** |

## 7. 常见问题

### 1) 为什么每个分组最多只有 100 条？

这是**设计内的体积上限**，不是抓取不全，也不是 bug：

```python
# src/generator.py:181-186
# ALL 播放列表每个分组最多 100 个
for ch in channels[:100]:
    ...
if len(channels) > 100:
    all_lines.append(f"# ... and {len(channels) - 100} more")
```

`all_merged.m3u` 里每个分组只写前 100 条，超出的部分用一行 `# ... and N more` 注释代替（播放器会忽略这行）。当前 `all_merged.m3u` 里有 **9 个分组**触发了上限，丢弃合计 **7,956 条**（各分组丢弃数：213 / 589 / 482 / 4,250 / 638 / 312 / 1,040 / 228 / 204）。

`hk_merged.m3u` **没有**这个上限（`src/generator.py:131-141` 是完整写出，无 `[:100]`），所以港澳台列表是「全量」的——只是它本来就只收港澳台。

要改这个上限，改 `src/generator.py` 的 `[:100]`；那是行为变更，不在文档范围内。

### 2) 为什么 `stats.json` 加起来比文件里的条目多得多？

因为三个数记的是三个不同阶段。以远端最新产物（2026-11-01）为例：

| 阶段 | 数字 | 说明 |
|---|---:|---|
| 分组完成后写 `stats.json` | 9,340 | 生成文件**之前**的计数（`src/main.py:249`） |
| 写文件前过滤脏名（`is_clean_name`） | 9,337 | 9,340 − 9,337 = **仅 3 条**名字带 `Chrome/`、`Mozilla` 等浏览器残留的被丢掉；9,337 只出现在文件第 6 行 `# Total:` 注释里（`src/generator.py:308/360`） |
| 应用 100 条/组上限后真正写入 | **1,381** | 9,337 − 7,956 = 1,381 |

**自洽校验**：`1,381 + 7,956 = 9,337` ✅ 正好等于 `# Total:` 行。

> 脏名过滤的收益从早期的 315 条掉到 3 条，是因为抓取/归一层的清理改好了 —— 不是过滤失效。
> 具体每天变，公式不变：`stats 求和 − Total = 脏名丢弃数`，`Total − 实际 EXTINF = 100/组丢弃数`。

一句话：`stats.json` 是「分组统计」，m3u 是「交付样本」。

### 3) 为什么港澳台列表只有几十个频道？

`hk_merged.m3u` 只收 `is_hk_region()` 判定为港澳台的频道，不是全球列表的子集拷贝。它在历史提交里一直在几十到一百多的量级波动（当前仓库快照 **78 条 / 10 分组**），源站死掉几个就能掉一截。

**这个数在 2026-10-29 的分组逻辑重构后明显变大了**：原先 `is_hk_region()` 与 `categorize()` 各维护一份港澳台关键词表，且前者有几条正则写成双反斜杠（`\\bmacau\\b`）永不命中，导致 `Macau TV` / `TTV` / `PTS` / `CNA 中央社` / `非凡商业台` / `东森财经新闻` / `港台电视31` 被判成港澳台却进不了 hk 列表。现在两者共用 `HK_TW_MO_RULES`，实测同一天两次全新运行：`hk_merged` 从 **58 条 / 7 分组** 变成 **107 条 / 9 分组**（13,470 条语料上 `is_hk_region()` 覆盖 92 → 145，丢失 0 条）。

（历史备注：重构当天仓库里的 `output/hk_merged.m3u` 还是重构前的 33 条，现在已由每日 CI 产出 **78 条 / 10 分组**。）

### 4) `--skip-fetch` 报「跳过抓取但无缓存数据，请先正常运行一次抓取」

因为 `--skip-fetch` 只读 `src/.cache/channels_raw.json`。两个坑：

- **`--no-cache` 那条路径不写缓存**（`src/main.py:67-79` 的 `else` 分支没有 `cache.set()`），所以「先 `--no-cache` 再 `--skip-fetch`」永远失败；
- 缓存 TTL 是 86400 秒（`src/lib/cache.py:11`），超过一天就失效。

正确用法：先不带 `--no-cache` 正常跑一次（这一步会写缓存），24 小时内再 `--skip-fetch`。

### 5) 为什么跑得这么慢？

先分清两段：**验证阶段**（逐条探测上万个 URL）占整个跑批 95% 以上，是纯网络等待；
**分组阶段**只占几秒。真正的瓶颈是验证，不是分类。

分组侧的历史说法需要更正。`categorizer.py` 里几百个正则确实以**字符串**形式传给 `re.search`
（未预编译），审计报告 `audit-c-engineering.md` §3.4 据此测出「1,379 频道 40.2s，预编译后 1.0s」。
但 2026-11-02 用 `scripts/categorize_dataset/current_snapshot.tsv`（1,164 条真实频道名）复测：

```console
$ # 归一 + 分类，连跑两遍
真实语料 1,164 条: 0.82s → 1,413 条/s     # 换算 19,500 条 ≈ 13.8s
第二遍（re 缓存已热）: 0.82s → 1,412 条/s  # 速度完全相同
```

**第二遍没有变快**，说明 `re` 的 512 条内部缓存被冲掉**不是**当前瓶颈 ——
审计报告那个 40× 是旧代码的数字，现已不复现。CI 日志里「分组 5.4s / 19,547 条」也印证同一量级。

> 局限：复测用的是 1,164 条快照（原 13,470 条的 `corpus.tsv` 已不在仓库里），
> 样本量小于报告口径。要下定论请用完整语料复测。

想更快：把正则预编译成 `re.Pattern` 仍是好实践（收益已不是 40×），
以及跳过验证（`--skip-validation`）—— 后者才是量级差别。

### 6) 抓取阶段一堆源报错 / 返回 0 channels，正常吗？

**大部分不再是正常现象 —— 这曾经是个真 bug，已修。** 2026-10-29 逐源体检发现 20 个源里
**11 个产出 0 条**，而总量仍有 18,285 条、`exit=0`、产物照常生成（看总量和退出码完全发现不了）。
根因是 8 个 markdown 表格源被当成 m3u 解析、2 个指向已死的 GitHub 代理、1 个源站停服。
修完后现在按**内容嗅探**格式（不再按扩展名），0 条会打 WARNING。

当前实测（2026-11-02，`scripts/check_sources.py`）：**30 个启用源全部有产出，合计 22,215 条**。
贡献量最大的：`iptv-org` 11,374 / `CCSH-iptv` 2,414 / `free-tv-all` 2,043 / `suxuang-myIPTV` 1,211 /
`gitee-why006-TV` 1,160 / `epg-pw` 1,125。

所以现在的口径是：**源站波动是常态（单个源某天 0 条、超时都正常），但「整批 0 产出」不是。**
排查顺序：先跑 `scripts/check_sources.py` 看是哪个源，再看它是不是格式变更或域名失效。
全过程见 [source-health.md](source-health.md)。

源全挂时会怎样：`stats.json` 会变成很小的数字或空对象，产物基本没内容。这种「静默产出空文件」
由 CI 的 `scripts/check_output.py` 兜底，它有 5 类断言（不是只比一个总数）：

| 常量 | 值 | 检查什么 |
|---|---:|---|
| `MIN_TOTAL_CHANNELS` | 3,000 | `stats.json` 频道总数下限 |
| `MIN_TOTAL_EXTINF` | 1,000 | `all_merged.m3u` 实际 EXTINF 行数下限 |
| `MIN_HK_CHANNELS` | 20 | `hk_merged.m3u` 实际 EXTINF 行数下限 |

另有分组覆盖、`#EXTGRP` 分段数与 `min(K,100)` 一致性等断言。本地跑**没有**这层保护。

### 7) 跑完多了个 `src/.cache/` 目录，要提交吗？

不要。它是缓存：`src/lib/cache.py:13` 用 `Path(__file__).parent.parent / ".cache"`，因为 `cache.py` 在 `src/lib/` 下，`parent.parent` 正好是 `src/`（这是已知的路径 bug，正确位置应是仓库根 `.cache/`）。`.gitignore` 里没有 `.cache`，所以它会显示为未跟踪文件。删掉即可，下次运行会重建：

```bash
rm -rf src/.cache
```

### 8) 程序说「运行失败」，退出码是几？

`871e32d` 起是 **1**（失败会写 stderr 并 `raise SystemExit(1)`），CI 能感知；`871e32d` 之前的版本只 `print` 后 `return`，退出码 0，CI 会把失败当成功。自己校验：

```bash
git show 871e32d:src/main.py | grep -c SystemExit   # 1
python -m src.main --skip-fetch; echo "EXIT=$?"      # 无缓存时 EXIT=1
```

### 9) 能把产物写到别处、不污染仓库吗？

可以，`--output` / `-o` 就是干这个的：

```bash
python -m src.main --skip-validation --output /tmp/iptv-out
```

注意缓存目录不受 `--output` 影响，仍会落在 `src/.cache/`。

---

## 附录：本文数字的核实命令

> 下面的「期望值」是 **2026-11-01 远端产物**的实测结果，会随源站存活情况漂移。
> 复核时先 `git fetch` 再跑，数字不同不代表命令写错。

```bash
cd live-tv
git fetch origin -q

# 数据源数量（配置 32 个 / 启用 30 个 / 停用 2 个）
python3 -c "
import yaml; d=yaml.safe_load(open('config/sources.yaml')); s=d['sources']
print(len(s), len([x for x in s if x.get('enabled', True)]))"      # 32 30

# 三个口径的频道数（用远端最新提交，避免本地产物过期）
git show origin/main:output/stats.json > /tmp/stats.json
python3 -c "import json;d=json.load(open('/tmp/stats.json'));print(sum(d.values()))"  # 9340
python3 -c "import json;print(len(json.load(open('/tmp/stats.json'))))"              # 52

git show origin/main:output/all_merged.m3u > /tmp/all.m3u
git show origin/main:output/hk_merged.m3u  > /tmp/hk.m3u
grep -c '^#EXTINF' /tmp/all.m3u     # 1381  ← 实际交付条数
grep -c '^#EXTINF' /tmp/hk.m3u      # 78
grep -c '^#EXTGRP' /tmp/hk.m3u      # 10
head -6 /tmp/all.m3u | tail -1      # # Total: 9337 channels, 52 categories

# 口径自洽验证：Total = 实际条数 + 被 100/组上限丢弃的条数
grep -c '^# \.\.\. and' /tmp/all.m3u                                # 9 个分组超限
grep '^# \.\.\. and' /tmp/all.m3u | sed 's/[^0-9]//g' | tr '\n' ' '  # 213 589 482 4250 638 312 1040 228 204
grep '^# \.\.\. and' /tmp/all.m3u | sed 's/[^0-9]//g' | awk '{s+=$1} END {print s}'
# 7956   →   1381 + 7956 = 9337 ✅ 与 # Total: 行一致

# 代码事实
python -m src.main --help
grep -n 'channels\[:100\]' src/generator.py
wc -l src/*.py src/group/*.py src/lib/*.py
```
