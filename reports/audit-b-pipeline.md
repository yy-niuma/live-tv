# 数据管道健壮性审计报告

- 审计对象：`/home/hermes/.hermes/projects/live-tv`（commit `f75575a`，2026-10-28）
- 范围：`src/fetcher.py`、`src/validator.py`、`src/generator.py`、`src/main.py`、`src/lib/cache.py`、`src/lib/whitelist.py`、`src/config.py`、`config/sources.yaml`、`config/proxy.txt`、`.github/workflows/update.yml`
- 方式：只读审计 + 在副本 `/home/hermes/.hermes/cache/scratch/ltv/` 内做破坏性实验（原仓库 src/ 未改动、未 commit/push）
- 环境：venv Python 3.14.4 / aiohttp 3.14.5（CI 用 3.11）

---

## 一、实测行为（跑一次的真实输出/耗时/频道数变化）

### 1.1 基线：完整抓取 + 跳过验证（21 个真实源）

```
$ .venv/bin/python -u -m src.main --skip-validation -o /tmp/out-r1
real 3m43.936s   user 1m37.428s   EXIT=0
  ✓ 抓取完成: 共 16859 个频道
  ✓ 分组完成: 共 53 个分组
  ✓ 港澳台: 58 频道, 10 分组
  ✓ 全球: 11931 频道, 53 分组
```

阶段耗时（同一份缓存，单独计时）：

| 阶段 | 耗时 | 产出 |
|---|---|---|
| 构造 Channel（16859 条） | 0.04s | — |
| `Grouper.group()` | **150.1s** | 16859 → 12469，53 组 |
| `Generator.generate_hk_and_all()` | 2.6s | all/hk 两个 m3u |
| 抓取 20 源 + 写 6MB 缓存 | ≈70s（总时长减其余阶段） | 16859 条去重后频道 |

**生成结果与日志头严重不符：**

```
$ head -7 /tmp/out-r1/all_merged.m3u
#PLAYLIST:All IPTV 2026-10-29
# Total: 11931 channels, 53 categories

$ grep -c '^#EXTINF' /tmp/out-r1/all_merged.m3u
1379
$ grep -c '^# \.\.\. and' /tmp/out-r1/all_merged.m3u
9
```

11931 声称 vs 1379 实际 = **丢弃 88.4%**。仓库里已提交的 `output/` 同样如此：
声称 8168、实际 `grep -c '^#EXTINF'` 得分 **1168**（丢弃 85.7%），9 个分组带 `# ... and N more` 注释。

### 1.2 逐源抓取实测（探针 `probe1.py`，只抓不验证，wall 2.1s）

| 源 | 结果 | 备注 |
|---|---|---|
| iptv-org | 11344 | |
| CCSH-iptv | 2812 | |
| suxuang-myIPTV | 1211 | |
| gitee-why006-TV | 1160 | |
| epg-pw | 649 | |
| zhi35-iptv | 394 | |
| vbskycn-iptv4 | 391 | |
| fanmingming-live | 82 | |
| hujingguang-iptv | 71 | |
| **sammy0101 (priority 1)** | **0** | `ClientConnectorDNSError: raw.gh.registry.cyou [No address associated with hostname]` |
| **xiweiwong-hk-iptv (priority 2)** | **0** | 同上 |
| **freetv-fun (priority 2)** | **0** | `ClientResponseError: 403 Forbidden` |
| **Harbin-byte-iptv** | **0** | 无异常，静默 0 |
| **free-tv-hk / tw / cn / jp / kr / us / uk** | **0 ×7** | 无异常，静默 0 |

- 20 源中 **3 个抛错、8 个静默返回 0**，**只有 9 个源真正产出数据**。
- 优先级最高的两个港源（priority 1/2）已失效，直接导致 `hk_merged.m3u` 萎缩到 33~58 条（`git log` 逐日核对：32/32/32/32/33）。
- 8 个 `.md` 源返回的是 GitHub Markdown 表格（`| # | Channel | Link | ...`），而 `fetcher.py:92` 只按 `.yml/.yaml` 分流，其余全部当 m3u 解析 → 结构性 0 产出。

### 1.3 错误处理实测（副本 `config-test-err`：1 好源 + 无效域名 + 黑洞 IP + 404）

```
$ .venv/bin/python -u -m src.main -c config-test-err -o /tmp/out-err --no-cache --fetch-timeout 120
real 1m40.651s   EXIT=0
[Fetcher] bad-dns attempt 1..3 failed: ... [Name or service not known]
[Fetcher] http-404 attempt 1..3 failed: 404, message='Not Found'
[Fetcher] blackhole-ip attempt 1 failed:            ← 异常信息为空
[Fetcher] good-github: got 82 channels
  ✓ 抓取完成: 共 82 个频道
  ✓ 验证完成: 8/82 个有效
完成！   ← EXIT=0，3/4 源失败，无任何非零退出码
```

**per-source 隔离是有效的**（`gather(return_exceptions=True)` + `_fetch_source` 自身 try/except），单源失败不会打死进程 —— 这是本项目唯一做对的地方。但：

