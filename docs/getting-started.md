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

## 6. 常见问题

### 1) 为什么每个分组最多只有 100 条？

这是**设计内的体积上限**，不是抓取不全，也不是 bug：

```python
# src/generator.py:167-172
# ALL 播放列表每个分组最多 100 个
for ch in channels[:100]:
    ...
if len(channels) > 100:
    all_lines.append(f"# ... and {len(channels) - 100} more")
```

`all_merged.m3u` 里每个分组只写前 100 条，超出的部分用一行 `# ... and N more` 注释代替（播放器会忽略这行）。当前 `all_merged.m3u` 里有 9 个分组触发了上限，丢弃合计 6,892 条。

`hk_merged.m3u` **没有**这个上限（`src/generator.py:144-149` 是完整写出），所以港澳台列表是「全量」的——只是它本来就只收港澳台。

要改这个上限，改 `src/generator.py` 的 `[:100]`；那是行为变更，不在文档范围内。

### 2) 为什么 `stats.json` 加起来比文件里的条目多得多？

因为三个数记的是三个不同阶段：

| 阶段 | 数字（仓库快照） | 说明 |
|---|---:|---|
| 分组完成后写 `stats.json` | 8,371 | 生成文件**之前**的计数 |
| 写文件前过滤脏名（`is_clean_name`） | 8,056 | 8371 − 8056 = 315 条名字带 `Chrome/`、`Mozilla` 等浏览器残留的被丢掉；8056 只出现在文件第 6 行注释里 |
| 应用 100 条/组上限后真正写入 | **1,164** | 8056 − 6892 = 1164 |

一句话：`stats.json` 是「分组统计」，m3u 是「交付样本」。

### 3) 为什么港澳台列表只有几十个频道？

`hk_merged.m3u` 只收 `is_hk_region()` 判定为港澳台的频道（TVB / ViuTV / RTHK / HOY TV / Now TV / 台湾 / 澳门 等 7 个分组），不是全球列表的子集拷贝。它在历史提交里一直在几十的量级波动（本次实测 58 条，仓库快照 33 条），源站死掉几个就能掉一截。

另外有个已知缺陷会让它偏少：`categorizer.py` 里若干正则写成了双反斜杠（如 `\\bmacau\\b`），永远匹配不上，于是 `Macau TV` 这类英文名频道被分类成「🇲🇴 澳门」但 `is_hk_region()` 返回 `False`，进不了 hk 列表（实测见 `docs/architecture.md`）。

### 4) `--skip-fetch` 报「跳过抓取但无缓存数据，请先正常运行一次抓取」

因为 `--skip-fetch` 只读 `src/.cache/channels_raw.json`。两个坑：

- **`--no-cache` 那条路径不写缓存**（`src/main.py:67-79` 的 `else` 分支没有 `cache.set()`），所以「先 `--no-cache` 再 `--skip-fetch`」永远失败；
- 缓存 TTL 是 86400 秒（`src/lib/cache.py:11`），超过一天就失效。

正确用法：先不带 `--no-cache` 正常跑一次（这一步会写缓存），24 小时内再 `--skip-fetch`。

### 5) 为什么跑得这么慢？

瓶颈是「合并同名频道 + 分类」这一段：`categorizer.py` 里几百个正则都以**字符串**形式传给 `re.search`，`re` 的内部缓存只有 512 条，交替访问时被反复冲掉，于是时间几乎都花在重新编译正则上（本地审计报告 `audit-c-engineering.md` §3.4 有 cProfile 证据）。本机样例：1,379 个频道要 40 秒左右。

想快：等 `categorizer` 做正则预编译（该改造未落地）；现在能做的只有减少频道量或跳过验证。

### 6) 抓取阶段一堆源报错 / 返回 0 channels，正常吗？

正常，且每天都在变。本次实测：`sammy0101`、`xiweiwong-hk-iptv`（`raw.gh.registry.cyou` DNS 解析失败）和 `freetv-fun`（403）三个源重试 3 次后放弃；`free-tv-hk/tw/cn/jp/kr/us/uk` 七个源返回 0 条；真正贡献量的是 `iptv-org`（11,367 条）、`CCSH-iptv`（2,819 条）、`suxuang-myIPTV`（1,211 条）、`gitee-why006-TV`（1,160 条）。

源全挂时会怎样：`stats.json` 会变成很小的数字或空对象，产物基本没内容。这种「静默产出空文件」由 CI 的 `scripts/check_output.py` 兜底（频道总数 < 3000 或港澳台为 0 就非零退出），本地跑没有这层保护。

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

```bash
cd live-tv

# 数据源数量（20 个，全部 enabled）
python3 -c "import yaml;d=yaml.safe_load(open('config/sources.yaml'));print(len(d['sources']))"

# 三个口径的频道数
python3 -c "import json;print(sum(json.load(open('output/stats.json')).values()))"   # 8371
python3 -c "import json;print(len(json.load(open('output/stats.json'))))"            # 51
grep -c '^#EXTINF' output/all_merged.m3u      # 1164
grep -c '^#EXTINF' output/hk_merged.m3u       # 33
grep -c '^#EXTGRP' output/hk_merged.m3u       # 7
head -6 output/all_merged.m3u | tail -1       # # Total: 8056 channels, 51 categories

# 100/组上限的证据
grep -c '^# \.\.\. and' output/all_merged.m3u                     # 9 个分组超限
grep '^# \.\.\. and' output/all_merged.m3u | sed 's/[^0-9]//g'    # 293 427 562 581 246 869 172 168 3574，合计 6892

# 代码事实
python -m src.main --help
grep -n 'channels\[:100\]' src/generator.py
wc -l src/*.py src/group/*.py src/lib/*.py
```
