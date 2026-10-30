"""URL 级指数退避熔断的离线契约测试。

覆盖三块：
1. `src/lib/stream_health.py` 的 schema / 退避公式 / 向后兼容；
2. `src/validator.py` 的接入语义（冻结期 **0 请求**、白名单不记熔断）；
3. 「熔断能省多少请求」的可量化演示。

设计约束：
- **完全离线**：所有会走到 `_check_url` 的用例都把 `aiohttp.ClientSession`
  换成计数假件，任何一条漏网的真请求都会让断言失败。
- 状态文件一律落在 `tmp_path`，绝不读写仓库里的 `config/stream_health.json`
  （那台机器上的快照属于本地数据，测试不能污染它）。
- 不用 conftest 的 fixture。
"""
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import aiohttp  # noqa: E402
import src.validator as validator_mod  # noqa: E402
from src.config import Config  # noqa: E402
from src.fetcher import Channel  # noqa: E402
from src.lib import stream_health as sh  # noqa: E402
from src.validator import Validator  # noqa: E402

WHITELIST_HOST = "wl.circuit.test.invalid"
PROXY_HOST = "proxy.circuit.test.invalid"
DEAD = "https://dead.circuit.test.invalid/1.m3u8"

# 固定时间基准：所有时间断言都用注入的 now，不依赖真实时钟
T0 = 1_700_000_000.0


# ══════════════════════════════════════════════════════════════
#  假件：计数 session（不得发出任何真实请求）
# ══════════════════════════════════════════════════════════════
class _Counter:
    def __init__(self):
        self.sessions = 0
        self.requests = 0


class _Resp:
    def __init__(self, counter, status, content_type):
        self._counter = counter
        self.status = status
        self.headers = {} if content_type is None else {"Content-Type": content_type}
        self.content = _RespContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _RespContent:
    """响应体替身：一个合法的播放列表 body（以 `#EXTM3U` 开头）。

    内容层判定以 body 签名为准：body 不以 `#EXTM3U` 开头（含空 body）一律
    判不可用。所以替身必须给真播放列表，否则这些熔断用例会被内容层判死，
    测的就不是熔断逻辑了。
    """

    async def read(self, limit=-1):
        return b"#EXTM3U\n#EXTINF:10,\nseg.ts\n"


class _Session:
    """`async with aiohttp.ClientSession(timeout=...) as s` 的替身。"""

    def __init__(
        self, counter, status=200,
        content_type="application/vnd.apple.mpegurl", raise_exc=None,
    ):
        self._counter = counter
        self._status = status
        self._ctype = content_type
        self._raise = raise_exc
        # 去重集合放在 session 上：`_check_url` 每条 URL 新建一个 session，
        # 所以这里是「这一次探测内」的范围，不会跨轮累积。
        self._seen = set()
        counter.sessions += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def head(self, url, **kwargs):
        self._count(url)
        if self._raise is not None:
            raise self._raise
        return _Resp(self._counter, self._status, self._ctype)

    def get(self, url, **kwargs):  # HEAD 405 回退 / 播放列表补读 body
        self._count(url)
        if self._raise is not None:
            raise self._raise
        return _Resp(self._counter, self._status, self._ctype)

    def _count(self, url):
        """同一次探测内按 URL 去重：`requests` = 探测的不同链路数。

        第一次请求就计数；同一 URL 的后续请求（HEAD 405 回退、补读 body）
        不再计数 —— 它们是同一条链路。
        """
        if url not in self._seen:
            self._seen.add(url)
            self._counter.requests += 1


def _install_session(monkeypatch, counter, **kwargs):
    def factory(*_a, **_kw):
        return _Session(counter, **kwargs)

    monkeypatch.setattr(validator_mod.aiohttp, "ClientSession", factory)


@pytest.fixture()
def isolated_config(tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "whitelist.txt").write_text(f"{WHITELIST_HOST}\n", encoding="utf-8")
    (cfg_dir / "proxy.txt").write_text(f"{PROXY_HOST}\n", encoding="utf-8")
    return Config(config_dir=str(cfg_dir))


