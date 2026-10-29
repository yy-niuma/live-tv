"""`src/lib/stream_health.py` 与「合并时优先挑能播链路」的契约。

背景（2026-10-29 实测）：`merge_duplicate_channels()` 只按 CDN 白名单 +
URL 优先级挑主链路，**不知道哪条真的能播**。所以只做同名去重
（`东森新闻` / `东森新闻台`）会让 `hk_merged` 的可播条数从 77 掉到 53
—— 11 个频道组内各有 1 条可播，合并后主 URL 全是死链。

`health` 参数就是为解决这个：**已实测可播 > 未知 > 已实测不可播**。
"""
import json

import pytest
from src.group.normalize import merge_duplicate_channels
from src.lib import stream_health


def _ch(name, url, normalized=None):
    return {"name": name, "url": url, "_normalized_name": normalized or name}


# ---------------------------------------------------------------- load / save


def test_load_missing_file_returns_empty(tmp_path):
    assert stream_health.load(tmp_path / "nope.json") == {}


def test_load_broken_json_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert stream_health.load(p) == {}


def test_load_non_dict_returns_empty(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert stream_health.load(p) == {}


def test_save_then_load_roundtrip(tmp_path):
    out = tmp_path / "health.json"
    stream_health.save(
        [
            {"url": "https://a/1.m3u8", "ok": True},
            {"url": "https://b/2.m3u8", "ok": False},
            {"url": "", "ok": True},            # 空 url 跳过
            {"url": "https://c/3.m3u8"},        # 没有 ok 跳过，不猜
        ],
        out,
    )
    assert stream_health.load(out) == {
        "https://a/1.m3u8": True,
        "https://b/2.m3u8": False,
    }


def test_merge_from_files_later_wins(tmp_path):
    f1, f2 = tmp_path / "1.json", tmp_path / "2.json"
    f1.write_text(
        json.dumps({"results": [{"url": "u1", "ok": False}]}), encoding="utf-8"
    )
    f2.write_text(
        json.dumps({"results": [{"url": "u1", "ok": True}]}), encoding="utf-8"
    )
    out = tmp_path / "h.json"
    stream_health.merge_from_files([f1, f2], out)
    assert stream_health.load(out) == {"u1": True}


# ------------------------------------------------- merge_duplicate_channels


DEAD_WHITELISTED = (
    "https://rthktv31-live.akamaized.net/hls/live/2036818/RTHKTV31/master.m3u8"
)
LIVE_PLAIN = "http://example.com/rthk31.m3u8"


def test_known_good_url_wins_over_whitelisted_dead_url():
    """这正是实测到的回归：白名单里已死链的 URL 会压过实测可播的普通 URL。"""
    chans = [
        _ch("RTHK 31", DEAD_WHITELISTED, "RTHK 31"),
        _ch("RTHK 31", LIVE_PLAIN, "RTHK 31"),
    ]
    health = {DEAD_WHITELISTED: False, LIVE_PLAIN: True}
    merged = merge_duplicate_channels(chans, health=health)
    assert len(merged) == 1
    assert merged[0]["url"] == LIVE_PLAIN, "应挑实测可播的那条"


def test_without_health_old_behaviour_is_unchanged():
    """不传 health 时必须和旧版逐字节一致，否则老用户升级就变行为。"""
    chans = [
        _ch("RTHK 31", DEAD_WHITELISTED, "RTHK 31"),
        _ch("RTHK 31", LIVE_PLAIN, "RTHK 31"),
    ]
    merged = merge_duplicate_channels(chans)
    assert merged[0]["url"] == DEAD_WHITELISTED, "旧行为：CDN 白名单优先"


def test_unknown_url_ranks_between_good_and_bad():
    """未知不能被当成「坏」——否则没跑过 check_streams 的 URL 会被无理由降级。"""
    unknown = "http://unknown.example.com/x.m3u8"
    bad = "http://bad.example.com/y.m3u8"
    good = "http://good.example.com/z.m3u8"
    chans = [
        _ch("X", bad, "X"),
        _ch("X", unknown, "X"),
        _ch("X", good, "X"),
    ]
    health = {bad: False, good: True}
    merged = merge_duplicate_channels(chans, health=health)
    assert merged[0]["url"] == good
    assert merged[0]["_backup_urls"][0] == unknown, "未知应排第二，坏链排最后"


def test_backup_urls_still_capped_at_two():
    urls = [f"http://h{i}.example.com/s.m3u8" for i in range(6)]
    chans = [_ch("Y", u, "Y") for u in urls]
    merged = merge_duplicate_channels(chans, health={u: True for u in urls})
    assert len(merged[0]["_backup_urls"]) == 2


def test_empty_health_behaves_like_none():
    chans = [
        _ch("RTHK 31", DEAD_WHITELISTED, "RTHK 31"),
        _ch("RTHK 31", LIVE_PLAIN, "RTHK 31"),
    ]
    assert (
        merge_duplicate_channels(chans, health={})[0]["url"]
        == merge_duplicate_channels(chans)[0]["url"]
    )


@pytest.mark.parametrize("flag", [True, False])
def test_all_bad_group_still_picks_something(flag):
    """整组都不可播时不能返回空 —— 有备用链路总比没有强。"""
    a, b = "http://bad1.example.com/a.m3u8", "http://bad2.example.com/b.m3u8"
    merged = merge_duplicate_channels([_ch("Z", a, "Z"), _ch("Z", b, "Z")],
                                      health={a: False, b: False})
    assert len(merged) == 1
    assert merged[0]["url"] in {a, b}
