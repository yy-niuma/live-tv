# categorize() 重构方案

> 配套文档：`docs/categorize-bug-analysis.md`（缺陷实测证据）
> 配套补丁：`patches/0001-categorizer-boundary-and-region.diff`、`patches/0002-generator-category-order.diff`
> 状态：0001 已在仓库副本上验证（known_bugs 5/24 → 23/24，known_good 27/27 不退化，语料 13470 条无回退）；
> 0002 只做机械验证（apply 通过、pytest 无新增失败），排序行为未被自动化用例覆盖。

---

## 0. 一句话方案

**把 234 个散落在 15 个 if 块里的正则，收敛成一张「带优先级 + 词边界策略 + 命中理由」的有序规则表；港澳台判定只保留一份事实来源；`🌐 国际` 不再是兜底，而是最后一级「无 genre 无产地」桶。** 分 6 步迁移，每步单独可验收、可回滚。

---

## 1. 目标分类体系（完整清单）

### 1.1 建议保留 + 新增

| 层 | 分类 | 现状 | 建议 |
|---|---|---|---|
| 官方 | `📺 央视频道` | 有，但漏判 24 条（`\b` 问题） | 保留，正则重写 |
| 省级 | `📺 北京` … `📺 天津`（32 个） | 有，只认中文写法 | 保留，追加拼音/英文别名 + 分组名 `XX频道` 两种信号 |
| 国内兜底 | `🇨🇳 中国源` | **已产出 116 条但不在 `CATEGORY_ORDER`** | 升格为正式分类，承接「地市/县市台 + 未细分国内源」（本方案实测 329 条） |
| 卫视 | `📡 卫视频道` | 有，被裸 `atv` 污染到 603 条 | 保留，收敛到 37 条 |
| 港澳台品牌 | `📺 TVB`/`📺 ViuTV`/`📺 RTHK`/`📺 HOY TV`/`📺 Now TV`/`📺 有线电视`/`🇲🇴 澳门`/`🇹🇼 台湾` | 有，判定与 `is_hk_region` 打架 | 保留，改为共用 `_region_category()` |
| 类型 | `🎬 电影频道`/`🎵 音乐频道`/`📰 新闻财经`/`🧸 儿童频道`/`🎭 综艺频道`/`⚽ 体育频道`/`📺 纪录片` | 有 | 保留，仅修块序与词边界 |
| 国际 | `🌐 国际频道` | 有（160 条） | 保留，语义固化为「**有明确品牌/国家标记**的国际台」 |
| 国际 | `🌐 国际` | 有（6448 条），**不在 `CATEGORY_ORDER`** | 保留，语义固化为「**无 genre、无产地**的全球长尾」，进 `CATEGORY_ORDER` 且排在 `🌐 国际频道` 之后 |
| 杂项 | `🇲🇾 马来西亚` | `recategorize_others` 会产出，不在表内 | 要么补进表（本方案做法），要么并入 `🌐 国际频道` |
| 死分类 | `📺 其他`、`🇯🇵 日本`…`🌏 大洋洲`（12 个） | 从不产出 | 见 §1.3 |

### 1.2 `🌐 国际` vs `🌐 国际频道`：保留双桶（明确建议）

**建议：保留两个桶，但把语义写死在文档和测试里，不要合并。**

理由（基于实测，不是口味）：

1. 两个桶的**判据确实不同**：`🌐 国际频道` 的 160 条是命中 `bbc/cnn/nhk/dw/trt/tv5/france24/半岛…` 的"有名字的国际台"；`🌐 国际` 的 6448 条里 2387 条 `group=General`、1310 条 `group=Undefined`——**连 genre 都没有**。合并会让 BBC World/NHK World 这类用户真正想找的台淹没在 6448 条长尾里。
2. 合并的唯一好处是"少一个分类"，代价是**播放器里无法定位**；而现在的痛苦不是"有两个国际桶"，而是"两者都没进 `CATEGORY_ORDER`，排序乱"。**修排序即可，不必合并。**
3. 若一定要合并：只能保留 `🌐 国际`（因为 `known_bugs.tsv` 里 12 条期望值写的就是 `🌐 国际`），而 `known_good.tsv` 又要求 `CNN Portugal`/`TRT World`/`NHK World` 落 `🌐 国际频道`——**两个数据集直接冲突**，合并必须先改数据集。成本 > 收益。