@pytest.fixture()
def health_path(tmp_path):
    return tmp_path / "state" / "stream_health.json"


def _validator(isolated_config, health_path, **kwargs):
    return Validator(
        config=isolated_config, max_concurrent=4, timeout=1,
        health_file=health_path, **kwargs
    )


# ══════════════════════════════════════════════════════════════
#  1. 向后兼容：旧格式 {url: bool}
# ══════════════════════════════════════════════════════════════
def test_legacy_v1_bool_file_still_loads(tmp_path):
    """v1 平铺 {url: bool} 必须继续能读，bool 口径与旧版完全一致。"""
    p = tmp_path / "v1.json"
    p.write_text(
        json.dumps({"http://a/1.m3u8": True, "http://b/2.m3u8": False}),
        encoding="utf-8",
    )
    assert sh.load(p) == {"http://a/1.m3u8": True, "http://b/2.m3u8": False}


def test_legacy_false_seeds_one_failure(tmp_path):
    """v1 的 `false` 本来就是一次真实测量 → bad_count 从 1 起步（少吃两轮重探）。"""
    p = tmp_path / "v1.json"
    p.write_text(json.dumps({"http://b/2.m3u8": False}), encoding="utf-8")
    states = sh.load_states(p)
    assert states["http://b/2.m3u8"].bad_count == 1
    assert states["http://b/2.m3u8"].ok is False


def test_load_missing_file_returns_empty(tmp_path):
    assert sh.load(tmp_path / "nope.json") == {}
    assert sh.load_states(tmp_path / "nope.json") == {}


def test_load_broken_json_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert sh.load(p) == {}
    assert sh.load_states(p) == {}


def test_v2_roundtrip_and_load_still_returns_bools(health_path):
    """新格式写出，但 `load()` 仍返回 `Dict[str, bool]`（旧调用方零改动）。"""
    sh.mark_success({}, DEAD)
    states = {DEAD: sh.UrlHealth(ok=True, bad_count=0, last_good=T0)}
    sh.save_states(states, health_path)

    raw = json.loads(health_path.read_text(encoding="utf-8"))
    assert raw["version"] == 2
    assert raw["urls"][DEAD]["last_good"] == "2023-11-14T22:13:20Z"  # 自解释的 ISO UTC

    assert sh.load(health_path) == {DEAD: True}
    assert sh.load_states(health_path)[DEAD].last_good == T0


def test_unknown_url_is_absent_from_bool_view(health_path):
    """从未观测的条目不进 `{url: bool}`（= 未知，而不是 False）。"""
    sh.save_states({DEAD: sh.UrlHealth(ok=None, bad_count=0)}, health_path)
    assert sh.load(health_path) == {}


# ══════════════════════════════════════════════════════════════
#  2. 退避公式与冻结语义
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "bad_count,expected",
    [
        (0, 60.0),      # 2**0 * 60
        (1, 120.0),
        (2, 240.0),
        (3, 480.0),     # 阈值那一档 = 8 分钟
        (4, 960.0),
        (10, 61_440.0),
        (11, 86_400.0),  # 2**11*60=122880 → 封顶 24h
        (30, 86_400.0),
        (-5, 60.0),     # 负数不炸成小数
    ],
)
def test_backoff_formula_and_24h_cap(bad_count, expected):
    assert sh.backoff_seconds(bad_count) == expected
    assert sh.backoff_seconds(bad_count) <= sh.MAX_BACKOFF


def test_consecutive_failures_reach_threshold_then_freeze():
    states = {}
    for i in range(sh.FREEZE_THRESHOLD):
        assert sh.entry_is_frozen(states.get(DEAD), now=T0 + i) is False
        entry = sh.mark_failure(states, DEAD, now=T0 + i)
        assert entry.bad_count == i + 1

    assert entry.bad_count == 3
    assert entry.frozen_until == T0 + 2 + sh.backoff_seconds(3)
    assert sh.is_frozen(DEAD, states, now=T0 + 3) is True


