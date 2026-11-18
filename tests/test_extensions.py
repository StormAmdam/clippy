"""Community extensions: installing, what they add, switching on and off, and code that runs only when trusted."""
import io
import json
import zipfile
from pathlib import Path

import pytest

from clippy import extensions

ROOT = Path(__file__).resolve().parent.parent
COMMUNITY = ROOT / "community"


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    d = tmp_path / "extensions"
    monkeypatch.setattr(extensions, "EXT_DIR", d)
    monkeypatch.setattr(extensions, "STATE_FILE", d / "_state.json")
    extensions.changed()
    yield d
    extensions.changed()


def _no_internet(monkeypatch):
    import httpx

    def refuse(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "get", refuse)
    monkeypatch.setattr(httpx, "stream", refuse)


def test_the_community_list_matches_its_folders():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "community_index.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_pack_switches_on_when_installed_and_adds_its_things(ext_dir):
    from clippy import finder, top
    extensions.install_from_folder(COMMUNITY / "more-countdowns")
    extensions.install_from_folder(COMMUNITY / "extra-caption-styles")
    extensions.install_from_folder(COMMUNITY / "more-topics")
    rows = {r["id"]: r for r in extensions.installed()}
    assert all(r["enabled"] and not r["code"] for r in rows.values())
    assert rows["more-countdowns"]["adds"] == ["4 countdown themes"]
    assert {"funny", "awkward", "comebacks"} <= set(top.themes())               # next to the built-in ones
    assert top.theme("awkward")["title"] == "Top {n} Most Awkward Moments"
    styles = extensions.caption_styles()
    assert set(styles) == {"pop", "subtitle"} and styles["pop"]["words"] == 1
    assert styles["pop"]["preview"] == "/ext/extra-caption-styles/pop.jpg"
    assert "gaming" in finder.all_niches() and "podcasts" in finder.all_niches()
    extensions.set_enabled("more-countdowns", False)                            # off: gone again
    assert "awkward" not in top.themes() and "pop" in extensions.caption_styles()
    extensions.remove("extra-caption-styles")
    assert extensions.caption_styles() == {} and not (ext_dir / "extra-caption-styles").exists()


def test_an_extension_caption_style_draws_captions(ext_dir):
    import numpy as np

    from clippy.config import Settings
    from clippy.overlay import Overlay
    extensions.install_from_folder(COMMUNITY / "extra-caption-styles")
    words = [{"w": "hello", "s": 0.0, "e": 0.5}, {"w": "world", "s": 0.5, "e": 1.0}]
    ov = Overlay(Settings(caption_style="pop"), words, 2.0, "", [], [], lambda t: {"caption_y": 1300, "title_y": 200})
    assert ov.st["words"] == 1
    frame = np.zeros((1920, 1080, 3), np.uint8)
    ov.draw(frame, 0.2)
    assert frame.any()


def test_code_only_runs_once_trusted_and_its_mistakes_never_stop_a_video(ext_dir, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "extension.json").write_text(json.dumps({"id": "marker", "name": "Marker", "code": "main.py"}))
    (src / "main.py").write_text(
        "from pathlib import Path\n"
        "def clip_rendered(path, clip, video, **_):\n"
        "    Path(path).with_suffix('.seen').write_text(clip['title'])\n"
        "def video_done(result, **_):\n"
        "    raise RuntimeError('oops')\n")
    row = extensions.install_from_folder(src)
    assert row["code"] and not row["enabled"]                                   # code: off until trusted
    out = tmp_path / "short.mp4"
    extensions.run_hook("clip_rendered", path=out, clip={"title": "Hi"}, video={})
    assert not out.with_suffix(".seen").exists()
    with pytest.raises(extensions.ExtensionError, match="trust"):
        extensions.set_enabled("marker", True)
    assert extensions.set_enabled("marker", True, trust=True)["enabled"]
    extensions.run_hook("clip_rendered", path=out, clip={"title": "Hi"}, video={})
    assert out.with_suffix(".seen").read_text() == "Hi"
    said = []
    extensions.run_hook("video_done", log=said.append, result={})
    assert "Marker" in said[0] and "oops" in said[0]
    extensions.install_from_folder(src)                                        # an update with new code: ask again
    assert not next(r for r in extensions.installed() if r["id"] == "marker")["enabled"]


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_zips_install_from_a_folder_inside_and_cannot_write_outside(ext_dir, tmp_path):
    data = _zip({"repo-main/README.md": "hi",
                 "repo-main/ext/extension.json": json.dumps({"id": "zipped", "name": "Zipped",
                                                             "finder_topics": {"knitting": ["knitting podcast"]}}),
                 "repo-main/ext/../../escape.txt": "nope", "repo-main/ext/sounds/whoosh1.wav": "RIFF"})
    row = extensions.install_from_zip(data)
    assert row["id"] == "zipped" and row["enabled"]
    assert (ext_dir / "zipped" / "sounds" / "whoosh1.wav").exists()
    assert not (tmp_path / "escape.txt").exists() and not (ext_dir / "escape.txt").exists()
    with pytest.raises(extensions.ExtensionError, match="extension.json"):
        extensions.install_from_zip(_zip({"a/readme.txt": "no manifest"}))
    with pytest.raises(extensions.ExtensionError, match="isn't a zip"):
        extensions.install_from_zip(b"<html>not found</html>")


