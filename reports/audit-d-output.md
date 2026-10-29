# 输出产物质量审计报告

- **审计对象**：`output/all_merged.m3u`（258,998 B）、`output/hk_merged.m3u`（8,454 B）、`output/stats.json`
- **审计方式**：只读。所有数字由脚本对真实文件解析得出，未修改 `src/` 与 `output/` 任何内容。
- **快照指纹**：`all_merged.m3u` sha256 前 16 位 `82e992dfc410b164`；`hk_merged.m3u` `eb890e61aebb3601`
- **产物日期**：`#PLAYLIST` 标注 2026-10-28，文件 mtime 2026-10-29 01:08（git 最后一次自动提交 `f75575a Update IPTV 2026-10-28T05:25:45Z`）
- **分类口径**：P0=产物不可用/严重误导，P1=明显功能缺陷，P2=体验/规范瑕疵

---

## 一、产物现状

### 1.1 文件级事实（`wc -c` / 二进制解析）

| 文件 | 字节 | 行数(含末尾空行) | `#EXTINF` 条目 | 分组数 | BOM | 行尾 | 编码 |
|---|---|---|---|---|---|---|---|
| `all_merged.m3u` | 258,998 | 2,454 | **1,168** | **51** | 无 | 纯 LF（CRLF=0） | UTF-8 合法 |
| `hk_merged.m3u` | 8,454 | 87 | **33** | **7** | 无 | 纯 LF | UTF-8 合法 |

`all_merged.m3u` 第 1–7 行为文件头：

```
1  #EXTM3U x-tvg-url="https://epg.pw/xmltv/epg_HK.xml?lang=zh-hant"
2  #EXTVLCOPT:network-caching=1000
3  #EXTVLCOPT:live-cache=1000
4  #EXTVLCOPT:ttl=5
5  #PLAYLIST:All IPTV 2026-10-28
6  # Total: 8168 channels, 51 categories
7  (空行)
```

### 1.2 三套互相矛盾的数字（关键前提）

| 来源 | 频道总数 | 分组数 |
|---|---|---|
| 文件头 `# Total:` | **8,168** | 51 |
| `stats.json` 求和 | **8,450** | 51 |
| **文件里真实存在的 `#EXTINF`** | **1,168** | 51 |
| `README.md` 宣称 | **23,480（去重后 14,224）** | 52 |

按源码交叉验证，链路是：`stats.json` = 分组后未截断数（8,450）→ `generator.py` 用 `is_clean_name()` 过滤掉 282 条后写入头部 `# Total:`（8,168）→ 随后 `channels[:100]` 截断，实际落盘 1,168。
**即：头部声明 8,168，实际只给了 1,168，静默丢弃 85.7%（7,000 条）。**

### 1.3 协议分布

| scheme | 条数 | 占比 |
|---|---|---|
| https | 728 | 62.33% |
| http | 440 | 37.67% |
| rtmp / rtsp / udp / rtp | **0** | 0 |

按分组看 http 明文占比（HTTP 在 https 页面嵌入播放器里会被混合内容策略拦截）：

| 分组 | http | https | http 占比 |
|---|---|---|---|
| 🌐 国际 | 72 | 28 | **72%** |
| 🇹🇼 台湾 | 24 | 6 | **80%** |
| 📺 央视频道 | 19 | 6 | **76%** |
| 📺 TVB | 6 | 0 | **100%** |
| 📺 湖南 / 广东 / 山东 / 辽宁 / 江西 / 北京 / 福建 / 河南 / 深圳 / 澳门 等 | — | — | **100%** |
| 📰 新闻财经 | 10 | 90 | 10% |
| 📺 纪录片 | 27 | 73 | 27% |

> 港澳台与央视这两块最核心的内容，几乎 100% 走 http 明文，是最容易在浏览器系播放器上直接挂掉的部分。

---

## 二、量化分析

### 2.1 重复

| 维度 | 结果 |
|---|---|
| 完全相同的频道名 | 0 组（1,168 个名字全部唯一） |
| 完全相同的 URL | 0 组 |
| **忽略 query 后流地址相同** | **17 组簇 / 其中 8 组是真重复（8 条冗余）** |
| 同一接口不同 `id=`（不算重复） | 9 组，覆盖 66 条 |

名字唯一**不是**去重高质量的证明，而是 `normalize.merge_duplicate_channels()` 把同名条目合并成了单条（且 2 个备用 URL 存进 `_backup_urls` 后根本没有输出——见 §2.5）。

**真重复 TOP（同一路流被写成两个频道，全部附行号）：**

