"""tests/test_validator.py

离线测试 `src.validator.Validator`：
- 白名单 CDN 短路（不联网就能拿到“通过”路径）
- 代理域名 / 空 URL 剔除
- 坏输入不抛未捕获异常
- Content-Type 判定（同步纯逻辑，用假 response）
- 已修复的缺陷回归守卫：探测过程抛异常的频道（畸形 IPv6 字面量 URL、非字符串 url）
  必须被剔除。2026-10-30 修复 `Validator.validate()` 后，这两个用例由 xfail(strict)
  转成普通通过用例。

设计约束：
- 完全离线：所有“通过”用例都走 whitelist 短路；坏输入在发起 socket 之前就失败。
- fixture 全部内联；配置目录直接落在 tmp_path，避免依赖仓库 config/*.txt 的当前内容。
- 不使用 conftest.py / pytest.ini 提供的任何 fixture。
"""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import Config  # noqa: E402
from src.fetcher import Channel  # noqa: E402
from src.validator import Validator  # noqa: E402

WHITELIST_HOST = "cdn.whitelist.test.invalid"
PROXY_HOST = "proxy.blocked.test.invalid"


# ──────────────────────────────────────────────────────────────
#  fixture（内联）
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def isolated_config(tmp_path):
    """只含两条测试规则的配置目录：一条白名单、一条代理黑名单。"""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "whitelist.txt").write_text(f"{WHITELIST_HOST}\n", encoding="utf-8")
    (cfg_dir / "proxy.txt").write_text(f"{PROXY_HOST}\n", encoding="utf-8")
    return Config(config_dir=str(cfg_dir))


@pytest.fixture()
def validator(isolated_config):
    return Validator(config=isolated_config, max_concurrent=4, timeout=1)


@pytest.fixture()
def channel_factory():
    def _make(url, name="测试频道"):
        return Channel(name=name, url=url)

    return _make


class _RawUrl:
    """绕过 Channel 的 .strip()，用来注入非字符串/畸形 url。"""

    def __init__(self, url):
        self.name = "raw"
        self.url = url
        self.logo = ""
        self.group = ""


class _FakeResponse:
    def __init__(self, status=200, content_type=None):
        self.status = status
        self.headers = {} if content_type is None else {"Content-Type": content_type}


# ──────────────────────────────────────────────────────────────
#  正常 http/https 的 .m3u8 / .m3u（经白名单短路，不联网）
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        f"https://{WHITELIST_HOST}/gh/a/list.m3u8",
        f"https://{WHITELIST_HOST}/gh/a/list.m3u",
        f"http://{WHITELIST_HOST}/raw/list.m3u8",
        f"http://{WHITELIST_HOST}/raw/list.m3u",
    ],
)
async def test_whitelisted_http_m3u8_and_m3u_pass(validator, channel_factory, url):
    ch = channel_factory(url)
    assert await validator.validate([ch]) == [ch]


@pytest.mark.asyncio
async def test_proxy_domain_is_rejected(validator, channel_factory):
    ch = channel_factory(f"https://{PROXY_HOST}/x/list.m3u8")
    assert await validator.validate([ch]) == []


# ──────────────────────────────────────────────────────────────
#  空输入 / 空列表 / 非字符串元素：不得抛未捕获异常
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_empty_url_is_rejected_without_network(validator, channel_factory):
    ch = channel_factory("")
    assert await validator.validate([ch]) == []


@pytest.mark.asyncio
async def test_empty_list_returns_empty_list(validator):
    assert await validator.validate([]) == []


@pytest.mark.asyncio
async def test_none_element_does_not_raise(validator):
    """None 元素走 asyncio.gather(return_exceptions=True)，异常不会向外抛。

    修复后（2026-10-30）：`validate()` 用 `valid is True` 严格判定，AttributeError
    这类异常对象不再被当成「通过」，因此 None 会被剔除而不是保留。
    """
    result = await validator.validate([None])
    assert isinstance(result, list)
    assert result == []