1. 4 个源跑了 **100.6 秒**：黑洞 IP 单源 3 次 × 30s 超时 + 退避 1+2+3s ≈ 93s。**默认 `--fetch-timeout 90` 会被这一条源直接击穿**。
2. `asyncio.TimeoutError` 的 `str()` 为空 → 日志里只有 `attempt 1 failed: ` 后面啥也没有。
3. 3/4 源失败、52/82 频道被验证淘汰，进程仍然 `EXIT=0`、打印"完成！"。

### 1.4 全局超时实测（1 好源 + 1 黑洞源，`--fetch-timeout 20`）

```
$ .venv/bin/python -u -m src.main -c config-test-timeout -o /tmp/out-to --no-cache --fetch-timeout 20
real 0m21.130s   EXIT=0
[Fetcher] good-github: got 82 channels      ← 82 条已到手
  ❌ 抓取超时（20s），请增加超时或使用 --skip-fetch 跳过
❌ 运行失败
--- output 目录 ---
all_merged.m3u 大小为 13 字节，内容是 PRE-EXISTING（上一次的旧文件，未被触碰）
```

已抓到的 82 个频道**全部丢弃**，因为 `main.py:57` 把 `wait_for` 套在 `fetch_all()` 外层，超时即 cancel 整个 gather，没有部分成功语义。而且 `EXIT=0`，CI 完全感知不到。

### 1.5 验证器实测（120 条随机抽样，复刻逻辑 + 真实验证器对照）

```
sample=120 wall=43.6s  replica_pass=58  real_validator_pass=65
原因分布: {"通过":58, "状态码403":12, "HEAD异常TimeoutError":11,
          "HEAD异常ClientConnectorError":11, "状态码405":8, "状态码404":6,
          "HTML":6, "HEAD异常DNSError":3, "CT拒绝":1, "状态码502":1, "状态码302":1, ...}
假阴性(判定失效但 GET 可取数据)=13   假阳性(判定有效但 GET 失败)=2
```

假阴性明细（HEAD 判死，GET 实测有数据）：

```
 状态码405   200/ct=application/x-mpegURL/bytes=2048  https://jmp2.uk/plu-668bf91208d5490008065ffd.m3u8
 状态码404   206/ct=application/x-mpegURL/bytes=940   https://jmp2.uk/stvp-IN4000012ML
 状态码404   200/ct=application/vnd.apple.mpegurl      https://e320...mediatailor.eu-west-1.amazonaws...
HEAD超时    206/ct=application/vnd.apple.mpegurl      https://figarotv-live.freecaster.com/live/...
CT拒绝(text/plain)  206/ct=text/plain/bytes=2048      http://r.jdshipin.com/sE5vO
```

- 405 的 8 条会被 `validator.py:72` 的 GET 回退救回来（对照 `real_validator_pass=65` 与 replica 58 的差）；
- **但 404/403/超时没有任何回退**：3 条 HEAD 404 但 GET 返回 200/206 的 URL 被永久丢弃。

吞吐实测（真实 `Validator`，600 条）：

```
PERF n=600 pass=321 wall=64.6s  rate=9.29 url/s
EXTRAPOLATE full 16859 -> 30.3 min
```

### 1.6 未捕获异常被当成"有效"（validator.py:26-27）

```
--- 未捕获异常是否被当作有效 ---
  bad-ipv6-bracket kept=True  url='http://[::1/list.m3u8'      ← ValueError 逃逸，被当 True
  bad-port         kept=False url='http://example.com:99999/list.m3u8'
  space-in-url     kept=False url='http://exa mple.com/a.m3u8'
  no-scheme        kept=False url='example.com/a.m3u8'
  ctrl-char        kept=False url='http://example.com/a\x00b.m3u8'
  empty-host       kept=False url='http:///a.m3u8'
```

`urlparse` 对畸形 IPv6 括号抛 `ValueError`（不是 `aiohttp.ClientError`，`validator.py:77` 接不住），异常对象在 `if valid` 里恒为真 → 坏 URL 混进播放列表。

### 1.7 缓存实测

```
default_ttl 86400
hit: [{'a': 1}]
ttl=0 过期? None
损坏文件 -> None
无timestamp -> None
未来ts -> future            ← 时钟回拨/伪造时间戳不设防
key 注入测试 ../: True       ← cache.set('../evil') 写到缓存目录外
```

缓存目录 = `src/.cache/channels_raw.json`，实测 **6.01 MB**，`timestamp` 为 `time.time()`，无内容/配置指纹。

### 1.8 幂等性实测（同一份缓存，连跑两次）

```
$ .venv/bin/python -u -m src.main --skip-fetch --skip-validation -o /tmp/idem1
$ .venv/bin/python -u -m src.main --skip-fetch --skip-validation -o /tmp/idem2
d2a5017ebb9639e6efaa2e08df5d830d  /tmp/idem1/all_merged.m3u
d2a5017ebb9639e6efaa2e08df5d830d  /tmp/idem2/all_merged.m3u
edffe01e70f89921a94f9686e9d77fb4  /tmp/idem1/hk_merged.m3u
edffe01e70f89921a94f9686e9d77fb4  /tmp/idem2/hk_merged.m3u
414735470112c1d84989ac9780850f10  /tmp/idem1/stats.json
414735470112c1d84989ac9780850f10  /tmp/idem2/stats.json
```

