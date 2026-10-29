# 架构

> 本文引用的 `audit-c-engineering.md` 是只读审计产出，**不入库**（见 `.gitignore`），只存在于本地磁盘。

本文描述 `live-tv` 当前代码的**真实结构**：每个文件的行数用 `wc -l` 打出来，数据流按 `src/main.py` 的实际调用顺序画，已知问题交叉引用审计报告 `audit-c-engineering.md` 的章节号（该报告只读、不入库；本文所有结论都能用命令复核）。

> 基线：数据提交 `074c677` 之上的工程整改批次（`871e32d` 退出码修复、`5221621` CI、`7ff4be1` 依赖与工程配置、`3020583` 测试）。行数与行号均按当前工作区实测。

---

## 1. 模块地图

```
live-tv/
├── src/
│   ├── main.py            入口：argparse + run() 四阶段流水线
│   ├── config.py          配置加载（sources.yaml / whitelist.txt / proxy.txt）
│   ├── fetcher.py         抓取 + M3U/YAML 解析（Channel 定义在这里）
│   ├── validator.py       URL 有效性验证
│   ├── grouper.py         别名归一 + 同名合并 + 分类调度
│   ├── generator.py       m3u 生成（含 100/组上限、港澳台切分）
│   ├── logo_map.py        频道名 → logo URL 的硬编码映射 + 模糊匹配
│   ├── group/
│   │   ├── normalize.py   繁简转换、噪声清理、URL 优先级、同名合并
│   │   └── categorizer.py 分类规则表 + categorize() + is_hk_region()
│   └── lib/
│       ├── cache.py       JSON 文件缓存（带 TTL）
│       └── whitelist.py   港澳台 CDN 正则白名单
├── config/                业务规则的第二现场（376 行，见 §6）
└── output/                all_merged.m3u / hk_merged.m3u / stats.json
```

行数（`wc -l src/*.py src/group/*.py src/lib/*.py`，合计 **2,200**）：

| 文件 | 行数 | 占比 | 职责 |
|---|---:|---:|---|
| `src/group/categorizer.py` | 684 | 31.1% | 分类规则与判定：`_match()` `HK_TW_MO_RULES` `_region_category()` `is_hk_region()` `recategorize_others()` `categorize()` |
| `src/group/normalize.py` | 318 | 14.5% | 频道名归一（繁简、噪声、别名）、URL 优先级、同名合并 |
| `src/logo_map.py` | 302 | 13.8% | 硬编码 logo 表 + `get_logo()` / `get_logo_fuzzy()` |
| `src/fetcher.py` | 187 | 8.5% | `Channel` 数据类 + 20 源并发抓取 + M3U/YAML 解析 + 按 URL 去重 |
| `src/generator.py` | 196 | 8.9% | m3u 文本拼装、分类排序（`CATEGORY_ORDER` + `KNOWN_CATEGORIES`）、脏名过滤、100/组截断 |
| `src/main.py` | 168 | 7.7% | CLI 参数、四阶段编排、`stats.json` 写出 |
| `src/grouper.py` | 92 | 4.2% | 别名表加载、调 `normalize.*` 合并、调 `categorize()` 分组 |
| `src/validator.py` | 92 | 4.2% | HEAD/GET 探测、代理域名拒绝、CDN 白名单放行 |
| `src/config.py` | 57 | 2.6% | 三个配置文件的最薄封装（懒加载 + 空列表即「未加载」） |
| `src/lib/cache.py` | 49 | 2.3% | `SimpleCache`：`get/set/clear`，默认 TTL 86400s |
| `src/lib/whitelist.py` | 48 | 2.2% | 港澳台 CDN 的 `re.Pattern` 列表 + `is_hk_cdn_whitelisted()` |
| `src/__init__.py` | 3 | — | 只有 `__version__ = "1.0.0"`（无 tag 对应，读不到） |
| `src/group/__init__.py`、`src/lib/__init__.py` | 1 / 1 | — | 空 |

