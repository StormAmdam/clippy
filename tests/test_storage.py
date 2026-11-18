import importlib
import json
import os
import time

import pytest


def write(path, size=None, text=None, age_days=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text)
    else:
        path.write_bytes(b"0" * size)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "out"
    write(r / "A" / "source.mp4", 3000)
    write(r / "A" / "clips" / "01.mp4", 500)
    write(r / "A" / "clips" / "01.jpg", 50)
    write(r / "A" / "transcript.json", 100)
    write(r / "A" / "info.json", text='{"title": "Alpha"}')            # 18 bytes
    write(r / "B" / "clips-abc" / "02.mp4", 700)
    write(r / "B" / "info.json", text='{"title": "Beta"}')             # 17 bytes
    write(r / "_auto" / "review.json", text="[]")                      # internal, never a project
    write(r / "_jobs.json", text="[]")
    return r


def test_usage_sums_sources_and_clips(root):
    from clippy import storage
    u = storage.usage(root)
    assert (u["sources"], u["clips"], u["total"]) == (3000, 1250, 4385)
    assert [p["id"] for p in u["projects"]] == ["A", "B"]
    a = u["projects"][0]
    assert (a["title"], a["has_source"], a["source_bytes"], a["clips_bytes"], a["total"]) == ("Alpha", True, 3000, 550, 3668)


def test_delete_source_keeps_clips_and_transcript(root):
    from clippy import storage
    assert storage.delete_source(root, "A") == 3000
    assert not (root / "A" / "source.mp4").exists()
    assert (root / "A" / "clips" / "01.mp4").exists() and (root / "A" / "transcript.json").exists()


def test_delete_project_removes_folder(root):
    from clippy import storage
    assert storage.delete_project(root, "B") == 717
    assert not (root / "B").exists()


@pytest.mark.parametrize("bad", ["../x", "_auto", "a/b", "", "nope"])
def test_rejects_traversal_and_internal_dirs(root, bad):
    from clippy import storage
    write(root.parent / "x" / "keep.txt", 10)
    with pytest.raises(ValueError):
        storage.delete_project(root, bad)
    with pytest.raises(ValueError):
        storage.delete_source(root, bad)
    assert (root.parent / "x" / "keep.txt").exists() and (root / "_auto" / "review.json").exists()


def test_cleanup_respects_age_and_keep_set(tmp_path):
    from clippy import storage
    r = tmp_path / "out"
    for vid, age in (("old1", 10), ("old2", 10), ("new", 1)):
        write(r / vid / "source.mp4", 1000, age_days=age)
        write(r / vid / "clips" / "01.mp4", 10, age_days=age)
    assert storage.cleanup_sources(r, older_than_days=7, keep={"old2"}) == 1000
    assert not (r / "old1" / "source.mp4").exists()
    assert (r / "old2" / "source.mp4").exists() and (r / "new" / "source.mp4").exists()
    assert (r / "old1" / "clips" / "01.mp4").exists()


