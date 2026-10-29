import re, sys, time, types
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
from src.config import Config
from src.fetcher import Channel
import src.group.categorizer as C
from src.grouper import Grouper

_c = {}
def cached_search(pattern, string, flags=0):
    key = (pattern, flags)
    rx = _c.get(key)
    if rx is None:
        rx = _c[key] = re.compile(pattern, flags)
    return rx.search(string)

# monkeypatch ONLY the reference held by categorizer (source untouched)
C.re = types.SimpleNamespace(search=cached_search, IGNORECASE=re.IGNORECASE, compile=re.compile)

text = open("/tmp/livetv_audit_out/all_merged.m3u", encoding="utf-8").read()
names = re.findall(r'#EXTINF:-1[^,]*,(.+)', text)
chans = [Channel(name=n, url=f"http://x/{i}") for i, n in enumerate(names)]
cfg = Config("/home/hermes/.hermes/projects/live-tv/config")
t = time.time(); Grouper(cfg).group(chans); dt = time.time() - t
print(f"with precompiled patterns: {len(chans)} channels in {dt:.1f}s")
print("distinct (pattern,flags) compiled:", len(_c))
