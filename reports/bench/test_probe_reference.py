# 参考测试实现（未纳入仓库，仅供报告引用）。
# 8/9 条在现状代码上通过；test_strip_noise 断言的是期望行为，当前会失败 = 缺陷 C-P2-7。
# 运行：PYTHONPATH=. pytest reports/bench/test_probe_reference.py -q
import sys, time
sys.path.insert(0, "/home/hermes/.hermes/projects/live-tv")
import pytest
from src.config import Config
from src.fetcher import Channel
from src.generator import build_extinf, is_clean_name, Generator
from src.group.normalize import convert_tc_to_sc, strip_noise, normalize_channel_name, get_url_priority
from src.group.categorizer import categorize, is_hk_region
from src.lib.cache import SimpleCache

def test_strip_noise():
    assert strip_noise("CCTV5 体育 1080P") == "CCTV5 体育"
    assert strip_noise("翡翠台【蓝光1】") == "翡翠台"

def test_tc_to_sc():
    assert convert_tc_to_sc("翡翠台新聞") == "翡翠台新闻"

def test_normalize_keeps_alias():
    assert normalize_channel_name("翡翠台 (1080P)", {}) == "翡翠台"
    assert normalize_channel_name("CCTV-1", {"CCTV-1": "CCTV1"}) == "CCTV1"

def test_categorize_golden():
    assert categorize("CCTV-1 综合", "") == "📺 央视频道"
    assert categorize("CCTV5 体育", "") == "📺 央视频道"
    assert categorize("翡翠台", "") == "📺 TVB"
    assert categorize("HBO", "Movies") == "🎬 电影频道"
    assert categorize("Discovery Channel", "") == "📺 纪录片"
    assert categorize("TVBS新闻", "") == "🇹🇼 台湾"

def test_url_priority():
    assert get_url_priority("http://tvb.com/a.m3u8") == 1
    assert get_url_priority("http://example.com/a.m3u8") == 3

def test_is_clean_name():
    assert is_clean_name("Mozilla/5.0 Chrome/120") is False
    assert is_clean_name("翡翠台") is True
    assert is_clean_name("") is False

def test_build_extinf():
    ch = Channel(name="翡翠台", url="http://x/1.m3u8", logo="http://logo.png")
    line = build_extinf(ch, "📺 TVB")
    assert line.startswith('#EXTINF:-1 tvg-name="翡翠台"')
    assert 'group-title="📺 TVB"' in line
    assert line.endswith(",翡翠台")

def test_generate_cap(tmp_path):
    chans = [Channel(name=f"CH{i}", url=f"http://x/{i}.m3u8") for i in range(150)]
    res = Generator().generate_hk_and_all({"🎬 电影频道": chans}, str(tmp_path))
    out = (tmp_path / "all_merged.m3u").read_text(encoding="utf-8")
    assert res["all"]["channels"] == 150
    assert out.count("#EXTINF") == 100          # 现有截断行为（缺陷，见 P0-1）
    assert "# ... and 50 more" in out

def test_cache_ttl(tmp_path, monkeypatch):
    c = SimpleCache(str(tmp_path), default_ttl=10)
    c.set("k", [1, 2])
    assert c.get("k") == [1, 2]
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 11)
    assert c.get("k") is None
