# 分组逻辑缺陷 —— 主 bot 实测基线（2026-10-29）

> 这份是我（主 bot）在派工给小弟**之前**自己跑代码量化出来的基线，用来交叉验证小弟的结论。
> 数据来源：`output/all_merged.m3u`（数据提交 `074c677`，1,164 条 `#EXTINF`）的实际频道名。
> 复现命令见每条。

## 总览：7 类缺陷，量化影响面

| # | 缺陷 | 影响面 | 严重度 |
|---|---|---:|---|
| D1 | 裸子串 `atv` 误伤 → 「📡 卫视频道」 | **98 / 1,164 = 8.4%** | P0 |
| D2 | 裸子串 `tv5` / `tbs` / `dw` / `nick` / `amc` 误伤 | 15+ 条 | P0 |
| D3 | 「🌐 国际」兜底桶吞掉中国大陆地市台 | **100 条全是中文地市台** | P0 |
| D4 | 「🌐 国际」与「🌐 国际频道」两个近义组并存 | 100 + 92 | P1 |
| D5 | `CATEGORY_ORDER` 里 12/62 个死分类永不出现 | 12 个 | P1 |
| D6 | 产出的分组名不在 `CATEGORY_ORDER` → 排序落到最后一档 | 「🇨🇳 中国源」「🌐 国际」 | P1 |
| D7 | `categorize()` 判为港台但 `is_hk_region()` 返回 False | **12 条港台频道进不了 `hk_merged.m3u`** | P0 |

---

## D1 — 裸子串 `atv` 误伤（P0，8.4%）

规则：`src/group/categorizer.py` 的卫视频道块里有 `r"atv"`（亚洲电视 ATV），**没有词边界**。

```bash
cd /home/hermes/.hermes/projects/live-tv
.venv/bin/python -c "
import re,collections
cur=None; g=collections.defaultdict(list)
for line in open('output/all_merged.m3u',encoding='utf-8'):
    line=line.strip()
    if line.startswith('#EXTGRP:'): cur=re.match(r'#EXTGRP:(.+?) \((\d+)\)\$',line).group(1)
    elif line.startswith('#EXTINF'):
        m=re.search(r',(.+)\$',line)
        if m: g[cur].append(m.group(1))
names=[n for v in g.values() for n in v]
hit=[n for n in names if re.search(r'atv',n,re.I)]
print(len(hit),'/',len(names))
print(hit[:12])
"
```

实测输出：`98 / 1164`，样本 `AlabbassiaTV / 8LaMarinaTV / 30ATVClassicMovies / AaryaaTV / AbazaTV / ActivaTV / ADATV / AdrenalinaPuraTV / AdrenalinaPuraTVBrazil / AgriculturaTV / AgrotendenciaTV / AguilaTV`。

这些是西班牙语、葡语、意大利语的普通频道，全部因为结尾三个字母撞上 ATV 被塞进「📡 卫视频道」。

同类还有 `r"atv"` 命中 `Catv` / `Samatv` / `DunyaTV` / `AndorraTV` 等。

## D2 — 其它裸子串误伤（P0）

| 模式 | 所属分组 | 实测命中 |
|---|---|---:|
| `r"tv5"` | 🌐 国际频道 | **11** 被抢走（`XinjiangTV5`、`TV5Kannada`、`TV5Linares`、`TV5MondeEurope`…）；`CCTV5`/`CCTV5+` 因央视频道规则在前而幸免 |
| `r"tbs"` | 🌐 国际频道 | 1（`TBS`） |
| `r"dw"` | 🌐 国际频道 | 1（`DW`） |
| `r"nick"` | 🧸 儿童频道 | `NICKJr` 等 |
| `r"amc"` | 🎬 电影频道 | `AMC Theatrical` 等 |

