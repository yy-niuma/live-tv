# 数据源体检（2026-10-29）

## 为什么会有这份文档

`python -m src.main` 只打印总量。2026-10-29 逐源体检发现：**20 个源里 11 个产出 0 条**，
而整条流水线「看起来完全正常」——总数仍有 18,285 条、`exit=0`、产物正常生成。

三种失效方式，全都静默：

| 失效方式 | 表现 | 源数 |
|---|---|---:|
| markdown 表格被当成 m3u 解析 | HTTP 200、`got 0 channels`、**无警告** | 8 |
| GitHub 代理域名已死 | HTTP 连接失败（`curl` 返回 `000`，0.001s 秒断） | 2 |
| 源站停服 | 两个域名都 20s 超时 | 1 |

修复后（2026-10-29 再加 6 个源）25 个启用源里：**18 个 m3u + 7 个 markdown**，0 个 `empty`。

复现命令：

```console
$ .venv/bin/python scripts/check_sources.py
```

退出码 `0` = 每个启用源都抓到了内容；`1` = 存在 0 条的源。

---

## 修复前后

| | 修复前 | 修复后 |
|---|---:|---:|
| 启用源数 | 20 | 19 → **25**（同日又加 6 个，见 [source-discovery.md](source-discovery.md)） |
| 零产出源 | **11** | **0** |
| 抓取合计 | 18,285 条 | 20,771 → **22,219 条** |

---

## 逐源明细（修复后实测）

| 源 | 频道数 | 判定格式 | 优先级 |
|---|---:|---|---:|
| `iptv-org` | 11,367 | m3u | 4 |
| `CCSH-iptv` | 2,819 | m3u | 3 |
| `free-tv-all` | 2,043 | m3u | 6 |
| `suxuang-myIPTV` | 1,211 | m3u | 4 |
| `gitee-why006-TV` | 1,160 | m3u | 3 |
| `qist-tvbox` | 824 | m3u | 3 |
| `epg-pw` | 756 | m3u | 2 |
| `vbskycn-iptv4` | 430 | m3u | 5 |
| `zhi35-iptv` | 393 | m3u | 2 |
| `xiweiwong-hk-iptv` | 252 | m3u | 2 |
| `newsboy-hktw` | 167 | m3u | 5 |
| `yuechan-live-gntv` | 140 | m3u | 2 |
| `millerarice-hk-tw` | 139 | m3u | 5 |
| `jifeng-iptv-hkmt` | 94 | m3u | 4 |
| `fanmingming-live` | 82 | m3u | 3 |
| `hebijunge-tvbox-hktw` | 81 | m3u | 3 |
| `hujingguang-iptv` | 70 | m3u | 4 |
| `free-tv-uk` | 55 | markdown | 6 |
| `sammy0101` | 32 | m3u | 1 |
| `free-tv-us` | 28 | markdown | 6 |
| `free-tv-kr` | 22 | markdown | 5 |
| `free-tv-cn` | 21 | markdown | 5 |
| `free-tv-jp` | 15 | markdown | 5 |
| `free-tv-tw` | 13 | markdown | 5 |
| `free-tv-hk` | 5 | markdown | 5 |
| **合计** | **22,219** | 18 m3u + 7 markdown | 25 个启用源 |

---

## 三个问题的具体证据

### 1. markdown 表格被当成 m3u（8 个源，可修，已修）

旧 `_fetch_url()` 按**后缀**分派：`.yml`/`.yaml` → YAML，**其他一律当 m3u**。
Free-TV 的 `lists/*.md` 是 markdown 表格：

```markdown
| #   | Channel | Link | Logo | EPG id |
|:---:|:-------:|:----:|:----:|:------:|
| 31  | RTHK TV 31 | [>](https://rthktv31-live.akamaized.net/.../master.m3u8) | <img src="https://i.imgur.com/kf818kM.png"/> | RTHKTV31.hk |
```

`_fetch_m3u()` 只认 `#EXTINF` 行 + 紧随的 `http` 开头的行 —— 一行都不匹配，返回 `[]`。