@pytest.mark.asyncio
async def test_non_string_url_does_not_raise(validator):
    """url 是 int 时 urlparse 会抛 AttributeError，但不会逃出 validate()。"""
    result = await validator.validate([_RawUrl(123)])
    assert isinstance(result, list)
    assert result == []


# ──────────────────────────────────────────────────────────────
#  明显坏输入
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "example.invalid/list.m3u8",  # 无 scheme
        "list.m3u8",                  # 相对路径
        "ftp://example.invalid/x.m3u8",  # 非 http(s) scheme
    ],
)
async def test_obvious_bad_urls_are_rejected(validator, url):
    """无 scheme / 相对路径 / 非 http(s) 都会被剔除。

    剔除发生在 _check_url：aiohttp 在建立连接前就抛 InvalidURL（ClientError 子类），
    被 `except aiohttp.ClientError` 捕获 → False，因此不需要真实网络。
    """
    result = await validator.validate([_RawUrl(url)])
    assert result == []


@pytest.mark.asyncio
async def test_malformed_ipv6_literal_url_is_rejected(validator, channel_factory):
    """畸形 IPv6 字面量 URL 必须被剔除（原 xfail(strict) 守卫，已于本轮修复）。

    回归登记：urlparse('http://[::1/list.m3u8') 抛 ValueError('Invalid IPv6 URL')，
    该异常逃出 `except (aiohttp.ClientError, asyncio.TimeoutError)` 一路冒到 gather；
    修复前 `if valid` 把它当成真值保留，修复后 `valid is True` 将其剔除。
    """
    ch = channel_factory("http://[::1/list.m3u8")
    assert await validator.validate([ch]) == []


@pytest.mark.asyncio
async def test_exception_objects_must_not_count_as_valid(validator):
    """异常对象一律不算有效（原 xfail(strict) 守卫，已于本轮修复）。

    同一根因：urlparse(123) 抛 AttributeError，gather(return_exceptions=True) 把异常
    对象放进结果列表；修复后判定口径是 `valid is True`，异常不是 True，故被剔除。
    """
    assert await validator.validate([_RawUrl(123)]) == []


@pytest.mark.asyncio
async def test_probe_exception_from_validate_one_is_not_kept(
    validator, channel_factory, monkeypatch
):
    """直接构造「gather 收到异常对象」的路径，不依赖 urlparse 的具体异常类型。"""
    good = channel_factory(f"https://{WHITELIST_HOST}/ok/list.m3u8", name="好")
    boom = channel_factory(f"https://{WHITELIST_HOST}/boom/list.m3u8", name="炸")

    async def fake_validate_one(ch):
        if ch.name == "炸":
            raise RuntimeError("模拟探测时抛异常")
        return True

    monkeypatch.setattr(validator, "_validate_one", fake_validate_one)
    assert await validator.validate([good, boom]) == [good]


@pytest.mark.asyncio
async def test_validate_requires_literal_true_not_merely_truthy(
    validator, channel_factory, monkeypatch
):
    """契约固化：判定用 `is True`，真值但非 True 的返回值也不算有效。"""
    ch = channel_factory(f"https://{WHITELIST_HOST}/x/list.m3u8")

    async def fake_validate_one(_ch):
        return ["非布尔真值"]  # 布尔上下文为真，但不是 True

    monkeypatch.setattr(validator, "_validate_one", fake_validate_one)
    assert await validator.validate([ch]) == []


@pytest.mark.asyncio
async def test_mixed_batch_keeps_only_genuinely_valid_channel(
    validator, channel_factory
):
    """控制器基线场景：正常 / 抛异常 / 代理拒绝 三条混在一起，只应留 1 条。"""
    good = channel_factory(f"https://{WHITELIST_HOST}/a/list.m3u8", name="正常")
    boom = channel_factory("http://[::1/list.m3u8", name="抛异常")
    blocked = channel_factory(f"https://{PROXY_HOST}/b/list.m3u8", name="代理")
    kept = await validator.validate([good, boom, blocked])
    assert [c.name for c in kept] == ["正常"]