---

## 2. 数据流

`src/main.py:17-132` 的 `run()` 就是全部流程，四步顺序硬编码：

```
config/sources.yaml ──(Config.sources, 只取 enabled≠false)──► 20 个源
        │
        │ ① 抓取  Fetcher.fetch_all()            src/fetcher.py:42
        │   · 每源独立协程，Semaphore(10) 限流，最多重试 3 次（退避 1s/2s/3s）
        │   · 按 URL 后缀判 .yaml/.yml → _fetch_yaml()，否则 _fetch_m3u()
        │   · 全量抓完按 URL 去重（保留首次出现）
        ▼
   Channel[]（name/url/logo/group/raw_attrs）          ← 实测 16,901 条
        │
        │ ② 验证  Validator.validate()           src/validator.py:22
        │   · proxy.txt 命中的域名直接丢弃
        │   · whitelist.txt 命中的域名直接放行（不探测）
        │   · 其余发 HEAD（405 回退 GET），要求 200 且 Content-Type 不是 text/html
        │   · Semaphore(20)、单条 timeout 10s
        ▼
   Channel[]（有效，--skip-validation 时原样透传）
        │
        │ ③ 分组  Grouper.group()                src/grouper.py:36
        │   · config/alias.txt（168 行，"->" 或 "=" 分隔）建别名表
        │   · normalize_channel_name()：繁简转换 → 去噪声 → 别名替换
        │   · normalize_channels() → merge_duplicate_channels()：同名合并，
        │     保留 URL 优先级最高的作主用，最多带 2 个备用
        │   · 每个频道 categorize(name, group, logo) 得到分类键
        ▼
   {分组名: Channel[]}                                  ← 实测 12,505 条 / 53 组
        │
        │ ④ 生成  Generator.generate_hk_and_all()  src/generator.py:105
        │   · is_clean_name() 丢脏名（浏览器 UA 残留等）        ← 8371→8056
        │   · is_hk_region() 切出港澳台子集
        │   · all_merged：按 CATEGORY_ORDER 排序，每分组只写前 100 条  ← 8056→1164
        │   · hk_merged：同样排序，**不截断**
        ▼
output/all_merged.m3u   output/hk_merged.m3u
output/stats.json      ← 注意：这里是 ③ 的产物，不是 ④ 的
```

**关键不变量（写文档/改代码时必须知道）**：

1. `stats.json` 记录的是**第 ③ 步的计数**（`src/main.py:115`），所以它永远 ≥ `all_merged.m3u` 的条目数，差值 = 脏名过滤量 + 100/组截断量。
2. `all_merged.m3u` 每分组上限 100 条（`src/generator.py:182`），`hk_merged.m3u` 无上限（`src/generator.py:131-141`）。
3. 两个文件头部的 `# Total: N channels` 都是**截断前**的数，不等于实际 `#EXTINF` 条数。

---

## 3. 各模块职责与实现要点

### 3.1 `config.py`（57 行）

`Config(config_dir=None)` 只做三件事：读 `sources.yaml`（过滤 `enabled: false`）、读 `whitelist.txt`、读 `proxy.txt`（跳空行与 `#` 注释）。
默认目录 `Path(__file__).parent.parent / "config"`，即仓库 `config/`。

已知问题：三个属性都用「**空列表就当没加载**」判断（`if not self._sources: self._load_sources()`），所以配置文件为空时每次访问都会重新读盘；也没有任何 schema 校验（`config/` 的 376 行是事实上的业务规则，改错一个键不会报错）。

### 3.2 `fetcher.py`（187 行）

- `Channel` 是**手写类**，不是 dataclass（`from dataclasses import dataclass` 导入后未使用）。
- `_EXTINF_RE` / `_ATTR_RE` 两个正则解析 M3U；只认 `tvg-name|tvg-logo|tvg-chnid|group-title|attribute` 五个属性。
- `fetch_all()` 用 `asyncio.gather(return_exceptions=True)`，单源失败只 `print`，不中断。
- 抓完按 URL 去重（`seen` 集合），所以同一条流在多源出现时只留一份，`_source`/`_priority` 也跟着第一条走。

