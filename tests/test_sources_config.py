"""`config/sources.yaml` 的完整性约束（纯本地，不发网络请求）。

这些断言都来自真实踩过的坑：

- 2026-10-29 发现 `sammy0101` / `xiweiwong` 两个源指向的 GitHub 代理域名
  `raw.gh.registry.cyou` 已死（http=000），让 priority 1/2 的两个香港源静默归零。
- `Harbin-byte-iptv` 与 `free-tv-hk` 内容逐字节相同（md5 一致），是 Free-TV 的旧 fork。
- 8 个 `.md` 源曾被当成 m3u 解析（见 `tests/test_fetcher_parse.py`）。

这里只钉「配置自身是否自洽」；能不能抓到内容靠 `scripts/check_sources.py`
（需要网络，不进 CI）。
"""
from pathlib import Path

import pytest
import yaml

SOURCES_YAML = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"

# 已经确认停服/失效的域名 —— 别再有人加回去
KNOWN_DEAD_HOSTS = {
    # 该 GitHub 代理已死（curl 返回 000，0.001s 秒断）
    "raw.gh.registry.cyou": "改用直连 raw.githubusercontent.com 或 gh-proxy.com",
    "t.freetv.fun": "2026-10-29 实测 20s 超时，源站疑似停服",
    "freetv.fun": "同上",
}


def _load() -> dict:
    with SOURCES_YAML.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def raw_config() -> dict:
    return _load()


@pytest.fixture(scope="module")
def all_sources(raw_config) -> list[dict]:
    return raw_config.get("sources", [])


@pytest.fixture(scope="module")
def enabled_sources(all_sources) -> list[dict]:
    return [s for s in all_sources if s.get("enabled", True)]


def test_sources_yaml_is_parseable_and_non_empty(all_sources):
    assert all_sources, "config/sources.yaml 里没有任何源"
    assert len(all_sources) >= 10, f"源数量掉到 {len(all_sources)} 个，确认是否误删"


def test_enabled_sources_exist(enabled_sources):
    assert len(enabled_sources) >= 8, f"启用的源只剩 {len(enabled_sources)} 个"


def test_source_names_are_unique(all_sources):
    names = [s["name"] for s in all_sources]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"源名重复：{sorted(dupes)}"


def test_source_urls_are_unique_when_enabled(enabled_sources):
    """两个启用的源指向同一 URL 只是浪费请求（合并阶段反正会去重）。"""
    urls = [s["url"] for s in enabled_sources]
    dupes = {u for u in urls if urls.count(u) > 1}
    assert not dupes, f"启用的源里有重复 URL：{sorted(dupes)}"


@pytest.mark.parametrize("field", ["name", "url", "priority"])
def test_required_fields_present(all_sources, field):
    missing = [s.get("name", "<unnamed>") for s in all_sources if field not in s]
    assert not missing, f"这些源缺少 `{field}` 字段：{missing}"


def test_all_urls_are_https(all_sources):
    bad = [s["url"] for s in all_sources if not s["url"].startswith("https://")]
    assert not bad, f"以下源不是 https：{bad}"


def test_priority_within_documented_range(all_sources):
    """配置注释里写的是 1~6。"""
    bad = [
        (s["name"], s["priority"])
        for s in all_sources
        if not 1 <= s["priority"] <= 6
    ]
    assert not bad, f"priority 超出 1~6：{bad}"


def test_no_known_dead_hosts(enabled_sources):
    """**启用的**源不能用已确认失效的域名。

    停用的源允许留着（比如 `freetv-fun` 只是停用、等源站恢复），所以这里只看 enabled。
    """
    offenders = []
    for s in enabled_sources:
        for host, why in KNOWN_DEAD_HOSTS.items():
            if host in s["url"]:
                offenders.append((s["name"], host, why))
    assert not offenders, f"这些启用的源用了已知失效的域名：{offenders}"


def test_headers_block_is_a_flat_mapping(all_sources):
    """`headers:` 会被原样传进 aiohttp，值必须是字符串。"""
    for s in all_sources:
        headers = s.get("headers")
        if not headers:
            continue
        assert isinstance(headers, dict), f"{s['name']}: headers 必须是 dict"
        for k, v in headers.items():
            assert isinstance(v, str), f"{s['name']}: headers[{k!r}] 必须是字符串"


def test_disabled_sources_keep_a_reason_comment(raw_config):
    """停用的源必须在 YAML 里写明原因 —— 否则半年后没人知道为什么关的。

    做法：读源文件原文，检查每个 `enabled: false` 附近 3 行内有没有 `#` 注释。
    """
    text = SOURCES_YAML.read_text(encoding="utf-8")
    lines = text.splitlines()
    problems = []
    for i, line in enumerate(lines):
        if line.strip() == "enabled: false":
            window = lines[max(0, i - 3): i + 1]
            if not any(ln.strip().startswith("#") for ln in window):
                problems.append(f"第 {i + 1} 行的 enabled: false 上方没有说明注释")
    assert not problems, "; ".join(problems)


def test_markdown_sources_are_expected_format(all_sources):
    """`.md` 源走 markdown 表格解析。留一条断言提醒：新增 .md 源要确认它真是
    表格或 m3u 文本，不是纯 HTML 页面（`parse_text()` 会判成 empty 并打 WARNING）。"""
    md = [s["name"] for s in all_sources if s["url"].endswith(".md")]
    assert md, "现在没有 .md 源了？若确实清空了，请同步删掉本用例"
