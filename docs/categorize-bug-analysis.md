# categorize() 缺陷分析（实测版）

> 分支：`feature/categorize-accuracy`
> 基线提交：`bb29b78`
> 分析对象：`src/group/categorizer.py`（670 行，`categorize()` 13 个顺序 if 块，234 个模式）
> 结论数字全部来自本机实跑，命令与输出附在文末附录；未实测的推断已单独标注「推断」。

---

## 1. 结论摘要

| 指标 | 基线 | 补丁草案后 | 数据来源 |
|---|---|---|---|
| `scripts/eval_categorize.py` known_bugs | **5/24** | **23/24** | 附录 A / B |
| `scripts/eval_categorize.py` known_good | **27/27** | **27/27** | 附录 A / B |
| 真实语料 `🌐 国际` 兜底桶 | **6829 / 13470（50.7%）** | 6448 / 13470（47.9%） | §4.1 / §7 |
| 其中含中文名（=中国地市台等污染） | **968** | **89（-90.8%）** | §4.1 / §7 |
| `📡 卫视频道` 桶 | **603**（其中 585 条来自裸 `atv`） | 37 | §3.2 |
| `📺 央视频道` | 148 | 205 | §3.2 |
| `is_hk_region` 与 `categorize` 冲突条数 | **32** | **0**（不变量 A、B 均 0） | §6 |
| `hk_merged` 候选频道数 | 92 | 141（丢失 0） | §6.4 |
| 仓库测试 | 283 passed / 23 xfailed | 282 passed / 10 xfailed / 14 failed | 附录 C |

「14 failed」中 13 条是 `tests/test_known_defects.py` 的 `xfail(strict=True)` 变成 **XPASS**（缺陷被修好，按该文件的设计必须回来删标记），1 条是 `test_categorize_golden.py::intl-01-bbc-world-news` 与新数据集的口径冲突（详见 §8.3）。**没有任何一条是行为回退。**

---

## 2. 方法与可复现性

### 2.1 语料怎么来的

不跑 pretend 样本，直接用真实源：

```
python .venv/bin/python /home/hermes/.hermes/cache/scratch/livetv_build_corpus.py
#   → 抓 config/sources.yaml 里 20 个源，成功 18 个（sammy0101 / xiweiwong-hk-iptv
#     因 raw.gh.registry.cyou DNS 解析失败，本次没抓到）
#   → 原始 20929 条 → 按 URL 去重 19623 条
python .venv/bin/python /home/hermes/.hermes/cache/scratch/livetv_make_corpus.py
#   → 走真实 Grouper.group()（normalize + 合并同名 + categorize）
#   → 最终 13470 条，52 个分组，落盘 corpus.tsv（cat / name / group / logo）
```

语料规模 13470 条，与线上产物 `output/stats.json`（`🌐 国际` 3893、各组求和 8,371）同一量级、同一形态：本次没做 URL 校验（线上 Validator 会过滤掉一部分），所以绝对数偏大，但**分布形态一致**（`🌐 国际` 都是第一大桶）。

### 2.2 规则块怎么抽的

用 `ast` 从源码抽列表字面量与紧随的 `return` 分类，避免手抄 234 个模式抄错：
`livetv_ast_blocks.py` → 10 个关键字列表共 203 个模式 + 31 个内联 `re.search`/`_match` 模式 = 234。

### 2.3 指标怎么算的

- **命中 / 夺标 / 被遮蔽**：对每条语料，逐块逐模式 `re.search`；`夺标` = 最终分类等于该块分类，`被遮蔽` = 命中但最终落到别的分类。
- **内嵌命中（embedded）**：命中的子串前后两侧都是 `[A-Za-z0-9]`，即"匹配落在更长的单词内部"——这是裸子串误伤的**直接证据**，不靠主观判断。
- 脚本：`livetv_rule_audit.py`（规则级）、`livetv_profiles.py`（兜底桶/港区/死分类/裸模式清单）、`livetv_drift.py`（补丁前后逐条漂移）。

---

## 3. 缺陷清单（19 条，按实测影响面排序）

影响面 = 全量 13470 条语料中**实际改变分组的条数**或**实测误伤条数**。前 10 条见 §3.1，其余见 §3.2。

### 3.1 影响面 TOP 10