已知问题：`self._semaphore` 在 `__init__` 里是 `None`，只有 `fetch_all()` 开头才赋值，单独调 `_fetch_url()` 会 `AttributeError`；`_fetch_m3u()` 把 HTTP 与解析耦在一起，无法单测（审计报告 `audit-c-engineering.md` §3.5b、§5 第 2 步）；库层用 `print` 而非 `logging`（§1.5）。

### 3.3 `validator.py`（92 行）

三道关：代理域名拒绝 → CDN 白名单直接通过 → HEAD 探测（405 时降级 GET），要求 `status == 200` 且 `Content-Type` 非 `text/html`。

已知问题（**最危险的一处**）：`validate()` 的 `return [ch for ch, valid in zip(channels, results) if valid]`（`:27`），而 `results` 来自 `gather(return_exceptions=True)` —— 异常对象恒为真，于是「验证过程抛异常」被解释成「验证通过」。实测 `http://[::1/list.m3u8`（`urlparse` 抛 `ValueError`）被保留；详见 §3.5b。另外并发 20 + 单条 10s 是整条流水线的时间黑洞（§2.6）。

### 3.4 `grouper.py`（92 行）

只做调度：加载别名（`config/alias.txt`，非空行 144 条）→ 调 `normalize_channel_name()` → 把 `Channel` 摊平成 `dict` 交给 `normalize_channels()` → 再拼回 `Channel` → 逐个 `categorize()` 分桶。

已知问题：Channel → dict → Channel 的往返**丢掉了 `raw_attrs`**（重建时没传 `**kwargs`），所以 `_source` / `_priority` 在合并后全部消失——后续任何「按源优先级」的逻辑都拿不到数据（§3.5）。

### 3.5 `group/normalize.py`（318 行）

- `convert_tc_to_sc()`：**词表级**繁简替换（约 100 组词，不是逐字转换）。
- `strip_noise()`：清除画质/码率等噪声。
- `normalize_channel_name()`：繁简 → 噪声清理 → 别名替换（带前后边界判断）。
- `get_url_priority()`：1 = 港澳台 CDN 白名单域名，2 = 已知聚合站，3 = 其他。
- `merge_duplicate_channels()`：按 `_normalized_name` 归组，主用 URL 取优先级最高者，另存最多 2 个备用到 `_backup_urls`。

已知问题：`strip_noise()` 里 `re.compile(r'\s+').sub('', ...)` 把**所有内部空格删掉**（实测 `"TVB 翡翠台"` → `"TVB翡翠台"`），下游 `logo_map` 只能靠 `norm_nospace` 分支打补丁（§3.5）；`_SPECIAL_MAPPING` 每次调用重建；`original` 变量赋值后未使用。

### 3.6 `group/categorizer.py`（684 行）

全项目最重的文件：`PROVINCE_KEYWORDS`（32 组省级关键词表）+ `HK_TW_MO_RULES` + 一系列分类正则 + 8 个函数。

**2026-10-29 重构过一次**，此前 `categorize()` 与 `is_hk_region()` 各维护一份港澳台关键词表，两套结论会打架。现在港澳台判定只有一处：

