# 分组逻辑重构报告（2026-10-29）

本文是 `src/group/categorizer.py` 那轮重构的**完整实测记录** —— 动机、改了什么、每个机制各自买到了多少、
以及过程中我自己犯的错。README 只留结论，细节全在这里。

- 重构提交：`a00e134`（第一版）、`8a292b3`（第二遍修 `\b` 边界）、`f075455` / `3b3fa80`（统计口径更正）
- 涉及文件：`src/group/categorizer.py`、`src/generator.py`、`tests/`、`scripts/eval_categorize.py`
- 配套文档：[`categorize-bug-analysis.md`](categorize-bug-analysis.md)（缺陷清单）、
  [`categorize-improvement-proposal.md`](categorize-improvement-proposal.md)（方案与 TODO）、
  [`categorize-baseline-findings.md`](categorize-baseline-findings.md)（基线量化）

---

## 0. 动手前的基线问题

| 问题 | 表现 |
|---|---|
| 港澳台判定有两套关键词表 | `is_hk_region()` 的 `hk_exact`/`tw_exact`/`mo_exact` 与 `categorize()` 各维护一份，结论会打架 |
| 双反斜杠正则永不命中 | `r"\\bmacau\\b"` 实际匹配「字面反斜杠 + b」，于是 `categorize("Macau TV")` = `🇲🇴 澳门` 而 `is_hk_region("Macau TV")` = `False` |
| 裸子串误伤 | 没有词边界的 `r"atv"` 把 `AricaTV` / `BarazaTV` / `AndorraTV` / `AgriculturaTV` 全吸进「📡 卫视频道」（实测 98/1,164 = 8.4% 的产物条目） |
| 兜底链太弱 | `recategorize_others()` 末尾 `return "🌐 国际"` 把没命中的全倒进国际桶（该桶 100 条里 100 条是大陆地市台） |
| `CATEGORY_ORDER` 与产出不匹配 | 表里 13 个死分类；实际产出的 `🇨🇳 中国源` / `🇲🇾 马来西亚` / `🌐 国际` **不在表内**，排序静默落到文件末尾 |

---

## 1. 重构做了什么

`categorize()` 与 `is_hk_region()` 改为共用同一套 `HK_TW_MO_RULES` + `_region_category()`，
港澳台判定从「两处实现」收敛到「一处」。`is_hk_region()` 从 136 行缩到 11 行，
那段「无论条件如何都 `return False`」的不可达分支随之消失。

抽样验证（实测）：

```
is_hk_region("Macau TV")   -> True      # 重构前 False
is_hk_region("TTV")        -> True      # 重构前 False
is_hk_region("PTS")        -> True      # 重构前 False
categorize("Macau TV")     -> 🇲🇴 澳门   # 两边终于一致
```

---

## 2. 重构前后对比（可复现）

评测集在 `scripts/categorize_dataset/`：`known_bugs.tsv`（24 条已知错判）+ `known_good.tsv`（27 条不能退化的正确判定）。

```console
$ python scripts/eval_categorize.py
# 重构前：known_bugs 5/24，known_good 27/27，合计 32/51  → RESULT: FAIL
# 重构后：known_bugs 23/24，known_good 27/27，合计 50/51  → 剩 1 条已知残留
```

同一份 **13,470 条真实频道名语料**（`corpus.tsv`，四列 `cat/name/group/logo`）上跑：

| 指标 | 重构前 | 重构后 |
|---|---:|---:|
| `is_hk_region()` 判为港澳台 | 92 | **145**（新增 53 / 丢失 0；第一版 141，第二遍修 `\b` 再 +4） |
| `categorize()` 产出的分组数 | 52 | 52（**集合完全相同，零新增零消失**） |
| `📡 卫视频道` 桶大小 | 603 | **37** |
| `🇨🇳 中国源` 桶大小 | 116 | 327（入境 236 − 出境 25） |
| 分类发生变化的条目 | — | **1,891 条（14.0%）**，11,579 条不变 |

