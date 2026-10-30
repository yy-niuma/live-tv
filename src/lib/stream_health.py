"""流可用性提示（stream health hints）+ URL 级指数退避熔断。

## 为什么需要它

`merge_duplicate_channels()` 合并同名频道时，用「CDN 白名单 + URL 优先级」挑主链路：

```python
def sort_key(c):
    if is_hk_cdn_whitelisted(c["url"]):
        return (0, 0)
    return (get_url_priority(c["url"]), 0)
```

它**不知道哪条 URL 真的能播**。2026-10-29 实测到这个后果：

- `hk_merged.m3u` 167 条里 77 条可播；
- 只是把「东森新闻 / 东森新闻台」这类尾部多个「台」的同名频道
  合并（`config/alias.txt`），条数 167 → 144，可播却 **77 → 53**
  —— 因为**合并后选中的主链路是死链，可播的那条被降级成备用**；
- 11 个频道逐个可查：合并前组内各有 1 条可播，合并后主 URL 全是死链。

也就是说：**去重本身在制造死链**，跟「源不够多」是两件事。

## 怎么用（快照部分）

`scripts/check_streams.py --health-out config/stream_health.json` 把逐条实测
结果落成 `{url: bool}` 的映射；`Grouper` 启动时如果看到这个文件就读进来，
合并时按

    已实测可播  >  未知  >  已实测不可播

排序（同一档内仍然优先 CDN 白名单，再按 URL 优先级），从而在保持去重的同时不挑死链。

文件不存在 = 全部未知 = 行为与旧版完全一致（不是必需依赖，也不会凭空判断）。

## 熔断部分（本模块的第二职责）

一次完整跑批的耗时里，验证阶段占 99%，而 `config/stream_health.json` 里
174 条实测 URL 有 103 条是死链（59.2%）—— 旧版 `validator.py` 每一轮都把
这 103 条重探一遍。所以同一份状态文件现在还要承载「这条 URL 最近连续失败几次、
什么时候可以再试」，让验证阶段能**跳过已知死链**。

借鉴 `Guovin/iptv-api` 的 `utils/frozen.py`：

    FREEZE_THRESHOLD = 3          # 连续失败 3 次才冻结
    BASE_BACKOFF     = 60         # 起始 60 秒
    MAX_BACKOFF      = 24h        # 上限 24 小时
    backoff          = min(MAX_BACKOFF, 2 ** bad_count * BASE_BACKOFF)
    成功即清零（保留旧计数会让后续无关失败过早冻结）
    冻结过期后 bad_count -= 1，减到阈值以下才真正解冻（缓慢衰减，不是一次抹平）

## 文件格式（v2，向后兼容 v1）

v1（旧，只读兼容）：

    {"http://a/1.m3u8": true, "http://b/2.m3u8": false}

v2（现在写出的）：

    {
      "version": 2,
      "generated_at": "2026-10-30T12:00:00Z",
      "urls": {
        "http://a/1.m3u8": {
          "ok": true,
          "bad_count": 0,
          "last_bad": null,
          "last_good": "2026-10-30T12:00:00Z",
          "frozen_until": null
        }
      }
    }

- 时间戳一律 **ISO-8601 UTC 带 `Z`**，人能直接看懂、时区无歧义；进程内用
  epoch 秒（float）运算。
- `load()` **仍然返回 `Dict[str, bool]`**，所有旧调用方（`src/main.py` →
  `Grouper`、`merge_duplicate_channels`）零改动：
  `bad_count == 0 and ok is True` 即 `True`，其余为 `False`，`ok is None` 的条目
  不出现（= 未知）。
- 读的时候逐条判断：值是 `bool` 就是 v1 条目，值是 `dict` 就是 v2 条目，因此
  **同一个文件里可以混着两种**（迁移期不会出现「读一半就瘫」）。
- v1 的 `false` 会被当作「已经观测到 1 次失败」（`bad_count = 1`，`last_bad`
  未知），因为那本来就是一次真实测量；否则旧快照里那 103 条死链还要白探两轮。

## 注意

- 这是**快照 + 退避状态**，不是承诺。URL 随时会烂，所以快照只作为「平手时的裁决依据」，
  不会让一条已知不可播的 URL 永久出局（它仍可能作为备用写入）。
- 文件进 git 还是不进：建议**不进**（机器相关、时效性强）。CI 想用就先跑一遍
  `check_streams.py` 再跑 `src.main`。`config/stream_health.json` 已在 `.gitignore`。
- 熔断状态**只反映真正发出过请求的观测**。命中 CDN 白名单的 URL 一个包都没发，
  所以它既不累加失败也不清零，**永远不会进入熔断器**（详见 `src/validator.py`
  里 `_validate_one` 的顺序说明）。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "stream_health.json"
)

# 熔断参数（与 Guovin/iptv-api utils/frozen.py 对齐）
FREEZE_THRESHOLD = 3
BASE_BACKOFF = 60.0
MAX_BACKOFF = 24 * 3600.0

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


# ------------------------------------------------------------------ 时间戳


def _now(now: Optional[float] = None) -> float:
    return time.time() if now is None else float(now)


def to_iso(ts: Optional[float]) -> Optional[str]:
    """epoch 秒 → `2026-10-30T12:00:00Z`；None 原样返回。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(_ISO_FMT)