| 符号 | 行 | 行数 | 职责 |
|---|---:|---:|---|
| `PROVINCE_KEYWORDS` | 10 | — | 32 组省级关键词表 |
| `_match()` | 48 | 9 | 名称/分组上做正则命中（`_excluded()` 之外的唯一匹配入口） |
| `_excluded()` | 59 | 37 | **全仓无调用方的死代码**（`grep -rn "_excluded" src` 只有定义） |
| `HK_TW_MO_RULES` | 108 | — | 港澳台统一规则表（港/台/澳三组，`categorize()` 与 `is_hk_region()` 共用） |
| `_REGION_EXTRA` / `_REGION_NAME_VETO` / `_REGION_GROUP_VETO` | 146 / 153 / 159 | — | 附加地区词、名称否决词、分组否决词 |
| `_region_extra()` | 162 | 4 | 附加地区词命中 |
| `_region_category()` | 168 | 15 | 返回 `📺 TVB` / `🇹🇼 台湾` / `🇲🇴 澳门` 之一或 `None` —— **唯一的港澳台判定实现** |
| `PROVINCE_LATIN` | 188 | — | 拼音省名（`zhejiang` / `xinjiang` …） |
| `CJK_CITY_SUFFIX` / `CONTENT_WORDS` / `_LOCAL_OK_WORDS` / `CONTENT_WORDS_STRICT` | 203–219 | — | 地市台识别的词表与反例 |
| `GROUP_TITLE_ZH_MAPPING` | 224 | — | 10 个中文 group → 分类 |
| `CCTV_RE` / `CETV_RE` | 242 / 248 | — | 央视/教育台正则（用 `(?![a-z])` 而非 `\b`，因为 `\b` 在「数字+中文」边界不成立） |
| `_looks_like_cn_local()` | 255 | 26 | 地市台三级判据（后缀 + 内容词反例 + 外来地区词否决） |
| `is_hk_region()` | 286 | **11** | 直接委托 `_region_category() or _region_extra()` |
| `GROUP_TITLE_EN_MAPPING` | 302 | — | 英文 group → 分类（iptv-org 用） |
| `LOGO_REGION_PATTERNS` / `CHANNEL_REGION_PATTERNS` | 366 / 381 | — | logo 域名、频道名前缀 → 地区 |
| `recategorize_others()` | 425 | 61 | 「🌐 国际」与地市台的二次细分，14 个分支 |
| `categorize()` | 491 | **187** | 主判定，18 个分支的顺序 if |

以上行数用 AST 实测（`ast.walk` 取 `lineno`/`end_lineno`），不是估算。

已修复（本次重构）：`is_hk_region()` 从 136 行缩到 11 行，那段「无论条件如何都 `return False`」的不可达分支随之一并消失；双反斜杠正则（`\\bmacau\\b` 等永不匹配）已删除，实测 `is_hk_region("Macau TV")` / `is_hk_region("TTV")` / `is_hk_region("PTS")` 全部 `True`。

仍然存在的已知问题：

- `_excluded()` 是死代码（37 行，无调用方），未删是因为本批次不想动无关逻辑。
- 所有正则以**字符串**形式传给 `re.search`，`re` 的 512 条内部缓存被反复冲掉，时间主要花在重新编译上（审计报告 §3.4 的 cProfile 实测：1,379 频道 40.2s，预编译后 1.0s，约 40×。**该 40× 是那份报告的实测值，本次重构未复测，也未预编译**）。
- `CATEGORY_ORDER` 里 12 个「预留但当前不产出」的分类仍与 `categorize()` 不对应（§3.8）；
  已由 `tests/test_category_order_contract.py` 的 `RESERVED_CATEGORIES` 钉住——一旦其中某个开始产出，用例失败。
- 3 条已知残留缺陷（`ATV` 归卫视但 `is_hk_region=False`、`DetetivesMedicos`、`CNNInternational` 落 `🌐 国际频道`）登记在 `docs/categorize-bug-analysis.md` 与 `tests/test_known_defects.py`。原第 4 条 `HOY资讯台` 已修 —— 它其实是重构用 `r"\bhoy\b"` 引入的新回归（`\b` 在 CJK 边界不成立），不是既有缺陷。

回归护栏：`scripts/eval_categorize.py`（`known_bugs.tsv` 24 条 + `known_good.tsv` 27 条，当前 50/51）、`tests/test_categorize_golden.py`（行为钉死表）、`tests/test_known_defects.py`（8 条 xfail 契约）。