最大三类位移：`📡 卫视频道` → `🌐 国际` 423、`🌐 国际` → `🇨🇳 中国源` 235、`🎵 音乐频道` → `🌐 国际` 88。

修掉的裸子串还有 `tv5` / `tbs` / `dw` / `nick` / `amc`（`XinjiangTV5` 曾被 `tv5` 抢进「国际频道」）。
**刻意没加词边界的**：`movie` / `cinema` / `kids` / `影视` / `影城` —— 这些是内容词，加边界会丢真命中。

---

## 3. 端到端产物变化

同一天三次全新运行（`--no-cache --skip-validation`）：

| 产物 | 重构前（`074c677`） | 重构第一版（`a00e134`） | 当前（`8a292b3`） |
|---|---:|---:|---:|
| 抓取到手 | 16,901 | 16,994 | 16,991 |
| 同名合并后 | 12,505 | 12,578 | 12,578 |
| `stats.json` 求和 / 分组数 | 12,505 / 53 | 12,578 / 53 | 12,578 / 53 |
| `all_merged.m3u` 的 `#EXTINF` | 1,378 | 1,702 | **1,706** |
| `all_merged.m3u` 文件头 `# Total:` | 12,505 | 12,000 | 12,000 |
| `hk_merged.m3u` 的 `#EXTINF` | 58 | 103 | **107** |
| `hk_merged.m3u` 分组数 | 7 | 9 | 9 |
| 字节数（all / hk） | 257,714 / 8,376 † | 396,882 / 23,992 | 397,605 / 24,715 |

† 第一列那两个字节数其实是**仓库里 `output/` 快照**的值，不是那次运行的，别混用。

`hk_merged` 从 58 涨到 107（+84%）是港台判定修好的直接结果：原先 `Macau TV` / `TTV` / `PTS` /
`CNA 中央社` / `非凡商业台` / `东森财经新闻` / `港台电视31` 这些被判成港澳台却进不了港澳台列表。

`103 → 107` 这 4 条是第二遍修 `\b` 边界捞回来的，逐条核对过：

```console
$ diff <(grep '^#EXTINF' livetv_postpatch/hk_merged.m3u | sed 's/.*,//' | sort) \
       <(grep '^#EXTINF' livetv_head_run/hk_merged.m3u   | sed 's/.*,//' | sort)
3a4,5
> HOY78
> HOYInfotainment
4a7
> HOY资讯台
8a12
> PTS3
```

只有 `>` 没有 `<` —— 四行全是新增，**没有任何一条被挤掉**。

> **两次运行输入不完全相同**：抓取到手 16,994 vs 16,991（`freetv-fun` 403、`raw.gh.registry.cyou` DNS 解析失败，
> 源本身在飘），但同名合并后都是 12,578 条。所以逐项数字可比，但**不是严格受控对照**，
> 只有 `hk_merged` 那 4 条是逐条 diff 确认的。

> ⚠️ **仓库里的 `output/` 是重构前生成的**（数据提交 `074c677`），所以 README 引用的
> `8,371 / 8,056 / 1,164 / 33` 都是旧分布。下一次 CI 跑完会变。**不要拿旧快照对照新代码判断对错。**

---

## 4. 第二遍修正：`\b` 在 CJK / 数字边界失效

重构第一版把 `\bxxx\b` 当词边界通解，但 **Python 的 `\w` 含 CJK，所以 `\b` 在「拉丁字母 + 中文」
和「字母 + 数字」之间不成立**。重构里已经为央视用了 `(?![a-z])` 而不是 `\b`，
却没把这个结论推广到其他分支，于是留下同类缺陷。

实测方式：从 `corpus.tsv` 里筛「含 target 但 `\b` 尾部断言失败」的条目。