**落地动作**：`CATEGORY_ORDER` 里 `🌐 国际频道` 与 `🌐 国际` 相邻（`国际频道` 在前）；在两个分类的注释里写死上述语义；新增一条断言：`🌐 国际频道` 里的频道名必须至少命中一个国际品牌词（见 §4.3 测试 R4）。

### 1.3 死分类的处置（三选一，建议 B）

- **A. 全删**（连 `tests/test_generator.py:122` 的 `📺 其他` 断言一起改）——最干净，但要动测试。
- **B. 保留但标注"预留" + 不进产物**（本方案 0002 的做法）：`CATEGORY_ORDER` 里加注释说明"当前 0 产出"，同时把真正产出的 3 个分类补进去。**优点：不动测试、立即修好排序；缺点：表里仍有 13 项噪声。**
- **C. 实现产地识别**：用 `tvg-country`/`tvg-language`/logo 域名 填满 `🇯🇵 日本`…`🌏 大洋洲`（估计需另开一个 lane，语料里 `General` 长尾有 2387 条可喂）。

建议**先 B 后 C**：B 立刻消除"最大桶排最后"的用户可见问题，C 作为独立能力（产地识别）单独立项，不要和分类关键词混在一起做。

### 1.4 为什么不新增 `📺 地市台` 而是复用 `🇨🇳 中国源`

`known_bugs.tsv` 里 3 条地市台样本的期望值已经是 `🇨🇳 中国源`，且 `🇨🇳 中国源` 已由 logo 规则产出 116 条。新增平行分类会立刻产生"同一概念两个字符串"（正是本方案要消灭的 D16 类问题）。**如果要区分"省级"与"地市级"，正确做法是给分类加层级字段（`province`/`city`），不是再造一个分类名。**

---

## 2. 规则表设计

### 2.1 目标结构

```python
# categorizer.py（重构后骨架）
@dataclass(frozen=True)
class Rule:
    cat: str                 # 命中的分类
    priority: int            # 小者优先；同价按列表顺序
    patterns: tuple[str, ...]
    kind: str                # "brand" | "content" | "geo" | "group" —— 决定词边界策略
    why: str                 # 命中理由，写进 explain()，也写进回归用例的断言消息
    scope: str = "full"      # "full" = name+group；"name" = 只看频道名

RULES: tuple[Rule, ...] = (...)          # 有序，唯一事实来源

def match_rule(name: str, group: str) -> Rule | None:
    """返回命中的第一条规则（不改行为，只把 if 链变成数据）。"""

def categorize(name, group="", logo="") -> str:
    r = match_rule(name, group)
    if r: return r.cat
    ...                     # 兜底链：logo → 中文group → 英文group → 地市台 → 国际

def explain(name, group="", logo="") -> tuple[str, str, str]:
    """(分类, 命中规则 why, 命中模式) —— 排查线上误判用，TUI/CLI 可直接展示。"""
```

**为什么值得改**：现状下"为什么这条进了国际频道"只能靠人肉读 13 个 if；`explain()` 让每次误判都自带理由，回归用例也能断言"命中理由"而不只是分类（分类对了但理由是错的，下次改规则就会翻车）。

### 2.2 词边界策略（核心，必须按判据走）

实测把模式分三类，判据是**内嵌命中率**（命中子串两侧都是字母数字的比例）与**加边界后丢失的真命中**：

#### (a) 必须加边界：短拉丁品牌词