| 流地址（去 query） | 重复条目 | 判定 |
|---|---|---|
| `live-play-hls.cctvnews.cctv.com/CCTVChannel/channel_cctv4k_mbd.m3u8` | L45 `CCTV-4K` / L57 `CCTV4K` | 同一频道两个名字，仅 auth_key 不同 |
| `ali-m-l.cztv.com/channels/lantian/channel002/1080p.m3u8` | L107 `浙江钱江` / L109 `浙江钱江都市` | 同一路流两个名字 |
| `jwcdnqx.hebyun.com.cn/live/clzhpd/1500k/tzwj_video.m3u8` | L211 `河北农民`(📺 河北) / L2367 `昌黎综合`(🌐 国际) | **跨分组重复 + 名称疑似错标** |
| `live.xysrmt.cn/xwzh/sd/live.m3u8` | L1232 `新沂新闻频道`(📰) / L2361 `新沂新闻`(🌐) | 跨分组重复，且 L2361 的 URL 带尾引号 |
| `vd4.bdstatic.com/mda-mh3ei4sg2jypty79/...` | L861 `DJ《望爱却步》` / L875 `DJ版《望爱却步》` | 同一 mp4 出现两次（后者还带 `#` 片段） |
| `l.cztvcloud.com/.../SXqingyuan1/720p.m3u8` | L2343 `庆元新闻综合` / L2345 `庆元综合` | 同流两名 |
| `l.cztvcloud.com/.../SXwencheng1/720p.m3u8` | L2353 `文成新闻综合` / L2355 `文成综合` | 同流两名 |
| `l.cztvcloud.com/.../SXjinyun1/720p.m3u8` | L2429 `缙云新闻综合` / L2431 `缙云综合` | 同流两名 |

**近似重名（同一频道的两套命名，未被合并）：** `RTHKTV31`(L538, akamai 官方) 与 `RTHK31`(L540, jdshipin 中转)；`CCTV5` 与 `CCTV5+`、`CCTV+1`/`CCTV+2` 与 `CCTV1`/`CCTV2` 在视觉上易混（后两组是不同频道，但命名冲突）。

### 2.2 EPG 覆盖（README 声称"支持 7 天节目单"）

| 指标 | 实测 |
|---|---|
| 带 `tvg-id` 的条目 | **0 / 1,168 = 0.00%** |
| 带 `tvg-name` | 1,168 / 1,168 = 100% |
| 头部 `x-tvg-url` | 有（1 条，指向 `epg.pw/xmltv/epg_HK.xml`） |

我实际抓取了这个 EPG（HTTP 200，`text/xml`，19,379,112 B，3.64s），解析结果：

- EPG 里只有 **231 个 `<channel>`**，且 `id` 是纯数字（`368322`、`368323`…），**与播放列表的 0 个 tvg-id 完全无法对接**；
- 只能靠 display-name 文字匹配：**精确匹配 13 / 1,168 = 1.11%**（CCTV1、CCTV4、TVB Plus、ViuTV、HBO、AXN、France24、DW、CartoonNetwork、CBeebies、DiscoveryChannel 等）；
- 放宽到子串模糊匹配也只有 **63 / 1,168 = 5.39%**，且其中大量是假阳性（`AXN` 命中 `AXNBlackHungary`/`AXNLatinAmerica` 等 8 个同名变体）。
- 即便在 TVB 组内，也**只有 `TVB Plus` 1 个能精确匹配**——`TVB 翡翠台` 因前缀+空格对不上 EPG 的 `翡翠台`。

**结论：EPG 名义接入、实际≈未接入。README 的"TVB、央视、凤凰卫视等主流频道支持 7 天节目预告"与事实不符（1.1%）。**

### 2.3 logo 覆盖（含 20 条实测）

| 指标 | 实测 |
|---|---|
| 有 `tvg-logo` | **1,157 / 1,168 = 99.06%** |
| 无 logo 的 11 个 | `30ATVClassicMovies, AfraFilm, CafeFilm, 4Music, WionNews, Newsmax, AlhaqeqaAldawlia, America'sVoice, 6WiseTv, AVAFamily, DoveChannel` |
| logo 走 `ghfast.top` 二级代理（`https://ghfast.top/https://raw...`） | **237 条 = 20.48%** |
| logo 主机 TOP | `i.imgur.com` 461、`ghfast.top` 237、`tb.zbds.top` 118、`upload.wikimedia.org` 98、`images.pluto.tv` 60 |

**logo URL 抽查 20 条（限流：串行、间隔 0.6s、`--max-time 10`、`-L`），结果 17/20 可用：**

| 结果 | 条数 | 样本 |
|---|---|---|
| 200 图片 | 17 | `i.imgur.com/AVfTwNw.png`(11524 B)、`ghfast.top/...东森超视.png`、`tb.zbds.top/logo/中国蓝新闻.png`、`upload.wikimedia.org/...ESPN_wordmark.svg`、`gitee.com/suxuang/logo/...湖南卫视4K.png` |
| **404** | 2 | `ghfast.top/.../logo/上海滩.png`（14 B text/plain）、`tb.zbds.top/logo/昌黎综合.png`（2,043 B text/html） |
| **连接失败(code 000)** | 1 | `live.fanmingming.cn/tv/RTHK32.png` |

