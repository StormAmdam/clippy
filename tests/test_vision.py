"""The AI's eyes: framing that keeps the important thing in the picture, and rating how clips look."""
import subprocess

import httpx
import numpy as np
import pytest

from clippy import config, llm, reframe, vision


# ───────────────────────── the AI client ─────────────────────────

def _client(monkeypatch, kind="llama.cpp"):
    c = llm.LLM(config.Settings(llm_url="http://127.0.0.1:8080/v1"))
    c.server = llm.Server("http://127.0.0.1:8080/v1", kind, ["m"])
    c.model = "m"
    return c


def test_images_go_with_the_prompt_to_openai_style_servers(monkeypatch):
    seen = {}

    def post(url, headers=None, json=None, timeout=None):
        seen.update(json)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(llm.httpx, "post", post)
    c = _client(monkeypatch)
    assert c.json("sys", "look", {"type": "object"}, images=[b"\xff\xd8jpeg"]) == {"ok": True}
    parts = seen["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "look"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,/9hqcGVn")


def test_images_go_to_ollama_its_own_way(monkeypatch):
    seen = {}

    def post(url, json=None, timeout=None):
        seen.update(json)
        return httpx.Response(200, json={"message": {"content": '{"ok": 1}'}}, request=httpx.Request("POST", url))
    monkeypatch.setattr(llm.httpx, "post", post)
    c = _client(monkeypatch, "Ollama")
    c.context = 8192
    c.json("sys", "look", {"type": "object"}, images=[b"abc"])
    assert seen["messages"][1]["images"] == ["YWJj"]


@pytest.mark.parametrize("props,expect", [({"modalities": {"vision": True}}, True),
                                          ({"modalities": {"vision": False}}, False), ({}, False)])
def test_llama_cpp_says_whether_it_can_see(monkeypatch, props, expect):
    monkeypatch.setattr(llm.httpx, "get", lambda url, **k: httpx.Response(200, json=props,
                                                                          request=httpx.Request("GET", url)))
    assert _client(monkeypatch).can_see() is expect


def test_other_servers_are_not_assumed_to_see(monkeypatch):
    assert _client(monkeypatch, "LM Studio").can_see() is False


# ───────────────────────── asking about frames ─────────────────────────

class FakeLLM:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def json(self, system, user, schema, max_tokens=0, temperature=0, images=None):
        self.calls.append(len(images or []))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_the_ais_boxes_become_pixels_and_nonsense_is_ignored():
    frames = [np.zeros((288, 512, 3), np.uint8)] * 3
    eyes = vision.Eyes(FakeLLM({"frames": [
        {"n": 1, "kind": "stream", "subject": [100, 400, 600, 1000], "cam": [700, 0, 1000, 330], "wide": False},
        {"n": 2, "kind": "scene", "subject": [5000, 0, 9000, 10], "cam": [], "wide": True},
        {"n": 9, "kind": "scene", "subject": [0, 0, 500, 500], "cam": [], "wide": False}]}), log=lambda m: None)
    v = eyes.shots(frames)
    assert v[0]["kind"] == "stream" and v[0]["subject"] == pytest.approx((51.2, 115.2, 307.2, 288.0))
    assert v[0]["cam"] == pytest.approx((358.4, 0.0, 512.0, 95.04)) and v[0]["scale"] == (512, 288)
    assert v[1]["subject"] is None and v[1]["wide"] is True                 # a box off the scale is dropped
    assert v[2] is None                                                    # frame 9 doesn't exist


def test_a_failing_ai_leaves_the_framing_alone():
    eyes = vision.Eyes(FakeLLM(RuntimeError("timeout")), log=lambda m: None)
    assert eyes.shots([np.zeros((10, 10, 3), np.uint8)] * 2) == [None, None]
    assert eyes.rate([np.zeros((10, 10, 3), np.uint8)]) is None


def test_many_frames_go_in_several_requests():
    fake = FakeLLM({"frames": []})
    vision.Eyes(fake, log=lambda m: None).shots([np.zeros((10, 10, 3), np.uint8)] * (vision.MAX_IMAGES + 3))
    assert fake.calls == [vision.MAX_IMAGES, 3]