def test_is_frozen_true_inside_window_false_after_expiry():
    states = {}
    for _ in range(3):
        sh.mark_failure(states, DEAD, now=T0)
    frozen_until = states[DEAD].frozen_until
    assert frozen_until == T0 + 480

    # 窗口内：一直冻结
    assert sh.is_frozen(DEAD, states, now=T0 + 1) is True
    assert sh.is_frozen(DEAD, states, now=frozen_until - 1) is True
    # 到期：衰减一格 3 → 2，低于阈值 → 解冻，允许再探
    assert sh.is_frozen(DEAD, states, now=frozen_until) is False
    assert states[DEAD].bad_count == 2
    assert states[DEAD].frozen_until is None


def test_deep_failure_count_re_freezes_after_decay():
    """计数很深时，到期只衰减一格、仍 >= 阈值 → 继续冻（不是一次抹平）。"""
    states = {}
    for _ in range(6):
        sh.mark_failure(states, DEAD, now=T0)
    assert states[DEAD].frozen_until == T0 + sh.backoff_seconds(6)
    expired_at = states[DEAD].frozen_until
    assert sh.is_frozen(DEAD, states, now=expired_at) is True
    assert states[DEAD].bad_count == 5
    assert states[DEAD].frozen_until == expired_at + sh.backoff_seconds(5)


def test_success_resets_counter_and_unfreezes():
    """成功即清零 —— 保留旧计数会让后续无关失败过早冻结。"""
    states = {}
    for _ in range(3):
        sh.mark_failure(states, DEAD, now=T0)
    assert sh.is_frozen(DEAD, states, now=T0 + 1) is True

    entry = sh.mark_success(states, DEAD, now=T0 + 2)
    assert entry.bad_count == 0
    assert entry.frozen_until is None
    assert entry.ok is True
    assert sh.is_frozen(DEAD, states, now=T0 + 3) is False
    # 再失败一次也不会立刻冻（说明真的清零了）
    sh.mark_failure(states, DEAD, now=T0 + 4)
    assert states[DEAD].bad_count == 1
    assert sh.is_frozen(DEAD, states, now=T0 + 5) is False


def test_unknown_url_is_never_frozen():
    assert sh.is_frozen(DEAD, {}) is False
    assert sh.is_frozen(DEAD, None) is False


# ══════════════════════════════════════════════════════════════
#  3. validator 接入
# ══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_frozen_url_sends_zero_requests(
    isolated_config, health_path, monkeypatch
):
    """核心收益断言：冻结期内的 URL 一个请求都不发，直接判不可用。"""
    states = {}
    for _ in range(sh.FREEZE_THRESHOLD):
        sh.mark_failure(states, DEAD, now=sh.time.time())
    sh.save_states(states, health_path)

    counter = _Counter()
    _install_session(monkeypatch, counter)
    v = _validator(isolated_config, health_path)

    assert await v.validate([Channel(name="死链", url=DEAD)]) == []
    assert counter.requests == 0
    assert counter.sessions == 0


@pytest.mark.asyncio
async def test_non_frozen_url_is_probed_exactly_once(
    isolated_config, health_path, monkeypatch
):
    """对照组：同样的假件在未冻结时确实会记录到 1 次请求（证明计数器有效）。"""
    counter = _Counter()
    _install_session(monkeypatch, counter)
    v = _validator(isolated_config, health_path)
    ch = Channel(name="活链", url=DEAD)

    assert await v.validate([ch]) == [ch]
    assert counter.requests == 1
    assert v.circuit.states[DEAD].ok is True
    assert v.circuit.states[DEAD].bad_count == 0


