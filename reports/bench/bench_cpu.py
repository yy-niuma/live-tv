import asyncio, sys, time
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
from src.config import Config
from src.fetcher import Fetcher
from src.grouper import Grouper
from src.generator import Generator

cfg = Config("/home/hermes/.hermes/projects/live-tv/config")
ch = asyncio.run(Fetcher(cfg).fetch_all())
print("channels:", len(ch))
t = time.time(); grouped = Grouper(cfg).group(ch); g_dt = time.time() - t
print(f"Grouper.group(): {g_dt:.1f}s  -> {len(grouped)} groups, {sum(len(v) for v in grouped.values())} channels")
t = time.time(); res = Generator().generate_hk_and_all(grouped, "/tmp/livetv_audit_out2"); e_dt = time.time() - t
print(f"Generator.generate_hk_and_all(): {e_dt:.1f}s -> {res}")
print(f"CPU total: {g_dt + e_dt:.1f}s")