**同输入下字节级一致**，顺序不是随机的（`gather` 保序 + dict 插入序 + `sorted` 稳定）。幂等的真正威胁不在代码内的随机性，而在外部输入与时间戳（见第三节）。

---

## 二、错误处理与容错缺口

### 2.1 已确认的容错能力（正面）

| 能力 | 位置 | 结论 |
|---|---|---|
| per-source 隔离 | `fetcher.py:48` `gather(..., return_exceptions=True)` + `fetcher.py:81-86` | ✅ 单源崩溃不影响其他源 |
| 重试 | `fetcher.py:73-83`，3 次 | ⚠️ 有，但策略粗糙（见 2.3） |
| 空 URL 兜底 | `validator.py:32-33` | ✅ |
| 缓存损坏容错 | `cache.py:31-32` | ✅ 静默回退为未命中 |

### 2.2 P0 级缺口

**(1) 全局超时 = 全量丢弃，无部分成功**
`main.py:57` / `main.py:67`：

```python
channels = await asyncio.wait_for(fetcher.fetch_all(), timeout=fetch_timeout)
```

`fetch_timeout` 是"整体墙钟预算"，不是"单源预算"。任何一个源卡到 30s×3+退避，整批结果作废（1.4 实测）。同时 `fetcher.py:101` 的 `ClientTimeout(total=30)` 是硬编码的，`--fetch-timeout` 对**单请求**毫无影响 —— CLI 参数与实际控制点脱节。

**(2) 0 频道仍然覆盖发布**
`generator.py:105-177` 没有任何最小阈值检查，`main.py:101` 从不校验 `result['all']['channels']`。实测（副本 `config-empty`，`sources: []`）：

```
BEFORE: 2881 lines, 1379 channels, md5=d2a5017e...
AFTER : 6 lines, 0 channels, md5=b2a7909c...
--- 内容 ---
#EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"
#EXTVLCOPT:network-caching=1000
...
# Total: 0 channels, 0 categories
EXIT=0
```

一次 `sources.yaml` 写错（YAML 合法但 `sources: []`）就能把线上播放列表清空，CI 还会照常 commit + push。

**(3) 失败退出码恒为 0**
`main.py:147-149`：

```python
if result is None:
    print("\n❌ 运行失败")
    return          # ← 没有 sys.exit(1)
```

实测三种失败路径均 `EXIT=0`：抓取超时（1.4）、`--skip-fetch` 无缓存（1.3 之外单独验）、全部源失败。CI 的 `if: steps.changes.outputs.changed == 'true'` 只看 output/ 有没有变化，不看上一阶段是否成功 —— **失败被包装成"无变化，跳过提交"**。

**(4) 输出静默截断 88%**
`generator.py:167-172`：

```python
# ALL 播放列表每个分组最多 100 个
for ch in channels[:100]:
```

实测：`🌐 国际` 6063 条 → 输出 100 条；11 个分组被截断；总计 12469 → 1379。头行 `# Total: 11931`（`generator.py:162` 用的是未截断的 `total_all`）与文件实际内容不符，**这是用户可见的硬伤，不是内部指标问题**。

### 2.3 P1 级缺口

- **验证器把异常当有效**（`validator.py:26-27`）：`return [ch for ch, valid in zip(channels, results) if valid]`，异常对象恒真。实测 `http://[::1/list.m3u8` 判为有效（1.6）。修复：`if ok is True`。
- **假阴性**（`validator.py:71-76`）：只有 `resp.status == 405` 才回退 GET。实测 120 抽样 13 条假阴性（10.8%），含 HEAD 404 但 GET 206 的 3 条（1.5）。HEAD 对短链/CDN 的语义本来就不可靠。
- **`sources.yaml` 的 `headers:` 是死配置**：`grep -rn "headers" src/` 只有 `validator.py:84` 读响应头，请求头从未被传入。`freetv-fun` 因此 403（该源配置了 `User-Agent`）。
- **`priority` 是死配置**：`fetcher.py:79` 写进 `raw_attrs["_priority"]`，但 `grouper.py:50-56` 重建字典时把 `raw_attrs` 整个丢掉，`normalize.py:267-271` 只按 URL 模式（`get_url_priority`）排序。改 `priority` 对输出零影响。
- **`_backup_urls` 算了不用**：`normalize.py:285-292` 为每个频道挑 2 个备用 URL，`generator.build_extinf` 完全不输出 → 多线路容灾能力白丢。
- **重试策略**：`fetcher.py:83` `await asyncio.sleep(1 * (attempt + 1))` —— 线性 1/2/3s，非指数、无抖动；**最后一次失败后仍 sleep 3s**（循环末尾无条件执行，白白多等 3s/源）；404/403 这种不可重试错误也照重试 3 次（1.3 日志可见）；`max_retries` 不区分错误类型。
- **配置无 schema 校验**（`config.py:37-44`）：坏 YAML → 裸 traceback `yaml.parser.ParserError` + `EXIT=1`；条目是字符串 → `AttributeError: 'str' object has no attribute 'get'`（`config.py:44`）。两者都是"报错即崩"，没有"第 N 个源缺 url"这种可操作提示。