def test_links_people_paste_become_downloads():
    assert extensions.zip_url("https://github.com/someone/clippy-neon") == \
        ("https://codeload.github.com/someone/clippy-neon/zip/HEAD", "")
    assert extensions.zip_url("https://github.com/someone/pack.git") == ("https://codeload.github.com/someone/pack/zip/HEAD", "")
    assert extensions.zip_url("https://github.com/a/b/tree/main/extensions/neon") == \
        ("https://codeload.github.com/a/b/zip/main", "extensions/neon")
    assert extensions.zip_url("https://example.com/my-ext.zip") == ("https://example.com/my-ext.zip", "")
    with pytest.raises(extensions.ExtensionError):
        extensions.zip_url("file:///etc/passwd")


def test_without_internet_the_community_list_that_came_with_clippy_is_used(ext_dir, monkeypatch):
    _no_internet(monkeypatch)
    cat = extensions.catalog()
    assert cat["source"] == "bundled" and {"more-countdowns", "save-copies"} <= {i["id"] for i in cat["items"]}
    assert next(i for i in cat["items"] if i["id"] == "save-copies")["code"]
    row = extensions.install_from_catalog("more-topics")
    assert row["enabled"]
    assert next(i for i in extensions.catalog()["items"] if i["id"] == "more-topics")["installed"]


def test_extension_sounds_play_unless_you_have_your_own(ext_dir, tmp_path, monkeypatch):
    from clippy import sfx
    src = tmp_path / "pack"
    (src / "s").mkdir(parents=True)
    (src / "s" / "boom.wav").write_bytes(b"RIFF")
    (src / "extension.json").write_text(json.dumps({"id": "booms", "name": "Booms", "sounds": {"impact": ["s/boom.wav"]}}))
    extensions.install_from_folder(src)
    monkeypatch.setattr(sfx, "USER_DIR", tmp_path / "no-own-sounds")
    sfx.forget_user_sounds()
    assert [p.name for p in sfx._user_files("impact")] == ["boom.wav"] and sfx._user_files("pop") == ()
    sfx.forget_user_sounds()


def test_the_app_lists_styles_themes_and_shows_only_extension_pictures(ext_dir, tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    extensions.install_from_folder(COMMUNITY / "extra-caption-styles")
    extensions.install_from_folder(COMMUNITY / "save-copies")
    c = TestClient(server.app, base_url="http://127.0.0.1:7860", client=("127.0.0.1", 50000))
    assert [s["id"] for s in c.get("/api/styles").json()] == ["beast", "hormozi", "box", "clean", "pop", "subtitle"]
    assert "funny" in [t["id"] for t in c.get("/api/top-themes").json()]
    assert c.get("/ext/extra-caption-styles/pop.jpg").status_code == 200
    assert c.get("/ext/save-copies/main.py").status_code == 404                 # pictures only
    r = c.post("/api/extensions/save-copies/enable", json={"on": True})
    assert r.status_code == 400 and "trust" in r.json()["detail"]
    assert c.post("/api/extensions/save-copies/enable", json={"on": True, "trust": True}).json()["enabled"]
    names = [r["id"] for r in c.get("/api/extensions").json()["installed"]]
    assert names == ["extra-caption-styles", "save-copies"]
    assert c.delete("/api/extensions/save-copies").json() == {"ok": True}


def test_another_device_on_the_wifi_cannot_install_or_trust_extensions(ext_dir, tmp_output):
    # with --host 0.0.0.0 a phone can use Clippy; it must not get code onto this PC
    from fastapi.testclient import TestClient

    from clippy import server
    extensions.install_from_folder(COMMUNITY / "save-copies")
    phone = TestClient(server.app, base_url="http://192.168.1.5:7860", client=("192.168.1.20", 50000))
    for r in (phone.post("/api/extensions/install", json={"id": "more-topics"}),
              phone.post("/api/extensions/save-copies/enable", json={"on": True, "trust": True}),
              phone.delete("/api/extensions/save-copies"), phone.post("/api/quit")):
        assert r.status_code == 403 and "computer Clippy runs on" in r.json()["detail"]
    assert not next(r for r in extensions.installed() if r["id"] == "save-copies")["enabled"]
    assert phone.get("/api/extensions").status_code == 200                     # looking is fine