| # | 缺陷 | 位置 | 实测影响面 |
|---|---|---|---|
| D01 | 裸 `atv` 把一切 `*atv*` 当香港亚视 | `:515` | **585 条命中，416 条分组改变**（702 内嵌命中样例中 70 条明显误伤） |
| D02 | `🌐 国际` 是唯一兜底，中国地市台全灌进来 | `:460` / `:670` | **6829 条（50.7%）**，其中中文名 968 条，`新闻综合` 类 113 条 |
| D03 | 中文 `group-title` 完全没映射（只有英文表） | `:242-300` | 兜底桶里 **1763 条**带中文 group（`綜合` 250 / `新聞` 135 / `綜藝` 128 / `電影` 88 / `浙江频道` 64 …） |
| D04 | 央视正则用 `\b`，在「数字+中文」边界失效 | `:473-485` | 24 条实测（`cctv1综合`、`cctv10科教`、`cctv5plus`、`CGTN×6`…）；语料里 153 个含 cctv 的名字只有 148 条落在央视频道 |
| D05 | `is_hk_region` 与 `categorize` 两套关键词各写一份 | `:101-236` vs `:491-550` | **32 条**「分类是港澳台却进不了 hk_merged」+ 5 条反向 |
| D06 | 双反斜杠正则 `r"\\bmacau\\b"` 永远匹配不到 | `:143`（`ttv/ftv/pts/cna` 见 `:141`） | 澳门 2 条（`Macau TV`/`Macau`）+ 台湾 24 条（`TVBSNews`/`CNA`/`FTV`/`TTV`…） |
| D07 | 裸 `tv5` | `:583` | 40 条命中 / **7 条内嵌误伤**（`VTV5TayNamBo`、`SuperTV55`、`XinjiangTV5`、`cctv5plus`） |
| D08 | 国际频道块（7）先于新闻财经块（8） | `:579` vs `:597` | `cnn` 19 次命中 **0 次夺标**；`documentary` 223 命中 16 条被 `bbc` 截走 |
| D09 | 裸 `dw` | `:583` | 20 条命中 / **13 条内嵌误伤**（`AnandWariTV`、`HeartlandWeb`、`MarriedwithChildren`） |
| D10 | 裸 `nba` / `cba` | `:649` | `nba` 13 命中 12 条内嵌误伤（`ATNBangla`、`BaanBaanTV73`…）；`cba` 5 命中 5 条误伤（`CBCTelevisionCBAT-DT`…） |

### 3.2 其余 9 条

| # | 缺陷 | 位置 | 实测影响面 |
|---|---|---|---|
| D11 | 裸 `tbs` | `:581` | 5 条命中 / 2 条内嵌（`JTBSClassic`、`RTBSukmaindera`） |
| D12 | 裸 `amc` / `hbo`（电影块） | `:555` | `amc` 18 命中 2 条误伤（`IAmChannel`、`IslamChannel`）；`hbo` 19 命中 4 条误伤（`KhushbooBangla`、`NHBollyFlix/Gold`） |
| D13 | `kids_kw` 里根本没有 `kids` | `:612-621` | `DiscoveryKidsLatinAmericaChile` 被 `discovery` 判成纪录片；`\bkids?\b` 缺失 |
| D14 | `nick` 无边界（风险项，实测 0 误伤） | `:615` | 39 条命中，内嵌 0 —— 当前无害，但和其他品牌词不一致，属"下一颗雷" |
| D15 | `recategorize_others` 能把未知 group 整组塞进 `📺 TVB` | `:432-434` | 条件苛刻（须 `is_hk_region` 为真），本次语料未触发；属逻辑炸弹 |
| D16 | 分组名漂移 `'🎵 音乐'` vs `'🎵 音乐频道'` | `:441` | 该分支在 13470 条语料中 **0 命中**（潜伏缺陷）；一旦命中会产出 `CATEGORY_ORDER` 里没有的分组 |
| D17 | 死分类：`CATEGORY_ORDER` 62 项里 13 项从不产出；另有 3 项产出却不在表内 | `generator.py:15-52` | 死分类：`📺 其他`、`🇯🇵 日本`…`🌏 大洋洲` 共 13 项；未排序：`🇨🇳 中国源`(116)、`🌐 国际`(6829)、`🇲🇾 马来西亚`(4) → 排序落到最后一档 |
| D18 | `_excluded()` 死代码（23 个模式从不生效） | `:59-95` | 全仓库无调用点（`grep` 验证），维护者以为有排除逻辑 |
| D19 | `CHANNEL_REGION_PATTERNS` 定义但从不读取 | `:321-358` | `3ABN→宗教广播`、`TVP→欧洲`、`AlmereTV→荷兰`、`DSTV→非洲` 等 20 条映射全部失效 |

---

## 4. 逐条详证（含复现命令与真实输出）

### 4.1 D02 + D03：兜底桶污染

**触发条件**：频道名与 group 都命中不了前 12 个块 → `recategorize_others()` → 省级/港澳台/英文 group 都不中 → `return "🌐 国际"`。而中国地市台（`七台河新闻综合`、`余姚新闻综合`）、央视变体（`cctv1综合`）、源站给的中文 group（`浙江频道`、`地方频道`）都不在任何一张表里。

**复现**：

```bash
$ .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.group.categorizer import categorize
for n in ['七台河新闻综合','余姚新闻综合','伊犁哈萨克','cctv1综合','YMG未来']:
    print(n, '->', categorize(n, ''))"
七台河新闻综合 -> 🌐 国际
余姚新闻综合 -> 🌐 国际
伊犁哈萨克 -> 🌐 国际
cctv1综合 -> 🌐 国际
YMG未来 -> 🌐 国际
```

（`YMG未来` 的真实 group 是 `浙江频道`，同样是中文 group 未映射。）

**影响面（语料实测）**：