### 2.4 P2 级缺口

- `proxy.txt` 实测命中 0/16859 条，`validator.py:50` 用 `pd in domain` 子串匹配，`xray`/`clash` 这类词容易误杀正常域名（当前无命中，属隐患）。
- `whitelist` 同样子串匹配（`validator.py:59`），且命中即**完全跳过验证**：实测 444 条（2.6%）未验证，其中 `raw.githubusercontent.com` 50 条、`*.cloudfront.net` 若干。
- `fetcher.py:57-64` 按 URL 去重时保留"先到者"，无 priority 参与 —— 与 `priority` 设计意图矛盾。

---

## 三、幂等性与 CI 适配问题

### 3.1 代码内是幂等的（1.8 已证），但 CI 里不是

`update.yml:48-64` 有两步：

```yaml
- name: 抓取数据          # python -m src.main --no-cache --fetch-timeout 300
- name: 生成播放列表      # python -m src.main --skip-fetch
```

问题链：

1. 第一步 `--no-cache` → `main.py:62-70` 的 `else` 分支**从不调用 `cache.set`**（只有 `main.py:61` 的 `elif use_cache` 分支才写缓存）。
2. 第二步 `--skip-fetch` → 全新 Actions runner 上没有 `src/.cache/` → 走 `main.py:43-45`：

```
$ .venv/bin/python -u -m src.main --skip-fetch -o /tmp/ci-out      # 无缓存的全新副本
  ❌ 跳过抓取但无缓存数据，请先正常运行一次抓取
❌ 运行失败
EXIT=0
```

3. `EXIT=0` → 该 step 绿；output/ 是第一步写的，看起来"一切正常"。

**结论：CI 的第二步是彻底的死代码**，永远不会复用第一步的数据；它唯一的作用是让日志看起来像个四步流水线。

### 3.2 每日 diff 必然是"全量变化"

- `generator.py:140` / `generator.py:161` 写入 `datetime.now().strftime("%Y-%m-%d")`：
  - 用**本地时区**，CI 是 UTC、开发机是 HKT，跨日在 00:00–08:00 HKT 之间会出现"同一次运行、不同日期字符串"；
  - 每天必变 → `update.yml:69` 的 `git diff --stat output/ | grep -q "0 files changed"` 永远不会命中"无变化"，"跳过提交"分支是死代码。
- 第一步每次重新抓取，源内容本身每日漂移 → 输出整体重排是预期的。

不是 bug，但意味着：**"检查是否有更新"这个机制名存实亡**，真正需要它保护的场景（源全挂 → 输出变空）恰恰没有被保护（见 2.2(2)）。

### 3.3 环境/依赖漂移

- `requirements.txt` 全是 `>=`（`pyyaml>=6.0`、`aiohttp>=3.9.0`），CI 每次 `pip install` 拿最新版 → 一次 aiohttp 破坏性升级就能让每日任务静默变形。
- CI `PYTHON_VERSION: "3.11"`，本地 venv 是 **3.14.4**：`re` 缓存行为、asyncio 默认策略都不同，本地"跑得通"不代表 CI 一致。
- `src/.cache/` **不在 `.gitignore`**（实测 `git check-ignore -v src/.cache/channels_raw.json` → `rc=1`）：本地跑一次就会产生 6MB 未跟踪文件，`git add -A` 极易误提交。

---

## 四、可观测性缺口

**现状：只有 `print`。全仓库 `logging` 出现 0 次，无一条带时间戳/级别的日志。**

### 4.1 一次运行能拿到的全部信息

成功路径只有 6 行有效信息：

```
  ✓ 抓取完成: 共 16859 个频道
  ✓ 验证完成: 8/82 个有效
  ✓ 分组完成: 共 53 个分组
  ✓ 港澳台: 58 频道, 10 分组
  ✓ 全球: 11931 频道, 53 分组
```

### 4.2 缺失的关键指标（全部实测确认无法回答）

| 问题 | 现状 |
|---|---|
| 哪个源挂了？ | 只有一句 `[Fetcher] xxx attempt N failed: <可能为空>`，无汇总；成功的源只打 `got N channels` |
| 8 个 .md 源返回 0 是不是异常？ | **完全静默**，`got 0 channels` 与"这个源今天确实没内容"无法区分 |
| 验证淘汰的 51% 是因为什么？ | 无原因分布（403/404/超时/CT 拒绝各多少），只有总数 |
| 生成阶段丢了多少？ | `is_clean_name` 静默丢 538 条（`stats.json` 合计 12469 vs 生成 11931），无计数 |
| 100 条上限丢了多少？ | 无记录，头行数字反而误导（11931 vs 1379） |
| 每个源耗时？ | 无 |
| 本次运行是否健康？ | 无结论字段，`EXIT=0` 恒真 |

`stats.json` 本身也自相矛盾：它是 `main.py:106` 从 `grouped`（生成前的 12469）落的盘，而播放列表头写 11931、文件实际 1379 —— **同一个 run 产出三个不同口径的"频道总数"**。