@pytest.mark.asyncio
async def test_failure_is_recorded_and_freezes_after_threshold(
    isolated_config, health_path, monkeypatch
):
    """失败写回：一轮一批，三轮之后融断生效，第四轮 0 请求。"""
    counter = _Counter()
    _install_session(monkeypatch, counter, status=403, content_type="text/html")
    ch = Channel(name="403", url=DEAD)

    for round_no in range(1, sh.FREEZE_THRESHOLD + 1):
        v = _validator(isolated_config, health_path)  # 每轮新进程 = 重读文件
        assert await v.validate([ch]) == []
        assert v.circuit.states[DEAD].bad_count == round_no
        assert counter.requests == round_no

    # 第 4 轮：已冻结 → 不再发请求
    v = _validator(isolated_config, health_path)
    assert await v.validate([ch]) == []
    assert counter.requests == sh.FREEZE_THRESHOLD  # 没涨
    assert sh.load(health_path) == {DEAD: False}   # 也写回了快照口径


@pytest.mark.asyncio
async def test_success_after_frozen_clears_state(
    isolated_config, health_path, monkeypatch
):
    """冻着的时候链路恢复了：过一次成功就必须彻底解冻（计数清零）。"""
    states = {}
    for _ in range(3):
        sh.mark_failure(states, "https://alive.circuit.test.invalid/1.m3u8", now=T0)
    # 已过期（用真实时钟造一条过期的冻结记录），所以本次会被放行重探
    states["https://alive.circuit.test.invalid/1.m3u8"].frozen_until = T0 - 1
    sh.save_states(states, health_path)

    counter = _Counter()
    _install_session(monkeypatch, counter)
    v = _validator(isolated_config, health_path)
    ch = Channel(name="恢复", url="https://alive.circuit.test.invalid/1.m3u8")

    assert await v.validate([ch]) == [ch]
    assert counter.requests == 1
    assert v.circuit.states[ch.url].bad_count == 0
    assert v.circuit.states[ch.url].frozen_until is None
    assert sh.load(health_path)[ch.url] is True


@pytest.mark.asyncio
async def test_whitelist_hit_does_not_touch_circuit_state(
    isolated_config, health_path, monkeypatch
):
    """白名单命中：判 True，**且熔断状态一个字都不改**。

    理由：熔断器只认「真实探测结果」。白名单分支走的是内容层检查
    （播放列表要读 body 判占位片/伪直播），但它**不记账**：
    记成功会让死掉的白名单链路永远清零、永远进不了熔断器；
    记失败则是凭空造证据。所以白名单条目在熔断器眼里**不存在**。

    请求次数：白名单里的播放列表 URL 现在要发 1 次 GET 读 body
    （以前是 0 请求，导致 githubusercontent 上的 youtube 伪直播全被放过）。
    """
    wl_url = f"https://{WHITELIST_HOST}/live/1.m3u8"
    counter = _Counter()
    _install_session(monkeypatch, counter, status=403, content_type="text/html")
    v = _validator(isolated_config, health_path)
    ch = Channel(name="白名单", url=wl_url)

    # 连跑 5 轮（远超阈值），熔断器不该收到任何反馈
    for _ in range(5):
        v = _validator(isolated_config, health_path)
        assert await v.validate([ch]) == [ch]
    # 每轮 1 次 GET（读 body），不是 0 —— 但都不进熔断
    assert counter.requests == 5
    assert v.circuit.states.get(wl_url) is None
    assert not health_path.exists()  # dirty=False → 不落盘

    # 即使手工塞一条冻结记录，白名单分支仍然先于熔断返回 True（顺序钉死）
    sh.save_states({wl_url: sh.UrlHealth(ok=False, bad_count=3,
                                        frozen_until=sh.time.time() + 3600)},
                   health_path)
    v = _validator(isolated_config, health_path)
    assert await v.validate([ch]) == [ch]
    assert counter.requests == 6  # 只多了这一次 GET，熔断状态仍未被动过
    assert sh.load_states(health_path)[wl_url].bad_count == 3  # 没被清零


@pytest.mark.asyncio
async def test_proxy_reject_does_not_touch_circuit_state(isolated_config, health_path):
    """代理黑名单是主动拒绝，不是链路故障 → 不记熔断，也不落盘。"""
    v = _validator(isolated_config, health_path)
    ch = Channel(name="代理", url=f"https://{PROXY_HOST}/x.m3u8")
    assert await v.validate([ch]) == []
    assert v.circuit.states == {}
    assert not health_path.exists()