def from_iso(value) -> Optional[float]:
    """`2026-10-30T12:00:00Z` → epoch 秒。坏值/None 返回 None（不猜、不抛）。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return datetime.strptime(str(value), _ISO_FMT).replace(
            tzinfo=timezone.utc
        ).timestamp()
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ 单条状态


@dataclass
class UrlHealth:
    """一条 URL 的实测 + 熔断状态。

    `ok` 是最近一次**真实探测**的结论；`None` = 从未观测（未知）。
    `bad_count` 是「连续失败次数」，成功即清零。
    """

    ok: Optional[bool] = None
    bad_count: int = 0
    last_bad: Optional[float] = None
    last_good: Optional[float] = None
    frozen_until: Optional[float] = None

    # -- 序列化 ---------------------------------------------------
    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "bad_count": self.bad_count,
            "last_bad": to_iso(self.last_bad),
            "last_good": to_iso(self.last_good),
            "frozen_until": to_iso(self.frozen_until),
        }

    @classmethod
    def from_value(cls, value) -> "UrlHealth":
        """v1 的 `bool` 和 v2 的 `dict` 都能吃。"""
        if isinstance(value, dict):
            return cls(
                ok=None if value.get("ok") is None else bool(value.get("ok")),
                bad_count=max(0, int(value.get("bad_count") or 0)),
                last_bad=from_iso(value.get("last_bad")),
                last_good=from_iso(value.get("last_good")),
                frozen_until=from_iso(value.get("frozen_until")),
            )
        # v1：{url: bool}，一次真实测量
        if bool(value):
            return cls(ok=True, bad_count=0)
        return cls(ok=False, bad_count=1)

    def as_bool(self) -> Optional[bool]:
        """给旧调用方看的口径：`{url: bool}`。None = 未知（不出现在映射里）。"""
        if self.bad_count > 0 or self.ok is False:
            return False
        if self.ok is True:
            return True
        return None


# ------------------------------------------------------------------ 退避


def backoff_seconds(bad_count: int) -> float:
    """`min(24h, 2 ** bad_count * 60)`。负数按 0 处理，防 `2**-3` 变成分数。"""
    n = max(0, int(bad_count))
    return min(MAX_BACKOFF, float(BASE_BACKOFF) * (2 ** n))


def entry_is_frozen(entry: Optional[UrlHealth], now: Optional[float] = None) -> bool:
    """判断单条状态此刻是否处于冻结期。

    过期时按 Guovin 的做法**衰减一格**：`bad_count -= 1`，
    仍 >= 阈值就再冻一轮（更短的间隔里再试），否则解冻。
    副作用只落在传入的 entry 上（调用方决定是否回写）。
    """
    if entry is None or entry.frozen_until is None:
        return False
    n = _now(now)
    if n < entry.frozen_until:
        return True
    # 过期：逐格衰减，避免「冻够了就一次清零」导致死链立刻被反复重探
    entry.bad_count = max(0, entry.bad_count - 1)
    if entry.bad_count >= FREEZE_THRESHOLD:
        entry.frozen_until = n + backoff_seconds(entry.bad_count)
        return True
    entry.frozen_until = None
    return False


def is_frozen(url: str, states: Optional[Dict[str, UrlHealth]], now=None) -> bool:
    """`url` 此刻是否在冻结期（未知 URL / 空 states 恒 False）。"""
    if not states:
        return False
    return entry_is_frozen(states.get(str(url)), now)


def mark_success(
    states: Dict[str, UrlHealth], url: str, now: Optional[float] = None
) -> UrlHealth:
    """记一次成功：**计数清零**（保留旧计数会让后续无关失败过早冻结）。"""
    key = str(url)
    entry = states.get(key) or UrlHealth()
    entry.ok = True
    entry.bad_count = 0
    entry.last_good = _now(now)
    entry.frozen_until = None
    states[key] = entry
    return entry


def mark_failure(
    states: Dict[str, UrlHealth], url: str, now: Optional[float] = None
) -> UrlHealth:
    """记一次失败：计数 +1，到阈值就冻结 `2 ** n * 60` 秒。"""
    key = str(url)
    n = _now(now)
    entry = states.get(key) or UrlHealth()
    entry.ok = False
    entry.bad_count += 1
    entry.last_bad = n
    if entry.bad_count >= FREEZE_THRESHOLD:
        entry.frozen_until = n + backoff_seconds(entry.bad_count)
    states[key] = entry
    return entry


# ------------------------------------------------------------------ 读写


def _read_raw(path: Optional[Path | str] = None) -> Dict[str, object]:
    p = Path(path) if path else DEFAULT_PATH
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _entries_of(raw: Dict[str, object]) -> Dict[str, object]:
    inner = raw.get("urls")
    if isinstance(inner, dict):
        return inner
    # 没有 version/urls 包装 = v1 平铺格式（或迁移期混合）
    return {k: v for k, v in raw.items() if k not in ("version", "generated_at")}


def load_states(path: Optional[Path | str] = None) -> Dict[str, UrlHealth]:
    """读完整状态（v1/v2 都认）。文件不存在 / 坏 JSON → `{}`，不抛。"""
    out: Dict[str, UrlHealth] = {}
    for url, value in _entries_of(_read_raw(path)).items():
        if not isinstance(url, str) or not url:
            continue
        if not isinstance(value, (bool, dict, int, float)) and value is not None:
            continue
        out[url] = UrlHealth.from_value(value)
    return out


def load(path: Optional[Path | str] = None) -> Dict[str, bool]:
    """读 `{url: bool}`（旧接口，签名与返回值都不变）。

    文件不存在返回 `{}`（= 全部未知），不抛异常。v2 文件也读成 bool。
    """
    out: Dict[str, bool] = {}
    for url, entry in load_states(path).items():
        flag = entry.as_bool()
        if flag is not None:
            out[url] = flag
    return out


def _write_raw(payload: Dict[str, object], p: Path) -> Path:
    """原子写（同目录临时文件 + os.replace），半途失败不会毁掉旧快照。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=0, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".health-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def save_states(
    states: Dict[str, UrlHealth], path: Optional[Path | str] = None
) -> Path:
    """把完整状态落成 v2 文件。"""
    p = Path(path) if path else DEFAULT_PATH
    payload = {
        "version": 2,
        "generated_at": to_iso(time.time()),
        "urls": {str(u): e.to_dict() for u, e in sorted(states.items())},
    }
    return _write_raw(payload, p)


