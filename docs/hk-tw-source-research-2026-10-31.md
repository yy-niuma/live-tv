# 港澳台补充源调研记录（2026-10-31）

目标：在不换出口的前提下，为「地理封锁而非死链」的港台频道找可用替代链路。

## 结论速览

| 频道 | 结论 | 链路 | 证据 |
|---|---|---|---|
| RTHK 31 | ✅ 换链成功 | `https://fast.hidns.vip/163189/rthk31` | 序号 386921→386923→386925 推进；分片 h264 1920x1080 + aac |
| RTHK 32 | ✅ 换链成功 | `https://fast.hidns.vip/163189/rthk32` | 序号 129548→129549→129551 推进 |
| HOY 78 资讯台 | ✅ 新增（原本没有） | `https://fast.hidns.vip/163189/hoy78` | 序号 484194→484197→484199 推进 |
| ViuTV（hidns 备份） | ❌ 否决 | `https://fast.hidns.vip/163189/viu` | 30s 内序号冻在 534361 = 冻结流 |
| 翡翠台（cdn6 备份） | ❌ 否决 | `https://cdn6.cc.cd/163189/jade` | 间歇 `SSL: UNEXPECTED_EOF` / code 000，不稳 |
| TVBS 新闻 / 中天新闻（SRS 系） | ❌ 否决 | `jnzq.ohoyee.com:9080` / `222.128.55.152:9080` | 每次重取 `hls_ctx` 拿新 token，序号仍全程冻结 = 冻结流 |

最终落地 3 条源，全部 `display_name` + 单流直连路径。

## 判定「可用」的口径（本轮踩过的坑）

只看 HTTP 200 会同时放进两类假阳性，也会误杀真源：

1. **Content-Type 不可信。** `fast.hidns.vip` / `cdn6.cc.cd` 把播放列表标成
   `text/plain`，分片标成 `image/jpeg`。旧口径只认 `mpegurl` → 真能播的源被
   自己判死。现改为**一律以 body 是否以 `#EXTM3U` 开头为准**
   （`src/validator.py::_body_is_playlist`），Content-Type 只决定「要不要读 body」。
2. **HTTP 200 ≠ 活流。** SRS 系的 `hls_ctx` 是会话 token：同一个 token 反复取
   必然拿到同一份播放列表，看起来「在线」，实际是冻结静帧。必须**每次重新
   从 master 取新 token** 再比 `EXT-X-MEDIA-SEQUENCE`。
3. **采样窗口必须跨 ≥2 个 `EXT-X-TARGETDURATION`。** 7s 窗口去测 10s 分片周期
   会假报「序号不推进」（RTHK 32 第一轮就是这么误判的）。
4. **`Content-Type: text/plain` 的 master 里子列表可能是 root-relative**
   （`/live/xxx?hls_ctx=...`）。拼 `dirname + 子路径` 会得到 `host/live//live/...`
   → 假 404。必须用 `urljoin`。这一条一度让我把三条活源判成 404。

## 已否决的线索

- **RTHK 官方 feeds 是「假 200」**：`www.rthk.hk/feeds/dtt/rthktv3X_https.m3u8`
  master 200，但里面 `akamaized.net` 子流本机全部 403（纯 geo-block，加
  Referer/Origin 无效）。只看 master 状态码会误判「已修复」。
- **`hkdtmb.com` 已停运**：首页标题 `R.I.P HKDTMB / HKDVB (2019-2025)`，
  所有 `.m3u8` 路径返回同一份 SPA 公告页（HTTP 仍 200）。
- **`hoytv-live-stream.hoy.tv/ch76|77|78` 本机全 403**（geo-block）。
- **`4gtv.tv`** 被 Cloudflare 拦；`4gtvvideo.4gtv.tv` DNS 不存在；
  `cnlive.club` 的 4gtv 号段全是同一段 `sailei.0.ts` 占位片。
- **`rthk.hk/feeds/dtt/` 只有 tv31 / tv32 有效**，tv33/34、rthknews、dtt31
  等一律返回官网 404 SPA（HTTP 200 + `<!doctype html>`）。
- **`jdshipin` 的 id 命名空间不可信**：`id=rthk33` 实际指向 `cctv1`，
  `id=j2` 实际指向 `tvbp`（TVB Plus）。**不能用 id 反推台名。**
- **`fc` 是模糊 slug**：同 host 另有 `ztxw`（= 中天新闻，语义明确），
  所以 `fc` 不能当「中天新闻」写进产物。
- **`hkcable` 的 `hdNNN_h.live` 号段只有 hd110 一路**（有线电视新闻），
  100~135 其余全 404/非 m3u。
