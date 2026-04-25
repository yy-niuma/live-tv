"""JSON 文件缓存，支持 TTL"""
import json
import time
from pathlib import Path
from typing import Optional, Any


class SimpleCache:
    """JSON 文件缓存，支持 TTL"""

    def __init__(self, cache_dir: str = None, default_ttl: int = 86400):
        if cache_dir is None:
            cache_dir = Path(__file__).parent.parent / ".cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def get(self, key: str, ttl: int = None) -> Optional[Any]:
        """获取缓存，TTL 秒内有效"""
        if ttl is None:
            ttl = self.default_ttl
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) > ttl:
                return None
            return data.get("value")
        except (json.JSONDecodeError, IOError):
            return None

    def set(self, key: str, value: Any):
        """设置缓存"""
        path = self.cache_dir / f"{key}.json"
        data = {"timestamp": time.time(), "value": value}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear(self, key: str = None):
        """清除缓存"""
        if key:
            path = self.cache_dir / f"{key}.json"
            if path.exists():
                path.unlink()
        else:
            for p in self.cache_dir.glob("*.json"):
                p.unlink()
