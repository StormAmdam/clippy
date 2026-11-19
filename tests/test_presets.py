"""Saved editing styles: one named look for Make Clips, Find a Quote and Autopilot channels."""
import pytest

from clippy import autopilot, config, presets


def test_a_style_saves_the_look_and_fills_in_the_rest_from_settings(tmp_output):
    config.save_ui_settings({"caption_y": 0.5})
    p = presets.save("Podcast", {"caption_style": "clean", "teaser": False, "sfx": "false", "clips": 9, "nope": 1})
    s = p["settings"]
    assert (s["caption_style"], s["teaser"], s["sfx"], s["caption_y"]) == ("clean", False, False, 0.5)
    assert "clips" not in s and "nope" not in s                       # what to pick isn't part of a look
    assert set(s) == set(presets.KEYS)
    assert [x["name"] for x in presets.list_presets()] == ["Podcast"]


def test_the_same_name_updates_that_style_and_a_rename_cant_take_anothers_name(tmp_output):
    a = presets.save("Gaming", {"caption_style": "beast"})
    b = presets.save("gaming", {"highlight_color": "#3DFF7A"})
    assert a["id"] == b["id"] and b["settings"]["caption_style"] == "beast" and len(presets.list_presets()) == 1
    other = presets.save("Podcast", {})
    with pytest.raises(presets.PresetError, match="already"):
        presets.save("Gaming", {}, pid=other["id"])
    presets.delete(a["id"])
    assert [x["name"] for x in presets.list_presets()] == ["Podcast"]


@pytest.mark.parametrize("name,settings,msg", [("", {}, "name"), ("X", {"highlight_color": "yellow"}, "#FFE135"),
                                               ("X", {"caption_scale": "big"}, "valid")])
def test_bad_styles_are_explained(tmp_output, name, settings, msg):
    with pytest.raises(presets.PresetError, match=msg):
        presets.save(name, settings)


def test_a_job_gets_the_style_but_its_own_choices_win(tmp_output):
    p = presets.save("Clean", {"caption_style": "clean", "sfx": False, "caption_y": 0.4})
    cfg = config.load(presets.expand({"preset": p["id"], "caption_style": "box", "clips": 2}))
    assert (cfg.caption_style, cfg.sfx, cfg.caption_y, cfg.clips) == ("box", False, 0.4, 2)
    assert presets.expand({"preset": "gone", "clips": 2}) == {"clips": 2}     # deleted: the job's own settings
    assert presets.expand(None) == {}


def test_an_autopilot_channel_with_a_style_uses_it(tmp_output, monkeypatch):
    p = presets.save("Gaming", {"caption_style": "beast", "highlight_color": "#3DFF7A"})
    prof = autopilot.save_profile({"name": "Games", "preset": p["id"], "caption_style": "clean"})
    seen = []
    n = iter(range(1, 10))                                            # a new video each run (used ones are skipped)
    monkeypatch.setattr(autopilot.finder, "scan", lambda *a, **k: {"videos": [
        {"id": f"vid0000000{next(n)}", "title": "t", "duration": 600, "score": 80, "licence": "creativeCommon",
         "channel": "c"}]})
    monkeypatch.setattr(autopilot, "_eligible", lambda r, p: True)
    monkeypatch.setattr(autopilot, "notify", lambda *a, **k: None, raising=False)

    def run_pipeline(url, overrides, **k):
        seen.append(overrides)
        return {"clips": [], "title": "t"}

    autopilot.run_profile(prof["id"], run_pipeline)
    assert seen[0]["preset"] == p["id"] and "caption_style" not in seen[0]   # the style decides, not the channel
    prof = autopilot.save_profile({**autopilot.get_profile(prof["id"]), "preset": ""})
    autopilot.run_profile(prof["id"], run_pipeline)
    assert seen[1]["caption_style"] == "clean" and "preset" not in seen[1]


def test_styles_through_the_server(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    r = c.post("/api/presets", json={"name": "Podcast", "settings": {"caption_style": "clean"}})
    pid = r.json()["id"]
    assert c.get("/api/presets").json()["presets"][0]["name"] == "Podcast"
    assert c.post("/api/presets", json={"name": " ", "settings": {}}).status_code == 400
    assert c.delete(f"/api/presets/{pid}").json() == {"ok": True} and c.get("/api/presets").json()["presets"] == []