| target | 被 `\b` 击落 | 真实频道样例 | 处理 |
|---|---:|---|---|
| `hoy` | 3 | `HOY资讯台` / `HOY78` / `HOYInfotainment` | ✅ 改 `(?<![a-z])hoy` |
| `pts` | 1 | `PTS3`（公视 3 台） | ✅ 改 `(?<![a-z])pts(?![a-z])` |
| `trt` | 3 | `TRT1` / `TRT2` / `TRT3` | ✅ 改 `(?<![a-z])trt(?![a-z])` |
| `ttv` / `ftv` / `cna` | 各 0~3 | `TTVNews` / `FTVNews` / `CNAInternational` | 改了正则，但语料里这几条仍被更早分支命中，**实测 0 变动** |
| `cnn` / `voa` | 2 / 1 | `A2CNN` / `VOA美国之音` | 改了正则，**实测 0 变动**（均被更早分支吃掉） |
| `atv` / `tv5` / `now` / `nhk` / `dw` | 7 / 19 / 10 / 5 / 6 | `ATVAlanya`（土耳其）/ `TV52` / `Now14` / `NHKWorld` / `DWEnglish` | ❌ **不动**：改宽会把土耳其 ATV、阿尔巴尼亚 TV52、印度 Now 误收 |

第二遍改动前后对比（同一份 13,470 条语料）：

```
总变动 7 条 / 13470
  🌐 国际      -> 📺 HOY TV     3   (HOY78 / HOYInfotainment / HOY资讯台)
  🌐 国际      -> 🇹🇼 台湾        1   (PTS3)
  🌐 国际      -> 🌐 国际频道     3   (TRT1 / TRT2 / TRT3，从兜底进宽桶)

hk 覆盖：141 -> 145，丢失 0，新增 4
```

`iHOY爱历史`（历史纪录片频道，名字带 hoy 但不是 HOY TV）被前置否定 `(?<![a-z])` 正确挡在外面，
已加负向测试钉住。

### ⚠️ HOY 这条不能算「既有缺陷」

`\bhoy\b` 击落 `HOY资讯台` / `HOY78` / `HOYInfotainment` 是**本次重构引入的新回归** —— 基线版本
对这三条判的是 `📺 HOY TV`。我一开始在 README / CHANGELOG / xfail reason 里把它写成「既有缺陷」，
并编了个根因（「类型词判定先于品牌判定」），这是错的，已全部撤回。

修法用 `(?<![a-z])hoy`（只做前置否定）而不是 `\bhoy\b`：要同时容纳 `HOY78` / `HOY资讯台` /
`HOYInfotainment`，又要排除 `iHOY爱历史`。

---

## 5. 各机制的隔离贡献

原计划拆成 S1–S6 六步实施，但重构实际以**单个提交** `a00e134` 落地，**中间态代码从未存在**，
所以「S1 之后 / S1+S2 之后」的累积数字无法复跑 —— 编不出来。

替代方案：把 13,470 条语料的 baseline 与 current 判定各跑一遍缓存下来
（`mech_cache.json`，13,470 条 × 7 字段），再按每个机制**针对的频道子集**统计翻转。

| 机制 | 发生变化的条数 | 主要位移 |
|---|---:|---|
| **S1** 港澳台判定统一 + 双反斜杠修复 | 53 | `is_hk_region()` 翻转 **+53 / −0** |
| **S2** 词边界 `atv`/`tv5`/`tbs`/`dw`/`nick`/`amc` | 631 ⚠️ | `📡 卫视频道` → `🌐 国际` 416、→ `🎵 音乐` 45、→ `🎭 综艺` 42、→ `📰 新闻` 40 |
| **S3** 央视/教育台 `\b` → `(?![a-z])` | 23 | → `📺 央视频道`：自 `🌐 国际` **12**、自 `🇨🇳 中国源` **6**、自 `🌐 国际频道` 3、自 `🎭 综艺` 1、自 `📰 新闻` 1 |
| **S4** 地市台兜底链 | 236 | 入境 `🇨🇳 中国源` 236：自 `🌐 国际` **235**、自 `📺 HOY TV` 1 |
| **S5** 国际新闻品牌块前移 | 42 | `🌐 国际频道` → `🌐 国际` 20 / `📰 新闻财经` 7 / `📺 纪录片` 4 / `🎭 综艺` 3 / `🎬 电影` 3 / `🧸 儿童` 2 |
| **S6** `CATEGORY_ORDER` 62 → 65 项 | — | 产出但不在表内 **3 → 0**；两版死分类都是 **13 个** |

