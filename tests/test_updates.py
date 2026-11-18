"""New versions: Clippy asks GitHub, says so, and (Windows installer) downloads, checks and runs the update."""
import hashlib
import time

import httpx
import pytest

from clippy import components, updates
from clippy.version import VERSION


@pytest.fixture
def fresh(monkeypatch, tmp_path, tmp_output):
    updates._cache.update(t=0.0, release=None, error="")
    monkeypatch.setattr(components, "DOWNLOADS", tmp_path / "downloads")
    components.TASKS.pop("update", None)
    yield
    updates._cache.update(t=0.0, release=None, error="")
    components.TASKS.pop("update", None)


def release(tag, digest="", name=None):
    name = name or f"Clippy-Setup-{tag.lstrip('v')}-win64.exe"
    return {"tag_name": tag, "html_url": f"https://github.com/StormAmdam/clippy/releases/tag/{tag}",
            "body": "## New\n- **Faster** clips", "published_at": "2026-12-01T10:00:00Z",
            "assets": [{"name": name, "browser_download_url": f"https://example.com/{name}", "digest": digest},
                       {"name": "Clippy-portable-x-win64.zip", "browser_download_url": "https://example.com/z"}]}


def github_answers(monkeypatch, data, calls=None):
    def get(url, **k):
        if calls is not None:
            calls.append(url)
        if isinstance(data, Exception):
            raise data
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))
    monkeypatch.setattr(updates.httpx, "get", get)


def test_versions_compare_like_people_expect():
    assert updates.parse("v0.2.1") > updates.parse("0.2.0") > updates.parse("0.1.9")
    assert updates.parse("0.10.0") > updates.parse("0.9.9")
    assert updates.parse("0.2.1") > updates.parse("0.2.1-dev.5") > updates.parse("0.2.0")
    assert updates.parse("rubbish") == (0, 0, 0, 0)


def test_a_newer_release_is_offered_and_checked_only_every_few_hours(fresh, monkeypatch):
    calls = []
    github_answers(monkeypatch, release("v99.0.0"), calls)
    monkeypatch.setattr(updates, "how", lambda: "installer")
    s = updates.status()
    assert s["newer"] and s["latest"] == "99.0.0" and s["current"] == VERSION and s["can_install"]
    assert "Faster" in s["notes"]
    updates.status()
    assert len(calls) == 1                                  # remembered: GitHub isn't asked on every page
    updates.status(force=True)
    assert len(calls) == 2


def test_the_same_or_an_older_release_is_not_offered(fresh, monkeypatch):
    github_answers(monkeypatch, release("v" + VERSION))
    assert not updates.status()["newer"]
    updates._cache.update(t=0.0, release=None)
    github_answers(monkeypatch, release("v0.0.1"))
    assert not updates.status()["newer"]


def test_offline_or_switched_off_says_nothing_new(fresh, monkeypatch):
    github_answers(monkeypatch, httpx.ConnectError("offline"))
    s = updates.status()
    assert not s["newer"] and "offline" in s["error"]
    from clippy import config
    config.save_ui_settings({"check_updates": False})
    calls = []
    github_answers(monkeypatch, release("v99.0.0"), calls)
    assert not updates.status()["newer"] and calls == []    # off: GitHub isn't asked at all
    assert updates.status(force=True)["newer"]               # but Check Now still checks


def test_only_the_installed_windows_app_updates_itself(fresh, monkeypatch):
    for how in ("portable", "install-line"):
        monkeypatch.setattr(updates, "how", lambda how=how: how)
        with pytest.raises(updates.UpdateError):
            updates.install()


def _wait(task_id="update"):
    for _ in range(100):
        t = components.TASKS[task_id]
        if t.state != "running":
            return t
        time.sleep(0.05)
    raise AssertionError("the update task never finished")


def test_the_update_is_downloaded_checked_and_run(fresh, monkeypatch):
    payload = b"MZ new installer"
    good = "sha256:" + hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(updates, "how", lambda: "installer")
    ran = []
    monkeypatch.setattr(updates, "run_installer", ran.append)

    def fetch(url, dest, task, label):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return dest

    monkeypatch.setattr(components, "fetch", fetch)
    github_answers(monkeypatch, release("v99.0.0", digest="sha256:" + "0" * 64))
    updates.install()
    t = _wait()
    assert t.state == "failed" and "doesn't match" in t.error and ran == []
    assert not list(components.DOWNLOADS.glob("*.exe"))      # a damaged download isn't kept
    github_answers(monkeypatch, release("v99.0.0", digest=good))
    updates._cache.update(t=0.0, release=None)
    updates.install()
    t = _wait()
    assert t.state == "done" and [p.name for p in ran] == ["Clippy-Setup-99.0.0-win64.exe"]


def test_installers_from_earlier_updates_are_tidied_away(fresh, monkeypatch):
    components.DOWNLOADS.mkdir(parents=True)
    old = components.DOWNLOADS / f"Clippy-Setup-{VERSION}-win64.exe"
    newer = components.DOWNLOADS / "Clippy-Setup-99.0.0-win64.exe"
    old.write_bytes(b"x")
    newer.write_bytes(b"x")
    github_answers(monkeypatch, release("v" + VERSION))
    updates.status()
    assert not old.exists() and newer.exists()


def test_only_this_pc_can_start_an_update(fresh, monkeypatch, tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    github_answers(monkeypatch, release("v99.0.0"))
    here = TestClient(server.app, base_url="http://127.0.0.1:7860", client=("127.0.0.1", 50000))
    phone = TestClient(server.app, base_url="http://192.168.1.5:7860", client=("192.168.1.20", 50000))
    assert here.get("/api/update").json()["local"] is True
    assert phone.get("/api/update").json()["local"] is False
    assert phone.post("/api/update/install").status_code == 403
    monkeypatch.setattr(updates, "how", lambda: "portable")
    r = here.post("/api/update/install")
    assert r.status_code == 400 and "download page" in r.json()["detail"]
