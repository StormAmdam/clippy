"""Faster without changing the result: transcription that stays on a small graphics card, rendering on several
cores, the same caption tilt every time."""
import hashlib
import os
import subprocess
import sys

import numpy as np

from clippy import transcribe


def test_a_small_card_steps_down_on_the_gpu_before_the_cpu():
    assert transcribe.gpu_steps("float16", 3000) == transcribe.GPU_STEPS
    assert transcribe.gpu_steps("int8_float16", 2000) == [("int8_float16", 8), ("int8_float16", 4), ("int8_float16", 2)]
    assert transcribe.gpu_steps("int8_float16", 1100) == [("int8_float16", 2)]


def test_running_out_of_gpu_memory_tries_smaller_batches_first(tmp_path, monkeypatch):
    import faster_whisper
    from clippy import config
    tried = []

    class Word:
        def __init__(self, w, s):
            self.word, self.start, self.end, self.probability = w, s, s + 0.3, 0.9

    class Seg:
        def __init__(self):
            self.end, self.text, self.words = 1.0, "hi there", [Word("hi", 0.1), Word("there", 0.5)]

    class Info:
        language = "en"

    class Model:
        def __init__(self, name, device, compute_type, **k):
            self.device, self.compute = device, compute_type

    class Batched:
        def __init__(self, model):
            self.model = model

        def transcribe(self, audio, batch_size, **k):
            tried.append((self.model.device, self.model.compute, batch_size))
            if batch_size > 2:
                raise RuntimeError("CUDA failed with error out of memory")
            return iter([Seg()]), Info()

    monkeypatch.setattr(faster_whisper, "WhisperModel", Model)
    monkeypatch.setattr(faster_whisper, "BatchedInferencePipeline", Batched)
    monkeypatch.setattr(transcribe, "_pick_device", lambda cfg, log: ("cuda", "float16", None))
    monkeypatch.setattr(transcribe.gpu, "free_vram_mb", lambda: 3000)
    monkeypatch.setattr(transcribe, "load_audio", lambda p: np.zeros(16000, np.float32))
    tr = transcribe.transcribe(config.Settings(), tmp_path / "v.mp4", tmp_path, log=lambda m: None)
    assert tried == [("cuda", "float16", 8), ("cuda", "int8_float16", 8), ("cuda", "int8_float16", 4),
                     ("cuda", "int8_float16", 2)]                   # never the CPU: it fit with smaller batches
    assert [w["w"] for w in tr["words"]] == ["hi", "there"] and tr["device"] == "cuda"


def test_the_caption_tilt_is_the_same_in_every_run(tmp_path):
    """Python's string hash changes each launch; the tilt of caption words mustn't (Quick Fix keeps the look)."""
    code = ("import hashlib, numpy as np; from clippy.config import Settings; from clippy.overlay import Overlay;"
            "w=[{'w':'Hello','s':0.0,'e':0.4},{'w':'there','s':0.5,'e':0.9}];"
            "ov=Overlay(Settings(caption_style='beast'), w, 2.0, '', [], [], lambda t: {'caption_y': 1300, 'title_y': 220});"
            "f=np.zeros((1920,1080,3),np.uint8); ov.draw(f, 0.2); print(hashlib.md5(f.tobytes()).hexdigest())")
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd(),
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout.strip() for seed in ("1", "2", "3")}
    assert len(outs) == 1 and len(next(iter(outs))) == 32


def test_several_cores_send_the_encoder_exactly_the_same_frames(tmp_path, monkeypatch):
    from clippy import config, render
    from clippy.download import video_stream_info
    from tests.conftest import make_words
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=3", "-f", "lavfi", "-i",
                    "sine=f=440:d=3", "-shortest", "-pix_fmt", "yuv420p", str(src)], check=True)
    real, size = subprocess.Popen, render.OUT_W * render.OUT_H * 3
    words = make_words("one two three four five six", start=0.2, step=0.4)
    clip = {"start": 0.0, "end": 2.8, "i0": 0, "i1": 6, "title": "Same Frames", "emphasis": ["three"], "emoji": []}

    def frames_sent(workers: int) -> list[str]:
        frames = []

        class Tee:
            def __init__(self, inner):
                self.inner, self.buf = inner, b""

            def write(self, b):
                self.buf += b
                while len(self.buf) >= size:
                    frames.append(hashlib.md5(self.buf[:size]).hexdigest())
                    self.buf = self.buf[size:]
                return self.inner.write(b)

            def close(self):
                return self.inner.close()

        def popen(cmd, *a, **k):
            p = real(cmd, *a, **k)
            if "rawvideo" in cmd and k.get("stdin") == subprocess.PIPE:
                p.stdin = Tee(p.stdin)
            return p
        monkeypatch.setattr(render.subprocess, "Popen", popen)
        monkeypatch.setattr(render, "COMPOSE_WORKERS", workers)
        render.render_clip(config.Settings(teaser=False), src, video_stream_info(src), clip, words, None,
                           tmp_path / f"out{workers}.mp4", log=lambda m: None)
        return frames

    one, three = frames_sent(1), frames_sent(3)
    assert len(one) == 70 and one == three                          # the same frames, from 3 threads