```
=== 🌐 国际 桶: 6829 条 / 全量 13470 (50.7%)
  含中日韩字符: 968 (14.2%)   纯拉丁: 5861
  中文名尾部特征分布: 新闻综合 113 / 少儿 12 / 电视台 11 / 频道 9 / 科教 8 / 民生 5 …
  国际桶内 group 分布 TOP12: General 2154, Undefined 1208, Religious 645, '' 389,
      綜合 244, Legislative 162, 新聞 156, Culture 117, 綜藝 115, 運動 95, 電影 91,
      直播中国 88
带中文 group 的条目数: 1763 / 6829
```

`General`/`Undefined`/`Religious` 是英文表里主动映射到 `🌐 国际` 的（`GROUP_TITLE_EN_MAPPING:272-279`），这部分是"真·长尾"，可接受；**问题在 1763 条带中文 group 的**——它们本该按 group 落位。

**建议修法**：① 中文 `group-title` 映射表（只收语义明确的）；② 地市台三级判据（后缀 / 纯中文名 / 中文 group）；③ 省级分组名 `XX频道` → `📺 XX`。

**风险**：中文 group 里 `綜合`/`電影`/`新聞` 有源站误标（实测 `group=綜合` 下的名字是 `aastha`、`alrayyan` 这类印度/中东频道），**不能**无脑映射——必须按 group 抽样验证后再收（本补丁只收 9 个 group，见方案文档 §3.3）。

### 4.2 D01：裸 `atv`

**触发条件**：`overseas_satellite` 里有裸 `r"atv"`（`:515`），任何名字里出现 `atv` 三个字母的频道都会在**第 4 块**被判为 `📡 卫视频道`，而第 4 块在电影/新闻/体育之前。

**复现**：

```bash
$ .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.group.categorizer import categorize
for n in ['AricaTV','Catv','VoATV','ATV','DunyaTV']: print(n,'->',categorize(n,''))"
AricaTV -> 📡 卫视频道
Catv -> 📡 卫视频道
VoATV -> 📡 卫视频道      # VOA 是新闻台，被 atv 截走
ATV -> 📡 卫视频道        # 这条是对的
DunyaTV -> 📡 卫视频道
```

**影响面**：585 条命中，其中 70 条匹配落在更长单词内部（`30ATVClassicMovies`、`AdrenalinaPuraTVBrazil`、`AfricaTV3`…）。补丁后 `📡 卫视频道` 从 603 条降到 37 条，`atv` 仅剩 `ATV`、`ATV+`、`atv` 这类真亚视名称（`\batv\b` 实测仍命中 4 条）。

**建议修法**：`r"\batv\b"`；`Asia Television`/`亚洲电视` 保留。

**风险**：`ATV World`/`ATV Home` 之类仍命中（`\b` 在空格处成立），符合预期；`ATVHD`（无分隔）会漏 —— 语料中 0 例，可接受。

### 4.3 D04：央视正则的 `\b` 在 CJK 边界失效

**触发条件**：`r"\bcctv[\-_ ]?(\d+|news|…)\b"`。Python 的 `\b` 把 CJK 当 `\w`，所以 `cctv1综合` 里数字与「综」之间**没有边界**，整条规则不成立；退路 `r"\bcctv\b"` 同样要求 `cctv1` 后是边界，也失败。

**复现**：

```bash
$ .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.group.categorizer import categorize
for n in ['CCTV-1','cctv1综合','cctv10科教','cctv5plus','CGTN英语']: print(n,'->',categorize(n,''))"
CCTV-1 -> 📺 央视频道
cctv1综合 -> 🌐 国际          # 应为央视频道
cctv10科教 -> 🌐 国际
cctv5plus -> 🌐 国际频道      # 而且是被下面的 tv5 抢走的
CGTN英语 -> 🌐 国际
```

**影响面**：语料里 153 个含 `cctv` 的名字，24 条不在央视频道（`cctv1综合`/`cctv2财经`/`cctv3综艺`/`cctv4e`/`cctv4欧洲`/`cctv4美洲`/`cctv4中文国际`/`cctv5体育`/`cctv5plus`/`cctv5plus体育赛事`/`cctv6电影`/`cctv9纪录`/`cctv10科教`/`cctv11戏曲`/`cctv13新闻`/`cctv14少儿`/`cctv15音乐`/`cctv第一剧场` + `CGTN` 6 条 + `CCTV4K真`/`CCTV4欧洲`/`CCTV4美洲`/`CCTV中学生`/`CCTV发现之旅`/`CCTV老故事` 6 条走 logo 判成 `🇨🇳 中国源`）。补丁后 央视频道 205 条。

**建议修法**：改用 `(?![a-z])`（只挡拉丁字母后缀）而不是 `\b`；把 `CGTN` 纳入。

**风险**：`\bcctv` 前缀匹配会命中 `CCTV5+`/`CCTV4K` 等（期望）；`RCCTV`/`RedCCTV` 因前有字母不受 `\b` 约束（实测仍留在 `🌐 国际`，符合"非央视"）。

### 4.4 D05 + D06：港澳台判定两套实现互相打架

**触发条件 A（双反斜杠）**：`is_hk_region` 里 `mo_exact = [r"澳门", r"澳視", r"\\bmacau\\b", …]`（`:143`）——`r"\\b"` 是**字面反斜杠 + b**，不是词边界，因此对 `Macau TV` 永不匹配；`tw_exact` 的 `r"\\bttv\\b"` 等同理（`:141`）。