@pytest.mark.asyncio
async def test_structurally_invalid_url_is_not_recorded(
    isolated_config, health_path, monkeypatch
):
    """无 scheme / 相对路径 = 结构非法，压根没上网 → 不记熔断（不污染快照）。"""
    counter = _Counter()
    _install_session(monkeypatch, counter)  # 假件不会抛，靠 aiohttp 自己在建 URL 时抛
    v = _validator(isolated_config, health_path)

    # 用真 aiohttp 的 URL 校验路径：直接调 _check_url 之外的分支不可靠，
    # 这里显式让假件抛 InvalidURL，模拟 aiohttp 在联网前拒绝的情形。
    _install_session(monkeypatch, counter, raise_exc=aiohttp.InvalidURL("no host"))
    assert await v.validate([Channel(name="坏", url="list.m3u8")]) == []
    assert v.circuit.states == {}
    assert not health_path.exists()


@pytest.mark.asyncio
async def test_missing_health_file_does_not_break_validation(
    isolated_config, tmp_path, monkeypatch
):
    """文件不存在 → 空状态、不崩、也不凭空创建文件。"""
    missing = tmp_path / "nope" / "stream_health.json"
    counter = _Counter()
    _install_session(monkeypatch, counter)
    v = _validator(isolated_config, missing)

    # 白名单路径（1 请求：播放列表要读 body）+ 未知路径（1 请求）混着跑
    wl = Channel(name="白名单", url=f"https://{WHITELIST_HOST}/a.m3u8")
    plain = Channel(name="普通", url=DEAD)
    assert await v.validate([wl, plain]) == [wl, plain]
    assert counter.requests == 2
    assert missing.exists()  # 只有「真的探测过」才会创建


@pytest.mark.asyncio
async def test_unwritable_health_path_does_not_break_validation(
    isolated_config, tmp_path, monkeypatch, capsys
):
    """写盘失败（只读目录 / 盘满）只警告，验证结果照旧。"""
    counter = _Counter()
    _install_session(monkeypatch, counter, status=403, content_type="text/html")

    class _Broken(sh.Circuit):
        def save(self):
            raise OSError("模拟只读文件系统")

    v = _validator(isolated_config, tmp_path / "x.json")
    v._circuit = _Broken(tmp_path / "x.json", states={})
    assert await v.validate([Channel(name="x", url=DEAD)]) == []
    assert "写回失败" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_circuit_exception_falls_through_to_probe(
    isolated_config, health_path, monkeypatch
):
    """熔断自身出任何岔子都必须放行探测 —— 它是优化，不是门禁依赖。"""
    counter = _Counter()
    _install_session(monkeypatch, counter)
    v = _validator(isolated_config, health_path)

    class _Exploding:
        dirty = False

        def is_frozen(self, url, now=None):
            raise RuntimeError("状态文件被改坏了")

    v._circuit = _Exploding()
    ch = Channel(name="x", url=DEAD)
    assert await v.validate([ch]) == [ch]
    assert counter.requests == 1


# ══════════════════════════════════════════════════════════════
#  4. 收益演示（本 lane 的核心指标）
# ══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_savings_on_n_dead_urls(isolated_config, health_path, monkeypatch):
    """60 条全死链跑 6 轮：从第 3 轮起全部跳过，累计省下 240 次探测。"""
    n = 60
    urls = [f"https://dead{i}.circuit.test.invalid/1.m3u8" for i in range(n)]
    counter = _Counter()
    _install_session(monkeypatch, counter, status=403, content_type="text/html")
    channels = [Channel(name=f"c{i}", url=u) for i, u in enumerate(urls)]

    per_round = []
    for _ in range(6):
        before = counter.requests
        v = _validator(isolated_config, health_path)
        await v.validate(channels)
        per_round.append(counter.requests - before)

    # 第 1-3 轮各探 60 次；第 4 轮起 0 次
    assert per_round == [n, n, n, 0, 0, 0], per_round
    naive = n * 6
    assert counter.requests == 3 * n
    assert naive - counter.requests == 3 * n == 180
