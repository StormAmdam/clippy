import importlib
import subprocess

import pytest

from conftest import make_words


def test_store_roundtrip_marks_running_interrupted(tmp_path):
    from clippy.jobs import JobStore
    s = JobStore(tmp_path / "jobs.json")
    a, b = s.create(url="a"), s.create(url="b")
    s.update(a["id"], state="running")
    s.update(b["id"], state="done")
    s2 = JobStore(tmp_path / "jobs.json")
    assert s2.get(a["id"])["state"] == "interrupted"
    assert s2.get(b["id"])["state"] == "done"


@pytest.mark.parametrize("content", ['{"not": "a list"}', '[{"state": "done"}, "junk", 3]', "{{{"])
def test_damaged_jobs_file_never_stops_clippy_from_starting(tmp_path, content):
    from clippy.jobs import JobStore
    (tmp_path / "jobs.json").write_text(content)
    s = JobStore(tmp_path / "jobs.json")          # must not raise
    assert s.all() == []
    assert s.get(s.create(url="a")["id"])["url"] == "a"


def test_cancel_queued_job_is_immediate(tmp_path):
    from clippy.jobs import JobStore
    s = JobStore(tmp_path / "jobs.json")
    j = s.create(url="a")
    assert s.request_cancel(j["id"]) is True
    assert s.get(j["id"])["state"] == "cancelled"
    assert s.request_cancel(j["id"]) is False      # already finished
    assert s.request_cancel("nope") is False


def test_progress_fn_raises_cancelled_when_requested(tmp_path):
    from clippy.jobs import Cancelled, JobStore
    s = JobStore(tmp_path / "jobs.json")
    j = s.create(url="a")
    s.update(j["id"], state="running")
    prog = s.progress_fn(j["id"])
    prog("render", 0.5, "half")
    assert s.get(j["id"])["pct"] == 0.5
    assert s.request_cancel(j["id"]) is True
    assert s.get(j["id"])["state"] == "running"     # a running job stops at its next progress tick
    with pytest.raises(Cancelled):
        prog("render", 0.6, "more")


def test_history_keeps_newest_60_jobs(tmp_path):
    from clippy.jobs import JobStore
    s = JobStore(tmp_path / "jobs.json")
    ids = []
    for i in range(70):
        j = s.create(url=str(i))
        s.update(j["id"], state="done")
        ids.append(j["id"])
    kept = {j["id"] for j in JobStore(tmp_path / "jobs.json").all()}
    assert len(kept) == 60 and ids[-1] in kept and ids[0] not in kept


def test_cancel_endpoint(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import server
    server = importlib.reload(server)              # picks up the temp output dir
    job = server.STORE.create(url="x")
    client = TestClient(server.app, base_url="http://127.0.0.1:7860")                # no `with` → background workers stay off
    r = client.post(f"/api/jobs/{job['id']}/cancel")
    assert r.status_code == 200 and r.json() == {"ok": True, "state": "cancelled"}
    assert client.post("/api/jobs/nope/cancel").status_code == 404


class Stop(Exception):
    pass


def test_render_stopped_midway_leaves_no_files(tmp_path):
    from clippy.config import Settings
    from clippy.download import video_stream_info
    from clippy.render import render_clip
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=3",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    words = make_words("one two three four five", start=0.2, step=0.5)
    clip = {"start": 0.0, "end": 2.8, "i0": 0, "i1": 5, "title": "Test", "emphasis": [], "emoji": []}
    out_dir = tmp_path / "clips"
    out_dir.mkdir()

    def progress(p, msg):
        if msg == "Rendering…":
            raise Stop()

    with pytest.raises(Stop):
        render_clip(Settings(teaser=False), src, video_stream_info(src), clip, words, None,
                    out_dir / "01-test.mp4", progress=progress, log=lambda m: None)
    assert list(out_dir.iterdir()) == []


def test_full_render_keeps_every_frame_and_audio(tmp_path):
    import json as _json

    from clippy.config import Settings
    from clippy.download import video_stream_info
    from clippy.render import render_clip
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=3",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    words = make_words("one two three four five", start=0.2, step=0.5)
    clip = {"start": 0.0, "end": 2.8, "i0": 0, "i1": 5, "title": "Test", "emphasis": [], "emoji": []}
    out = tmp_path / "clips" / "01-test.mp4"
    out.parent.mkdir()
    stats = render_clip(Settings(teaser=False), src, video_stream_info(src), clip, words, None, out, log=lambda m: None)
    probe = _json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                        "stream=codec_type,nb_read_frames,width,height", "-of", "json", str(out)],
                                       capture_output=True, text=True).stdout)["streams"]
    video = next(s for s in probe if s["codec_type"] == "video")
    assert (video["width"], video["height"], int(video["nb_read_frames"])) == (1080, 1920, 70)   # 2.8 s × 25 fps
    assert any(s["codec_type"] == "audio" for s in probe)
    assert stats["duration"] == 2.8 and out.with_suffix(".jpg").exists()
    assert sorted(p.name for p in out.parent.iterdir()) == ["01-test.jpg", "01-test.mp4"]