**触发条件 B（关键词集不一致）**：`categorize` 的台湾块用裸 `r"tvbs"`（`:492`），`is_hk_region` 用 `tvb_kw_exact` 的 `r"\btvbs\b"`，而 `TVBSNews` 里 `tvbs` 后面紧跟 `n`，`\b` 不成立；更狠的是 `exclude` 里的 `r"\btvb(?=[a-z])"`（`:172`）会先把 `tvbsnews` 判死。

**复现**：

```bash
$ .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.group.categorizer import categorize, is_hk_region
for n in ['Macau TV','Macau','TVBSNews','CNA','FTV','TTV','TDM','Now財經']:
    c=categorize(n,''); print(f'{n:10} cat={c:12} hk={is_hk_region(n,\"\",c)}')"
Macau TV   cat=🇲🇴 澳门       hk=False
Macau      cat=🇲🇴 澳门       hk=False
TVBSNews   cat=🇹🇼 台湾       hk=False
CNA        cat=🇹🇼 台湾       hk=False
FTV        cat=🇹🇼 台湾       hk=False
TTV        cat=🇹🇼 台湾       hk=False
TDM        cat=🌐 国际       hk=False
Now財經    cat=🌐 国际       hk=False
```

**影响面（语料实测）**：
- A 向（分类是港澳台，却进不了 hk_merged）：**32 条**——`🇹🇼 台湾` 24、`📺 HOY TV` 4、`🇲🇴 澳门` 2、`📺 Now TV` 2。
- B 向（`is_hk_region=True` 但分类不是港澳台）：5 条（`凤凰卫视`/`星空卫视`×2/`凤凰香港台`/`无线新闻台`）——其中 `无线新闻台` 是 TVB 子频道被判成 `📰 新闻财经`，属分类错。

**建议修法**：把港澳台判定抽成唯一事实来源 `_region_category()`，`is_hk_region` 与 `categorize` 都调它；`凤凰/星空` 单独归入「仅地域」表（地域属港、分类归卫视）。验收用不变量断言（§6）。

**风险**：`hk_merged` 会新增约 50 条（实测 92→141，含 `PhoenixChineseChannel`/`PhoenixInfoNewsChannel`/`TVBSNews`/`TDM-MacauSatellite` 等），需要人工抽查一遍新增项；**实测更正**：本次合并后 `is_hk_region()` 覆盖 92 → 141，**丢失 0 条**（后续第二遍修 `\b` 在 CJK/数字边界失效的问题，最终覆盖为 92 → 145，见 README「第二遍修正」）（`凤凰香港台` / `凤凰卫视` / `星空卫视` / `StarTV` / `phoenix` 仍全部 `hk=True`）。原稿此处写的「`凤凰香港台` 会从 hk 列表消失」不成立，已删。真正的残留是反过来的：`ATV`（亚洲电视，香港）实测 `is_hk_region('ATV')=False`、分类却是 `📡 卫视频道`，因为 `\batv\b` 现在命中「卫视频道」规则而港区规则没有裸 ATV 词条。

### 4.5 D07–D12：其余裸子串

统一复现命令（判据：命中子串前后都是字母数字 ⇒ 落在单词内部 ⇒ 误伤）：

```bash
$ .venv/bin/python /home/hermes/.hermes/cache/scratch/livetv_profiles.py   # 裸模式清单段落
  'atv'        在 📡 卫视频道     hits=585  内嵌=70   例: ['30ATVClassicMovies','AdrenalinaPuraTVBrazil','AfricaTV3']
  'dw'         在 🌐 国际频道     hits=20   内嵌=13   例: ['AnandWariTV','HeartlandWeb','IMPDTVWorldwide']
  'nba'        在 ⚽ 体育频道     hits=13   内嵌=12   例: ['ATNBangla','ATNBanglaUK','AfarinBaxcha']
  'tv5'        在 🌐 国际频道     hits=40   内嵌=7    例: ['SuperTV55','VTV5TayNamBo','VTV5TayNguyen']
  'cba'        在 ⚽ 体育频道     hits=5    内嵌=5    例: ['CBCTelevisionCBAT-DT','IBCBakthi','RepublicBangla']
  'hbo'        在 🎬 电影频道     hits=19   内嵌=4    例: ['KhushbooBangla','NHBollyFlix','NHBollyGold']
  'amc'        在 🎬 电影频道     hits=18   内嵌=2    例: ['IAmChannel','IslamChannel']
  'tbs'        在 🌐 国际频道     hits=5    内嵌=2    例: ['JTBSClassic','RTBSukmaindera']
  'trt'        在 🌐 国际频道     hits=28   内嵌=3    例: ['HTRTV','RTRTV','RTTRTrentino']
  'mtv'        在 🎵 音乐频道     hits=234  内嵌=10   例: ['BestofMTVDK','CFMTVChannel98','CMTvKenya']
  'movie'      在 🎬 电影频道     hits=741  内嵌=106  例: ['24HourFreeMovies','ABNBibleMoviesChannel']
  'cinema'     在 🎬 电影频道     hits=50   内嵌=8    例: ['MyCinemaEurope','PlutoTVCinemaItaliano']
  'nick'       在 🧸 儿童频道     hits=39   内嵌=0
```