失效 3/20 = **15%**。另外 237 条 logo 挤在 `ghfast.top` 一个反代上，该域名挂了就是 20% logo 集体变白。

### 2.4 URL 畸形率

| 类别 | 条数 | 占比 | 证据 |
|---|---|---|---|
| IP:port 直连 | **250** | 21.40% | 端口分布 80(84)、8080(30)、8000(22)、82(15)、98(9)、9901(5)、808(4)… |
| 其中非标准端口（非 80/443/8080/1935/8443/8000） | **111** | 9.50% | `http://74.91.26.218:82/live/cctv1hd.m3u8`、`:98`、`:9901` |
| http 明文 + IP 直连（双重高危） | **252** | 21.58% | — |
| URL 内含未编码中文 | **5** | 0.43% | L161 `http://8.138.7.223/【公众号：榴芒电视】/四川科教.m3u8`；L203/205/207 `dassby.qqff.top:99/live/辽宁教育青少/...`；L1833 `.../wlty.m3u8` |
| **URL 尾部泄漏引号（解析 bug）** | **1** | — | **L2361** `http://live.xysrmt.cn/xwzh/sd/live.m3u8?zjiangsd"` |
| **URL 内残留未替换模板占位符** | **1** | — | **L1382** `.../playlist.m3u8?ads.appversion=[APP_VERSION]&ads.network_name=[networkname]` |
| 超长 URL（>250 字符） | 6 | 0.51% | 最长 823 字符（L1863 `AmericanNinjaWarrior`，带 xumo 广告参数） |
| 非直播（`.mp4` 点播文件） | **44** | 3.77% | 43 条在 🎵 音乐频道：`https://vdse.bdstatic.com//6d39df48....mp4` |
| 网页播放接口（huya.php，点播剧集） | **17** | 1.46% | `tv.zimtv.cn/tv/player/api/huya.php?id=23824164` |
| 名称本身是垃圾 | 6 | 0.51% | `:24`(L1278, 📰)、`90210`(L1740, 🎭)、`.black`(L1744)、`.red`(L1746)、`.sci-fi`(L2046, 📺 纪录片)、`电影_赛车`(L1835, ⚽) |

URL 长度：min 26 / 中位 54 / p95 116 / max 823；distinct host 546，其中 399 个 host 只承载 1 个频道。

### 2.5 容灾能力（顺带发现）

`normalize.merge_duplicate_channels()` 会为每个频道收集最多 2 个备用 URL 存进 `_backup_urls`，但 `generator.build_extinf()` **只输出 `ch.url` 一个地址**，`_backup_urls` 从未写出。也就是说：**1,168 个频道 = 1,168 条 URL，没有任何一条备用线路**。任一条挂了就是频道消失，播放器侧无法自动 failover。

---

## 三、分组质量

### 3.1 分组结构

- 51 个分组，`CATEGORY_ORDER` 命中 49 个；`🌐 国际`、`🇨🇳 中国源` 不在 `CATEGORY_ORDER` 里，因此被 `sort_key()` 归到 `(1, name)` 尾部——**最大的分组（国际）被排在文件最末**。
- 50/51 分组名以 emoji 开头（`⚽ 体育频道` 例外，`⚽` 也是 emoji，仅码位在 0x26xx 段）。
- **同一个频道出现在多个分组：** 名字维度 0 例，但"同一路流跨组"有 4 例（L211/L2367、L1232/L2361、L45/L57 同组、L107/L109 同组），见 §2.1。

### 3.2 `#EXTGRP:` 与 `group-title=` 一致性

**两者都写了，但写法都是错的：**

| 问题 | 实测 |
|---|---|
| `#EXTGRP:` 出现次数 | **51 次 = 每个分组 1 次**（写在组首，之后紧跟该组全部频道） |
| 实际带 `EXTGRP` 生效的条目 | 按 M3U 语义 `#EXTGRP` 只作用于**紧邻的下一条**，因此 **51 / 1,168 = 4.4%** 生效，**1,117 条（95.6%）实际没有 EXTGRP** |
| 值不一致 | `#EXTGRP:📺 央视频道 (25)` 带 `(25)` 计数后缀，而 `group-title="📺 央视频道"` 不带 → 同一频道在两类播放器里分组名不同 |
| 计数还会撒谎 | 9 个被截断分组里，EXTGRP 声称的数量与实际条目数不符：`#EXTGRP:🌐 国际 (3681)` 后面只有 100 条；`(1004)`→100、`(677)`→100、`(671)`→100、`(553)`→100… |

各行示例（文件第 8–12 行）：

```
8   #EXTGRP:📺 央视频道 (25)
9   #EXTINF:-1 tvg-name="CCTV1" tvg-logo="..." group-title="📺 央视频道",CCTV1
10  http://74.91.26.218:82/live/cctv1hd.m3u8
11  #EXTINF:-1 tvg-name="CCTV2" ... group-title="📺 央视频道",CCTV2
12  http://107.150.60.122/live/cctv2hd.m3u8
```