| 模式 | 内嵌/总命中 | 结论 |
|---|---|---|
| `atv` | 70/585 | `\batv\b` |
| `dw` | 13/20 | `\bdw\b` |
| `nba` | 12/13 | `\bnba\b` |
| `cba` | 5/5 | `\bcba\b` |
| `tv5` | 7/40 | `\btv5\b` + 单独保留 `tv5monde` |
| `tbs` | 2/5 | 直接**移除**（TBS 是 Turner 美国综合台，不该归"国际频道"） |
| `hbo` | 4/19 | `\bhbo(?![a-z])` |
| `amc` | 2/18 | `\bamc(?![a-z])` |
| `mgm` | 0/0 | `\bmgm(?![a-z])`（预防性） |
| `trt` | 3/28 | `\btrt\b` |
| `startv` | 2/10 | `\bstartv\b`、`\bstar\s*tv\b` |
| `nick` | 0/39 | `\bnick(?:elodeon\|jr\|toons)?(?![a-z])`（实测无伤，纯一致性） |
| `tdm` | — | `\btdm\b`（澳门台英文名） |
| `hoy` | 1/5 | `\bhoy\b` |

#### (b) 不能加边界：内容词 / 复合词

| 模式 | 反例（加边界就丢） | 结论 |
|---|---|---|
| `movie` | `24HourFreeMovies`、`ABNBibleMoviesChannel`、`ARTFLIXMovieClassics` | 裸匹配；106/741 内嵌但语义都对 |
| `cinema` | `PlutoTVCinemaItaliano`、`MyCinemaEurope` | 裸匹配（`cinemax` 另有独立模式） |
| `kids` | `DiscoveryKidsLatinAmerica` —— `\bkids?\b` 实测**失败**（`kids` 后紧跟 `latin`） | 裸匹配 |
| `影视`/`影城`/`电视剧`/`综艺`/`体育`/`财经`/`新闻台` | 中文无词边界概念 | 裸匹配 |
| `卫视` | `东方卫视`/`三沙卫视` | 裸匹配 **但加负向前瞻**：`卫视(?!电影\|電影\|体育\|體育)`，否则抢走 `卫视电影台`（golden movie-06） |
| `espn` | 语料 0 内嵌 | 可加可不加，本补丁保留裸匹配（零收益改动不做） |

#### (c) `\b` 对 CJK 无效——必须换写法

这是本项目最贵的一条教训（D04 让 24 条 CCTV 掉进兜底桶）：

```python
# ✗ 错：cctv1综合 里 "1" 与 "综" 之间没有 \b
r"\bcctv[\-_ ]?(\d+|news)\b"
# ✓ 对：只挡拉丁字母后缀
r"\bcctv[\s\-_]*\+?\d{1,2}(?:plus|\+|k)?(?![a-z])"
```

同理 `(?u)` 之类帮不上忙；判据：**只要模式右端可能紧跟中文，就不要用 `\b`，用 `(?![a-z])`／`(?=[\s\-\d])`。**

### 2.3 块序（优先级）重新排列

现状的教训是"宽桶必须排在窄桶之后"：

```
1  央视（窄，品牌）            → 重写正则
2  省级（窄，地名）            → +拼音 + group「XX频道」
3  港澳台（窄，品牌）          → 共用 _region_category()
4  卫视频道（中，含 atv\b）
5  电影 / 6 音乐（宽，内容词）
7  国际新闻品牌（窄！新增）    ← 必须早于 8，否则 cnn 被宽桶吃掉 19 次
8  国际频道（宽）
9  新闻财经
10 儿童 / 11 综艺 / 12 体育 / 13 纪录片
14 中国地市台（启发式，窄→中）
15 兜底链（logo → 中文group → 英文group → 国际）
```

**判据**：任何"宽桶"（模式集里含裸品牌词）都必须排在同题材的窄桶之后；`explain()` 可在 CI 里断言"命中宽桶的频道名不得同时命中窄桶模式"。

---

## 3. 兜底链设计

### 3.1 顺序（不可随意调换）

```
1. logo 域名/路径 → 产地（现有 LOGO_REGION_PATTERNS，建议补齐并启用 CHANNEL_REGION_PATTERNS）
2. 港澳台（_region_category）
3. 省级：中文表 → 拼音表 → group 里的「XX频道」
4. 中文 group-title 映射（GROUP_TITLE_ZH_MAPPING）
5. 英文 group-title 映射（GROUP_TITLE_EN_MAPPING，现有）
6. 中国地市台启发式（_looks_like_cn_local）
7. 音乐（按 group 兜）
8. 🌐 国际
```