**关键判据（写进方案文档 §2.2）**：内嵌命中多 ⇒ 必须加边界；内嵌命中多但语义仍正确（`movie`/`cinema` 是内容词，`24HourFreeMovies` 本来就是电影台）⇒ **不能**加边界；内嵌 0（`nick`）⇒ 可加可不加，为一致性加。

**风险（必须写进 review 说明）**：`mtv` 加边界后语料里 88 条离开 `🎵 音乐频道`（原本靠 `agrfmtv`/`adhyatm tv` 里的 `mtv` 误中，实测多为宗教/综合台，是**修正**），但同时 55 条真·MTV 类节目（`BestofMTV`、`HumTV`）因 `\bmtv` 要求前置边界而改由 `group=Entertainment` 落到 `🎭 综艺频道`。这是本次补丁里**唯一一处需要产品口径拍板**的取舍（保留裸 `mtv` 则 88 条宗教台继续被误判为音乐）。

### 4.6 D08：国际频道块抢在新闻财经前面

**触发条件**：块 7 `intl_kw` 有裸 `r"bbc"`/`r"cnn"`，块 8 `news_kw` 也有 `r"cnn"`；块 7 在前，所以 `CNN International`、`BBC World News` 永远停在 `🌐 国际频道`。

**复现**：

```bash
$ .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.group.categorizer import categorize
for n in ['CNN International','BBC World News','CNN Portugal','Al Jazeera English','TRT World']:
    print(f'{n:22} -> {categorize(n,\"\")}')"
CNN International      -> 🌐 国际频道
BBC World News         -> 🌐 国际频道
CNN Portugal           -> 🌐 国际频道
Al Jazeera English     -> 🌐 国际频道
TRT World              -> 🌐 国际频道
```

**影响面**：`cnn` 在语料中 19 次命中、**0 次夺标**（全部被块 7 截走）；`documentary` 223 命中里 16 条被裸 `bbc` 截走（`BBCEarthCzechia`、`AlJazeeraDocumentary` 等）。

**建议修法**：新增一个**高优先级窄规则**（只认 `cnn international|intl`、`bbc world news|bbc news`），放在块 7 之前；**不要**把新闻块整体前移，否则 `CNN Portugal`（known_good 要求 `🌐 国际频道`）会退化。

**风险**：口径争议——见 §8.3，仓库里 `tests/test_categorize_golden.py::intl-01-bbc-world-news` 断言的正是"BBC World News → 🌐 国际频道"，与 `known_bugs.tsv` 的期望相反。**二者必须选一个**，本补丁按数据集（`新闻财经`）实现，并建议同步更新 golden 用例。

### 4.7 D13：`kids_kw` 缺 `kids`

**复现**：

```bash
$ .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from src.group.categorizer import categorize
print(categorize('DiscoveryKidsLatinAmericaChile',''))"
📺 纪录片
```

`kids_kw`（`:612-621`）列了 `cartoon/disney/nick/少儿/儿童…` 但没有 `kids` 本身，所以 `Discovery Kids` 只能被块 13 的 `discovery` 收走。**影响面**：语料中含 `kid` 的频道 41 条补丁后从 `🌐 国际` 迁到 `🧸 儿童频道`。
**注意**：`\bkids?\b` 在 `DiscoveryKidsLatinAmerica` 上**仍然失败**（`kids` 后紧跟 `latin`，无边界），实测必须用裸 `r"kids"`。这条教训已写入方案文档 §2.2 的判据。

### 4.8 D17：死分类与未排序分类

```bash
$ .venv/bin/python /home/hermes/.hermes/cache/scratch/livetv_profiles.py   # 「分组名一致性」段落
=== 分组名一致性
  产出但不在 CATEGORY_ORDER（排序甩到末尾）: ['🇨🇳 中国源', '🇲🇾 马来西亚', '🌐 国际']
  CATEGORY_ORDER 里有、全量语料从不产出（死分类）: ['📺 有线电视', '🇯🇵 日本', '🇰🇷 韩国',
    '🌏 亚洲（东南亚）', '🇮🇳 印度', '🌏 亚洲（其他）', '🌍 欧洲', '🇺🇸 北美', '🌎 拉丁美洲',
    '🌍 中东', '🌍 非洲', '🌏 大洋洲', '📺 其他']
  产出分组数=52  CATEGORY_ORDER=62
```

（`📺 有线电视` 为何 0 产出，已逐条核过：语料中含 `有线/有線/cable` 的只有 11 条，其中唯一的中文名是 `有线新闻`（规则要求完整「有线电视」，未命中，最终按 logo 落 `🇨🇳 中国源`），其余 `CharoenCable37TV`/`CableImagenArmstrong`/`Kuban24` 等是泰国、美国、俄罗斯的有线网，本就不属香港有线。）

`sort_key()` 对未知分类返回 `(1, cat)`，即 `🌐 国际`（6829 条，最大桶）在产物里被排到**所有已知分组之后**，且按字符串序和其他未排序分类混在一起。

