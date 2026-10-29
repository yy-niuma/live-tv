"""tests/test_validator.py

离线测试 `src.validator.Validator`：
- 白名单 CDN 短路（不联网就能拿到“通过”路径）
- 代理域名 / 空 URL 剔除
- 坏输入不抛未捕获异常
- Content-Type 判定（同步纯逻辑，用假 response）
- 已确认的缺陷：畸形 IPv6 字面量 URL 会“逃过” validate（用 xfail strict 登记）

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

    注意：当前实现把“抛异常”当成“通过”，所以 None 会被保留在结果里（见文件末尾
    test_exception_objects_must_not_count_as_valid 的 xfail 与报告说明）。
    """
    result = await validator.validate([None])
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_non_string_url_does_not_raise(validator):
    """url 是 int 时 urlparse 会抛 AttributeError，但不会逃出 validate()。"""
    result = await validator.validate([_RawUrl(123)])
    assert isinstance(result, list)


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "已复现的缺陷：urlparse('http://[::1/list.m3u8') 抛 ValueError('Invalid IPv6 URL')，"
        "该异常对象在 validate() 的 `if valid` 布尔判断里为真，于是畸形 IPv6 URL 会被当成"
        "“验证通过”保留下来（Channel 正常构造路径下同样如此）。期望：应被剔除。"
    ),
)
@pytest.mark.asyncio
async def test_malformed_ipv6_literal_url_is_rejected(validator, channel_factory):
    ch = channel_factory("http://[::1/list.m3u8")
    assert await validator.validate([ch]) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "同一根因（异常对象 truthy）：urlparse(123) 抛 AttributeError，gather 把异常当 True，"
        "非字符串 url 被当成有效频道保留。期望：应被剔除。"
    ),
)
@pytest.mark.asyncio
async def test_exception_objects_must_not_count_as_valid(validator):
    assert await validator.validate([_RawUrl(123)]) == []


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
    ["text/html; charset=utf-8", "text/plain", "application/json"],
)
def test_valid_response_rejects_non_stream_content_types(validator, content_type):
    assert validator._is_valid_response(_FakeResponse(200, content_type)) is False


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