### 3.2 中国地市台的三级判据（本补丁实测：兜底桶中文名 968 → 89）

```python
def _looks_like_cn_local(name, group) -> bool:
    # 0) 名字里出现 卫视/港澳/外国地区词 → 一律不判地市台（防误伤）
    # 1) 中文名以地市特征后缀结尾：新闻综合|综合频道|新闻频道|电视台|广播电视台|
    #    公共/经济/都市/生活/科教/文旅/民生/法制/法治/文体频道|综合|资讯
    # 2) 纯中文名（无拉丁字母）+ 2~8 字 + 不含内容词（剧/影/春晚/动画/音乐/球/赛/直播…），
    #    且 group 为空或 group 是已知内容分组时**不猜**（交给 §3.3 映射表）
    # 3) group ∈ {地方频道, 直播中国} → 直接判
```

**为什么规则 2 要看 group**：`七龙珠`（group=`动画频道`）这类动画片名是纯中文、2-8 字、无内容词，会被规则 2 误判成 `🇨🇳 中国源`（已单独验证：加 group 约束前 `categorize('七龙珠','动画频道')` = `🇨🇳 中国源`，加约束后 = `🧸 儿童频道`）。把"group 已指明内容类型"的情况排除后，`livetv_review.py` 的「新增 `🇨🇳` 中国源里可能误判」检查项实测剩 **4 条 / 329 条（1.2%）**：`句容影院`、`赣州教育`、`现代教育`（group 为 `地方频道`/`其它`，源站本就把它们归地方台，可接受）、`直播中国精编直播`（风景机位合辑，本质是数据质量问题而非分类错误）。

### 3.3 中文 group 映射：只收实测可信的

```python
GROUP_TITLE_ZH_MAPPING = {
    "电影": "🎬 电影频道",      # 实测该 group 下全是 CHC/1905 真电影频道
    "地方频道": "🇨🇳 中国源",   # 万州三峡移民/任丘综合...
    "直播中国": "🇨🇳 中国源",   # 风景直播机位
    "春晚频道": "🎭 综艺频道",
    "咪咕赛事": "⚽ 体育频道",
    "点播电影": "🎬 电影频道",
    "戏曲频道": "🎭 综艺频道",
    "纪录频道": "📺 纪录片",
    "动画频道": "🧸 儿童频道",
    "🪁动画频道": "🧸 儿童频道",
}
```

**刻意不收**：`綜合`(250)/`新聞`(135)/`綜藝`(128)/`運動`(98)/`電影`(88)/`知識`(56)。理由：抽样显示这些繁体 group 在源站被**误标**——`group=綜合` 下是 `aastha`/`alrayyan`（印度/中东台），`group=電影` 下是 `.black`/`amediahit`/`axn`。映射它们等于把国际长尾灌进中文分类。**判断依据必须写成注释**，否则下一个人会"顺手补全"。

### 3.4 港澳台一致性契约（必须实现）

```python
_region_category(name, group) -> str | None      # 唯一事实来源：港澳台品牌分类
_region_extra(name, group) -> bool               # 仅地域（凤凰/星空/凤凰香港台）
is_hk_region(...) = _region_category(...) or _region_extra(...)
categorize(...)   = 直接 return _region_category(...) 的结果（不再自建关键词表）
```

不变量（进 CI，见 §4.3）：

- **A**：`categorize()` ∈ 港澳台品牌集 ⇒ `is_hk_region()` 为真。
- **B**：`is_hk_region()` 为真 ⇒ 分类 ∉ {`🌐 国际`, `🌐 国际频道`}。
- **C**：允许 `凤凰卫视`/`星空卫视` 这类"地域港、分类卫视"的显式白名单（`_region_extra`），并写测试锁住，防止有人"统一"回去。

---

## 4. 验收标准

### 4.1 主指标（现有数据集）

