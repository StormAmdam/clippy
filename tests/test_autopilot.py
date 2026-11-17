import time

from clippy import autopilot


def test_profile_save_cleans_input(tmp_output):
    p = autopilot.save_profile({"name": "X", "sources": ["@Foo", " ", "https://www.youtube.com/@Bar", "@Foo"],
                                "niches": ["podcasts", "bogus"], "videos_per_run": 0, "clips_per_video": -3})
    assert p["sources"] == ["https://www.youtube.com/@Foo", "https://www.youtube.com/@Bar"]
    assert p["niches"] == ["podcasts"]
    assert p["videos_per_run"] == 1 and p["clips_per_video"] == 1
    assert len(p["id"]) == 8 and autopilot.get_profile(p["id"])["name"] == "X"


def test_eligibility_safe_vs_any():
    safe, anything = {"source_mode": "safe"}, {"source_mode": "any"}
    assert autopilot._eligible({"cc": True}, safe)
    assert autopilot._eligible({"niche": "watchlist"}, safe)
    assert not autopilot._eligible({"cc": False, "niche": "podcasts"}, safe)
    assert autopilot._eligible({"cc": False, "niche": "podcasts"}, anything)


def test_render_description_fills_placeholders():
    profile = {"description_template": "{caption}\n\n{hashtags}\n\n{source_channel} {source_url}",
               "extra_hashtags": "podcast #clips"}
    item = {"caption": "Hi", "hashtags": ["#a"], "source_channel": "Chan", "source_url": "u"}
    assert autopilot.render_description(profile, item) == "Hi\n\n#a #podcast #clips\n\nChan u"


def test_next_publish_slot_spacing(tmp_output):
    p = autopilot.save_profile({"name": "S", "spacing_hours": 4})
    before = time.time()
    first = autopilot.next_publish_slot(autopilot.get_profile(p["id"]))
    second = autopilot.next_publish_slot(autopilot.get_profile(p["id"]))
    assert before + 15 * 60 - 1 <= first <= time.time() + 15 * 60 + 1
    assert second == first + 4 * 3600
    q = autopilot.save_profile({"name": "Now", "spacing_hours": 0})
    assert autopilot.next_publish_slot(autopilot.get_profile(q["id"])) is None


def test_cancelled_or_failed_scheduled_run_waits_for_its_next_slot(tmp_output, monkeypatch):
    import importlib

    from clippy import finder, server
    server = importlib.reload(server)
    p = autopilot.save_profile({"name": "Sched", "niches": ["podcasts"], "auto_every_hours": 6})
    assert server._profile_due(autopilot.get_profile(p["id"]), time.time())          # never ran, so it's due

    def scan_until_user_cancels(*a, progress=lambda f, m: None, **k):
        server.STORE.request_cancel(job["id"])                                       # Cancel pressed mid-scan
        progress(0.5, "Scanning…")
        return {"videos": []}

    monkeypatch.setattr(finder, "scan", scan_until_user_cancels)
    job = server.STORE.create(kind="auto", profile_id=p["id"], url=p["name"])
    server._run_job(job["id"])
    assert server.STORE.get(job["id"])["state"] == "cancelled"
    assert not server._profile_due(autopilot.get_profile(p["id"]), time.time())      # not restarted a minute later

    autopilot._update_profile(p["id"], last_run=0)
    monkeypatch.setattr(finder, "scan", lambda *a, **k: {"videos": []})            # "No new eligible videos found"
    job = server.STORE.create(kind="auto", profile_id=p["id"], url=p["name"])
    server._run_job(job["id"])
    assert server.STORE.get(job["id"])["state"] == "error"
    assert not server._profile_due(autopilot.get_profile(p["id"]), time.time())      # no rescanning every minute