def test_job_records_video_title_early_and_finishes(tmp_output, monkeypatch):
    from clippy import pipeline, server
    server = importlib.reload(server)

    def fake_run(url, overrides, on_progress, log, on_info=None):
        on_info({"title": "Steve Jobs at Stanford"})
        assert server.STORE.get(job["id"])["title"] == "Steve Jobs at Stanford"   # visible while it still runs
        return {"title": "Steve Jobs at Stanford", "clips": []}

    monkeypatch.setattr(pipeline, "run", fake_run)
    job = server.STORE.create(url="https://youtu.be/x")
    server._run_job(job["id"])
    assert server.STORE.get(job["id"])["state"] == "done"


def test_job_cancelled_inside_pipeline_is_marked_cancelled(tmp_output, monkeypatch):
    from clippy import pipeline, server
    from clippy.jobs import Cancelled
    server = importlib.reload(server)

    def fake_run(url, overrides, on_progress, log, on_info=None):
        raise Cancelled()

    monkeypatch.setattr(pipeline, "run", fake_run)
    job = server.STORE.create(url="https://youtu.be/x")
    server._run_job(job["id"])
    assert server.STORE.get(job["id"])["state"] == "cancelled"


def test_gpu_encoder_dying_mid_render_falls_back_to_cpu_instead_of_hanging(tmp_path, monkeypatch):
    import threading
    import time

    from clippy import gpu, render
    from clippy.config import Settings
    from clippy.download import video_stream_info
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=3",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    words = make_words("one two three four five", start=0.2, step=0.5)
    clip = {"start": 0.0, "end": 2.8, "i0": 0, "i1": 5, "title": "Test", "emphasis": [], "emoji": []}
    out = tmp_path / "clips" / "01-test.mp4"
    out.parent.mkdir()

    real_args = render._encoder_args
    monkeypatch.setattr(gpu, "has_nvenc", lambda: True)                # try the GPU encoder first…
    monkeypatch.setattr(gpu, "has_cuda_decode", lambda: False)
    monkeypatch.setattr(render, "_encoder_args",                        # …and have it die, like NVENC out of VRAM
                        lambda cfg, nvenc: ["-c:v", "no_such_encoder"] if nvenc else real_args(cfg, False))

    class SlowStart(render.FrameStream):                               # decoding slower than compositing
        def __iter__(self):
            for n, frame in enumerate(super().__iter__()):
                if n < 4:
                    time.sleep(0.4)
                yield frame
    monkeypatch.setattr(render, "FrameStream", SlowStart)

    outcome = {}

    def work():
        try:
            outcome["stats"] = render.render_clip(Settings(teaser=False), src, video_stream_info(src), clip, words,
                                                  None, out, log=lambda m: None)
        except BaseException as e:
            outcome["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(60)
    assert not t.is_alive(), "render hung after the GPU encoder died"
    assert "error" not in outcome, outcome.get("error")
    assert out.exists() and outcome["stats"]["duration"] == 2.8


def test_job_snapshots_do_not_change_while_a_request_reads_them(tmp_path):
    from clippy.jobs import JobStore
    store = JobStore(tmp_path / "jobs.json")
    job = store.create(url="u")
    seen, listed = store.get(job["id"]), store.all()[0]
    store.update(job["id"], title="New title", pct=0.5)               # the worker moves on mid-serialisation
    store.log_fn(job["id"])("downloading")
    assert "title" not in seen and seen["pct"] == 0.0 and seen["log"] == []
    assert "title" not in listed
    assert store.get(job["id"])["title"] == "New title"


def test_job_cancelled_while_waiting_can_never_start(tmp_path):
    from clippy.jobs import JobStore
    store = JobStore(tmp_path / "jobs.json")
    a, b = store.create(url="a"), store.create(url="b")
    store.request_cancel(b["id"])
    assert store.start(a["id"]) is True and store.get(a["id"])["state"] == "running"
    assert store.start(b["id"]) is False and store.get(b["id"])["state"] == "cancelled"
    assert store.start(a["id"]) is False                               # already running
