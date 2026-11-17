import time

from clippy import finder


def test_sp_param_known_youtube_value():
    # sort by views, uploaded this month, type video, 20+ minutes — the value YouTube itself uses
    assert finder.sp_param("views", "month", "long") == "CAMSBggEEAEYAg=="


def test_sp_param_creative_commons_without_sort():
    # bytes 12 04 | 10 01 (type video) 30 01 (creative commons) → base64 by hand
    assert finder.sp_param("relevance", None, None, cc=True) == "EgQQATAB"


def test_heat_bumps_ignores_intro_and_finds_spike():
    vals = [1.0] * 3 + [0.3] * 50 + [0.9] + [0.3] * 46
    bumps = finder.heat_bumps(vals)
    assert bumps[:4] == [0.0, 0.0, 0.0, 0.0]
    assert bumps[53] == 1.0
    assert max(bumps[4:53]) == 0.0


def test_score_videos_ranks_breakout_first():
    now = time.time()
    base = {"duration": 3600, "like_count": 1000, "comment_count": 100, "license": None}
    vids = [
        {**base, "id": "big", "view_count": 1_000_000, "timestamp": now - 86400, "channel_follower_count": 10_000_000},
        {**base, "id": "breakout", "view_count": 1_000_000, "timestamp": now - 86400, "channel_follower_count": 10_000},
        {**base, "id": "slow", "view_count": 10_000, "timestamp": now - 10 * 86400, "channel_follower_count": 10_000_000},
    ]
    rows = finder.score_videos(vids, now=now)
    assert [r["id"] for r in rows] == ["breakout", "big", "slow"]
    assert any("channel size" in w for w in rows[0]["why"])


def test_fix_subs_looks_up_only_suspicious_channels(monkeypatch):
    asked = []

    def fake_channel_subs(cids):
        asked.append(list(cids))
        return {"UC1": 21_500_000}

    monkeypatch.setattr(finder, "_channel_subs", fake_channel_subs)
    vids = [{"channel_id": "UC1", "view_count": 39_000_000, "channel_follower_count": 215},
            {"channel_id": "UC2", "view_count": 1_000, "channel_follower_count": 50_000}]
    finder._fix_subs(vids)
    assert asked == [["UC1"]]
    assert vids[0]["channel_follower_count"] == 21_500_000
    assert vids[1]["channel_follower_count"] == 50_000