> ### S4 的口径订正
> 第一版探针写的是 `c_cat == "🇨🇳 中国源"` —— 这是**状态探针**，不是变化探针，
> 把「baseline 本来就是中国源」的 91 条也算进去了，报出 327。其他机制都带 `b_cat != c_cat`。
> 统一成变化口径后是 **236 条**（中国源总数 327 = 236 入境 + 91 原有留存）。
>
> `🇨🇳 中国源` 还有 **25 条出境**（→ `📺 央视频道` 10、`📺 湖北` 5、`📡 卫视频道` 3、
> `📺 四川` 3、`📺 陕西` 3、`🇹🇼 台湾` 1）：新版把地名识别做细了，原先兜底进「中国源」的
> 现在能落到具体省份。**兜底桶不是只进不出。** 116 + 236 − 25 = 327 自洽。

> ⚠️ **S2 的 631 被探测口径放大**：探针用 `re.search(r"atv|tv5|tbs|dw|nick|amc", name)`
> 匹配名字子串，`DLTV5`（含 `tv5`）、`DWArabic`（含 `dw`）会被算进去，而它们的位移其实是 S5 造成的。
> **这个数字只能读作「这批子集里发生翻转的总量」，不能读作「词边界修复的精确贡献」**
> ——后者见上面第 4 节那张逐 target 表。

### S6 的死分类 13 个

预留块的 12 个（`🇮🇳 印度` `🇯🇵 日本` `🇰🇷 韩国` `🇺🇸 北美` `🌍 中东` `🌍 欧洲` `🌍 非洲`
`🌎 拉丁美洲` `🌏 亚洲（东南亚）` `🌏 亚洲（其他）` `🌏 大洋洲` `📺 其他`）+ `📺 有线电视`。

⚠️ **`📺 有线电视` 是「语料没覆盖到」不是「产不出来」**：`categorize("有线电视新闻", "")`
实测返回它，真实产物 `all_merged` / `hk_merged` 各有 1 条。预留块那 12 个才是真的调不出来。

---

## 6. 一处测量口径错误（自查并已更正）

第一版统计脚本调的是 `categorize(name, group)`，**漏了第三个参数 `logo`**。
而生产路径 `src/grouper.py:92` 是 `categorize(name, group, logo)`，
`LOGO_REGION_PATTERNS` 正是靠 logo URL 的域名/文件名片段判地区：

| logo 片段 | 分类 |
|---|---|
| `Astro` | 🇲🇾 马来西亚 |
| `epg.112114.xyz/logo/TVB` | 📺 TVB |
| `gitee.com/suxuang` | 🇨🇳 中国源 |

连带搞错了 **5 个数字**（已全部按带 logo 口径更正）：

| 指标 | 无 logo（错） | 带 logo（对） |
|---|---:|---:|
| 死分类数 | 14 | **13** |
| `🇲🇾 马来西亚` 产出 | 0（被报成「从不产出」） | **4**（`AstroAOD`/`AstroAEC`/`AstroQJ`/`Astro欢喜台`） |
| `categorize()` 产出分组数（前→后） | 50 → 51 | **52 → 52**（集合完全相同） |
| `🇨🇳 中国源` 桶（前→后） | 0 → 272 | **116 → 327** |
| 旧表「产出但不在表内」 | 2 个 | **3 个**（多 `🇲🇾 马来西亚`） |

其中「`🇨🇳 中国源` 重构前 = 0、该组不存在」错得最难看：baseline 靠 `gitee.com/suxuang` 这条
logo 规则**早就在产出 116 条中国源**。`categorize-bug-analysis.md` 里写的「产出分组数=52」本来就是对的，
反而是我 README 里的 50→51 把它改错了。

**S1–S5 也已用带 logo 口径重跑**（13,470 条 × baseline/current 各一次，约 40 分钟）：

