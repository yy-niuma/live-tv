# 选源方法：怎么判断一个直播源「值得加」

> 结论先行：**总频道数不是选源指标**。2026-10-29 实测了 60+ 个候选 URL：
> 大多数能给几千条频道，但相对现有语料**可播的新增港台条目 = 0**。
> 真正决定价值的是三件事：URL 新颖度 × 新增条目可播率 × 上游是否还在更新。

## 三步口径

| 步骤 | 做法 | 为什么 |
|---|---|---|
| ① 新颖度 | 抓候选源，URL 集合减去**当前全部启用源**抓到的 URL 集合 | 聚合源之间 95% 重叠；不减去就是自己骗自己（`iptv-org` 一家就有 11,367 条，含所有国家子列表） |
| ② 可播率 | 只对**新增**条目跑 `src/validator.py`（HEAD 优先，失败 GET），不抽样 | 新增 2,631 条却 0 条可播的源很常见：`t.freetv.fun` 抽 80 条 → 0 条可播 |
| ③ 活跃度 | GitHub `pushed_at` + 文件最近 commit | 停更源会腐烂；但停更 ≠ 立刻没价值，要看第 ② 步的实测结果 |

## 2026-10-29 实测：60+ 候选里只有 6 个值得加

| 候选 | 更新 | 新增 URL | 新增港台 | 新增可播 | 结论 |
|---|---|---:|---:|---:|---|
| `qist/tvbox` | 2026-10-29 | 762 | 31 | 9 | ✅ 加入（p3） |
| `YueChan/Live` GNTV.m3u | 2026-10-13 | 101 | 17 | 9 | ✅ 加入（p2） |
| `hebijunge/tvbox-config` 港台.m3u | 2026-10-28 | 15 | 10 | 6 | ✅ 加入（p3） |
| `Jifeng4ever/iptv` hkmt.m3u8 | 2026-08-26 | 31 | 23 | 7 | ✅ 加入（p4） |
| `joy-sheng/newsboy` 台湾香港澳门2024 | 2025-07（停更） | 120 | 55 | 30 | ✅ 加入但降级（p5），停更源有腐烂风险 |
| `MillerArice/iptv` 港台.m3u | 2026-02 | 122 | 73 | 12 | ✅ 加入（p5），与其它源零重叠 |
| `t.freetv.fun/m3u/playlist.m3u` | 活跃 | **2,631** | 73 | **0** | ❌ 抽 80 条 0 可播；且需 UA + 21s，超 30s 超时的边缘 |
| `Guovin/iptv-api` gd 分支 | 2026-08-27 | 814 | — | 2% | ❌ 分支两月未更新，可播率 2% |
| `YanG-1989/m3u` Gather.m3u | 2026-09-18 | 123 | 0 | 0（抽 80 条） | ❌ 抽检全死链 |
| `Kimentanm/aptv` | 2026-09-21 | 55 | 4 | 18/55（33%，多是春晚老录像） | ❌ 内容质量低 |
| `jk2024988/TV2024` tw.m3u | 2026-10-11 | 2,481 | 84 | 0 | ❌ 量大全死 |
| `lubin776/0` tvh.m3u8 | 2026-10-27 | 195 | 59 | 0 | ❌ 同上 |
| `asdjkl6/zx` g.m3u | 2025-05 | 882 | 87 | 3（3%） | ❌ |
| `kaige-cai/live`、`frankkk1/t`、`h1rone/GDIPTV`、`xiechangan123/CN` | 各异 | 656/62/73/73 | 37/18/42/8 | 0 | ❌ 全死链 |
| `free-tv-*` 各区域 `.md`、`iptv-org` 国家子列表、`freetv-hk.m3u8`、`zhi35`、`epg-pw`、`vbskycn-raw` | — | 0 | 0 | 0 | 已在现有语料里（`iptv-org` 索引 / `free-tv-all` 覆盖） |

判据不是「新增多少」，而是「新增可播多少」：`jk2024988` 新增 2,481 条却 0 条可播，
`joy-sheng` 只新增 120 条但 30 条可播 —— 后者才是要的源。

## 加源前后实测（同一台机器，同一天）