---

## 5. 词边界审计总表（10 个关键字列表 + 6 个内联块）

| 块 | 行号 | 模式数 | 主要问题 |
|---|---|---|---|
| 央视（内联） | 473-485 | 4 条正则 | `\b` 对 CJK 失效；缺 `CGTN`；`cctv5plus` 落到 `tv5` |
| 省级 | 486-488 | 32×~7 | 纯中文关键词，`XinjiangTV5`/`ZhejiangSatelliteTV` 这类拉丁写法 0 覆盖 |
| 台湾 | 491-506 | 35 | 与 `is_hk_region.tw_exact` 不同步（裸 `tvbs` vs `\btvbs\b`） |
| 卫视频道 | 510-519 | 12 | 裸 `atv`（D01）；`star tv`/`startv` 无边界（`DaystarTV` 误伤 2 条） |
| TVB/ViuTV/RTHK/HOY/Now/有线/澳门 | 524-550 | 26 | 拼在一坨正则里、`hoy` 裸匹配（`iHOY爱历史` 误伤）；`now财经` 只有简体 |
| 电影 | 553-563 | 19 | 裸 `hbo/amc/mgm`；`cinema`/`movie` 是有意不加边界（内容词） |
| 音乐 | 568-574 | 12 | 裸 `mtv`（10 条内嵌）；`vmv`/`m tv` 实际 0 命中 |
| 国际频道 | 579-592 | 29 | 裸 `bbc/cnn/tbs/dw/trt/tv5`；块序早于新闻块（D08） |
| 新闻财经 | 597-607 | 18 | `cnn` 被块 7 全量遮蔽（19 命中 0 夺标） |
| 儿童 | 612-621 | 17 | 缺 `kids`（D13）；`nick` 无边界（D14） |
| 综艺 | 626-633 | 14 | `综合台`/`综合频道` 与省级/地市台抢食（6 条被遮蔽） |
| 体育 | 638-653 | 33 | 裸 `nba`/`cba`（D10）；`espn` 无边界但语料 0 内嵌 |
| 纪录片 | 658-665 | 14 | 无边界问题；但块序在儿童之后，靠 `discovery` 抢 `Discovery Kids` |

**被遮蔽命中 TOP**（规则命中但最终丢给别的块，说明块序有问题）：

```
  19  lost  📰 新闻财经   'cnn'           hits=19   won=0
  16  lost  📺 纪录片     'documentary'   hits=223  won=207
   9  lost  🎬 电影频道   '影视'          hits=57   won=48
   8  lost  📰 新闻财经   '财经'          hits=13   won=5
   7  lost  🎬 电影频道   'movie'         hits=741  won=734
   6  lost  🎭 综艺频道   '综艺'          hits=22   won=16
```

`电影/综艺/财经` 被遮蔽是**合理**的（省级/港澳台优先，`广东影视` 本就该进 `📺 广东`）；只有 `cnn` 是块序 bug。

---

## 6. 分类一致性契约的现状与验收

### 6.1 现存的三个不变量（本补丁固定下来）

- **A（单向，必须成立）**：`categorize()` 返回港澳台品牌分类（`📺 TVB`/`📺 ViuTV`/`📺 RTHK`/`📺 HOY TV`/`📺 Now TV`/`📺 有线电视`/`🇲🇴 澳门`/`🇹🇼 台湾`）⇒ `is_hk_region()` 必须为 `True`。
- **B（单向，必须成立）**：`is_hk_region()` 为 `True` 的频道，分类不得是 `🌐 国际` / `🌐 国际频道`（否则就是"进了港区列表却没人认识"）。
- **C（允许的反向例外）**：`凤凰卫视`/`凤凰香港台`/`星空卫视` 这类"地域属港、内容属卫视"的频道可以 `hk=True` 而分类为 `📡 卫视频道`——这是有意的，因为 `hk_merged.m3u` 是**地域**筛选器，不是分类筛选器。

### 6.2 实测

```
=== 不变量 A（categorize 判港澳台但 hk_region=False）：违反 0 条      （基线 32 条）
=== 不变量 B（hk_region=True 却落 🌐 国际/国际频道）：违反 0 条        （基线 0 条，因凤凰被分类到卫视）
=== 不变量检查（基线）：违反 32 条
```

### 6.3 为什么不能简单合并成"分类 ⇔ 地域"

`tests/test_categorize_golden.py` 明确断言 `凤凰卫视中文台`/`星空卫视` 的港区判定为 `True`（sat-01..04），而 `known_good.tsv` 要求它们的分类是 `📡 卫视频道`。所以契约只能是**单向包含 + 显式白名单**，不能是等价。任何"统一成一张表就完事"的方案都会撞上这两条既有契约之一。

### 6.4 hk_merged 影响

```
=== hk_merged 候选集规模：基线 92 → 候选 141
   新增样例: ['CanalMacau','FTV','NOWNEWS','PhoenixChineseChannel','PhoenixInfoNewsChannel',
             'StarTV','TDM-MacauSatellite','TTV','TVBSNews','TVBSNews*$','TVBS亚洲','TVBS欢乐台']
   丢失样例: []
```