| 指标 | 基线 | 第一步目标 | 最终目标 | 实测（本补丁） |
|---|---|---|---|---|
| known_bugs | 5/24 | ≥ 17/24 | ≥ 22/24 | **23/24** |
| known_good | 27/27 | 27/27 | 27/27 | **27/27** |
| `🌐 国际` 桶占比 | 50.7% | ≤ 50% | ≤ 49% | **47.9%** |
| `🌐 国际` 中文名条数 | 968 | ≤ 500 | ≤ 250 | **89** |
| `📡 卫视频道` 条数 | 603 | ≤ 100 | ≤ 60 | **37** |
| 不变量 A/B 违反数 | 32 / 0 | 0 / 0 | 0 / 0 | **0 / 0** |
| `hk_merged` 候选数 | 92 | ≥ 100 | ≥ 120 | **141**（丢失 0） |
| pytest | 283 passed / 23 xfail | 无新增失败 | 无新增失败 | 282 passed / 10 xfail / 13 XPASS / 1 golden 冲突 |

`known_bugs` 的 1 条未通过项：`DetetivesMedicos`——**只凭名字不可判**（真实 group=`Documentary`，而 `eval_categorize.py` 传的 group 恒为空）。达成 24/24 的唯一干净办法是让数据集支持 group 列（见 §6 TODO-1），**不建议**加 `detetives` 硬编码。

### 4.2 建议扩充的样本集（可直接追加进 `scripts/categorize_dataset/known_bugs.tsv`）

以下 30 条全部来自本次真实语料，均已人工核对语义：

```
VoATV	🌐 国际	裸 atv 把 VOA 新闻台截走
AdrenalinaPuraTVBrazil	🌐 国际	裸 atv
AfricaTV3	🌐 国际	裸 atv
30ATVClassicMovies	🎬 电影频道	裸 atv 抢先于电影块
iHOY爱历史	📺 纪录片	裸 hoy
HTRTV	🌐 国际	裸 trt
RTRTV	🌐 国际	裸 trt
JTBSClassic	🌐 国际	裸 tbs
RTBSukmaindera	🌐 国际	裸 tbs
ImamHusseinTV5	🌐 国际	裸 tv5
VTV5TayNamBo	🌐 国际	裸 tv5
SuperTV55	🌐 国际	裸 tv5
ATNBangla	🌐 国际	裸 nba
BaanBaanTV73	🌐 国际	裸 nba
AfarinBaxcha	🌐 国际	裸 nba
RepublicBangla	🌐 国际	裸 nba/cba
CBCTelevisionCBAT-DT	🌐 国际	裸 cba
IBCBakthi	🌐 国际	裸 cba
IslamChannel	🌐 国际	裸 amc
IAmChannel	🌐 国际	裸 amc
NHBollyGold	🌐 国际	裸 hbo
KhushbooBangla	🌐 国际	裸 hbo
AnandWariTV	🌐 国际	裸 dw
HeartlandWeb	🌐 国际	裸 dw
MarriedwithChildren	🌐 国际	裸 dw
cctv1综合	📺 央视频道	\b 在数字+中文边界失效
cctv5plus	📺 央视频道	tv5 抢走
CGTN英语	📺 央视频道	缺 CGTN
TVBSNews	🇹🇼 台湾	同时验证 is_hk_region
TDM-MacauSatellite	🇲🇴 澳门	澳门英文台
```

**不退化集（known_good）建议补 8 条对照组**，专门锁住"不能过度泛化"的边界：

```
ATV	📡 卫视频道	加 \b 后仍要认得真亚视
凤凰卫视中文台	📡 卫视频道	且 is_hk_region=True（地域港、分类卫视）
星空卫视	📡 卫视频道	同上
卫视电影台	🎬 电影频道	卫视兜底必须负向前瞻 电影/体育
CNN Portugal	🌐 国际频道	地区版不进新闻财经
BestofMTV	🎵 音乐频道	mtv 加边界后仍需认出（当前会落综艺，见 §6 TODO-2）
NHK World	🌐 国际频道	不能因为"新闻品牌"规则被抢走
七龙珠	🧸 儿童频道	group=动画频道，地市台启发式不得误吃
```

