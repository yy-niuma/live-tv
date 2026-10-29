import asyncio, re, sys, time
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
from src.config import Config
from src.fetcher import Channel
from src.validator import Validator

text = open("/tmp/livetv_audit_out/all_merged.m3u", encoding="utf-8").read()
urls = [l.strip() for l in text.splitlines() if l.startswith("http")]
print("urls in local all_merged.m3u:", len(urls))

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
chans = [Channel(name=f"ch{i}", url=u) for i, u in enumerate(urls[:N])]
cfg = Config("/home/hermes/.hermes/projects/live-tv/config")
v = Validator(cfg)
t0 = time.time()
ok = asyncio.run(v.validate(chans))
dt = time.time() - t0
print(f"validated {N} urls in {dt:.1f}s -> {N/dt:.1f} url/s, valid={len(ok)}")
print(f"extrapolated 16859 urls: {16859/(N/dt)/60:.1f} min")