---

## 7. 补丁后兜底桶的真实成分（说明"没做完的部分"）

```
=== 国际桶 6448（基线 6829），含中文 89（基线 968）
   group TOP15: General 2387, Undefined 1310, Religious 744, '' 397, 綜合 250,
                Legislative 168, 新聞 135, 綜藝 128, Culture 127, 運動 98, 電影 88,
                Lifestyle 85, 其它 78, Shop 68, 知識 56
   残余中文样例: BBS佛教广播 / Fox新闻 / chc动作电影 / 世界地理 / 东北热剧 / 中国之声 /
                中国功夫 / 乌兰察布新闻 / 亚洲新闻 / 八大第一台 / 内江科教生活 / 内蒙少儿 …
```

剩下 89 条中文名的成因（逐类已核）：
1. **繁体 group 误标**（`電影` 88 / `新聞` 135 / `綜藝` 128 / `運動` 98 / `知識` 56 / `綜合` 250）：抽样显示这些 group 下多为拉丁名外国台，**映射它们会把噪声灌进中文分类**，因此刻意不映射。
2. **397 条 `group=''` 的脏名字**：name 字段本身是 `Chile"tvg-id=""tvg-country="智利"…group-title="儿童",yettv` 这种解析残渣（`generator.is_clean_name()` 只过滤 `chrome/`、`group-title="#EXTGRP`，漏掉这一类）。属数据清洗问题，不属分类问题（见 §8.2）。
3. 少量 `中国之声`（收音机）、`中国功夫`/`东北热剧`（点播内容）、`内蒙少儿`（少数民族语少儿）——需要专门的"内容型"分类或上游过滤。

**这就是"国际仍是 47.9%"的诚实解释**：剩余大头是 iptv-org 的 `General`/`Undefined` 长尾（真实无 genre 信息），继续压它需要「产地识别」（按 tvg-country / logo 域名 / 语言字段），不是再加关键词能解决的。

---

## 8. 未纳入本次补丁的问题（如实登记）

### 8.1 D15/D16 只做"顺手修"，没有专门测试
`recategorize_others` 的 `暂归 📺 TVB` 分支与 `'🎵 音乐'` 分支在 13470 条语料中 **0 命中**，补丁里直接删掉了这两段逻辑（改为统一命名 + 地域表），但没有为此新增回归用例（`tests/` 不在本 lane 的写权限内）。

### 8.2 脏频道名（389 条）
`group=''` 且 name 含 `tvg-id=`/`group-title=` 残渣的条目有 389 条，属 `src/fetcher.py` 解析 + `src/generator.py:is_clean_name()` 的职责，**本 lane 未改**（禁改 `src/`）。建议在 fetcher 解析层修：`#EXTINF` 行里出现两个 `tvg-` 属性时按最后一个逗号切名。

### 8.3 数据集与 golden 测试互相矛盾（需 owner 拍板）
| 用例 | `known_bugs.tsv` 期望 | `tests/test_categorize_golden.py` 断言 | 本补丁选择 |
|---|---|---|---|
| `BBC World News` | `📰 新闻财经` | `🌐 国际频道` | 按数据集 → `📰 新闻财经`，golden 用例需同步改 |

同样，`tests/test_known_defects.py` 里 13 条 `xfail(strict=True)` 已被修好（XPASS），按该文件自己的规则必须**删掉标记**，否则 CI 会红。这两处都需要有 `tests/` 写权限的人来做（见方案文档 §5 步骤 5）。

### 8.4 `DetetivesMedicos` 这类"只能靠 group 判"的样本
`eval_categorize.py` 调的是 `categorize(name, "")`——**group 恒为空**。`DetetivesMedicos`（真实 group=`Documentary`）在只看名字时没有任何可判据，补丁后仍是 `🌐 国际`（known_bugs 23/24 的那 1 条失败）。**不建议**为它加 `detetives` 之类的样本级硬编码；建议把 `eval_categorize.py` 的数据集扩成 3 列（name/expected/group），或在 `known_bugs.tsv` 里注明"需 group"。

### 8.5 未做的事
- 没有逐步（按迁移步骤）实测中间态数字，方案文档 §5 里标了「预估」的地方请勿当作实测。
- 未验证 `hk_merged.m3u` 新增的 49 条频道的可用性（只验证了分类口径），URL 有效性依赖 Validator。
- 繁体/少数民族语/方言台（`内蒙少儿`、`八大第一台`）没有专门规则。

---

## 附录 A：基线 eval 原始输出

