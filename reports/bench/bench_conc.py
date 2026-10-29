import asyncio, sys, time
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
from src.config import Config
from src.fetcher import Channel
from src.validator import Validator

urls = [l.strip() for l in open("/tmp/livetv_audit_out/all_merged.m3u", encoding="utf-8") if l.startswith("http")][:150]
cfg = Config("/home/hermes/.hermes/projects/live-tv/config")

async def bench(conc, timeout):
    chans = [Channel(name=f"c{i}", url=u) for i, u in enumerate(urls)]
    v = Validator(cfg, max_concurrent=conc, timeout=timeout)
    t0 = time.time(); ok = await v.validate(chans); dt = time.time()-t0
    print(f"concurrency={conc:3d} timeout={timeout:2d}s -> {dt:6.1f}s, {len(urls)/dt:5.1f} url/s, valid={ok}, extrapolated 16859: {16859/(len(urls)/dt)/60:5.1f} min")

for conc, to in ((20, 10), (50, 10), (50, 5)):
    asyncio.run(bench(conc, to))