def test_vision_off_or_an_ai_that_cant_see_means_no_eyes(monkeypatch):
    assert vision.eyes_for(config.Settings(vision="off")) is None

    class Blind:
        def __init__(self, cfg, log=print):
            self.model = "m"

        def wait_ready(self, timeout=0):
            pass

        def can_see(self):
            return False
    monkeypatch.setattr(llm, "LLM", Blind)
    assert vision.eyes_for(config.Settings(vision="auto")) is None


# ───────────────────────── framing ─────────────────────────

W, H, FPS = 1920, 1080, 25.0


def _crop_shot(cx=960.0, n=50):
    s = reframe.Shot(0, n, layout="crop")
    s.cx, s.cy, s.fw = np.full(n, cx), 400.0, 120.0
    return s


def test_a_stream_puts_the_webcam_on_top_and_the_action_below():
    s = _crop_shot(cx=1650)
    why = reframe.apply_view(s, {"kind": "stream", "subject": (200, 300, 900, 1080), "cam": (1300, 0, 1920, 350),
                                 "wide": False}, W, H, FPS)
    assert s.layout == "split" and "webcam" in why
    top, bottom = s.panels
    assert top[0] >= 1300 and top[1] >= 0 and top[0] + top[2] <= 1920.5          # inside the webcam
    assert abs(top[2] / top[3] - reframe.PANEL_ASPECT) < 0.01
    assert bottom[0] <= 200 and bottom[0] + bottom[2] >= 900                     # the whole action
    assert bottom[0] + bottom[2] <= 1300 + 1                                     # not the webcam again


def test_a_talking_shot_keeps_its_face_crop():
    s = _crop_shot(cx=960)
    reframe.apply_view(s, {"kind": "talking", "subject": (700, 150, 1250, 1080), "cam": None, "wide": False}, W, H, FPS)
    assert s.layout == "crop" and abs(float(s.cx[0]) - 960) < 1         # shoulders wider than the crop: still a crop


def test_a_crop_moves_to_keep_the_important_part_in():
    s = _crop_shot(cx=700)                                     # following a face on the left
    why = reframe.apply_view(s, {"kind": "scene", "subject": (700, 200, 1150, 900), "cam": None, "wide": False},
                             W, H, FPS)
    cw = H * 9 / 16
    assert "moved" in why and np.all(s.cx - cw / 2 <= 700 + 1) and np.all(s.cx + cw / 2 >= 1150 - 1)


def test_too_wide_for_a_tall_crop_shows_the_whole_picture():
    s = _crop_shot()
    reframe.apply_view(s, {"kind": "scene", "subject": (100, 200, 1800, 900), "cam": None, "wide": True}, W, H, FPS)
    assert s.layout == "fit" and s.fit_crop is None


def test_one_clear_subject_is_followed_instead_of_letterboxed():
    s = reframe.Shot(0, 40, layout="fit")
    s.fit_crop = (300.0, 1440.0)
    why = reframe.apply_view(s, {"kind": "scene", "subject": (1300, 300, 1600, 900), "cam": None, "wide": False},
                             W, H, FPS)
    assert s.layout == "crop" and "following" in why and abs(float(s.cx[0]) - 1450) < 1


def test_screens_and_slides_keep_the_whole_picture():
    s = _crop_shot()
    reframe.apply_view(s, {"kind": "screen", "subject": (0, 0, 1920, 1080), "cam": None, "wide": True}, W, H, FPS)
    assert s.layout == "fit"


def test_a_small_steady_face_in_a_corner_is_a_webcam():
    def track(cx, cy, fh, jitter=2.0, n=10):
        pts = [(i * 3, cx + (i % 2) * jitter, cy, fh * 0.8, fh, 0.9) for i in range(n)]
        p = np.array(pts)
        return {"pts": pts, "cx": float(np.median(p[:, 1])), "cy": float(np.median(p[:, 2])), "fh": fh}
    cam = track(1700, 150, 130)
    assert reframe.webcam_track([cam], 10, W, H) is cam
    assert reframe.webcam_track([track(960, 400, 300)], 10, W, H) is None      # a person in the middle
    assert reframe.webcam_track([track(1700, 150, 130, jitter=200)], 10, W, H) is None   # moving around
    x0, y0, x1, y1 = reframe.webcam_box(cam, W, H)
    assert x0 < 1700 < x1 and y0 < 150 < y1 and x1 <= W and y0 >= 0