| 机制 | 无 logo（旧） | 带 logo（新） | 是否变化 |
|---|---:|---:|---|
| S1 港澳台翻转 | 53（+53 / −0） | 53（+53 / −0） | 不变 |
| S2 词边界子集 | 631 | 631 | 不变 |
| S3 央视正则 | 23 | 23 | 分布变（多出「自 `🇨🇳 中国源` 6 条」） |
| S4 地市台兜底 | 272（状态探针） | 236（变化探针） | 口径 + 数值都变 |
| S5 国际新闻品牌 | 42 | 42 | 不变 |
| S6 死分类 | 14（误） | **13** | 变 |

**教训**：`categorize()` 的 `logo` 参数不能省。`tests/conftest.py` 的 `classify` fixture 已补上
`logo` 形参，`tests/test_categorize_golden.py` 加了 7 条 logo 契约用例把它钉住。

---

## 7. 顺带发现的两处残留

### `CHANNEL_REGION_PATTERNS` 是 25 条死数据

`src/group/categorizer.py:386` 定义了 `CHANNEL_REGION_PATTERNS`（25 条频道名 → 地区映射，
如 `ASTROAOD` → `🇲🇾 马来西亚`、`3ABN` → `🌐 宗教广播`），但 `grep -rn` 全仓**零引用**
—— 只有定义，没有任何地方读取。真正生效的是 `LOGO_REGION_PATTERNS`（9 条，靠 logo）。
本批次没删（不在重构范围），登记在案。

### MTV 副作用（实测，接受不修）

重构把音乐桶的裸 `mtv` 换成 `\bmtv(?![a-z])`。实测 189 条含 `mtv` 的频道里：

- `🎵 音乐频道` 31 条 —— `MTV` / `MTVLive` / `MTVRocks` 之外的真音乐台
- `🎭 综艺频道` 55 条 —— 主要是 **group 字段本身就是 `Entertainment`** 的 MTV 真人秀
  （`MTVCatfish` / `MTVTeenMom` / `MTVRidiculousness` / `MTVTheHills` / `MTVJerseyShore` / `MTVDating`）
- `🌐 国际` 88 条 —— 绝大多数根本不是 MTV，是 `GEMTV` / `MetaFilmTV` / `AdriftTV` 这类
  名字里恰好含 `mtv` 的地方台，**边界修复正是为了把它们赶出去**

判断：55 条落综艺里，真人秀落综艺语义上是对的；只有 `MTVRocks` / `MTVCLASSICS` 这两类纯音乐台
落综艺是遗憾，但它们的数据源 group 就是 `Entertainment`，跟随 group 是既定策略。
**这里不做名字级特例**，登记为已知取舍。

---

## 8. 流可用性实测（`scripts/check_streams.py`）

分组的准确 ≠ 链接活着。逐条 HEAD 请求 `hk_merged.m3u` 里的每条流 URL，
判定口径直接复用 `src/validator.py`（代理域名拒绝 / CDN 白名单 / HEAD 优先）：

```console
$ python scripts/check_streams.py <m3u> --jobs 20 --timeout 10 --json out.json
合计 107  可用 43  不可用 64  可用率 40.2%
$ echo $?
1
```

⚠️ **退出码 1 不是崩溃**：本工具的设计是「有死链就退 1」。

| 退出码 | 含义 |
|---:|---|
| `0` | 全部可用 |
| `1` | **跑完了**，存在不可用条目（`--max-bad-ratio` 传了则是超过该阈值） |
| `2` | 文件不存在 / 解析不出任何频道 —— 这才是真错误 |

| 产物 | 条数 | 可用 | 不可用 | 可用率 |
|---|---:|---:|---:|---:|
| 重构第一版 `a00e134` | 103 | 37 | 66 | 35.9% |
| 当前 `8a292b3` | 107 | 43 | 64 | 40.2% |

**别急着把 35.9% → 40.2% 当成收益。** 两份产物共用 103 条相同频道，逐条对比：