### 4.3 CI 日志里实际能看到什么

`update.yml:51-56` 用 `echo "::group::抓取阶段"` 包裹，22+ 行的源输出折叠在一个 group 里；`upload-artifact` 上传 `output/`（含 `stats.json`），但没有任何"机器可读的运行报告"，所以既无法做趋势对比，也无法在失败时快速定位。

---

## 五、缺陷清单

| ID | 级别 | 缺陷 | 位置 | 证据 |
|---|---|---|---|---|
| B-01 | **P0** | 每分组 100 条硬截断，静默丢弃 88% 频道且头行数字撒谎 | `generator.py:167-172`, `generator.py:162` | 11931 声称 / 1379 实际；实测 `sum(min(v,100))=1379` |
| B-02 | **P0** | 0 频道仍覆盖发布，可清空线上播放列表 | `generator.py:105-177`, `main.py:101` | 1379 条 → 0 条，`EXIT=0` |
| B-03 | **P0** | 失败退出码恒为 0，CI 无法感知失败 | `main.py:147-149` | 超时/3源失败/无缓存三种路径均 `EXIT=0` |
| B-04 | **P0** | 全局 `wait_for` 超时丢弃全部已抓数据，无部分成功 | `main.py:57`, `main.py:67`, `fetcher.py:48` | 82 条已到手仍被丢；默认 90s vs 单源最坏 93s |
| B-05 | **P1** | 未捕获异常被当作"有效" | `validator.py:26-27` | `http://[::1/list.m3u8` → `kept=True` |
| B-06 | **P1** | 验证仅 405 回退 GET，HEAD 404/403/超时直接判死 | `validator.py:71-76` | 120 抽样 13 条假阴性（10.8%） |
| B-07 | **P1** | 每 URL 新建 `ClientSession`，无连接复用，吞吐 9.29 url/s | `validator.py:69`, `fetcher.py:102`, `fetcher.py:153` | 600 条 64.6s → 外推 16859 条 30.3 min |
| B-08 | **P1** | 8 个 `.md` 源结构性 0 产出且完全静默 | `fetcher.py:92`, `config/sources.yaml` | 探针逐源: free-tv-* / Harbin 全 0，无异常 |
| B-09 | **P1** | 最高优先 2 个港源 DNS 失效，HK 列表萎缩无人告警 | `config/sources.yaml`, `fetcher.py:81-86` | sammy0101/xiweiwong 均 DNS 失败；hk 33-58 条 |
| B-10 | **P1** | `sources.yaml` 的 `headers:` 从未被使用 | `fetcher.py:99-105`, `fetcher.py:150-156` | `grep -rn headers src/` 仅 `validator.py:84`；freetv-fun 403 |
| B-11 | **P1** | 缓存 key 固定 + 24h TTL，改配置仍吃旧缓存 | `cache.py:11,18-30`, `main.py:46-51` | 命中缓存即不再读 `sources.yaml` |
| B-12 | **P1** | CI 第二步 `--skip-fetch` 必然失败（`--no-cache` 不写缓存），且失败为 0 退出 | `main.py:62-70`, `update.yml:58-64` | 全新副本 `--skip-fetch` → `❌ 无缓存数据`，`EXIT=0` |
| B-13 | **P1** | 配置无 schema 校验，错误形态是裸 traceback | `config.py:37-44` | `yaml.parser.ParserError`；`AttributeError: 'str' object has no attribute 'get'` |
| B-14 | **P2** | `priority` 配置形同虚设 | `fetcher.py:79`, `grouper.py:50-56`, `normalize.py:267-271` | `raw_attrs` 在 grouper 被丢弃 |
| B-15 | **P2** | `_backup_urls` 计算后不输出，多线路容灾丢失 | `normalize.py:283-292`, `generator.py:83-96` | `build_extinf` 无备选 URL 输出 |
| B-16 | **P2** | 重试线性退避、末次仍 sleep、404 也重试 | `fetcher.py:73-83` | 1.3 日志: 404 被重试 3 次；黑洞源 93s |
| B-17 | **P2** | 异常信息为空串，日志不可诊断 | `fetcher.py:82` | `blackhole-ip attempt 1 failed: ` |
| B-18 | **P2** | 无运行报告/无原因分布/无 per-source 耗时/`stats.json` 口径不一致 | `main.py:105-110` | 12469 / 11931 / 1379 三个数字 |
| B-19 | **P2** | 生成器用本地时区日期，本机与 CI 跨日不一致 | `generator.py:140`, `generator.py:161` | 本机 HKT 2026-10-29 vs repo UTC 2026-10-28 |
| B-20 | **P2** | `src/.cache` 未被 gitignore，6MB JSON 可能误提交 | `.gitignore` | `git check-ignore` rc=1；缓存 6.01MB |
| B-21 | **P2** | 缓存 key 无路径校验，可写出缓存目录 | `cache.py:36` | `cache.set('../evil')` 成功写在目录外 |
| B-22 | **P2** | 依赖未锁版本；本地 3.14 vs CI 3.11 | `requirements.txt`, `update.yml:22` | `aiohttp>=3.9.0` |
| B-23 | **P2** | 分组阶段 150s CPU：`re.search` 传字符串导致 57.8 万次重复编译 | `src/group/categorizer.py:48-56` | cProfile: 578316 次 `re._compile`，23.1s/25s |
| B-24 | **P2** | whitelist/proxy 子串匹配，命中 whitelist 即跳过验证 | `validator.py:50,59` | 444 条（2.6%）未验证 |