### 4.3 契约测试（比分类断言更重要）

| # | 断言 | 放在哪 |
|---|---|---|
| R1 | `categorize()` ∈ 港澳台品牌集 ⇒ `is_hk_region()` 为真 | `tests/test_known_defects.py`（现成的 `classify` fixture） |
| R2 | `is_hk_region()` 为真 ⇒ 分类 ∉ {`🌐 国际`,`🌐 国际频道`} | 同上 |
| R3 | `categorize()` 的返回值 ⊆ `generator.KNOWN_CATEGORIES` | 新文件（数据驱动，遍历 `known_bugs`+`known_good`+语料快照） |
| R4 | `🌐 国际频道` 的结果必须命中至少一个国际品牌词（禁止宽桶吞长尾） | 同上 |
| R5 | 每条规则至少有一个正例（防新增死规则） | 新文件，遍历 `RULES` |
| R6 | 产物快照漂移对比：`eval_categorize.py --snapshot A.tsv --snapshot B.tsv`，移组条数需人工过一遍 | CI 手动 job |

R3 能直接拦住 D17 类问题（产出未登记分类 → 排序落末档），成本最低、收益最高。

---

## 5. 迁移步骤（每步可独立验收、可回滚）

> 每步都是一个独立 PR/commit；出问题 `git revert` 单步即可，不牵连其他步。
> 「预估」= 我未逐步实测；「实测」= 已在本 lane 验证。

| 步 | 内容 | 影响面 | 验收 | 回滚 |
|---|---|---|---|---|
| **S1** 词边界 | `atv/tv5/tbs/dw/hbo/amc/mgm/trt/nba/cba/nick/startv/hoy/tdm` 按 §2.2 处理 | 语料 ~600 条移组 | known_bugs ≥ 17/24；known_good 27/27；`📡 卫视频道` ≤ 100（预估） | 单文件 revert |
| **S2** 央视正则 | `CCTV_RE`/`CETV_RE` 用 `(?![a-z])`，纳入 `CGTN` | +38 条进央视频道（实测 148→186） | `cctv1综合`/`cctv5plus`/`CGTN英语` 进央视频道（实测） | 独立函数，可单独回滚 |
| **S3** 港澳台统一 | `_region_category`/`_region_extra`，删两套关键词表 | 32 条冲突归零，hk 候选 92→141（实测） | R1/R2 断言 0 违反（实测 0） | 保留旧函数 1 个 release 做双跑对比 |
| **S4** 兜底链 | 中文 group 映射 + 地市台三级判据 + 拼音省名 + group「XX频道」 | 国际桶 6829→6448，中文污染 968→89（实测） | `七台河新闻综合`/`余姚新闻综合`/`伊犁哈萨克` 落 `🇨🇳 中国源`；`🇨🇳 中国源` 新增强制人工抽查 20 条 | 三步可拆成 3 个 commit（group 映射 / 地市台 / 拼音省名） |
| **S5** 分类表同步 | `CATEGORY_ORDER` 补 `🇨🇳 中国源`/`🌐 国际`/`🇲🇾 马来西亚`，死分类标注预留 | 只影响排序 | R3 通过；`all_merged.m3u` 里 `🌐 国际` 组不再排最后 | 单文件 revert |
| **S6**（可选）规则表化 | if 链 → `RULES` 数据表 + `explain()` | 行为应**零变化** | 全语料 `categorize()` 输出与 S5 后逐条一致（13470 条 0 diff）；`explain()` 每条都有 why | 独立 PR，纯重构 |

**S6 的关键约束**：它是**纯重构**，验收标准是"输出与重构前逐字节一致"，不要在同一 PR 里顺手调规则——否则出问题无法二分。

---

## 6. 遗留 TODO（明确不在本次范围）