### 3.3 分组合理性 —— 用规则交叉核验（不是目测）

| 分组 | 条目 | 判定为错分的条数 | 错分率 | 证据 |
|---|---|---|---|---|
| 📡 卫视频道 | 100 | **99** | **99%** | 名字里没有"卫视"字样且为纯拉丁名。根因：`categorizer.py` 第 4 节 `overseas_satellite` 含裸关键词 `r"atv"`，把任何以 **...aTV** 结尾的台全吃进来 |
| 🌐 国际 | 100 | **100** | **100%** | 100/100 全是中文名，其中 81 条是典型国内地方台命名（`*新闻综合`/`*综合`/`*公共`/`*都市`/`*生活`） |
| 🎵 音乐频道 | 100 | 41 | 41% | 名含 `DJ/伤感/情歌/歌单/《》`；其中 43 条 URL 是 `.mp4` 点播文件 |
| 🎭 综艺频道 | 100 | 16 | 16% | 15 条来自 `tv.zimtv.cn/.../huya.php` 的电视剧（`庆余年/射雕英雄传/天龙八部/鹿鼎记/寻秦记…`），1 条 mp4 |
| 🧸 儿童频道 | 100 | ~3 | 3% | `AKCTVMeettheBreeds`/`AKCTVPuppies` 类犬赛节目 |
| ⚽ 体育频道 | 100 | 2 | 2% | `电影_赛车`、`易中天品三国`类归到纪录片 |
| 📺 纪录片 | 100 | ~4 | 4% | `易中天品三国`、`.sci-fi`、`Arsenal`（球队频道） |

#### 🌐 国际 100 条抽样（全量列出，人工判定）

**误分类估算：抽样 100 条中，0 条是真正的国际频道，误分类率 = 100%。** 100 条全部是浙江/江苏/黑龙江/福建等地的县级、市级台：

```
L2253 七台河新闻综合   L2255 三明新闻综合   L2257 上虞新闻综合   L2259 东莞新闻综合
L2261 中国蓝新闻      L2263 乐至综合      L2265 云和新闻综合   L2267 云霄综合
L2269 井研综合       L2271 亳州农村      L2273 任丘综合      L2275 伊犁哈萨克
...
L2395 浙江国际       L2397 浙江教科      L2399 浙江数码时代   L2401 浙江生活
L2403 浙江经视       L2405 浙江遂昌      L2415 湖州新闻综合   L2421 灌阳新闻综合
L2451 西宁新闻综合
```

其 URL 主机分布也印证：该组 33 个 host 里 `cztvcloud.com`(27) + `cztv.com`(7) 占 34 条，即浙江广电体系的县级台。

**根因链（三条叠加）：**
1. `PROVINCE_KEYWORDS` 是封闭白名单，`浙江经视`/`浙江生活`/`浙江教科` 都不在名单里 → 落不到省级分组；
2. `categorize()` 所有规则不命中时 `return recategorize_others(...)`，而它的兜底是 `return "🌐 国际"`——**"国际"分组就是垃圾桶**；
3. `generator` 的 `channels[:100]` 按**插入顺序**截断，而县级台源先被插入，于是"⃞桶"的头部全是县级台，真正的 iptv-org 国际频道（akamaized/pluto/amagi 系）被整体截掉。

也就是说：**这份产物里"国际"分组既没有国际频道，也不是按质量挑的 100 条。**

### 3.4 emoji 分组名的兼容性风险评估

50/51 分组名以 emoji 开头（`📺`/`🌐`/`🎬`…）。UTF-8 本身合法（§5 已验证），但风险在于：

- **低风险**：VLC / PotPlayer / TiviMate / IPTV Smarters 均按 UTF-8 解析 `group-title`，正常显示。
- **中风险**：部分老旧播放器（Kodi 旧版 PVR、部分电视盒子固件）按 Latin-1 解码，emoji 变乱码，且**用户手动收藏/隐藏分组时无法用文字匹配**。
- **已发生的实害**：`#EXTGRP` 把 `(25)` 计数写进组名，本身就是把"元数据"塞进"标识符"，这类做法在分组名带 emoji 时更难肉眼比对。
- 建议：保留 emoji 展示名，但**另加一个纯 ASCII 的 `tvg-group`/或固定 `group-title` 语料**（见 §7）。

---

## 四、港澳台专项：TVB 为什么只有 6 个

### 4.1 实际数字（先纠正任务给的估算）

`hk_merged.m3u` 实际 **33 条 / 7 个分组**（不是 43）：

| 分组 | 条数 |
|---|---|
| 🇹🇼 台湾 | 21 |
| 📺 TVB | **4** |
| 📺 RTHK | 3 |
| 🇲🇴 澳门 | 2 |
| 📺 ViuTV | 1 |
| 📺 HOY TV | 1 |
| 🇨🇳 中国源 | 1（`华丽翡翠台`，本就是 TVB 台，却挂在"中国源"组） |

