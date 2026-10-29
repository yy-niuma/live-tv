"""流可用性提示（stream health hints）。

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

## 怎么用

`scripts/check_streams.py --health-out config/stream_health.json` 把逐条实测
结果落成一个 `{url: bool}` 的映射；`Grouper` 启动时如果看到这个文件就读进来，
合并时按

    已实测可播  >  未知  >  已实测不可播

排序（同一档内仍然优先 CDN 白名单，再按 URL 优先级），从而在保持去重的同时不挑死链。

文件不存在 = 全部未知 = 行为与旧版完全一致（不是必需依赖，也不会凭空判断）。

## 注意

- 这是**快照**，不是承诺。URL 随时会烂，所以它只作为「平手时的裁决依据」，
  不会让一条已知不可播的 URL 永久出局（它仍可能作为备用写入）。
- 文件进 git 还是不进：建议**不进**（机器相关、时效性强）。CI 想用就先跑一遍
  `check_streams.py` 再跑 `src.main`。`config/stream_health.json` 已在 `.gitignore`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "stream_health.json"
)


def load(path: Optional[Path | str] = None) -> Dict[str, bool]:
    """读 `{url: bool}`。文件不存在返回 `{}`（= 全部未知），不抛异常。"""
    p = Path(path) if path else DEFAULT_PATH
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


def save(results: list[dict], path: Optional[Path | str] = None) -> Path:
    """把 `check_streams.py` 的 `results` 落成 `{url: ok}`。

    `results` 里每条至少有 `url` 与 `ok`；缺 `ok` 的条目跳过（不猜）。
    """
    p = Path(path) if path else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    mapping = {
        str(r["url"]): bool(r["ok"])
        for r in results
        if isinstance(r, dict) and r.get("url") and "ok" in r
    }
    p.write_text(
        json.dumps(dict(sorted(mapping.items())), ensure_ascii=False, indent=0) + "\n",
        encoding="utf-8",
    )
    return p


def merge_from_files(paths: list[Path | str], out: Optional[Path | str] = None) -> Path:
    """合并多份 `check_streams --json` 产物到一个 health 文件（后写的覆盖先写的）。"""
    merged: Dict[str, bool] = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for r in data.get("results", []):
            if isinstance(r, dict) and r.get("url") and "ok" in r:
                merged[str(r["url"])] = bool(r["ok"])
    p = Path(out) if out else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(dict(sorted(merged.items())), ensure_ascii=False, indent=0) + "\n",
        encoding="utf-8",
    )
    return p