**修法**：`_fetch_url()` 改为「先抓文本、再按内容嗅探」，顺序是
`#EXTINF` → markdown 表格 → YAML → empty，并在 0 条时打 WARNING。
详见 `src/fetcher.py` 的模块 docstring 与 `tests/test_fetcher_parse.py`（15 个用例）。

**7 个启用的** markdown 源恢复后合计 **159 条**（hk 5 / tw 13 / cn 21 / jp 15 / kr 22 / us 28 / uk 55）。
第 8 个是 `Harbin-byte-iptv`（5 条），它与 `free-tv-hk` 逐字节相同，已停用 —— 所以那次「8 个源 164 条」里的 +5 是零增量。

> 格式嗅探的另一层收益：`free-tv-all` 这个 `.m3u8` 源也被判成 m3u 正常解析（2,043 条），而 `parse_text()` 对认不出的内容返回 `empty` 并打 WARNING —— 不会有第四种静默失效方式。

### 2. `raw.gh.registry.cyou` 代理已死（2 个源，可修，已修）

`sammy0101`（priority **1**，最高优先的香港源）和 `xiweiwong-hk-iptv`（priority 2）
都指向这个代理。实测：

```console
$ curl -sL --max-time 20 -o /dev/null -w '%{http_code} %{time_total}\n' \
    https://raw.gh.registry.cyou/sammy0101/hk-iptv-auto/refs/heads/main/hk_live.m3u
000 0.001202          ← 秒断，不是超时，是域名/DNS 层面就没了
```

同内容直连可用：

```console
$ curl -sL -w '%{http_code} %{time_total}\n' \
    https://raw.githubusercontent.com/sammy0101/hk-iptv-auto/main/hk_live.m3u
200 0.745260          ← 32 个 #EXTINF
$ curl -sL ... https://raw.githubusercontent.com/xiweiwong/hk-iptv-auto/main/hk_live.m3u
200 1.091458          ← 252 个 #EXTINF
```

**修法**：改成直连 `raw.githubusercontent.com`。项目里其他 3 个 GitHub 源本来就是直连
（`fanmingming` / `CCSH` / `hujingguang`），都正常工作，所以不需要再引入第三方代理。

### 3. `t.freetv.fun` 源站停服（1 个源，不可修，已停用）

`t.freetv.fun` 与 `freetv.fun` 两个域名都 20s 超时（`http=000`）。
保留条目标 `enabled: false`，等源站恢复时可以重新打开。

---

## 顺带清掉的重复源

`Harbin-byte-iptv` 的 `lists/hong_kong.md` 与 `Free-TV/IPTV` 的**逐字节相同**：

```console
$ md5sum free-tv-hk.md Harbin-byte-hk.md
93275abfecd1…  free-tv-hk.md
93275abfecd1…  Harbin-byte-hk.md
```

它是 Free-TV 的旧 fork。已标 `enabled: false`（不删，留痕）。

---

## 新增的源

| 源 | 频道数 | 说明 |
|---|---:|---|
| `free-tv-all` | 2,043 | `Free-TV/IPTV` 的 `playlist.m3u8` 全区域合并版，带 `group-title` / `tvg-logo` / `tvg-id`；亚洲部分 China 21 / Taiwan 13 / Hong Kong 5 / Macau 5 / Japan 21 / Korea 22 |

它与上面各区域 `.md` 部分重叠，靠合并阶段的 URL 去重收敛，所以放最低优先（6）。

---

## 防复发

| 手段 | 位置 |
|---|---|
| 0 条时打 WARNING（不再静默） | `src/fetcher.py` `_fetch_source()` |
| 逐源体检脚本 + 退出码 | `scripts/check_sources.py` |
| 配置自洽断言（URL 唯一、https、priority 范围、已知死域名黑名单、停用必须写原因） | `tests/test_sources_config.py`（11 用例） |
| 三种格式的解析契约 | `tests/test_fetcher_parse.py`（15 用例） |
| `headers:` 真的会传给 aiohttp | 同上（`test_headers_from_source_are_forwarded`） |

> 补充发现：`sources.yaml` 里 `freetv-fun` 早配了 `headers.User-Agent`，
> 但旧 `_fetch_source()` **从来没读过这个字段**，等于白配。现已透传。