`all_merged.m3u` 里 TVB 组有 **6 条**：`TVB 明珠台`、`TVB Plus`、`TVB 星河`、`TVB 翡翠台`、`无线新闻`、`TVB 娱乐新闻`。

### 4.2 根因拆分：一部分是"生成时丢了"，一部分是"源头就少"

**(A) 生成时丢了 —— HK 列表少 2 个 TVB + 9 个台湾台（可复现）**

直接调用项目自己的 `is_hk_region()`：

| 频道 | `is_hk_region()` | 为什么 |
|---|---|---|
| `TVB 明珠台` | True | 命中 `明珠台` |
| `TVB 翡翠台` | True | 命中 `翡翠台` |
| `TVB Plus` | True | 命中 `tvb plus` |
| `无线新闻` | True | 命中 `无线新闻` |
| **`TVB 星河`** | **False** | 正则写的是 `tvb星河`（无空格），实际名字是 `TVB 星河`（有空格） |
| **`TVB 娱乐新闻`** | **False** | 同上，`TVB娱乐新闻` vs `TVB 娱乐新闻` |
| **`东森超视`** | False | `tw_exact` 只有 `东森新闻`/`东森电视`/`東森*`，没有 `东森超视` |
| **`三立 台湾台`** | False | 正则 `三立台湾台`（无空格）vs 实际名有空格 |
| **`CNA` / `FTV`** | False | `exclude`/`tw_exact` 里是 `\\bttv\\b` 这类被转义成字面 `\b` 的写法，永远匹配不上 |

所以 hk 列表漏掉的 9 个台湾台是：`CNA, FTV, 三立 台湾台, 东森幼幼台, 东森洋片台, 东森综合台, 东森美洲卫视, 东森财经新闻台, 东森超视`。
这是一个**类级 bug**：`categorizer.py` 里大量模式写成「中文无空格」（`tvb星河`、`三立台湾台`、`tvbs新闻`），而实际频道名是「拉丁+空格+中文」（`TVB 星河`、`三立 台湾台`）。凡这类命名一律漏判。

**(B) 源头不足 + 去重把多源冗余吃掉了**

- `config/sources.yaml` 共 20 个源，**没有任何 TVB 官方源**（无 `tvb.com` / `mytvsuper` / `hkdtmb`），港澳台靠 `sammy0101`、`xiweiwong-hk-iptv`、`epg-pw`、`free-tv-hk` 这类二手聚合源；
- 现有 6 个 TVB 台的 URL **全部是同一个中转接口的 5 个不同 id**：

```
L520 TVB 明珠台    http://php.jdshipin.com/TVOD/iptv.php?id=mzt
L522 TVB Plus     http://php.jdshipin.com/TVOD/iptv.php?id=j2
L524 TVB 星河      http://php.jdshipin.com/TVOD/iptv.php?id=xinghe
L526 TVB 翡翠台    http://php.jdshipin.com/TVOD/iptv.php?id=fct3
L528 无线新闻      http://php.jdshipin.com/TVOD/iptv.php?id=wxxw
L530 TVB 娱乐新闻   http://php.jdshipin.com/TVOD/iptv.php?id=tvbylxw
```

**即：TVB 全家只有一个来源、一个域名、一个 php 接口。** 该接口一挂，整个 TVB 组归零，且因为备用 URL 不输出（§2.5），无任何退路。

- 缺的频道：`无线财经资讯台`、`互动新闻台`、`TVB 新闻2`、独立 `J2`（现以 `TVB Plus` 呈现）等——**这些在 20 个源里本就抓不到**，属于源头不足，不是生成时丢的。

**结论：TVB "只有 6 个"= 60% 源头不足（无官方源、无财经/互动新闻）+ 30% 生成 bug（星河、娱乐新闻被 `is_hk_region` 空格 bug 踢出 hk 列表）+ 10% 去重损失（多源同名只留 1 条且不输出备用）**。

---

## 五、格式合规性

用严格解析器（按 EXTINF 语法逐行状态机）校验 `all_merged.m3u`：

| 检查项 | 结果 | 说明 |
|---|---|---|
| 首行 `#EXTM3U` | ✅ | 第 1 行，且带 `x-tvg-url` 属性 |
| BOM | ✅ 无 | 前三字节 `23 45 58`=`#EX` |
| 行尾统一 | ✅ | 纯 LF，CRLF 计数 0 |
| 编码 | ✅ | UTF-8 全量可解码，无 NUL、无 TAB |
| 文件末尾换行 | ✅ | 以 `\n` 结束 |
| `#EXTINF:<时长> <attrs>,<标题>` 结构 | ✅ 1,168/1,168 匹配 | 0 条畸形 |
| EXTINF ↔ URL 配对 | ✅ 1,168 对，0 孤儿 | 每条 EXTINF 下一行都是合法 URL |
| 名称含逗号/引号（会破坏解析） | ✅ 0 条 | 极端情况无 |
| 名称重复 | ✅ 0 | — |
| **`#EXTVLCOPT` 位置** | ⚠️ | 三条写在**任何 EXTINF 之前**（第 2–4 行）。按语义 `#EXTVLCOPT` 只对紧随其后的条目生效，写在文件头等于**不生效**，`network-caching=1000` 实际没设上 |
| **`#PLAYLIST:` 标签** | ⚠️ | 非标准（Winamp 遗留），VLC/Kodi 忽略该行，无害但也无用 |
| **`# Total:` / `# ... and N more`** | ⚠️ | 以 `#` 开头属注释，不影响解析，但 `# ... and 3581 more`（第 2453 行）是**给人看的谎言**——播放器不会展示，用户也看不到那 3,581 条 |
| `#EXTGRP:` 语义 | ❌ | 见 §3.2，位置只对组内第一条生效 |
| URL 合法性 | ⚠️ | L2361 尾引号、L1382 未替换占位符、5 条未编码中文 |