| # | TODO | 为什么现在不做 |
|---|---|---|
| 1 | `eval_categorize.py` 数据集加第 3 列 group（`name\texpected\tgroup\twhy`），`DetetivesMedicos` 才能判对 | 需改 `scripts/eval_categorize.py`（本 lane 只允许改 `docs/`、`patches/`） |
| 2 | `mtv` 加边界后 `BestofMTV`/`HumTV` 落 `🎭 综艺频道`（原为 `🎵 音乐频道`） | 属产品口径取舍：保留裸 `mtv` 则 88 条宗教台继续被误判为音乐，二选一，需 owner 拍板 |
| 3 | 死分类清理（`📺 其他` + 12 地区桶）要么实现要么删除 | 删除要连带改 `tests/test_generator.py`，需测试写权限 |
| 4 | 产地识别（`tvg-country`/`tvg-language`/logo 域名）填满地区桶 | 独立能力，2387 条 `General` 长尾可喂；与关键词分类解耦做更安全 |
| 5 | 389 条脏频道名（name 里含 `tvg-id=`/`group-title=` 残渣） | 属 `src/fetcher.py` 解析 + `generator.is_clean_name()` 职责 |
| 6 | 繁体/少数民族语/方言台规则（`内蒙少儿`、`八大第一台`） | 样本量小（<20 条/类），先积累样本 |
| 7 | `CHANNEL_REGION_PATTERNS`（20 条产地映射）要不要启用 | 启用会改变 `🇲🇾 马来西亚` 等分组产出，需先定分类表（S5） |

---

## 7. 风险与回滚预案

| 风险 | 触发条件 | 预案 |
|---|---|---|
| 加边界导致真频道丢失 | 极端命名（`ATVHD`、`TVBAnywhere` 类） | §2.2 清单里都给了显式白名单模式；CI 的 known_good 对照组覆盖 |
| 地市台启发式误吃动画/剧集名 | group 为空且名字是纯中文内容名 | 规则 2 已用"group 已知内容分组时不猜"+ 内容词黑名单；新增 `🇨🇳 中国源` 需人工抽查 20 条 |
| hk_merged 变大后混入非港台 | 产地表启用过宽 | 不变量 B + 抽查 145 条新增项（第一版 141，第二遍修 `\b` 边界再 +4）；`_REGION_NAME_VETO` 已挡 `RightNowTV`/`canada` 类 |
| 中文 group 映射灌入噪声 | 源站误标（`綜合`/`電影`） | 只收 10 个实测可信 group，注释写明为什么其余的不能收 |
| 规则表化（S6）改变行为 | 重构时顺手改规则 | 验收 = 13470 条语料 0 diff；diff 不为 0 直接拒绝合并 |

---

## 8. 补丁文件说明

| 文件 | 内容 | 验证状态 |
|---|---|---|
| `patches/0001-categorizer-boundary-and-region.diff` | `src/group/categorizer.py`：词边界、央视正则、港澳台统一判定、兜底链（中文 group / 地市台 / 拼音省名）、命名统一 | **已实测**：副本 apply 干净；eval 5/24→23/24、27/27；语料 13470 条逐条漂移审计；pytest 无行为回退（13 XPASS + 1 golden 口径冲突） |
| `patches/0002-generator-category-order.diff` | `src/generator.py`：`CATEGORY_ORDER` 补齐 3 个实际产出分类、死分类标注预留、新增 `KNOWN_CATEGORIES` | **仅机械验证**：apply 干净、pytest 无新增失败；排序行为无自动化用例覆盖 |

应用方式（**不要**直接在工作区 apply，先在副本验证）：

```bash
cp -r src /tmp/livetv-check/src && cp -r scripts /tmp/livetv-check/ && cp -r tests /tmp/livetv-check/
cd /tmp/livetv-check
git apply --verbose /home/hermes/.config/superpowers/worktrees/live-tv/feature-categorize/patches/0001-categorizer-boundary-and-region.diff
git apply --verbose /home/hermes/.config/superpowers/worktrees/live-tv/feature-categorize/patches/0002-generator-category-order.diff
python scripts/eval_categorize.py     # 期望 known_bugs 23/24, known_good 27/27
python -m pytest -q                   # 期望 14 failed(13 XPASS + 1 golden 冲突), 282 passed, 10 xfailed
```