# ──────────────────────────────────────────────────────────────
#  Content-Type / 状态码判定（同步纯逻辑，无网络）
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "content_type",
    [
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "video/mp2t",
        "audio/aac",
        "application/octet-stream",
        None,  # 无 Content-Type 头：源码容忍
        "",
    ],
)
def test_valid_response_accepts_stream_content_types(validator, content_type):
    assert validator._is_valid_response(_FakeResponse(200, content_type)) is True


@pytest.mark.parametrize(
    "content_type",
    ["text/html; charset=utf-8", "application/json"],
)
def test_valid_response_rejects_non_stream_content_types(validator, content_type):
    assert validator._is_valid_response(_FakeResponse(200, content_type)) is False


def test_valid_response_accepts_text_plain(validator):
    """`text/plain` 必须在协议层放行。

    实测 `fast.hidns.vip` / `cdn6.cc.cd` 这类聚合源把播放列表标成
    `Content-Type: text/plain`，若在这一层就拒，这批真能播的源会被判死。
    但放行只是「允许去读 body」，是不是播放列表由 `_is_valid_content`
    按 body 是否以 `#EXTM3U` 开头决定 —— 见 test_content_layer_* 用例。
    """
    assert validator._is_valid_response(_FakeResponse(200, "text/plain")) is True


@pytest.mark.parametrize(
    "body,expected",
    [
        # 真播放列表：body 签名说了算，哪怕 Content-Type 是 text/plain
        ("#EXTM3U\n#EXTINF:10,\nseg.ts\n", True),
        # BOM + 前导换行也要认
        ("\ufeff\n#EXTM3U\n#EXTINF:10,\nseg.ts\n", True),
        # 空 body 的「播放列表」不是播放列表
        ("", False),
        ("   \n\t\n", False),
        # 被标成 text/plain 的 HTML 错误页：不能当活源
        ("<!doctype html><html><body>404 Not Found</body></html>", False),
        # 占位片：有码流没节目
        ("#EXTM3U\n#EXTINF:10,\nhttp://x/nosignal_h264/playlist.m3u8\n", False),
        # 伪直播：下一跳是点播平台
        ("#EXTM3U\n#EXTINF:10,\nhttps://www.youtube.com/watch?v=x\n", False),
        # 读不到 body（None）→ 保守放行，不拿「读不到」当「假」
        (None, True),
    ],
)
def test_content_layer_body_signature(validator, body, expected):
    assert validator._is_valid_content(body) is expected


@pytest.mark.parametrize("status", [301, 403, 404, 500])
def test_valid_response_rejects_non_200_status(validator, status):
    resp = _FakeResponse(status, "application/vnd.apple.mpegurl")
    assert validator._is_valid_response(resp) is False


# ──────────────────────────────────────────────────────────────
#  代理/白名单判定（同步纯逻辑）
# ──────────────────────────────────────────────────────────────
def test_proxy_domain_matching_is_substring_and_case_insensitive(validator):
    assert validator._is_proxy_domain(f"https://{PROXY_HOST.upper()}/a.m3u8") is True
    assert validator._is_proxy_domain("https://safe.test.invalid/a.m3u8") is False


def test_whitelist_matching_is_substring(validator):
    assert validator._is_whitelisted_cdn(f"https://{WHITELIST_HOST}/deep/path/list.m3u8") is True
    assert validator._is_whitelisted_cdn("https://safe.test.invalid/list.m3u8") is False


@pytest.mark.asyncio
async def test_proxy_check_wins_over_whitelist(isolated_config):
    """源码顺序：先代理黑名单，再白名单短路。"""
    cfg_dir = isolated_config.config_dir
    (cfg_dir / "whitelist.txt").write_text(f"{PROXY_HOST}\n", encoding="utf-8")
    v = Validator(config=Config(config_dir=str(cfg_dir)), max_concurrent=2, timeout=1)
    assert await v.validate([Channel(name="x", url=f"https://{PROXY_HOST}/a.m3u8")]) == []