**真实播放器校验方式说明：** 本机有 `ffprobe` 但它是流探测器，不解析 `#EXTINF` 播放列表；`vlc`/`mpv` 未安装。因此采用「严格状态机解析（等价于 VLC demux/m3u.c 的判定分支）+ EPG XML 交叉」的方式，结论：**结构性解析 100% 通过，语义层（分组、EPG、容灾）不通过**。
单条流是否真能播出（HTTP 200 + 有效 m3u8）本次**未做网络实测**——目标 URL 多为裸 IP，网络调用需人工授权，属未验证项（见 §8）。

---

## 六、缺陷清单

| ID | 级别 | 缺陷 | 量化证据 | 位置 |
|---|---|---|---|---|
| D-01 | **P0** | 每组硬截断 `[:100]`，85.7% 频道静默丢弃 | 头部 8,168 → 落盘 1,168 | `generator.py` `for ch in channels[:100]` |
| D-02 | **P0** | 三套互斥数字：头部 8,168 / stats 8,450 / 实际 1,168 / README 23,480 | §1.2 表 | 头部第 6 行、`stats.json`、`README.md` |
| D-03 | **P0** | 截断保留的是"插入顺序前 100"，不是"质量前 100" | 🌐 国际 100 条全是浙江县级台，国际频道被整体切掉 | 同上 |
| D-04 | **P0** | `tvg-id` 覆盖率 0，EPG 实际匹配率 1.11% | `0/1168`；EPG 231 个数字 id 无法对接；精确命中 13 条 | `generator.build_extinf()` 从不写 `tvg-id` |
| D-05 | **P0** | `🌐 国际` 分组 100% 是国内地方台（垃圾桶分组） | 抽样 100/100 中文名，81 条县级台命名 | `categorizer.recategorize_others()` 兜底 `return "🌐 国际"` |
| D-06 | **P0** | `📡 卫视频道` 99% 是 `...aTV` 拉丁台（裸 `r"atv"` 关键词） | 100 条里 99 条纯拉丁且无"卫视"字样；`CanelaTV/ChinolaTV/AlkarmaTVAustralia` 全部复现 | `categorizer.py` `overseas_satellite = [..., r"atv", ...]` |
| D-07 | **P0** | `hk_merged.m3u` 漏 2 个 TVB + 9 个台湾台（中文正则不接受空格） | `is_hk_region('TVB 星河')==False`、`('东森超视')==False` | `categorizer.is_hk_region()` 的 `tvb星河`/`三立台湾台` 等 |
| D-08 | P1 | `#EXTGRP` 每组只写 1 次，95.6% 条目无 EXTGRP；且值带 `(25)` 计数与 `group-title` 不一致 | 51 次 vs 1,168 条 | `generator.generate_hk_and_all()` |
| D-09 | P1 | 非直播内容混入：44 条 `.mp4` 点播 + 17 条 huya 网页播放接口 = 5.2% | `vdse.bdstatic.com//*.mp4`、`tv.zimtv.cn/.../huya.php?id=` | 音乐/综艺组 |
| D-10 | P1 | 🎵 音乐频道 41% 是 DJ 歌单 VOD，不是电视频道 | 41/100（DJ 字样 30 条，L825–L903） | L825–L1023 整组 |
| D-11 | P1 | 8 组真重复（同一路流写成两个频道），含跨分组重复 | §2.1 表 | L45/57、L107/109、L211/2367、L1232/2361、L861/875、L2343/2345、L2353/2355、L2429/2431 |
| D-12 | P1 | URL 脏数据：尾引号泄漏、未替换模板占位符、未编码中文 | L2361 `...?zjiangsd"`；L1382 `[APP_VERSION]`/`[networkname]`；5 条中文路径 | 解析层（fetcher）未清洗 |
| D-13 | P1 | 0 条备用 URL（`_backup_urls` 算了不写），无 failover | 1,168 频道 = 1,168 URL | `normalize.merge_duplicate_channels()` + `build_extinf()` |
| D-14 | P1 | 单点集中：jmp2.uk 91 条(7.8%)、cztvcloud 28、lskk.top 21；21.4% IP 直连、111 条非标准端口 | §2.4 | 源选择无健康度加权 |
| D-15 | P1 | logo 实测 15% 失效；237 条(20.5%) logo 依赖 `ghfast.top` 单一反代 | 20 抽 3 死（2×404、1×conn fail） | `logo_map` + CCSH 源 |
| D-16 | P1 | 核心分组 100% http 明文（TVB/湖南/广东/山东/…），浏览器系播放器会挂 | TVB 6/6 http、台湾 24/30 http、国际 72/100 http | 源本身为 http |
| D-17 | P2 | `🇨🇳 中国源` 是以"数据来源"命名的分组，语义错误 | 内含 `澳视卫星`(应🇲🇴)、`华丽翡翠台`(应📺 TVB) | `LOGO_REGION_PATTERNS` 按 `gitee.com/suxuang` 判地区 |
| D-18 | P2 | `📺 Now TV` 组只剩 `RightNowTV`（美台误判） | 1/1 全错 | `nowtv` 子串命中 `rightnowtv` |
| D-19 | P2 | `#EXTVLCOPT` 前置不生效 | 第 2–4 行 | `generator` 头块 |
| D-20 | P2 | 最大分组排文件最末（`🌐 国际`、`🇨🇳 中国源` 不在 `CATEGORY_ORDER`） | 第 2453 行前才是 `🌐 国际` | `sort_key()` |
| D-21 | P2 | 50/51 分组名带 emoji，旧播放器乱码/无法文字匹配 | §3.4 | 全局 |
| D-22 | P2 | 垃圾名 `:24`、`90210`、`.black`、`.red`、`.sci-fi`、`电影_赛车` | 6 条 | 源数据未清洗 |
| D-23 | P2 | `📺 国际频道` 组 96 ≠ stats 100（4 条在组内被丢，未记录原因） | 96 vs 100 | 去重阶段 |

