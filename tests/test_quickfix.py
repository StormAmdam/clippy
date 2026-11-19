"""Quick Fix: change where a short starts and ends, its caption words or title, and render only that short again."""
import json
import subprocess
import time

import pytest

from clippy import autopilot, pipeline, quickfix
from tests.conftest import make_words

TEXT = ("so welcome back everyone today my guest is Jorg he built a cafe from nothing and it nearly failed "
        "in the first week but then a food critic walked in by mistake and everything changed for him "
        "she ordered the only thing on the menu a cinnamon bun and wrote about it the next morning and by "
        "lunchtime there was a line around the block that never went away again")


def _project(out, vid="abc123", sidecar=True, teaser=None, words=None):
    d = out / vid
    (d / "clips").mkdir(parents=True)
    words = words or make_words(TEXT, start=1.0, step=0.5)
    (d / "transcript.json").write_text(json.dumps({"language": "en", "words": words}))
    (d / "info.json").write_text(json.dumps({"id": vid, "title": "Cafe story", "duration": 40.0,
                                             "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk"}))
    (d / "source.mp4").write_bytes(b"video")
    pick = {"start": 3.88, "end": 12.85, "i0": 6, "i1": 24, "title": "He Built A Cafe", "score": 80}
    if teaser:
        pick["teaser"] = teaser
    picks = [pick, {"start": 20.0, "end": 30.0, "i0": 38, "i1": 58, "title": "Other short"}]
    (d / "picks.json").write_text(json.dumps(picks))
    clips = []
    for n, p in enumerate(picks, 1):
        f = d / "clips" / f"0{n}-short.mp4"
        f.write_bytes(b"old render")
        f.with_suffix(".jpg").write_bytes(b"jpg")
        if sidecar:
            pipeline.sidecar(f).write_text(json.dumps({"pick": p, "overrides": {"caption_style": "box"},
                                                       "visual": False, "countdown": False}))
        clips.append({"title": p["title"], "start": p["start"], "end": p["end"], "duration": 9.0,
                      "file": f"{vid}/clips/0{n}-short.mp4", "thumb": f"{vid}/clips/0{n}-short.jpg"})
    (d / "result.json").write_text(json.dumps({"id": vid, "title": "Cafe story", "clips": clips}))
    return d


@pytest.fixture
def fake_render(monkeypatch):
    """render_clip stand-in: records what it was asked to render and writes the files a render makes."""
    seen = []

    def render(cfg, src, vinfo, clip, words, env, out, progress=None, log=None):
        seen.append({"cfg": cfg, "clip": clip, "words": words, "out": out})
        out.write_bytes(b"new render")
        out.with_suffix(".jpg").write_bytes(b"jpg")
        return {"duration": round(clip["end"] - clip["start"], 2), "cuts": 0}

    monkeypatch.setattr("clippy.render.render_clip", render)
    monkeypatch.setattr("clippy.download.video_stream_info", lambda p: {"width": 1920, "height": 1080, "fps": 25.0})
    return seen


def _gone(path, wait=5.0):
    t = time.time()
    while path.exists() and time.time() - t < wait:
        time.sleep(0.05)
    return not path.exists()


def test_the_editor_gets_where_the_short_sits_and_the_words_around_it(tmp_output):
    _project(tmp_output)
    d = quickfix.info("abc123/clips/01-short.mp4")
    assert (d["start"], d["end"], d["kind"], d["title"]) == (3.88, 12.85, "speech", "He Built A Cafe")
    assert d["source"] == "abc123/source.mp4" and d["duration"] == 40.0
    jorg = next(w for w in d["words"] if w["w"] == "Jorg")
    assert jorg["i"] == 8 and jorg["orig"] == "Jorg"
    assert d["words"][0]["i"] == 0                                   # context before the short too