def test_storage_endpoints_refuse_project_with_waiting_shorts(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    write(tmp_output / "A" / "source.mp4", 3000)
    write(tmp_output / "A" / "clips-p1" / "01.mp4", 500)
    write(tmp_output / "B" / "clips" / "02.mp4", 700)
    write(tmp_output / "_auto" / "review.json",
          text=json.dumps([{"id": "r1", "file": "A/clips-p1/01.mp4", "status": "pending", "created": 1}]))
    server = importlib.reload(server)
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    assert c.get("/api/storage").json()["total"] == 4200
    assert c.delete("/api/storage/A").status_code == 409
    assert c.post("/api/storage/A/source/delete").json() == {"freed": 3000}
    assert c.delete("/api/storage/B").json() == {"freed": 700}
    assert c.delete("/api/storage/_auto").status_code == 400


def test_youtube_ids_starting_with_underscore_are_projects(tmp_path):
    # real YouTube ids can start with "_" (e.g. _c2e1NcI3Sc); only Clippy's own folders are internal
    from clippy import storage
    r = tmp_path / "out"
    write(r / "_c2e1NcI3Sc" / "source.mp4", 900)
    write(r / "_finder" / "latest.json", text="{}")
    write(r / "_auto" / "review.json", text="[]")
    assert [p["id"] for p in storage.usage(r)["projects"]] == ["_c2e1NcI3Sc"]
    assert storage.delete_source(r, "_c2e1NcI3Sc") == 900
    for internal in ("_auto", "_finder"):
        with pytest.raises(ValueError):
            storage.delete_project(r, internal)


def test_library_lists_underscore_project(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    write(tmp_output / "_c2e1NcI3Sc" / "clips" / "01.mp4", 10)
    write(tmp_output / "_c2e1NcI3Sc" / "result.json", text=json.dumps(
        {"id": "_c2e1NcI3Sc", "title": "Beast", "created": 1, "clips": [{"file": "_c2e1NcI3Sc/clips/01.mp4"}]}))
    server = importlib.reload(server)
    assert [x["id"] for x in TestClient(server.app, base_url="http://127.0.0.1:7860").get("/api/library").json()] == ["_c2e1NcI3Sc"]


def test_download_cannot_be_deleted_while_a_job_runs(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    write(tmp_output / "A" / "source.mp4", 3000)
    server = importlib.reload(server)
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    job = server.STORE.create(url="https://youtu.be/A")
    server.STORE.update(job["id"], state="running")                  # e.g. re-rendering video A from its download
    assert c.post("/api/storage/A/source/delete").status_code == 409
    assert (tmp_output / "A" / "source.mp4").exists()
    server.STORE.update(job["id"], state="done")
    assert c.post("/api/storage/A/source/delete").json() == {"freed": 3000}


def test_missing_tools_hint_matches_the_package_manager(monkeypatch):
    from clippy import download
    have = set()
    monkeypatch.setattr(download.shutil, "which", lambda t: f"/usr/bin/{t}" if t in have else None)
    have.add("apt-get")
    assert download.install_hint(windows=False) == "sudo apt-get install ffmpeg   (yt-dlp: ./setup.sh installs it)"
    have.clear(); have.add("pacman")
    assert download.install_hint(windows=False) == "sudo pacman -S ffmpeg yt-dlp"
    have.clear()
    assert "./setup.sh" in download.install_hint(windows=False)
    assert download.install_hint(windows=True) == "Open Clippy, go to AI & Tools and press Set Up Everything."  # app


def test_a_job_without_video_tools_says_how_to_get_them(monkeypatch, tmp_output):
    from clippy import download, pipeline
    monkeypatch.setattr(download.shutil, "which", lambda t: None)
    with pytest.raises(RuntimeError, match="video tools .*ffmpeg.* aren't set up yet"):
        pipeline.run("https://youtu.be/dQw4w9WgXcQ", {})


def test_yt_dlp_runs_as_a_module_of_clippys_own_python(monkeypatch, tmp_path):
    # pip's yt-dlp.exe remembers the build machine's Python path, so the Windows app can't use it
    from clippy import download
    pyw = tmp_path / "python" / "pythonw.exe"
    pyw.parent.mkdir()
    pyw.write_bytes(b"")
    (tmp_path / "python" / "python.exe").write_bytes(b"")
    monkeypatch.setattr(download.sys, "executable", str(pyw))
    assert download.ytdlp() == [str(tmp_path / "python" / "python.exe"), "-m", "yt_dlp"]   # console: no windows
    monkeypatch.setattr(download.importlib.util, "find_spec", lambda name: None)
    assert download.ytdlp() == ["yt-dlp"]                          # not in Clippy's Python: the one on the PC


def test_a_silent_yt_dlp_failure_still_says_something():
    import subprocess

    from clippy import download
    assert "code 1" in download._why(subprocess.CompletedProcess([], 1, "", ""))
    assert download._why(subprocess.CompletedProcess([], 1, "", "x\nERROR: Video unavailable\n")) == "ERROR: Video unavailable"


def test_the_youtube_downloader_updates_itself_every_few_days(monkeypatch, tmp_path):
    from clippy import components
    stamp = tmp_path / "data" / "yt-dlp-updated.txt"
    monkeypatch.setattr(components, "YTDLP_STAMP", stamp)
    calls = []
    monkeypatch.setattr(components, "_pip", lambda *a: calls.append(a))
    assert components.update_ytdlp(log=lambda m: None)              # never updated: now
    assert calls == [("install", "--upgrade", "--no-warn-script-location", "yt-dlp[default]")] and stamp.exists()
    assert not components.update_ytdlp(log=lambda m: None)          # just did: not again for a few days
    os.utime(stamp, (time.time() - 4 * 86400,) * 2)
    def offline(*a):
        raise RuntimeError("no internet")
    monkeypatch.setattr(components, "_pip", offline)
    said = []
    assert not components.update_ytdlp(log=said.append)             # no internet: tries again next time
    assert "tries again" in said[0]