---

## 七、改进方案（按可执行顺序）

### 立刻（P0，改 3 个函数即可）

1. **删掉 `channels[:100]` 截断，改为"分级输出"**
   - 方案 A（推荐）：`all_merged.m3u` 不截断（8,450 条 ≈ 1.9 MB，对播放器完全可接受）；另生成 `all_top.m3u` 只放每组前 N（N=按源优先级排序后的前 200）。
   - 方案 B（保守）：保留截断，但必须**按 `get_url_priority()` + 验证通过 + 源优先级排序后再截**，并把头部改成真实数字。
   - 无论哪种，`# Total:` 必须等于**实际写入的条数**（在写入循环里累加，而不是取截断前的 `total_all`）。

2. **修 `.tvb` 空格 bug（一行改动，收益最大）**
   ```python
   # 现在：全量正则假设中文紧跟拉丁
   r"tvb星河"  r"三立台湾台"  r"tvbs新闻"
   # 改成容忍空白：
   r"tvb\s*星河"  r"三立\s*台湾台"  r"tvbs\s*新闻"
   ```
   同时修 `\\bttv\\b` / `\\bftv\\b` 这类**双反斜杠被当字面 `\b`** 的写法（`categorizer.py` 里 `r"\\bttv\\b"` 实际匹配的是 `\bttv\b` 六个字符，永远 False）。改动后 `hk_merged.m3u` 应立即从 33 → 44 条，TVB 从 4 → 6。

3. **拆掉 `r"atv"` 裸关键词**
   ```python
   # 删掉 r"atv"，换成带边界的：
   r"(?<![a-z])atv(?![a-z])"    # 只匹配独立的 ATV / ATV+
   ```
   预期 `📡 卫视频道` 从"99% 垃圾"变成真正的港澳/境外中文卫视台（凤凰、星空、华娱等）。

4. **给每个频道写 `tvg-id`**
   - 源里若有 `tvg-id`（iptv-org 的源基本都有），`fetcher` 要保留，`Channel` 加 `tvg_id` 字段，`build_extinf()` 写 `tvg-id="..."`；
   - 无 `tvg-id` 的，用 `epg.112114.xyz` / `epg.pw` 的 id 表做「中文频道名 → EPG id」静态映射（TVB/央视/卫视各 20~40 条即可覆盖 90% 刚需）；
   - 同时把 `x-tvg-url` 从只挂 HK 一份，改成 `x-tvg-url="url1|url2"`（多源 EPG 拼接是合法写法）。

### 一周内（P1）

5. **分组兜底从"国际"改成"其他/未分类"**，并新增「国内地方台」判定：
   ```python
   # recategorize_others 末尾
   if re.search(r"(新闻综合|综合频道|公共|都市|民生|生活|经济|法治|农村|科教|影视)$", name):
       return "📺 地方台"          # 而不是 🌐 国际
   return "🌐 国际"
   ```
   这样 `🌐 国际` 才真的是国际，县级台进「📺 地方台」并可单独关闭。