### 3.7 `logo_map.py`（302 行）

一张硬编码的 `频道名 → logo URL` 表：`LOGO_MAP` 169 个键（字面量写了 170 对，因有 1 个重复键），`LOGO_MAP_CASE` 是它的小写镜像（169 个键）。入口有 `normalize()` / `get_logo()` / `get_logo_with_fallback()` / `get_logo_fuzzy()`。`generator.build_extinf()` 对**每条**没 logo 的记录调用 `get_logo_fuzzy()`，未命中时做整表线性扫描。

已知问题：`"viutv"` 键重复定义（字面量 170 对 → 实际 169 键，后者静默覆盖前者）；`norm_nospace` 分支是给 `strip_noise` 空格 bug 打的补丁；全表线性扫描在放开 100/组截断后会线性放大（§3.4(c)）。

### 3.8 `generator.py`（198 行）

纯文本拼装，无 IO 依赖（只写文件）。要点：

- `CATEGORY_ORDER`（65 个分类的固定顺序，`len(CATEGORY_ORDER)` 实测 65）决定输出顺序；`KNOWN_CATEGORIES` 是它的 `frozenset` 视图，供生成端做一致性断言。未列出的分类排最后并按名称排序。
  **其中 12 个是「预留但 categorize() 当前不产出」的分组**（`🇯🇵 日本` / `🇰🇷 韩国` / `🌏 亚洲（东南亚）` / `🇮🇳 印度` / `🌏 亚洲（其他）` / `🌍 欧洲` / `🇺🇸 北美` / `🌎 拉丁美洲` / `🌍 中东` / `🌍 非洲` / `🌏 大洋洲` / `📺 其他`），原样保留是为了不破坏旧产物排序与 `tests/test_generator.py` 的 `sort_key` 断言。
  ⚠️ 两个容易搞混的点（2026-10-29 实测更正）：

  - `🇲🇾 马来西亚` **不是**预留项，它在 `CATEGORY_ORDER` 的在用段里（`generator.py` 第 43 行），语料上实测产出 **4 条**（`AstroAOD` / `AstroAEC` / `AstroQJ` / `Astro欢喜台`）。
    判它的不是频道名，是 **logo 域名里的 `Astro`**（`LOGO_REGION_PATTERNS`）。我最初用
    `categorize(name, group)` 两个参数测，漏了 `logo`，把它误报成「从不产出」—— 而生产路径
    `src/grouper.py:92` 是 `categorize(name, group, logo)` 三参数。**测分类必须传 logo。**
  - `📺 有线电视` 也不在预留块里，语料上 0 命中，但它**能**产出：
    `categorize("有线电视新闻", "")` → `📺 有线电视`，真实产物 `all_merged` / `hk_merged` 各有 1 条。
    属「语料没覆盖到」，不是「产不出来」。
- `is_clean_name()` 丢脏名：排除长度 < 2、含浏览器标识（`chrome/`、`safari`、`edg/`、`webkit` 等）、名字里带 URL 残留的条目。
- `build_extinf()` 输出 `#EXTINF:-1 tvg-name="…" tvg-logo="…" group-title="…",名字`（缺 logo 时用 `get_logo_fuzzy()` 兜底）。
- `generate_hk_and_all()`：先 `is_clean_name` 过滤，再用 `is_hk_region` 切 hk 子集，all 分支 `[:100]` 截断并写 `# ... and N more`。

已知问题：输出层**反向依赖分类层内部函数** `is_hk_region`（`generator.py:8`），分类规则一改产物就跟着变（§3.3）；`import re` 未使用；100/组上限让交付量与 `stats.json` 永久不一致（三口径推导见 [`getting-started.md`](getting-started.md) FAQ 1/2/3）。

### 3.9 `lib/cache.py`（49 行）

`SimpleCache`：一个 key 一个 JSON 文件，`{"timestamp": ..., "value": ...}`，默认 TTL 86400 秒。