def _apply_results(
    results: list, states: Dict[str, UrlHealth], now: Optional[float]
) -> None:
    """把 `check_streams.py` 的 results 当作「一次真实测量」写进 states。"""
    for r in results:
        if not isinstance(r, dict) or not r.get("url") or "ok" not in r:
            continue  # 缺 ok 的跳过（不猜）
        url = str(r["url"])
        if r["ok"]:
            mark_success(states, url, now)
        else:
            mark_failure(states, url, now)


def save(results: list[dict], path: Optional[Path | str] = None) -> Path:
    """把 `check_streams.py` 的 `results` 落成 health 文件（v2 写出，兼容 v1 读入）。

    `results` 里每条至少有 `url` 与 `ok`；缺 `ok` 的条目跳过（不猜）。
    **读-改-写合并**：文件里已有但本次没测的 URL 原样保留（不丢熔断计数）。
    """
    p = Path(path) if path else DEFAULT_PATH
    states = load_states(p)
    _apply_results(results, states, None)
    return save_states(states, p)


def merge_from_files(paths: list[Path | str], out: Optional[Path | str] = None) -> Path:
    """合并多份 `check_streams --json` 产物到一个 health 文件（后写的覆盖先写的）。"""
    p = Path(out) if out else DEFAULT_PATH
    states = load_states(p)
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        _apply_results(list(data.get("results", [])), states, None)
    return save_states(states, p)


# ------------------------------------------------------------------ 给验证器用的门面


class Circuit:
    """验证器用的状态门面：加载一次、查很多次、最后统一落盘。

    `Circuit(path)` 是**惰性只读**的：文件不存在就是空状态，任何操作都不抛；
    只有显式 `save()` 才写盘（`dirty` 为 False 时不写）。
    """

    def __init__(
        self,
        path: Optional[Path | str] = None,
        states: Optional[Dict[str, UrlHealth]] = None,
    ):
        self.path = Path(path) if path else DEFAULT_PATH
        self.states: Dict[str, UrlHealth] = (
            dict(states) if states is not None else load_states(self.path)
        )
        self.dirty = False
        # 本次跑批被熔断跳过、没发请求的 URL 数（收益指标）
        self.skipped = 0

    # -- 查询 -----------------------------------------------------
    def entry(self, url: str) -> Optional[UrlHealth]:
        return self.states.get(str(url))

    def is_frozen(self, url: str, now: Optional[float] = None) -> bool:
        frozen = is_frozen(url, self.states, now)
        if frozen:
            self.dirty = True  # 过期衰减可能改了计数
        return frozen

    def snapshot(self) -> Dict[str, bool]:
        """`{url: bool}`，喂给 `Grouper` / `merge_duplicate_channels`。"""
        out: Dict[str, bool] = {}
        for url, entry in self.states.items():
            flag = entry.as_bool()
            if flag is not None:
                out[url] = flag
        return out

    # -- 记录 -----------------------------------------------------
    def record_success(self, url: str, now: Optional[float] = None) -> UrlHealth:
        self.dirty = True
        return mark_success(self.states, url, now)

    def record_failure(self, url: str, now: Optional[float] = None) -> UrlHealth:
        self.dirty = True
        return mark_failure(self.states, url, now)

    # -- 落盘 -----------------------------------------------------
    def save(self) -> Path:
        path = save_states(self.states, self.path)
        self.dirty = False
        return path
