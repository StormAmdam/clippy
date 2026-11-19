"""Watching a recording folder: finished new recordings become shorts once, with a saved style."""
import json
import os

import pytest

from clippy import config, uploads, watcher


@pytest.fixture
def folder(tmp_output, tmp_path, monkeypatch):
    rec = tmp_path / "recordings"
    rec.mkdir()
    (rec / "old-stream.mp4").write_bytes(b"old" * 100)              # there before: left alone
    config.save_ui_settings({"watch_folder": str(rec), "watch_preset": "p1"})
    monkeypatch.setattr(uploads, "_probe", lambda p: {"video": True, "duration": 30.0})
    monkeypatch.setattr(uploads.shutil, "which", lambda n: "/usr/bin/" + n)
    watcher._pending.clear()
    queued = []
    q = lambda path, title, preset: queued.append((path, title, preset)) or f"job{len(queued)}"
    watcher.scan_once(q, now=0)                                     # first look: notes what's there
    yield rec, queued, q
    watcher._pending.clear()


def _record(rec, name, data, when):
    f = rec / name
    f.write_bytes(data)
    os.utime(f, (when, when))
    return f


def test_a_finished_new_recording_becomes_shorts_once(folder, tmp_output):
    rec, queued, q = folder
    _record(rec, "stream 1.mp4", b"x" * 1000, 1000)
    assert watcher.scan_once(q, now=100) == []                      # just appeared
    assert watcher.scan_once(q, now=130) == []                      # unchanged for 30 s: not yet
    assert watcher.scan_once(q, now=170) == ["stream 1.mp4"]        # unchanged for a minute: finished
    path, title, preset = queued[0]
    assert title == "stream 1" and preset == "p1" and len(queued) == 1
    assert open(path, "rb").read() == b"x" * 1000 and str(tmp_output) in path     # brought in like an upload
    assert (rec / "stream 1.mp4").exists()                          # the original stays where it was
    watcher._pending.clear()                                        # Clippy restarts
    for t in (200, 300, 400):
        watcher.scan_once(q, now=t)
    assert len(queued) == 1                                         # never twice


def test_a_recording_still_being_written_waits(folder):
    rec, queued, q = folder
    f = _record(rec, "live.mkv", b"x" * 10, 1000)
    watcher.scan_once(q, now=100)
    for t, size in ((150, 20), (200, 30)):                         # it keeps growing
        _record(rec, "live.mkv", b"x" * size, 1000 + t)
        assert watcher.scan_once(q, now=t) == []
    assert watcher.scan_once(q, now=270) == ["live.mkv"] and f.exists()


def test_partial_downloads_other_files_and_old_ones_are_skipped(folder):
    rec, queued, q = folder
    for name in ("copying.mp4.part", "notes.txt", ".hidden.mp4", "~lock.mp4", "clip.crdownload"):
        _record(rec, name, b"x" * 100, 1000)
    for t in (100, 200, 300):
        watcher.scan_once(q, now=t)
    assert queued == []


def test_the_same_name_with_new_content_is_a_new_recording(folder):
    rec, queued, q = folder
    _record(rec, "Replay.mp4", b"a" * 500, 1000)
    watcher.scan_once(q, now=100)
    watcher.scan_once(q, now=200)
    _record(rec, "Replay.mp4", b"b" * 800, 5000)                   # OBS saved a new replay under the same name
    watcher.scan_once(q, now=300)
    watcher.scan_once(q, now=400)
    assert len(queued) == 2 and queued[0][0] != queued[1][0]        # their own project each


def test_a_new_folder_leaves_what_is_there_alone(folder, tmp_path):
    rec, queued, q = folder
    other = tmp_path / "other"
    other.mkdir()
    _record(other, "already.mp4", b"z" * 100, 10)
    config.save_ui_settings({"watch_folder": str(other)})
    for t in (100, 200, 300):
        watcher.scan_once(q, now=t)
    assert queued == []
    state = json.loads(watcher._state_file().read_text())
    assert state["folder"] == str(other.resolve())


def test_bad_folders_are_explained_when_saved(tmp_output, tmp_path):
    from fastapi.testclient import TestClient

    from clippy import server
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    r = c.post("/api/settings", json={"watch_folder": str(tmp_path / "nope")})
    assert r.status_code == 400 and "can't find" in r.json()["detail"]
    r = c.post("/api/settings", json={"watch_folder": str(tmp_output)})
    assert r.status_code == 400 and "outside" in r.json()["detail"]
    assert c.post("/api/settings", json={"watch_folder": ""}).status_code == 200
    assert c.get("/api/watch").json()["watching"] is False


def test_status_lists_what_it_made(folder):
    rec, queued, q = folder
    _record(rec, "show.mp4", b"x" * 100, 1000)
    watcher.scan_once(q, now=100)
    watcher.scan_once(q, now=200)
    s = watcher.status()
    assert s["watching"] and [r["file"] for r in s["recent"]] == ["show.mp4"]


def test_a_recording_that_cant_be_brought_in_is_tried_again_then_left(folder, monkeypatch):
    rec, queued, q = folder
    _record(rec, "big.mp4", b"x" * 100, 1000)
    calls = []

    def full(f):
        calls.append(f.name)
        raise uploads.UploadError("Not enough free disk space")
    monkeypatch.setattr(watcher, "_import", full)
    watcher.scan_once(q, now=100)
    watcher.scan_once(q, now=200)                                   # tried: failed
    assert calls == ["big.mp4"] and queued == []
    watcher.scan_once(q, now=300)                                   # waits a few minutes before trying again
    assert calls == ["big.mp4"]
    for t in range(600, 600 + 400 * watcher.TRIES, 400):
        watcher.scan_once(q, now=t)
    assert len(calls) == watcher.TRIES                              # then it gives up, and says why
    assert any(v.get("error") for v in json.loads(watcher._state_file().read_text())["seen"].values())


def test_shorts_interrupted_by_closing_clippy_are_made_again(folder):
    rec, queued, q = folder
    _record(rec, "show.mp4", b"x" * 100, 1000)
    watcher.scan_once(q, now=100)
    watcher.scan_once(q, now=200)
    assert len(queued) == 1
    states = {"job1": "interrupted"}
    watcher.scan_once(q, now=300, job_state=lambda j: states.get(j))
    assert len(queued) == 2 and queued[1][0] == queued[0][0]        # the same recording, queued again
    watcher.scan_once(q, now=400, job_state=lambda j: states.get(j))
    assert len(queued) == 2                                         # once
