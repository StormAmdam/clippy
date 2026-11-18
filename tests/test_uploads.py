"""Videos uploaded from the person's own computer become projects like downloaded ones."""
import shutil
import subprocess

import pytest

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture
def client(tmp_output, monkeypatch):
    from fastapi.testclient import TestClient

    from clippy import server
    monkeypatch.setattr(server, "OUT", tmp_output)
    return TestClient(server.app, base_url="http://127.0.0.1:7860")


def _video(path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=1.5",
                    "-f", "lavfi", "-i", "sine=duration=1.5", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return path.read_bytes()


@needs_ffmpeg
def test_an_uploaded_video_becomes_a_project_named_after_the_file(client, tmp_output, tmp_path):
    from clippy import download
    data = _video(tmp_path / "v.mp4")
    r = client.post("/api/upload", params={"name": "Jörg’s café 🎬.mp4"}, content=data)
    assert r.status_code == 200, r.text
    up = r.json()
    assert up["id"].startswith("up-") and up["title"] == "Jörg’s café 🎬" and 1.0 < up["duration"] < 2.5
    src = tmp_output / up["id"] / "source.mp4"
    assert up["path"] == str(src) and src.read_bytes() == data
    info = download.probe(up["path"])                   # what the job sees: the file's name, not "source"
    assert info["id"] == up["id"] and info["title"] == "Jörg’s café 🎬" and info["local_path"]
    again = client.post("/api/upload", params={"name": "copy.mp4"}, content=data).json()
    assert again["id"] == up["id"] and again["title"] == "copy"           # same video: same project, transcript kept
    assert sorted(p.name for p in tmp_output.iterdir()) == ["_uploads", up["id"]]
    assert list((tmp_output / "_uploads").iterdir()) == []                # nothing half-uploaded left


def test_files_that_are_not_videos_are_refused(client, tmp_output):
    r = client.post("/api/upload", params={"name": "notes.txt"}, content=b"hello")
    assert r.status_code == 400 and "isn't a video" in r.json()["detail"]
    r = client.post("/api/upload", params={"name": "empty.mp4"}, content=b"")
    assert r.status_code == 400 and "empty" in r.json()["detail"]


@needs_ffmpeg
def test_a_file_named_like_a_video_without_a_video_inside_is_refused(client, tmp_output):
    r = client.post("/api/upload", params={"name": "fake.mp4"}, content=b"not a video at all" * 100)
    assert r.status_code == 400 and "couldn't find a video" in r.json()["detail"]
    assert not any(p.name.startswith("up-") for p in tmp_output.iterdir())


def test_not_enough_disk_space_is_said_before_uploading(client, tmp_output, monkeypatch):
    from clippy import uploads
    monkeypatch.setattr(uploads.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 10**9))
    r = client.post("/api/upload", params={"name": "big.mp4"}, content=b"x" * 1000,
                    headers={"Content-Length": str(5 * 10**9)})
    assert r.status_code == 400 and "Not enough free disk space" in r.json()["detail"]


def test_a_video_file_that_is_gone_says_so(tmp_output, monkeypatch):
    from clippy import pipeline
    monkeypatch.setattr(pipeline, "have_tools", lambda: [])
    with pytest.raises(RuntimeError, match="can't find the video file"):
        pipeline.run(str(tmp_output / "up-1234567890" / "source.mp4"), {})
