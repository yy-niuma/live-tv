# live-tv 一手核查记录（控制器自测，非子代理报告）

基线：`git clone https://github.com/yy-niuma/live-tv` @ `f75575a` (2026-10-28), 185 commits
本地路径：`/home/hermes/.hermes/projects/live-tv`
venv：`.venv`（pyyaml / aiohttp / aiofiles / charset-normalizer 已装）

---

## P0-1 生成器硬截断：每分组只输出 100 个，丢失 7282 个频道

`src/generator.py:167-172`
```python
# ALL 播放列表每个分组最多 100 个
for ch in channels[:100]:
    ...
if len(channels) > 100:
    all_lines.append(f"# ... and {len(channels) - 100} more")
```

实测（`output/all_merged.m3u` vs `output/stats.json`）：

| 分组 | m3u 实际 | stats | 丢失 |
|---|---|---|---|
| 🌐 国际 | 100 | 3870 | -3770 |
| 🎭 综艺频道 | 100 | 1005 | -905 |
| 📰 新闻财经 | 100 | 679 | -579 |
| 🎵 音乐频道 | 100 | 673 | -573 |
| 🎬 电影频道 | 100 | 603 | -503 |
| 📡 卫视频道 | 100 | 403 | -303 |
| 🧸 儿童频道 | 100 | 371 | -271 |
| 🎬 纪录片 | 100 | 292 | -192 |
| ⚽ 体育频道 | 100 | 282 | -182 |
| 🌐 国际频道 | 96 | 100 | -4 |
| 合计 | **1168** | **8450** | **-7282** |

9 个大分类**每个恰好 100** —— 截断特征。小分类（省/港澳台）未受影响，说明只有 >100 的组被砍。

## P0-2 输出文件含 9 行非法 M3U 语法

`# ... and N more` 被当作播放列表内容写出（`generator.py:172`）。实测 `output/all_merged.m3u`：

```
517:# ... and 296 more
822:# ... and 453 more
1025:# ... and 571 more
1422:# ... and 577 more
1625:# ... and 262 more
1828:# ... and 904 more
2031:# ... and 182 more
2234:# ... and 174 more
2453:# ... and 3581 more
```

这不是合法 m3u 指令（合法注释只能是 `#EXT...` 或普通 `#` 注释后不跟内容语义），
部分播放器会把它渲染成一个叫「... and 3581 more」的频道或直接报错。

## P0-3 自报总数与文件实际差 7000

`output/all_merged.m3u` 第 6 行：
```
# Total: 8168 channels, 51 categories
```
文件里实际 `#EXTINF` 行数：**1168**。

`generator.py:162` 用的是 `total_all`（截断前计数），而写出时用 `channels[:100]`（截断后）。
⇒ 头部信息、`stats.json`、README 三处全部虚报。

## P0-4 13 个死分类 / 2 个野分类

`CATEGORY_ORDER` 定义 62 个分类，`stats.json` 实际产生 51 个。

**死分类（定义了排序，但分类器从不返回）13 个：**
`🇮🇳 印度` `🇯🇵 日本` `🇰🇷 韩国` `🇺🇸 北美` `🌍 中东` `🌍 欧洲` `🌍 非洲`
`🌎 拉丁美洲` `🌏 亚洲（东南亚）` `🌏 亚洲（其他）` `🌏 大洋洲` `📺 其他` `📺 有线电视`

**野分类（产生了，但 CATEGORY_ORDER 里没有 → 排序走 except 分支排到末尾）2 个：**
`🌐 国际` (3870，**全站最大类**) / `🇨🇳 中国源` (7)

⇒ 精心写的国际细分规则（`categorizer.py:342-353` 的 DSTV→非洲、TV Chile→拉美、
Canal 13→拉美 等）**全是死代码**，一个都没生效。

## P0-5 兜底顺序错误：recategorize_others 抢走国际细分

`categorizer.py:443` 和 `460` 都在 `recategorize_others()`（365-465）里
`return "🌐 国际"`，而 `categorize()` 的国际细分在 **578-594**（第 7 步）。

调用顺序上 `recategorize_others` 先跑 → 兜底把所有无法精确匹配的频道标成 `🌐 国际`
→ 后面的国际细分逻辑（日/韩/欧/美/拉美）永远拿不到这些频道。

这就是「国际 3870 且细分分类全死」的机制。

## P0-6 README 完全失真，播放列表 URL 404

`README.md` 声称的地址指向 **`yy-niuma/iptv`**（仓库实际叫 `live-tv`）：

```
404  https://raw.githubusercontent.com/yy-niuma/iptv/main/output/all_merged.m3u
404  https://raw.githubusercontent.com/yy-niuma/iptv/main/output/hk_merged.m3u
200  https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/all_merged.m3u
200  https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/hk_merged.m3u
```

README 数字 vs 实际：

| 项 | README | 实际 |
|---|---|---|
| all_merged 分组 | 52 | 51 |
| 总频道（去重后） | 23,480 / **14,224** | **1,168** |
| 🌐 国际 | 9,072 | 3,870（stats）/ 100（输出） |
| 📺 TVB | 11 | 6（stats）/ 4（hk 输出） |
| 🇹🇼 台湾 | 67 | 30（stats）/ 21（hk 输出） |
| hk_merged 频道 | **162** | **33** |

⇒ 拿 README 地址的用户**根本订阅不到任何东西**（404）。

## P1-7 hk_merged 静默丢失 11 个港澳台频道

stats 港澳台类合计 **44**，hk_merged 实际 **33**：

| 分类 | stats | hk 输出 | 丢失 |
|---|---|---|---|
| 📺 TVB | 6 | 4 | -2 |
| 🇹🇼 台湾 | 30 | 21 | -9 |
| 📺 ViuTV | 1 | 1 | 0 |
| 📺 RTHK | 3 | 3 | 0 |
| 📺 HOY TV | 1 | 1 | 0 |
| 🇲🇴 澳门 | 2 | 2 | 0 |
| **🇨🇳 中国源** | — | **1** | 分类错乱 |

两个问题：
1. `is_clean_name()`（`generator.py:69-80`）的 `DIRTY_PATTERNS` 含 `"webkit"` / `"safari"` /
   `"edge/"` 等浏览器标识，会误杀名字里恰好含这些子串的**正常频道**（假阳性）。
2. hk 里混进 1 个 `🇨🇳 中国源` 分类的频道 —— `_is_hk_region()` 判定与分组不一致。

## 工程基线

- 14 个 .py，2161 行，`categorizer.py` 670 行（31%）
- **零测试文件**
- `requirements.txt` 4 个依赖**全部无上限 pin**（`pyyaml>=6.0` 等）
- 无 `pyproject.toml` / `setup.py`，无 ruff/flake8/black/mypy 配置
- `.gitignore` 仅 3 行
- `output/` 产物（259KB m3u）**提交进 git** —— 产物当 CDN 用
- CI 每天 UTC 0:00 跑

---

## 与子代理报告的关系

以上全部为我（控制器）独立实测，不是子代理自报。子代理 4 路审计
（分类/管道/工程/产物）回来后需与此表交叉验证：
**若子代理结论与本记录冲突，以可复现的命令输出为准，并把冲突点写进最终报告。**