def test_a_fix_renders_only_that_short_and_keeps_the_rest(tmp_output, fake_render):
    d = _project(tmp_output)
    picks_before = (d / "picks.json").read_text()
    r = quickfix.apply("abc123/clips/01-short.mp4", start=1.0, end=12.85, words={"8": "Jörg"}, title="He Built A Café")
    assert r["file"].replace("\\", "/") == "abc123/clips/01-short-r2.mp4"
    [call] = fake_render
    assert (call["clip"]["start"], call["clip"]["i0"], call["clip"]["i1"]) == (1.0, 0, 24)
    assert call["words"][8]["w"] == "Jörg" and call["words"][8]["s"] == 5.0      # its timing kept
    assert call["clip"]["title"] == "He Built A Café" and call["cfg"].caption_style == "box"   # its own look
    res = json.loads((d / "result.json").read_text())
    assert [c["file"].replace("\\", "/") for c in res["clips"]] == ["abc123/clips/01-short-r2.mp4",
                                                                    "abc123/clips/02-short.mp4"]
    assert res["clips"][0]["start"] == 1.0 and res["clips"][0]["title"] == "He Built A Café"
    assert (d / "picks.json").read_text() == picks_before          # nothing picked again
    assert (d / "clips/02-short.mp4").read_bytes() == b"old render"
    assert _gone(d / "clips/01-short.mp4") and _gone(d / "clips/01-short.jpg")
    side = json.loads(pipeline.sidecar(d / "clips/01-short-r2.mp4").read_text())
    assert side["edits"]["words"] == {"8": "Jörg"} and side["overrides"] == {"caption_style": "box"}
    again = quickfix.info(r["file"])                                 # fixing it again starts from the fixed one
    assert again["fixed"] == {"8": "Jörg"} and next(w for w in again["words"] if w["i"] == 8)["w"] == "Jörg"


def test_a_second_fix_gets_the_next_name_and_can_undo_a_word(tmp_output, fake_render):
    d = _project(tmp_output)
    first = quickfix.apply("abc123/clips/01-short.mp4", words={"8": "Jörg"})
    second = quickfix.apply(first["file"], words={"8": "Jorg"})        # back to what was said
    assert second["file"].endswith("01-short-r3.mp4")
    assert fake_render[-1]["words"][8]["w"] == "Jorg"
    assert json.loads(pipeline.sidecar(d / "clips/01-short-r3.mp4").read_text())["edits"]["words"] == {}


def test_the_review_queue_follows_the_fixed_short(tmp_output, fake_render):
    _project(tmp_output)
    autopilot._add_items([{"id": "r1", "status": "pending", "file": "abc123/clips/01-short.mp4", "created": 1.0,
                           "title": "Mine", "thumb": "abc123/clips/01-short.jpg"}])
    r = quickfix.apply("abc123/clips/01-short.mp4", words={"8": "Jörg"})
    item = autopilot.get_item("r1")
    assert item["file"] == r["file"] and item["thumb"] == r["thumb"] and item["title"] == "Mine"


def test_a_short_being_published_cant_be_changed(tmp_output, fake_render):
    _project(tmp_output)
    autopilot._add_items([{"id": "r1", "status": "uploading", "file": "abc123/clips/01-short.mp4", "created": 1.0}])
    with pytest.raises(quickfix.FixError, match="published"):
        quickfix.apply("abc123/clips/01-short.mp4", words={"8": "Jörg"})
    assert fake_render == []


def test_the_teaser_goes_when_its_moment_is_cut_out(tmp_output, fake_render):
    _project(tmp_output, teaser={"start": 10.0, "end": 12.4, "i0": 18, "i1": 23})
    quickfix.apply("abc123/clips/01-short.mp4", end=9.9)
    assert fake_render[-1]["clip"]["teaser"] is None
    quickfix.apply(quickfix.info("abc123/clips/01-short-r2.mp4")["file"], start=3.0)   # a pick without one: fine
    _project(tmp_output, vid="def456", teaser={"start": 10.0, "end": 12.4, "i0": 18, "i1": 23})
    quickfix.apply("def456/clips/01-short.mp4", start=3.0)
    assert fake_render[-1]["clip"]["teaser"]["start"] == 10.0        # still inside: kept


@pytest.mark.parametrize("start,end,msg", [(5.0, 6.0, "at least"), (0.0, 200.0, "inside"), (-1.0, 8.0, "inside"),
                                           (1.0, 190.0, "inside")])
def test_impossible_start_and_end_are_explained(tmp_output, fake_render, start, end, msg):
    _project(tmp_output)
    with pytest.raises(quickfix.FixError, match=msg):
        quickfix.apply("abc123/clips/01-short.mp4", start=start, end=end)


def test_nothing_changed_and_bad_paths_are_refused(tmp_output, fake_render):
    _project(tmp_output)
    with pytest.raises(quickfix.FixError, match="Nothing changed"):
        quickfix.apply("abc123/clips/01-short.mp4", title="He Built A Cafe")
    for bad in ("../settings.json", "abc123/source.mp4", "abc123/clips/nope.mp4", "_auto/clips/x.mp4"):
        with pytest.raises(quickfix.FixError):
            quickfix.info(bad)


