import asyncio, sys, time
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
from src.config import Config
from src.fetcher import Fetcher

cfg = Config("/home/hermes/.hermes/projects/live-tv/config")
t0 = time.time()
ch = asyncio.run(Fetcher(cfg).fetch_all())
print(f"fetch_all(): {len(ch)} channels in {time.time()-t0:.1f}s")
