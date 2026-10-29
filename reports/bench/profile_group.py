import cProfile, pstats, sys, time, io
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
from src.config import Config
from src.fetcher import Channel
from src.grouper import Grouper

cfg = Config("/home/hermes/.hermes/projects/live-tv/config")
# 用真实频道名（从上次抓取结果里取 stub）
import re
text = open("/tmp/livetv_audit_out/all_merged.m3u", encoding="utf-8").read()
names = re.findall(r'#EXTINF:-1[^,]*,(.+)', text)[:3000]
chans = [Channel(name=n, url=f"http://x/{i}", logo="", group="") for i, n in enumerate(names)]
print("profiling", len(chans), "channels")
pr = cProfile.Profile()
t = time.time(); pr.enable(); Grouper(cfg).group(chans); pr.disable()
print(f"elapsed {time.time()-t:.1f}s")
s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(18)
print("\n".join(s.getvalue().splitlines()[4:28]))