---

## 六、改进方案

### 6.1 P0：先止血（改动小、收益最大）

**(1) 去掉 100 条硬截断，或改成显式配置 + 诚实计数**（B-01）

```python
# generator.py
MAX_PER_CATEGORY = int(os.environ.get("MAX_PER_CATEGORY", "0"))  # 0 = 不限制

for cat, channels in sorted(all_grouped.items(), key=lambda x: sort_key(x[0])):
    emit = channels if MAX_PER_CATEGORY <= 0 else channels[:MAX_PER_CATEGORY]
    all_lines.append(f"#EXTGRP:{cat} ({len(channels)})")
    for ch in emit:
        ...
    if len(emit) < len(channels):
        all_lines.append(f"# ... and {len(channels)-len(emit)} more")
# 头行必须用真实写入数
emitted = sum(len(v) if MAX_PER_CATEGORY<=0 else min(len(v),MAX_PER_CATEGORY) for v in all_grouped.values())
```

**(2) 最小阈值 + 原子写**（B-02）

```python
# main.py
MIN_CHANNELS = 500          # 低于历史值的 20% 视为异常

if result["all_channels"] < MIN_CHANNELS:
    print(f"❌ 输出频道数 {result['all_channels']} 低于阈值 {MIN_CHANNELS}，拒绝覆盖")
    sys.exit(2)

# generator.py：先写 .tmp 再 os.replace，避免半截文件
def _atomic_write(path, lines):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)          # 同目录 rename，原子
```

阈值也可以基于上一次的 `stats.json` 做动态判断（`< 上次的 50%` 即拒绝），比硬编码更稳。

**(3) 失败必须非零退出**（B-03）

```python
# main.py:main()
if result is None:
    print("\n❌ 运行失败", file=sys.stderr)
    sys.exit(1)
```

CI 侧再加一道兜底（防止将来又出现 `EXIT=0` 的漏网之鱼）：

```yaml
- name: 抓取数据
  run: |
    python -u -m src.main --no-cache --fetch-timeout ${{ env.FETCH_TIMEOUT }} --output ./output \
      | tee fetch.log
    grep -q "抓取完成" fetch.log || { echo "::error::抓取阶段未完成"; exit 1; }
```

**(4) 部分成功语义**（B-04）

```python
# main.py：不要用全局 wait_for 包整个 fetch_all
fetcher = Fetcher(config, per_source_timeout=fetch_timeout)
channels, report = await fetcher.fetch_all()      # fetch_all 内部自己保证总时长
if not channels:
    sys.exit(1)
failed = [r for r in report if r["status"] != "ok"]
print(f"  ⚠ {len(failed)}/{len(report)} 个源失败: {[r['name'] for r in failed]}")
```

```python
# fetcher.py
async def _fetch_source(self, source) -> SourceResult:
    t0 = time.monotonic()
    for attempt in range(self.max_retries):
        try:
            chs = await asyncio.wait_for(self._fetch_url(url), timeout=self.per_source_timeout)
            return SourceResult(name, "ok", len(chs), time.monotonic()-t0, chs)
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            if isinstance(e, aiohttp.ClientResponseError) and e.status in (403, 404):
                break                                   # 不可重试
            if attempt < self.max_retries - 1:          # 末次不再 sleep
                await asyncio.sleep(min(2 ** attempt + random.random(), 10))   # 指数 + 抖动
    return SourceResult(name, "failed", 0, time.monotonic()-t0, [])
```

`per_source_timeout` 默认 30s（与现有 `ClientTimeout(total=30)` 对齐），`--fetch-timeout` 改为控制"单源预算"，语义与 help 文案一致。

### 6.2 P1：验证器与配置

**(5) 修异常真值 + 共享 session + 扩大 GET 回退**（B-05/B-06/B-07）

```python
class Validator:
    async def __aenter__(self):
        self._conn = aiohttp.TCPConnector(limit=self.max_concurrent, ttl_dns_cache=300,
                                          enable_cleanup_closed=True)
        self._session = aiohttp.ClientSession(
            connector=self._conn,
            timeout=aiohttp.ClientTimeout(total=self.timeout, connect=5, sock_read=self.timeout),
            headers={"User-Agent": "Mozilla/5.0 ... VLC/3.0.20"},
        )
        return self

    async def validate(self, channels):
        async with self:
            tasks = [self._validate_one(ch) for ch in channels]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            ok, reasons = [], Counter()
            for ch, r in zip(channels, results):
                if r is True:                       # 严格 is True，异常一律 False
                    ok.append(ch)
                else:
                    reasons[r if isinstance(r, str) else type(r).__name__] += 1
            print(f"  验证淘汰原因: {dict(reasons)}")
            return ok

    async def _check_url(self, url) -> bool | str:
        async with self._semaphore:
            try:
                async with self._session.head(url, allow_redirects=True) as resp:
                    if self._is_valid_response(resp):
                        return True
                    status = resp.status
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                status = type(e).__name__
            # HEAD 不可靠（405/404/403/timeout）→ 单次 GET Range 兜底
            if not isinstance(status, int) or status in (403, 404, 405, 501):
                try:
                    async with self._session.get(url, allow_redirects=True,
                                                 headers={"Range": "bytes=0-2047"}) as r:
                        return self._is_valid_response(r, ranged=True)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    return type(e).__name__
            return f"status_{status}"
```