def test_a_deleted_download_is_fetched_again_and_a_deleted_upload_is_explained(tmp_output, fake_render, monkeypatch):
    d = _project(tmp_output)
    (d / "source.mp4").unlink()
    fetched = []

    def download(url, info, workdir, h, progress=None):
        fetched.append(url)
        (workdir / "source.mp4").write_bytes(b"video")
        return workdir / "source.mp4"

    monkeypatch.setattr("clippy.download.download", download)
    assert quickfix.info("abc123/clips/01-short.mp4")["redownload"] is True
    quickfix.apply("abc123/clips/01-short.mp4", words={"8": "Jörg"})
    assert fetched == ["https://www.youtube.com/watch?v=abcdefghijk"]
    up = _project(tmp_output, vid="up-1234567890")
    (up / "source.mp4").unlink()
    (up / "info.json").write_text(json.dumps({"id": "up-1234567890", "title": "x", "duration": 40.0,
                                              "webpage_url": str(up / "source.mp4"), "uploaded": True}))
    with pytest.raises(quickfix.FixError, match="isn't on this PC"):
        quickfix.apply("up-1234567890/clips/01-short.mp4", words={"8": "Jörg"})


def test_shorts_made_before_they_remembered_their_pick(tmp_output, fake_render):
    _project(tmp_output, sidecar=False)
    d = quickfix.info("abc123/clips/02-short.mp4")
    assert (d["start"], d["end"], d["i0"]) == (20.0, 30.0, 38)       # found in picks.json
    quickfix.apply("abc123/clips/02-short.mp4", words={"40": "WOW"})
    assert fake_render[-1]["clip"]["title"] == "Other short" and fake_render[-1]["words"][40]["w"] == "WOW"


def test_countdowns_fix_words_but_keep_their_moments(tmp_output, fake_render):
    d = _project(tmp_output)
    f = d / "clips" / "01-short.mp4"
    segs = [{"rank": 2, "label": "#2", "start": 3.0, "end": 8.0, "i0": 4, "i1": 14},
            {"rank": 1, "label": "#1", "start": 20.0, "end": 26.0, "i0": 38, "i1": 50}]
    pipeline.sidecar(f).write_text(json.dumps({"pick": {"start": 3.0, "end": 26.0, "segments": segs, "title": "Top 2"},
                                               "overrides": {}, "visual": False, "countdown": True}))
    assert quickfix.info("abc123/clips/01-short.mp4")["kind"] == "countdown"
    quickfix.apply("abc123/clips/01-short.mp4", start=1.0, end=30.0, words={"8": "Jörg"})
    clip = fake_render[-1]["clip"]
    assert clip["segments"] == segs and (clip["start"], clip["end"]) == (3.0, 26.0)
    assert fake_render[-1]["cfg"].teaser is False


def test_the_server_queues_a_fix_as_a_job(tmp_output, monkeypatch):
    from fastapi.testclient import TestClient

    from clippy import server
    _project(tmp_output)
    made = []
    monkeypatch.setattr(server, "_new_job", lambda **f: made.append(f) or {"id": "j1"})
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    assert c.get("/api/fix", params={"file": "abc123/clips/01-short.mp4"}).json()["kind"] == "speech"
    assert c.get("/api/fix", params={"file": "../x.mp4"}).status_code == 400
    r = c.post("/api/fix", json={"file": "abc123/clips/01-short.mp4", "start": 2.0, "words": {"8": "Jörg"}})
    assert r.json() == {"id": "j1"} and made[0]["kind"] == "fix" and made[0]["options"]["words"] == {"8": "Jörg"}
    assert c.post("/api/fix", json={"file": "nope/clips/x.mp4"}).status_code == 400


