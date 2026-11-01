# 实测可播快照（stream_health）

> 本文描述 `src/lib/stream_health.py` 的机制：为什么需要它、怎么用、它的边界。
> 快照文件本身**不入库**（`.gitignore` 已排除）—— 机器相关且时效性强。

## 1. 为什么需要它

`merge_duplicate_channels()` 合并同名频道时只保留 1 主 URL + 2 备用，旧的排序依据是
**CDN 白名单 + URL 优先级** —— 它不知道哪条真的能播。这个缺陷在 2026-10-29 被实测到：

| `hk_merged.m3u` | 条数 | 可播 | 可用率 |
|---|---:|---:|---:|
| 不做同名合并 | 167 | 77 | 46.1% |
| 只做同名合并（旧排序） | 144 | **53** | 36.8% |
| 同名合并 + 实测可播排序 | 143 | **64** | 44.8% |

**只做去重会把可播条数从 77 打到 53** —— 11 个频道组内各有 1 条可播，合并后主 URL 全是死链。
换句话说：合并本身没错，错在「按静态规则挑主 URL」。

## 2. 怎么用

两步。第一步逐条实测，同时落一份健康状态文件：

```console
$ .venv/bin/python scripts/check_streams.py output/hk_merged.m3u \
      --health-out config/stream_health.json
```

第二步，下次生成时自动读取（也可显式 `--health-file` 指定）：

```console
$ python -m src.main
[Health] 载入 174 条实测结果（可播 71 / 不可播 103）
```

排序变成 **已实测可播 > 未知 > 已实测不可播**，同档内仍然优先 CDN 白名单。
快照不存在时行为与旧版完全相同 —— 它**不是必需依赖**。

### 文件格式（注意：不是 `{url: bool}`）

`--help` 和早期文档都说「`{url: bool}` 快照」，**那是 2026-10 升级 v2 之前的旧格式**。
现在落盘的 v2 结构是：

```json
{
  "version": 2,
  "generated_at": "2026-11-01T16:58:12Z",
  "urls": {
    "http://.../playlist.m3u8": {
      "ok": true, "bad_count": 0,
      "frozen_until": null, "last_bad": null,
      "last_good": "2026-11-01T13:24:54Z"
    }
  }
}
```

| 接口 | 返回 |
|---|---|
| `stream_health.load(path)` | `{url: bool}` —— **旧接口，签名与返回值都不变**，v2 文件也读成 bool |
| `stream_health.load_states(path)` | `{url: UrlHealth}` —— 完整状态（`bad_count` / 冻结期） |

`ok` 为 `null`（或条目缺失）= **未知**，不等于不可播。v1（纯 bool）文件仍能读。

当前快照实测（2026-11-01 16:58 UTC，19,320 条）：可播 8,797 / 不可播 10,523（存活 45.5%）。

## 3. 它和 CI 的关系（重要）

**CI 流水线不写、也不读这个快照。** 原因有两条：

1. **熔断冻结期太短**：`min(24h, 60 × 2^bad_count)`（连败 3 次也只冻结 8 分钟），
   远小于 CI 跑批间隔（天级）—— 快照在 CI 场景里几乎不生效。
2. **并发写冲突**：CI 的矩阵分片有 N 个 job 同时跑，让它们抢同一个快照文件
   只会引入竞态。分片模式下每片只交付「本片验证有效的 URL 列表」，
   由合并 job 汇总（见 [`docs/ci.md`](ci.md) §8）。

本快照是**本地/单机使用**的工具：跑一次完整流水线 → 用 `check_streams.py` 实测 →
后续生成时优先挑可播的链路。

## 4. 已知边界

> `_backup_urls` 目前**不会写进 M3U**（历史遗留，见
> [known-issues.md](known-issues.md)），所以主链路死了播放器侧没有 failover。
> 上面的排序只保证「挑的那条尽量能播」，**不解决 failover**。

机制细节（数据结构、冻结期计算、持久化格式）见
[`src/lib/stream_health.py`](../src/lib/stream_health.py) 的模块 docstring。
**注意该 docstring 仍写着旧格式 `{url: bool}`** —— 详见本文 §2「文件格式」。