要点：
- **一次 `ClientSession` 复用连接**（预期吞吐从 9.29 url/s 提升到 50+ url/s，30 分钟 → 5 分钟内）；
- `total/connect/sock_read` 分离，避免"能连上但读不动"的慢源吃掉整个 total；
- 回退到 GET 时用 `Range: bytes=0-2047`，只读 2KB，成本与 HEAD 同量级；
- 返回 `reason` 字符串而不是 bool，天然产出淘汰原因直方图。

**(6) 配置 schema 校验 + 字段真正接线**（B-10/B-13/B-14）

```python
# config.py
REQUIRED = ("name", "url")
def _load_sources(self):
    path = self.config_dir / "sources.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise SystemExit(f"❌ {path} 不是合法 YAML: {e}")      # 可操作报错，不是 traceback
    raw = data.get("sources")
    if not isinstance(raw, list) or not raw:
        raise SystemExit(f"❌ {path} 缺少非空的 sources 列表")
    out = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise SystemExit(f"❌ {path} 第 {i+1} 个源不是映射")
        missing = [k for k in REQUIRED if not s.get(k)]
        if missing:
            raise SystemExit(f"❌ {path} 第 {i+1} 个源缺少字段 {missing}")
        if not s["url"].startswith(("http://", "https://")):
            raise SystemExit(f"❌ {path} 源 {s['name']} 的 url 不是 http(s)")
        if s.get("enabled", True):
            out.append(s)
    if not out:
        raise SystemExit(f"❌ {path} 没有启用的源")
    return out
```

`headers` 接线（`fetcher.py`）：`session.get(url, headers=source.get("headers") or {"User-Agent": DEFAULT_UA})`。
`priority` 接线：`grouper.py:50-56` 的字典里补 `"priority": ch.raw_attrs.get("_priority", 999)`，`normalize.py` 的 `sort_key` 变成 `(source_priority, url_priority)`。

**(7) 缓存 key 加配置指纹 + 打通 CI**（B-11/B-12）

```python
# main.py
import hashlib
digest = hashlib.sha256(json.dumps(config.sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
cache_key = f"channels_raw_{digest}"      # 改配置即失效

if use_cache is False:
    ...fetch...
    cache.set(cache_key, [ch.__dict__ for ch in channels])   # --no-cache 也写，供下一步复用
```

`--no-cache` 的语义建议拆成两个参数：`--refresh`（忽略缓存但写缓存，CI 第一步用）与 `--no-cache`（读写都关）。这样 CI 第二步的 `--skip-fetch` 才有数据可用。

**(8) `.md` 源的处理**（B-08）

三个选择，按成本排序：
1. 最省事：在 `config.py` 加载时按后缀告警 —— `url` 以 `.md` 结尾 → 打印 `⚠ 源 X 指向 Markdown 文件，当前解析器不支持`，让噪声暴露在日志里；
2. `fetcher.py:92` 增加 `.md` 分支，解析 `| Channel | Link |` 表格（Free-TV 格式固定，20 行代码）；
3. 直接换成对应的 `.m3u` 端点（Free-TV 仓库同时提供 `lists/*.m3u`），并给 DNS 失效的 `raw.gh.registry.cyou` 换镜像域名。

### 6.3 P2：可观测性与工程卫生

**(9) 机器可读运行报告**（B-18）

```python
# main.py 结束处
report = {
    "run_at": datetime.now(timezone.utc).isoformat(),   # 统一 UTC
    "sources": [asdict(r) for r in source_report],      # name/status/n/elapsed/error
    "fetched": len(channels),
    "validated": len(valid_channels),
    "validation_drop_reasons": dict(reason_counter),
    "grouped": len(grouped),
    "dropped_by_name_filter": dropped,
    "emitted": {"hk": ...,"all": ...},
    "ok": failures == 0 and len(valid_channels) > MIN_CHANNELS,
}
json.dump(report, open(output_dir/"run_report.json","w"), ensure_ascii=False, indent=2)
```

CI 里直接 `cat output/run_report.json >> $GITHUB_STEP_SUMMARY`，人就只需要看一屏。

**(10) 日志换 `logging`**（B-17）

```python
logging.basicConfig(level=os.environ.get("LOG_LEVEL","INFO"),
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log.warning("源 %s 失败: %s", name, f"{type(e).__name__}: {e}" or repr(e))   # 空消息兜底
```