def test_a_real_fix_renders_a_playable_short(tmp_output):
    """Not a stand-in: ffmpeg renders the fixed short, and the new file plays at its new length."""
    d = _project(tmp_output, words=make_words(TEXT, start=0.2, step=0.25, length=0.2))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=12",
                    "-f", "lavfi", "-i", "sine=f=300:d=12", "-shortest", "-pix_fmt", "yuv420p", str(d / "source.mp4")],
                   check=True)
    (d / "info.json").write_text(json.dumps({"id": "abc123", "title": "x", "duration": 12.0}))
    pipeline.sidecar(d / "clips/01-short.mp4").write_text(json.dumps({
        "pick": {"start": 1.0, "end": 6.0, "i0": 4, "i1": 23, "title": "Test"}, "visual": False, "countdown": False,
        "overrides": {"teaser": False, "remove_silences": False}}))
    r = quickfix.apply("abc123/clips/01-short.mp4", start=2.0, end=6.0, words={"8": "Jörg"})
    out = tmp_output / r["file"]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(out)], capture_output=True, text=True).stdout)
    assert abs(dur - 4.0) < 0.2 and out.with_suffix(".jpg").exists()


# ───────────────────────── a clip from the transcript ─────────────────────────

def test_the_transcript_comes_as_sentences_to_search(tmp_output):
    _project(tmp_output)
    d = quickfix.transcript("abc123")
    assert d["source"] == "abc123/source.mp4" and d["title"] == "Cafe story"
    assert all({"n", "s", "e", "i0", "i1", "text"} <= set(line) for line in d["lines"])
    assert d["lines"][0]["i0"] == 0 and d["lines"][-1]["i1"] == len(TEXT.split())
    for bad in ("../x", "_auto", "nope", ""):
        with pytest.raises(quickfix.FixError):
            quickfix.transcript(bad)


def test_a_video_without_talking_has_no_transcript_to_search(tmp_output):
    d = _project(tmp_output)
    (d / "transcript.json").write_text(json.dumps({"words": []}))
    with pytest.raises(quickfix.FixError, match="no transcript"):
        quickfix.transcript("abc123")


def test_a_quote_becomes_a_new_short_beside_the_others(tmp_output, fake_render):
    d = _project(tmp_output)
    picks = (d / "picks.json").read_text()
    r = quickfix.make_clip("abc123", 8, 20, "Jorg's Cafe")
    [call] = fake_render
    assert (call["clip"]["i0"], call["clip"]["i1"], call["clip"]["title"]) == (8, 20, "Jorg's Cafe")
    assert call["clip"]["start"] == pytest.approx(4.92) and call["out"].parent.name == "clips-mine"
    entry = r["clips"][0]
    assert entry["file"].replace("\\", "/") == "abc123/clips-mine/01-jorgs-cafe.mp4" and entry["manual"]
    res = json.loads((d / "result.json").read_text())
    assert [c["file"].replace("\\", "/") for c in res["clips"]][:1] == ["abc123/clips-mine/01-jorgs-cafe.mp4"]
    assert len(res["clips"]) == 3 and (d / "picks.json").read_text() == picks
    again = quickfix.make_clip("abc123", 30, 12)                     # lines picked last-to-first: fine
    assert again["clips"][0]["file"].replace("\\", "/").startswith("abc123/clips-mine/02-")
    assert fake_render[-1]["clip"]["title"] == "cafe from nothing and it nearly"   # its first words
    fixed = quickfix.info(entry["file"])                              # and Quick Fix works on it
    assert fixed["start"] == pytest.approx(4.92)


@pytest.mark.parametrize("i0,i1,msg", [(8, 9, "at least"), (0, 2, "at least"), (-1, 5, "aren't"), (0, 999, "aren't")])
def test_impossible_quotes_are_explained(tmp_output, fake_render, i0, i1, msg):
    _project(tmp_output)
    with pytest.raises(quickfix.FixError, match=msg):
        quickfix.make_clip("abc123", i0, i1)


def test_a_quote_from_a_video_without_shorts_yet(tmp_output, fake_render):
    d = _project(tmp_output)
    (d / "result.json").unlink()
    quickfix.make_clip("abc123", 0, 20)
    res = json.loads((d / "result.json").read_text())
    assert res["title"] == "Cafe story" and len(res["clips"]) == 1


def test_the_server_queues_a_quote_as_a_job(tmp_output, monkeypatch):
    from fastapi.testclient import TestClient

    from clippy import server
    _project(tmp_output)
    made = []
    monkeypatch.setattr(server, "_new_job", lambda **f: made.append(f) or {"id": "j2"})
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    assert len(c.get("/api/transcript/abc123").json()["lines"]) > 1
    assert c.get("/api/transcript/_auto").status_code == 400
    r = c.post("/api/transcript/abc123/clip", json={"i0": 8, "i1": 20, "title": "Mine"})
    assert r.json() == {"id": "j2"} and made[0]["kind"] == "manual" and made[0]["options"]["i1"] == 20