- **`38.64.72.148` modn 中继**：2000-2030 / 4000-4030 号段命中 10 路
  （2003/2013/2015/2016/4005/4010/4012/4013/4025/4027），全部 1080p 可解码。
  但产物**已经在用**其中 4012/4013/2013/2015/4005 的现成链路，且 2003/2016/
  4010/4025/4027 无法确认台名（无 vision 配额、SDT 被转写成 `Service01`），
  **不猜名字，故未新增**。
- **`61.221.215.25:8800`** 命中 12 路（1/9/40/41/42/43/45/46/47/48/49/50），
  同样存在台名不可确认的问题，产物已在用 41/47/48，未新增。

## 方法论备注：怎么在不看画面的情况下认台

按可靠性从高到低：

1. **slug 本身即台名**：`rthk31` / `hoy78` / `xingjiaoge-tvbsxw` —— 只在 slug
   语义明确时采信。
2. **语料反查**：`output/all_merged.m3u` 里已有 `URL → 频道名` 映射
   （例：`modn/list/4012` = 民视新闻）。
3. **MPEG-TS 的 SDT**：本批源全部被转写成 `Service01`，**不可用**。
4. **抽帧 + 视觉识别**：最可靠但本轮配额打满（429）。

## 收口时才暴露的真问题：新源被死链压掉

三条源加进 `config/sources.yaml` 后跑全量，产物里 **RTHK 32 仍然是官方死链**
（RTHK 31 也是官方链，但它其实能播——见坑 1）。查下来是两个独立的坑叠在一起：

**坑 1：RTHK 32 的官方链路是「假 200」。**（注意：**RTHK 31 不是**，别混。）
`www.rthk.hk/feeds/dtt/rthktv32_https.m3u8` 自身 200、是合法 m3u；它的子列表
`rthktv32-live.akamaized.net/hls/live/2036819/RTHKTV32/stream4/streamPlaylist.m3u8`
**403**。而 RTHK 31 的同级链路实测完好：分片 `200 video/MP2T` 762KB，
`MEDIA-SEQUENCE` 179335188→179335189 在推进 —— **RTHK 31 用官方源就够了，
不需要替代源**（`rthk31-hidns` 只作冗余）。

旧口径只看 master，于是把 RTHK 32 记为 `True` 写进 `config/stream_health.json`，
它和 `fast.hidns.vip/163189/rthk32` 在合并时打平；平手后按 CDN 优先级
（`rthk.hk` 属 `norm.get_url_priority` 的 `hk_patterns`）选了那条死链。

→ 修法：`Validator._children_reachable()` 对 master 再往下探一跳，子流不可达
就判死。`_first_child_uri()` 摘 `#EXT-X-STREAM-INF` 后第一条非注释行，用
`urljoin` 解析（子列表可能是 root-relative，也可能是 RTHK 这种
`stream4/xxx.m3u8` 相对路径，`base + child` 会拼坏），且**必须 strip 掉 CRLF
的 `\r`**——RTHK 的播放列表就是 CRLF。只探第一个子流。

**更隐蔽的一类（子流层抓不到）**：子列表 200、**分片** 403。geo-block 压在
最底层时，任何只看播放列表的判据都会判活；最终判「真能播」必须落到分片。

**坑 2：合并用的是上一轮的快照。**
`Grouper` 读 `config/stream_health.json`，而这份快照是整轮**跑完才落盘**的。
所以就算本轮验出新结论，合并时用的仍是上一轮 —— 天生慢一拍。

→ 修法：`src/main.py` 用本轮 `valid_channels` **覆盖**快照里的同名 URL 再交给
`Grouper`。

**顺带被证明「本来就是假活」的 4 条**（新口径判死后核过 body）：

| 频道 | 实际 body | 结论 |
|---|---|---|
| 八大戏剧 / 八大第一 / 八大综合 | `haoyunlai.serv00.net/Smartv-1.php?id=…` 返回 384B 的 PHP `Deprecated: strpos()` 报错页 | 从来不是播放列表 |
| 莲花卫视 | `8.138.7.223/tv/lotustv.m3u8` 返回 MP4（`ftypisom` 头） | 后缀骗人，不是 HLS |

**另一族彻底死路：`31.43.191.125:8080/restream`。**
HEAD 恒 200 + `application/octet-stream`，GET 恒 406 + `text/html`，六种请求头
组合（裸 / Chrome UA / +`Accept` / +`Referer` / `HTTP/1.0` / +`Accept-Encoding`）
**全部一样**。不是 UA 拦截、不是缺 Referer，是服务端对这一族路径直接拒 GET。
台视 / 华视 / 民视等 6 条走这条线，不必再投入。HEAD 的 200 是假信号。