已知问题：默认目录用 `Path(__file__).parent.parent / ".cache"`，因为文件在 `src/lib/` 下，`parent.parent` 是 **`src/`**，缓存落在 `src/.cache/`（实测打印该路径），而 `.gitignore` 没覆盖它（§2.3 C-P2-3、§3.7）。

### 3.10 `lib/whitelist.py`（48 行）

港澳台 CDN 的 `re.Pattern` 列表（tvb.com / viutv.com / rthk.hk / hkdtmb.com / tdm.com.mo / now.com 等 + 若干 IP 段），供 `normalize.get_url_priority()` 判断 URL 优先级。**注意它和 `config/whitelist.txt`（验证器放行名单）是两套不同的东西**，名字相同、用途不同。

### 3.11 `main.py`（168 行）

- `run()`（`:17-132`）：四阶段编排，每阶段打印 `[Step n/4]`，返回 summary dict。
- `main()`（`:135-168`）：argparse 六个参数（`--config/-c`、`--output/-o`、`--no-cache`、`--skip-validation`、`--skip-fetch`、`--fetch-timeout`）。

已知问题：`--skip-fetch` 读的缓存，只有在 `use_cache=True` 且「缓存未命中」那条分支里才会被写（`:66`），`--no-cache` 分支（`:67-79`）不写——所以「先 `--no-cache` 再 `--skip-fetch`」必然失败；`run(output_dir: str = None)` 里把参数改写成 `Path`，注解与实现不符（mypy 报 3 条）；`import os` 未使用；两处 `from src.fetcher import Channel` 写在分支里（`:41`、`:51`）。

**退出码**：`871e32d` 起失败会 `raise SystemExit(1)`；此前版本失败只 `print` 后 `return`（退出码 0，CI 察觉不到）。

---

## 4. 模块依赖图

```
main ──► config
  │      fetcher ──► config
  │      validator ──► config, fetcher
  │      grouper ──► fetcher, group.categorizer, group.normalize
  │      generator ──► logo_map, group.categorizer
  │      lib.cache
  ▼
group.normalize ──► lib.whitelist   （函数内 import，带 try/except ImportError 兜底）
```

模块级**没有循环依赖**，但有三处结构性味道：

1. `generator → group.categorizer.is_hk_region`：输出层依赖分类层的内部判定（§3.3）。
2. `normalize → lib.whitelist` 用 `try/except ImportError` 兜底一个同仓模块，等于给「导入失败」写了一条静默降级路径（§3.3）。
3. 导入风格三种并存：`fetcher.py`/`validator.py` 用相对导入（`from .config import`），`main.py`/`grouper.py`/`generator.py` 用绝对导入（`from src.xxx import`），`normalize.py` 在函数内导入。结果是这套代码只能以 `python -m src.main` 在仓库根目录运行，既不能 `pip install`，也没有 `src/__main__.py`（所以 `python -m src` 也不可用）。

---

## 5. 已知问题索引（含审计报告章节号）