- 可用 → 不可用：**0 条**
- 不可用 → 可用：**5 条**（`中天综合台` / `公视` / `TVBS 新闻台` / `中天新闻台` / `东森洋片台`）

这 5 条是**同一条 URL 两次探测结果不同**（首次超时/源侧抖动），属测量噪声，不是代码效果。
扣掉噪声后：103 条共有频道上可用数 37 → 42，差值 5 全部来自复测恢复。

真正由这次修复新增的 4 条：

| 频道 | 结果 | URL |
|---|---|---|
| `PTS3` | ✅ 可用 | `http://111.59.139.85:11888/tsfile/live/1222_1.m3u8` |
| `HOY78` | ❌ 不可用 | `http://cdn.163189.xyz/live/hoy/stream.m3u8` |
| `HOYInfotainment` | ❌ 不可用 | `https://hoytv-live-stream.hoy.tv/ch78/index.m3u8` |
| `HOY资讯台` | ❌ 不可用 | `http://api.kkitv.itv888.vip:8080/streams/...` |

**「`hk_merged` 103 → 107」这个 +4 里只有 1 条（`PTS3`）是能播的。**
过 Validator 之后 HOY 那三路会被过滤掉 —— 也就是说**真实 CI 产物里的 `hk_merged`
只会变成约 104 条**，而不是 107。分类修对了不等于源能用。

> **重要限定**：上面两份产物都是 `--skip-validation` 跑出来的，本来就该含死链。
> 真实流水线会先过 `Validator` 再写 m3u。这组数字的意义是**回答「新增条目能不能播」**，
> 不是评价产物质量。

分组维度看可用率（当前 107 条）：`🇹🇼 台湾` 31/59 = 53%、`📺 TVB` 5/14 = 36%、
`📺 RTHK` 3/9 = 33%、`🇲🇴 澳门` 1/9 = 11%、`📡 卫视频道` 1/7 = 14%、
`📺 HOY TV` 1/4 = 25%、`📺 ViuTV` 1/3 = 33%、`📺 Now TV` 0/1、`📺 有线电视` 0/1。

---

## 9. 分组相关的已知残留（未修）

- `DetetivesMedicos` 仍判 `🌐 国际`，期望 `📺 纪录片`。其数据源 group 是 `Documentary`，
  但评测集 `known_*.tsv` 只有三列（名字/期望分类/原因）没有 group 列，仅凭名字判不出来。
  拒绝为单个样本硬编码 → 评测脚本因此退出码 1。
- `ATV`（亚洲电视，香港）分类为 `📡 卫视频道` 且 `is_hk_region('ATV')=False` → 不进 `hk_merged.m3u`。
  放宽会把土耳其 `ATVAlanya` 一起收进来，取舍未定。
- `CNNInternational`（无空格连写）落 `🌐 国际频道`，而 `CNN International`（带空格）落 `📰 新闻财经`。
  新闻块**有** `cnn` 规则，实测把它改成 `(?<![a-z])cnn(?![a-z])` 后连写形态**仍然**落 `🌐 国际频道`，
  说明更早被「国际频道」宽桶命中（很可能是 `international` 关键词）。**确切分支未定位。**

---

## 10. 回归护栏

| 护栏 | 作用 |
|---|---|
| `scripts/eval_categorize.py` | 评测集 50/51（24 bugs + 27 good），退出码 1 表示有残留 |
| `tests/test_categorize_golden.py` | 行为钉死表 + 7 条 logo 契约用例 |
| `tests/test_known_defects.py` | 8 条 xfail 契约（`strict=True`，修好后会 XPASS 报错提醒摘标记） |
| `tests/test_category_order_contract.py` | `CATEGORY_ORDER` 契约（11 用例，含「预留分组仍不产出」） |

```console
$ .venv/bin/python -m pytest                        # 323 passed, 7 xfailed
$ .venv/bin/python scripts/eval_categorize.py       # 50/51，退出码 1
$ .venv/bin/python -m ruff check src scripts        # All checks passed!
```
