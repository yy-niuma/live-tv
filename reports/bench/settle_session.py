import asyncio, sys, time
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
import aiohttp
from src.config import Config
from src.fetcher import Channel
from src.validator import Validator

urls = [l.strip() for l in open("/tmp/livetv_audit_out/all_merged.m3u", encoding="utf-8") if l.startswith("http")][:150]
cfg = Config("/home/hermes/.hermes/projects/live-tv/config")

sessions_created = {"n": 0}
real_session = aiohttp.ClientSession
class CountingSession(real_session):
    def __init__(self, *a, **kw):
        sessions_created["n"] += 1
        super().__init__(*a, **kw)

class SharedValidator(Validator):
    async def validate(self, channels):
        self._sem = asyncio.Semaphore(self.max_concurrent)
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=128)) as s:
            self._session = s
            return await super().validate(channels)
    async def _check_url(self, url):
        async with self._sem:
            try:
                async with self._session.head(url, allow_redirects=True) as resp:
                    return self._is_valid_response(resp)
            except Exception:
                return False

async def bench(label, v, patch):
    aiohttp.ClientSession = patch
    sessions_created["n"] = 0
    chans = [Channel(name=f"c{i}", url=u) for i, u in enumerate(urls)]
    t0 = time.time(); ok = await v.validate(chans); dt = time.time() - t0
    aiohttp.ClientSession = real_session
    print(f"{label:34} {dt:6.1f}s  {len(urls)/dt:5.2f} url/s  valid={len(ok):3d}  sessions_created={sessions_created['n']}")

async def main():
    await bench("per-request session (当前实现)", Validator(cfg), CountingSession)
    await bench("shared session (audit-b 建议)", SharedValidator(cfg), real_session)
asyncio.run(main())