| 严重度 | 问题 | 位置 | 交叉引用 |
|---|---|---|---|
| P0 | 100/组截断使交付量与 `stats.json` 不一致 | `generator.py:182` | `getting-started.md` FAQ 1/2/3；`audit-d-output.md` |
| P0 | ~~失败不产生非零退出码~~ **已修（`871e32d`）** | `main.py:154-158` | §2.3、C-P0-2 |
| P0 | `validate()` 把异常当有效 | `validator.py:27` | §3.5b、C-P1-8 |
| P0 | 零测试（HEAD 状态） | 全仓 | §1.2、C-P0-1 |
| P1 | `--no-cache` 不写缓存 → `--skip-fetch` 必失败 | `main.py:67-79` | §2.3、C-P1-3 |
| P1 | 正则未预编译，分类阶段慢 ~40× | `categorizer.py` | §3.4(a)（数据来自报告） |
| P1 | 验证阶段吞吐低，CI 30 分钟余量不足 | `validator.py:16` | §2.6（数据来自报告） |
| P2 | 缓存目录算错（`src/.cache`） | `lib/cache.py:13` | §2.3、C-P2-3 |
| P2 | 死代码：`_excluded()`、不可达尾部、`original` | `categorizer.py`、`normalize.py` | §3.5、C-P2-5 |
| P2 | 双反斜杠正则永不匹配 | `categorizer.py:141,143,396` | §3.5、C-P2-6 |
| P2 | `strip_noise` 删掉内部空格 | `normalize.py:84` | §3.5、C-P2-7 |
| P2 | `logo_map` 重复键 `"viutv"` | `logo_map.py:47` | §1.5、C-P2-8 |
| P2 | 库层 print 用于日志（0 处 logging） | `fetcher.py`、`grouper.py` | §1.5、C-P2-9 |
| P2 | 无 `pyproject.toml` / lock，不可安装 | 仓库根 | §3.1、C-P2-1 |
| P2 | `.gitignore` 只挡 `__pycache__/ *.pyc .venv/` | 仓库根 | §3.7、C-P2-4 |

---

## 6. `config/` 也是架构的一部分（376 行）

| 文件 | 行数 | 作用 | 谁在读 |
|---|---:|---|---|
| `config/sources.yaml` | 111 | 20 个数据源（`name` / `url` / `enabled` / `priority` / 可选 `headers`） | `Config.sources` |
| `config/alias.txt` | 168 | 频道别名映射（非空行 144 条），支持 `->` 与 `=` 两种分隔符，`#` 开头为注释 | `Grouper._load_aliases` |
| `config/groups.yaml` | 79 | 分组相关配置 | **当前无代码读取**（`grep -rn "groups.yaml" src` → 无命中） |
| `config/whitelist.txt` | 9 | 验证器直接放行的 CDN 域名 | `Validator._is_whitelisted_cdn` |
| `config/proxy.txt` | 9 | 验证器直接丢弃的代理域名 | `Validator._is_proxy_domain` |

这 376 行是**事实上的业务规则**，但没有任何 schema 校验：写错一个分组名、多打一个空格，都不会报错，只会让产物悄悄少一批频道。

`alias.txt` 的两种分隔符在代码里是硬事实（`grouper.py:28-31`），但文件里没有说明，属于最容易被改坏的地方。

---

## 7. 与审计报告的差异（为什么数字对不上）

审计报告 `audit-c-engineering.md` §1.1 记的代码规模是 **2,161 行 / 14 个 .py / `main.py` 159 行**；当前 `wc -l` 得到 **2,200 行 / `main.py` 168 行**。其中 9 行来自 `src/main.py` 的退出码修复（`print` + `return` → `file=sys.stderr` + `raise SystemExit(1)`，提交 `871e32d`）：`git show 074c677:src/main.py | wc -l` → `159`，当前 HEAD → `168`；+16 行来自 `src/generator.py`（182 → 198，其中 +14 是分组重构的 `CATEGORY_ORDER` 扩充、+2 是 `📺 有线电视` 的辨析注释）；`src/group/categorizer.py` 从 670 涨到 **684**，其中 +7 来自 2026-10-29 分组逻辑重构（`a00e134`，670 → 677）、+7 来自随后的第二遍修正（`8a292b3`，677 → 684，主要是说明 `\b` 在 CJK/数字边界失效的注释）。报告记录时其余文件行数逐条一致。

同理，报告 §1.2 说「零测试、182 次机器人提交」——机器人提交今天已是 **183** 次（`git rev-list --count --author=github-actions HEAD`）；「零测试」在 189 个历史提交里成立（`git rev-list --count 3020583^` → 189），但 `3020583` 起仓库已有 **306** 个用例，分组重构后经过多轮补齐现为 **323 passed / 7 xfailed**（330 例）。报告描述的是整改前的状态，本文描述现状。