def test_analyze_asks_the_ai_once_per_clip_and_follows_its_subject(tmp_path):
    src = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=4", "-pix_fmt",
                    "yuv420p", str(src)], check=True)
    asked = []

    class Eyes:
        def shots(self, frames):
            asked.append(len(frames))
            h, w = frames[0].shape[:2]
            return [{"kind": "scene", "subject": (0.70 * w, 0.2 * h, 0.85 * w, 0.95 * h), "cam": None, "wide": False,
                     "scale": (w, h)} for _ in frames]
    shots = reframe.analyze(str(src), 0.0, 100, 25.0, 640, 360, eyes=Eyes())
    assert asked == [1] and shots[0].layout == "crop"
    assert abs(float(shots[0].cx[0]) - 0.775 * 640) < 0.08 * 640                 # centred on what it pointed at


# ───────────────────────── picking ─────────────────────────

def test_the_best_looking_candidates_are_kept(monkeypatch):
    clips = [{"start": 0, "end": 30, "score": 80, "title": "Dull slide"},
             {"start": 40, "end": 70, "score": 72, "title": "Big moment"},
             {"start": 80, "end": 110, "score": 70, "title": "Fine"}]
    monkeypatch.setattr(vision, "frames_at", lambda src, times, width=512: [np.zeros((4, 4, 3), np.uint8)] * 4)
    looks = {"Dull slide": 1, "Big moment": 10, "Fine": 6}

    class Eyes:
        def rate(self, frames, about=""):
            return looks[about], "because"
    kept = vision.rerank(Eyes(), clips, "v.mp4", 2, log=lambda m: None)
    assert [c["title"] for c in kept] == ["Big moment", "Fine"]
    assert kept[0]["look"] == 10 and kept[0]["score_said"] == 72
    assert vision.with_extra(config.Settings(clips=4), Eyes()).clips == 6
    assert vision.with_extra(config.Settings(clips=4), None).clips == 4
    assert vision.rerank(None, clips, "v.mp4", 2) == clips[:2]


# ───────────────────────── the built-in AI's eyes ─────────────────────────

def test_the_built_in_ai_loads_its_vision_file(tmp_path, monkeypatch, tmp_output):
    from clippy import components, engine
    monkeypatch.setattr(components, "LLM_DIR", tmp_path)
    model = tmp_path / "Qwen3.5-4B-Q4_K_M.gguf"
    model.write_bytes(b"m")
    row = next(r for r in engine.models(config.load()) if r["file"] == model.name)
    assert row["vision"] == "missing" and row["mmproj_url"].endswith("mmproj-F16.gguf")
    engine.vision_file(model).write_bytes(b"v")
    assert engine.vision_file(model).name == "Qwen3.5-4B-Q4_K_M.mmproj.gguf"
    assert next(r for r in engine.models(config.load()) if r["file"] == model.name)["vision"] == "ready"
    assert engine._files() == [model]                                          # the vision file isn't a model
    seen = {}

    class Proc:
        def poll(self):
            return 1
    monkeypatch.setattr(components, "engine_exe", lambda: tmp_path / "llama-server")
    monkeypatch.setattr(components, "hardware", lambda: {"threads": 4, "vram_mb": 8000, "ram_mb": 16000})
    monkeypatch.setattr(engine.subprocess, "Popen", lambda args, **k: seen.update(args=args) or Proc())
    with pytest.raises(RuntimeError):
        engine.Engine().start(config.Settings(), model)
    assert seen["args"][-2:] == ["--mmproj", "Qwen3.5-4B-Q4_K_M.mmproj.gguf"]
    with pytest.raises(RuntimeError):
        engine.Engine().start(config.Settings(vision="off"), model)
    assert "--mmproj" not in seen["args"]
