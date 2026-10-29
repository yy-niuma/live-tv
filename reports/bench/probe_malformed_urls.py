import asyncio, sys
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
from src.config import Config
from src.fetcher import Channel
from src.validator import Validator

cfg = Config("/home/hermes/.hermes/projects/live-tv/config")
urls = [
    ("bad-ipv6-bracket", "http://[::1/list.m3u8"),
    ("bad-port",         "http://example.com:99999/list.m3u8"),
    ("space-in-url",     "http://exa mple.com/a.m3u8"),
    ("no-scheme",        "example.com/a.m3u8"),
    ("ctrl-char",        "http://example.com/a\x00b.m3u8"),
    ("empty-host",       "http:///a.m3u8"),
    ("rtmp-scheme",      "rtmp://example.com/live"),
]
chans = [Channel(name=k, url=u) for k, u in urls]

v = Validator(cfg)
# 走真实入口，同时看 gather 的原始结果类型
async def main():
    v._semaphore = asyncio.Semaphore(v.max_concurrent)
    results = await asyncio.gather(*[v._validate_one(ch) for ch in chans], return_exceptions=True)
    for (k, u), r in zip(urls, results):
        kind = type(r).__name__
        kept = bool(r)                      # ← validate() 里的判据就是这个
        print(f"  {k:18} result={kind:14} kept_by_validate()={kept}  {r if not isinstance(r,bool) else ''}")
    kept = [c.name for c in await v.validate(chans)]
    print("\nvalidate() 实际保留:", kept, f"({len(kept)}/{len(chans)})")
asyncio.run(main())