```
$ .venv/bin/python scripts/eval_categorize.py
known_bugs  (误判修复集): 5/24 通过
    FAIL 'AricaTV': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'BarazaTV': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'AndorraTV': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'AlkarmaTV': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'AgenciaTV': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'Samatv': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'DunyaTV': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'Catv': 期望 🌐 国际 / 实际 📡 卫视频道
    FAIL 'XinjiangTV5': 期望 📺 新疆 / 实际 🌐 国际频道
    FAIL 'TBS': 期望 🌐 国际 / 实际 🌐 国际频道
    FAIL 'DiscoveryKidsLatinAmericaChile': 期望 🧸 儿童频道 / 实际 📺 纪录片
    FAIL 'DetetivesMedicos': 期望 📺 纪录片 / 实际 🌐 国际
    FAIL 'Now財經': 期望 📺 Now TV / 实际 🌐 国际
    FAIL 'TDM': 期望 🇲🇴 澳门 / 实际 🌐 国际
    FAIL 'BBC World News': 期望 📰 新闻财经 / 实际 🌐 国际频道
    FAIL 'CNN International': 期望 📰 新闻财经 / 实际 🌐 国际频道
    FAIL '七台河新闻综合': 期望 🇨🇳 中国源 / 实际 🌐 国际
    FAIL '余姚新闻综合': 期望 🇨🇳 中国源 / 实际 🌐 国际
    FAIL '伊犁哈萨克': 期望 🇨🇳 中国源 / 实际 🌐 国际
known_good  (不退化集): 27/27 通过

合计: 32/51

RESULT: FAIL
```

## 附录 B：补丁 apply 后 eval 原始输出（在 `/tmp` 外的独立副本上 apply，仓库 `src/` 未改动）

```
$ cd /home/hermes/.hermes/cache/scratch/livetv/applytest   # = 仓库 src/tests/scripts 的干净副本
$ git apply /home/hermes/.hermes/cache/scratch/livetv/categorizer-fix.diff
Applied patch src/group/categorizer.py cleanly.
$ .venv/bin/python scripts/eval_categorize.py
known_bugs  (误判修复集): 23/24 通过
    FAIL 'DetetivesMedicos': 期望 📺 纪录片 / 实际 🌐 国际
known_good  (不退化集): 27/27 通过

合计: 50/51

RESULT: FAIL
```

## 附录 C：pytest（同一副本）

```
# 基线副本（未打补丁）
283 passed, 23 xfailed in 3.62s

# 打完两个补丁
14 failed, 282 passed, 10 xfailed in 1.06s
   ├─ 13 × XPASS(strict) tests/test_known_defects.py  → 缺陷已修，需删 xfail 标记
   └─ 1  × test_categorize_golden[intl-01-bbc-world-news] → 与 known_bugs 口径冲突（§8.3）
```

## 附录 D：复现脚本清单（均在 scratch，不入库）

| 脚本 | 作用 |
|---|---|
| `/home/hermes/.hermes/cache/scratch/livetv_build_corpus.py` | 抓 20 个真实源 → 存原始 m3u |
| `/home/hermes/.hermes/cache/scratch/livetv_make_corpus.py` | 解析 + 走 Grouper → `corpus.tsv`(13470 条) |
| `/home/hermes/.hermes/cache/scratch/livetv_ast_blocks.py` | ast 抽取 13 块 / 234 模式 |
| `/home/hermes/.hermes/cache/scratch/livetv_rule_audit.py` | 命中/夺标/被遮蔽/内嵌命中 |
| `/home/hermes/.hermes/cache/scratch/livetv_profiles.py` | 兜底桶成分、港区冲突、死分类、裸模式清单 |
| `/home/hermes/.hermes/cache/scratch/livetv_score.py` | 任意 categorizer 版本的 eval + 分布度量 |
| `/home/hermes/.hermes/cache/scratch/livetv_drift.py` | 基线 vs 候选逐条漂移 + 不变量断言 |

---

## 9. 未验证 / 已知残留（不要当成已解决）

| 项 | 状态 |
|---|---|
| `DetetivesMedicos` 仍判 `🌐 国际` | **未解决**（known_bugs 唯一的 1 条失败）。`eval_categorize.py` 只传 name、group 恒为空，该样本真实 group=`Documentary`，仅凭名字不可判；不建议加样本级硬编码 |
| `📺 HOY TV` 5→1、`📺 Now TV` 3→2 | **未逐条核实**。分布上确实减少了 4 条 HOY 与 1 条 Now，但 `grep -iE "hoy|now" corpus.tsv` 未找到对应的真实 HOY/Now 频道名（只命中 `Canal+Now`、`NBCSportsNOW`、`ScientologyNetwork` 等无关条目），疑为基线裸 `hoy`/`now tv` 误命中后被移出，**具体损失项未逐条确认** |
| 13 条 `xfail(strict=True)` 变 XPASS | **需有 tests/ 写权限的人删标记**，否则 CI 红（这是修好缺陷的正常后果，非回归） |
| `test_categorize_golden[intl-01-bbc-world-news]` 失败 | **需人工裁决**：golden 断言 `🌐 国际频道`，`known_bugs.tsv` 要求 `📰 新闻财经`，二者互斥 |
| `mtv` 加边界后的 55 条（`BestofMTV`/`HumTV` 等）改落 `🎭 综艺频道` | **口径未拍板**：保留裸 `mtv` 则 88 条宗教/综合台继续被误判为音乐，二选一 |
| 逐步（S1–S6）中间态数字 | **未实测**；方案文档 §5 的"验收"列是可测的目标值，不是已测结果 |
| `hk_merged` 新增 53 条频道的播放可用性 | **未验证**（只验证了分类/地域口径，URL 有效性依赖 Validator） |