**(11) 日期与顺序**（B-19）：`datetime.now(timezone.utc)`；或读 `SOURCE_DATE_EPOCH` 支持可复现构建；组内顺序建议显式 `sorted(channels, key=lambda c: (c.name, c.url))`，让输出与"源返回顺序"解耦。

**(12) 其它**：`.gitignore` 加 `.cache/`；`cache.py` 的 key 用 `re.sub(r'[^A-Za-z0-9_.-]', '_', key)` 清洗；`requirements.txt` 锁 `aiohttp==3.10.*` 之类精确版本；`categorizer.py` 把 `re.search("...")` 的字符串模式提到模块级 `re.compile`（B-23，单项就能砍掉 150s 里的绝大部分）。

---

## 七、我不确定/需要人工判断的点

1. **验证阶段的真实 CI 耗时**。本机 600 条抽样外推 30.3 分钟，已顶到 `update.yml:29` 的 `timeout-minutes: 30` 上限；但 GitHub US runner 对不可达的中国 IP 通常是"快速失败"而非"等 10s 超时"，真实耗时会显著低于本机。仓库每天 04:30 UTC 有提交，说明任务确实跑完了 —— 建议人工核对最近几次 Actions 的实际 duration（本机无 `gh`、无仓库凭据，我无法查）。若确在 20 分钟以上，B-07 就从 P1 升为 P0（睡眠式超时风险）。
2. **`--fetch-timeout 300` 是否掩盖了问题**。CI 传 300、默认 90，同一个参数在两个环境语义不同（单请求 30s 硬编码不受它影响）。是否要把"单源预算"和"总预算"拆成两个 CLI 参数，属于产品决策。
3. **100 条/分组的上限是不是刻意的**。`generator.py:167` 的注释写着"ALL 播放列表每个分组最多 100 个"，可能是有意为控制文件体积/客户端性能。若是刻意，那问题只在于"头行数字必须诚实"；若不是，则需整体放开（文件会从 259KB 涨到 ~2MB）。我不能替产品判断，但**当前头行 `# Total` 与内容不符无论如何都要修**。
4. **`is_clean_name` 丢掉的 538 条（4.3%）是否都是垃圾**。它按 `chrome/`、`webkit`、`http` + `.png` 等子串匹配，可能误杀真实频道（比如名字里带 "Edge" 的体育频道）。需要人工抽样 `stats.json` 与输出差异后再决定是否放宽。
5. **`priority` 到底想表达什么**。现在 `sources.yaml` 的 priority 与 `normalize.get_url_priority` 的 CDN 优先级是两套独立逻辑，且前者完全失效。到底哪套是"真理"需要作者确认 —— 我倾向于"源 priority 作为同 URL 优先级之后的第二排序键"。
6. **两个 DNS 失效源（sammy0101 / xiweiwong）是否有替代镜像**。`raw.gh.registry.cyou` 整体 NXDOMAIN，属于域名级失效而非单源问题；换域名需要作者知道该镜像的可用替代（gh-proxy.com 等）。我未擅自改配置。
7. **proxy.txt 当前零命中**。可能是匹配规则（`pd in domain`）写错了意图，也可能是维护者一直在等某些域名出现。合并为"要么修匹配、要么删规则"，需要人工确认设计意图。
8. **本地 venv 是 Python 3.14.4，CI 是 3.11**。B-23 的 cProfile 数字在 3.11 下会不同（`re` 模块缓存策略有差异），但"每次调用重新编译"的根因与版本无关。建议在 3.11 下复测一次再定优化幅度。

---

### 附：本次使用的复现命令

```bash
# 基线（跳过验证，用缓存或重抓）
.venv/bin/python -u -m src.main --skip-validation -o /tmp/out-r1

# 幂等性（同缓存连跑两次）
.venv/bin/python -u -m src.main --skip-fetch --skip-validation -o /tmp/idem1
.venv/bin/python -u -m src.main --skip-fetch --skip-validation -o /tmp/idem2
md5sum /tmp/idem1/*.m3u /tmp/idem2/*.m3u

# 错误处理（副本 config-test-err: 好源 + 无效域名 + 黑洞 IP + 404）
.venv/bin/python -u -m src.main -c config-test-err -o /tmp/out-err --no-cache --fetch-timeout 120

# 全局超时丢弃已抓数据（副本 config-test-timeout）
.venv/bin/python -u -m src.main -c config-test-timeout -o /tmp/out-to --no-cache --fetch-timeout 20

# 空源覆盖（副本 config-empty: sources: []）
.venv/bin/python -u -m src.main -c config-empty -o /tmp/o-overwrite --no-cache

# 统计核对
grep -c '^#EXTINF' output/all_merged.m3u
grep -c '^# \.\.\. and' output/all_merged.m3u
```

实验副本位于 `/home/hermes/.hermes/cache/scratch/ltv/`（`work/` 全量副本、`ci-sim/` CI 流程副本，含 `probe1.py`/`probe2.py`/`probe3.py` 三个只读探针）。原仓库 `src/`、`config/`、`output/` 未被修改（`git diff --stat` 为空，`git status` 仅显示 `?? reports/`），无 commit/push。副本位于 scratch 目录，24 小时空闲后自动清理；如需复核请在此之前使用。