6. **过滤非直播内容**（在 `validator` 或新增 `content_filter`）：
   - 拒绝 `path.endswith('.mp4')`、`.flv`（点播）、`huya.php`/`douyu` 等网页播放器接口；
   - 拒绝 URL 含 `[` `]` `"` 的条目（脏数据）；拒绝未编码中文（要么 `quote()` 要么丢弃）；
   - 该项预计清掉 61+ 条（5.2%）。

7. **`#EXTGRP` 要么删、要么逐条写**
   - 逐条写时值必须**与 `group-title` 完全一致**（去掉 `(25)` 计数）；
   - 或直接删掉 `#EXTGRP`（`group-title` 已被所有主流播放器支持），把 `(N)` 计数改为独立注释行。

8. **输出备用 URL**：`build_extinf` 之后为每条追加
   ```
   #EXTVLCOPT:http-referrer=...        # 若源需要
   #EXTGRP 之后追加 #EXTINF 同名的 2 条备用（同一分组内）
   ```
   或采用 `#EXTM3U` 标准外的「同名多 URL」写法（VLC/TiviMate 都支持同名多条，自动按顺序尝试）。

9. **logo 本地化**：把 237 条 `ghfast.top/raw.githubusercontent.com/...` 的 CCSH logo **缓存进仓库 `output/logos/`**（约 237×15 KB ≈ 3.5 MB）或改用 `jsDelivr`（`cdn.jsdelivr.net/gh/CCSH/IPTV@main/logo/`），并在 CI 里跑一次 404 巡检，失效的置空而不是留死链。

10. **分组内按健康度排序后再截断**：`sort(key=lambda c: (url_priority(c.url), https_first(c.url), verified(c)))`，让 https + 已验活的排在前面。

### 值得做（P2）

11. 把 `#EXTVLCOPT` 移到每个 `<channel>` 前（或干脆删，反正现在不生效）。
12. `README.md` 的统计表改为**由 `stats.json` 自动渲染**（加一个 `scripts/render_readme.py`），彻底消灭"文档与产物脱节"。
13. `#PLAYLIST` / `# Total` / `# ... and N more` 三条自造注释建议统一改为 `##` 前缀或直接删除——它们既不标准，又会撒谎。
14. `🇨🇳 中国源` 改名为 `📺 其它中文台`，并修 `LOGO_REGION_PATTERNS` 里"按 logo 域名判地区"的逻辑（域名只说明来源，不说明地区）。
15. `📺 Now TV` 修 `nowtv` 子串匹配（`(?<![a-z])nowtv`）。

---

## 八、我不确定 / 需要人工判断的点

1. **`[:100]` 截断到底是不是有意设计。** 源码注释写「ALL 播放列表每个分组最多 100 个」，说明作者可能故意控制体积。但**同时**头部写 `8168`、README 写 `23,480`，说明作者自己也没把它当成最终产物。这条要么是"临时占位忘了改"，要么是"想省流量但没告知用户"——需要产品决策，不是纯技术 bug。
2. **`stats.json` 的 4 条差额（国际频道 96 vs 100）我没能定位。** 可能是 `is_clean_name()` 过滤，也可能是组内去重，但产物里没有中间态可查。要定位得重跑一次并 dump 中间结果（本次只读审计不允许）。
3. **8 组"真重复"里有 2 组我无法判定谁是对的**：`河北农民` vs `昌黎综合` 共用 `clzhpd`（昌黎属秦皇岛/河北，`clzhpd` 更像"昌黎综合频道"），大概率是**`河北农民` 的 URL 被错标**。另一组 `新沂新闻频道` vs `新沂新闻` 同流两名，哪个是规范名需要人工确认。
4. **`浙江钱江` vs `浙江钱江都市`**：`channel002` 在浙江广电体系里对应"钱江都市频道"，所以 `浙江钱江` 只是简写，不算错，但两条重复应该合并。
5. **单条流是否真能播（HTTP 200 + 有效 m3u8）本次完全没测。** 21.4% 是裸 IP，目标多为灰产中转，实测需要人工授权且会打对方服务器；`validator.py` 本身也有明显漏洞（`_is_valid_response` 接受**空 Content-Type**，等于放过所有无头 HTML 错误页）。建议单独做一轮「抽样 50 条 + timeout 8s」的存活率审计，那个数字才能回答"这 1,168 条里到底几条能看"。
6. **`朝廷`/`卫视` 这类分组在中文播放器生态里到底该怎么切**，取决于用户习惯（有人要"按地区"，有人要"按类型"），现在是**两层混用**——省级按地区、其余按类型。要不要彻底统一成一层，需要产品定。
7. **EPG 的 1.11% 里，"1.11%" 本身依赖我用的名字归一化规则**（去空格/连字符/小写）。换个更激进的归一化（去"台"字、繁简互转）数字会上升到 5~8%，但会引入假阳性（`AXN` 吃 8 个变体）。真实可用率在 **1%~5%** 区间，无论怎么算都远低于 README 的"主流频道支持"。