```bash
# 加源前
.venv/bin/python -m src.main --no-cache --skip-validation --fetch-timeout 300 --output /tmp/before
.venv/bin/python scripts/check_streams.py /tmp/before/hk_merged.m3u --jobs 24 --timeout 8
#   抓取 18,390 → 同名合并 13,712 → hk_merged 122 条，可播 59（48.4%）

# 加 6 个源后
.venv/bin/python -m src.main --no-cache --skip-validation --fetch-timeout 300 --output /tmp/after
.venv/bin/python scripts/check_streams.py /tmp/after/hk_merged.m3u --jobs 24 --timeout 8
#   抓取 19,502 → 同名合并 14,247 → hk_merged 167 条，可播 76（45.5%）
```

**净增 17 条可播港台频道，0 条丢失**：
`TVBS 新闻`、`中天新闻`、`东森新闻`、`东森美洲`、`东森购物2`、`台视新闻台`、`TW台视新闻`、
`大爱`（含 1台/2台/2/二台 4 个变体）、`有线电视新闻台`、`有线电视财经信息台`、
`澳视Macau96台`、`HOY77台TV`、`RTHK普通話台`。

可用率从 48.4% 掉到 45.5% 是**分母变大**（122→167）而不是质量变差：
丢失可播条目 = 0，分子 59→76。

## 复用这套口径

```bash
# 1) 候选源逐个：总条数 / 港台命中 / 相对基线的 URL 新颖度
#    参考 scripts/check_sources.py 的抓取层（fetcher._get_text + parse_text）
# 2) 只对新增条目做可播性验证
.venv/bin/python scripts/check_streams.py <候选源导出的 m3u> --jobs 24 --timeout 8 --json out.json
```

判 keep 的经验阈值：**新增可播港台 ≥ 5 条**，或新增可播总数占比 ≥ 25% 且非垃圾分类（春晚/购物/录像）。

## 结构性天花板（2026-10-29 修了一半）

`hk_merged` 里同名频道只保留 1 主 URL + 2 备用（`merge_duplicate_channels`，
在 `src/group/normalize.py:237`），选「最优」的依据原来是 **CDN 白名单优先级，不是实测可播性**：

```python
def sort_key(c):
    if is_hk_cdn_whitelisted(c["url"]):
        return (0, 0)
    return (get_url_priority(c["url"]), 0)
```

所以白名单里已死链的 URL 会压过实测可播的 URL。这不是推测 —— 加完 alias 去重后实测到：

| `hk_merged.m3u` | 条数 | 可播 | 可用率 |
|---|---:|---:|---:|
| 不做同名合并 | 167 | 77 | 46.1% |
| 只做同名合并（旧排序） | 144 | **53** | 36.8% |
| 同名合并 + 实测可播排序 | 143 | **64** | 44.8% |

**只做去重就把可播条数从 77 打到 53**：11 个频道组内各有 1 条可播，合并后主 URL 全是死链。

### 修法：把实测结果喂进合并排序

```console
$ .venv/bin/python scripts/check_streams.py output/hk_merged.m3u \
      --health-out config/stream_health.json   # 产出 {url: bool} 快照
$ .venv/bin/python -m src.main                  # 自动读取，按 可播 > 未知 > 不可播 排
[Health] 载入 174 条实测结果（可播 71 / 不可播 103）
```

实现见 `src/lib/stream_health.py`；`merge_duplicate_channels(channels, health=...)`
新增可选参数，`health` 为 `None` 时行为与旧版逐字节一致。快照不入库（机器相关、时效性强）。

### 还剩一半：`_backup_urls` 不写进 M3U

合并阶段算出的 2 条备用链路（`_backup_urls`）在 `generator.build_extinf()` 里**根本没有输出**，
所以主链路死了播放器侧没有 failover。排序只保证「挑中的那条尽量能播」，
不能让挂掉的自动切备用。

下一步（按收益排序）：
1. 把 `_backup_urls` 写成 M3U 里的多条同名 `#EXTINF`，让播放器自己试；
2. 定期跑 `check_streams --health-out` 并接进 CI（先跑实测再生成，别让产物依赖过期快照）；
3. **继续堆源的收益已经很低**：60+ 候选里只有 6 个带来新增可播港台，合计 +17 条。
