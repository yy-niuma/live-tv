import asyncio, sys, time
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
import aiohttp
from src.config import Config
from src.fetcher import Channel
from src.validator import Validator

urls = [l.strip() for l in open("/tmp/livetv_audit_out/all_merged.m3u", encoding="utf-8") if l.startswith("http")][:120]
cfg = Config("/home/hermes/.hermes/projects/live-tv/config")

class SharedSessionValidator(Validator):
    async def validate(self, channels):
        self._sem = asyncio.Semaphore(self.max_concurrent)
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=64)) as s:
            self._session = s
            return await super().validate(channels)
    async def _check_url(self, url):
        async with self._sem:
            try:
                async with self._session.head(url, allow_redirects=True) as resp:
                    return self._is_valid_response(resp)
            except Exception:
                return False

async def bench(v):
    chans = [Channel(name=f"c{i}", url=u) for i, u in enumerate(urls)]
    t0 = time.time(); ok = await v.validate(chans); return time.time()-t0, len(ok)

for label, v in (("per-request session (current)", Validator(cfg)),
                 ("shared session (proposed)", SharedSessionValidator(cfg))):
    dt, ok = asyncio.run(bench(v))
    print(f"{label:32} {len(urls)} urls in {dt:6.1f}s -> {len(urls)/dt:5.1f} url/s (valid={ok})")