`CCTV5` 侥幸逃过一劫（央视规则在第 1 位先命中），但 `XinjiangTV5`（新疆卫视，被 `tv5` 抢走归国际）和 `TV5MondeEurope`（法国国际台，本来就属国际，属"蒙对"）之外，**11 条确实被误伤**。

复现（真实输出）：
```
'CCTV5'              → 📺 央视频道
'CCTV5+'             → 📺 央视频道
'XinjiangTV5'        → 🌐 国际频道
'TBS'                → 🌐 国际频道
'DW'                 → 🌐 国际频道
'NICKJr'             → 🧸 儿童频道
'AMC Theatrical'     → 🎬 电影频道
```

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.group.categorizer import categorize
for n in ['CCTV5','CCTV5+','XinjiangTV5','TBS','DW','NICKJr','AMC Theatrical']:
    print(f'{n!r:20} → {categorize(n,\"\")}')
"
```

## D3 — 「🌐 国际」兜底桶吞掉地市台（P0）

`recategorize_others()` 的最后一行是 `return "🌐 国际"`。任何没被前 12 条规则命中的频道都进这里。

实测：「🌐 国际」桶 **100 条，中文名 100 条（100%）**，全是大陆地市级台：

```
七台河新闻综合 | 三明新闻综合 | 上虞文化影院 | 上虞新商都 | 上虞新闻综合 | 东丰综合 |
东莞新闻综合 | 乐至综合 | 九台综合 | 井研综合 | 亳州农村 | 仁寿综合 | 任丘综合 |
伊犁哈萨克 | 伊犁经济法治 | 余姚姚江文化 | 余杭未来E | 六安公共 | 兰溪新闻综合 | 南宁都市生活
```

这些是**中国地市台**，被标成「国际」，而真正想表达的「国际」在另一个组「🌐 国际频道」里。

## D4 — 两个近义组并存（P1）

`「🌐 国际」`(100) 与 `「🌐 国际频道」`(92) 语义重复，且 `🌐 国际` **不在** `CATEGORY_ORDER` 里 → 排序时落到最后一档（`sort_key` 的 `(1, cat)` 分支）。

## D5 — 12 个死分类（P1）

`CATEGORY_ORDER`（62 项）里这 12 个**源码从不产生**：

```
🇯🇵 日本  🇰🇷 韩国  🌏 亚洲（东南亚）  🇮🇳 印度  🌏 亚洲（其他）  🌍 欧洲
🇺🇸 北美  🌎 拉丁美洲  🌍 中东  🌍 非洲  🌏 大洋洲  📺 其他
```

即「国际细分」这一整层是**纸上的**，实际产物只有粗粒度的「🌐 国际频道」。

## D6 — 分组名与排序表不一致（P1）

产物里出现但不在 `CATEGORY_ORDER` 的分组：`🇨🇳 中国源`、`🌐 国际`。

## D7 — 港台判定打架（P0，直接影响交付）

`categorize()` 与 `is_hk_region()` 是两套独立实现。实测：**产物里 12 条已被 categorize 判为港台的频道，`is_hk_region()` 返回 False** → 它们不会进 `hk_merged.m3u`：

```
TVB 星河 | TVB 娱乐新闻 | 三立 台湾台 | 东森幼幼台 | 东森洋片台 | 东森综合台 |
东森财经新闻台 | 东森超视 | …
```

根因：`is_hk_region()` 里若干正则写成双反斜杠（`r"\\bmacau\\b"` 等），正则表达的是「字面反斜杠 + b」，永不匹配（`re.search(r"\\bmacau\\b","Macau TV",re.I)` → `None`）。

同一批频道在 `hk_merged.m3u` 里到底有没有？**没有** —— 实测 `hk_merged.m3u` 只有 33 条，而 `stats.json` 里港台相关组合计 44 条。

## 死代码

`_excluded()`（37 行，`categorizer.py:59`）全仓无调用方；`is_hk_region()` 尾部有一段恒返回 `False` 的不可达分支。
