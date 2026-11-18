"""Speech-to-text with word timestamps (faster-whisper, on the GPU when possible)."""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import config, gpu
from .config import ROOT, Settings

SR = 16000
ENV_HZ = 100  # loudness envelope resolution (used to verify silences before cutting them)


def load_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def loudness_envelope(audio: np.ndarray) -> np.ndarray:
    hop = SR // ENV_HZ
    n = len(audio) // hop
    if n == 0:
        return np.zeros(0, np.float32)
    frames = audio[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    return (20 * np.log10(rms + 1e-9)).astype(np.float32)


def _pick_device(cfg: Settings, log) -> tuple[str, str, str | None]:
    """Returns (device, compute_type, service_to_restart)."""
    if cfg.whisper_device == "cpu":
        return "cpu", "int8", None
    gpu.preload_cuda_libs()
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() == 0:
            return "cpu", "int8", None
    except Exception:
        return "cpu", "int8", None

    need_fp16, need_int8 = 2600, 1400
    free = gpu.free_vram_mb() or 0
    paused = None
    if free < need_fp16 and cfg.free_gpu_for_whisper and gpu.service_active(cfg.llama_service):
        if gpu.stop_service(cfg.llama_service, need_fp16, log):
            paused = cfg.llama_service
            free = gpu.free_vram_mb() or 0
    if free < need_fp16 and cfg.free_gpu_for_whisper:
        from .engine import ENGINE
        if ENGINE.running():                  # the built-in AI starts again by itself when clips are picked
            ENGINE.stop()
            log("Paused the built-in AI so Whisper can use the graphics card")
            for _ in range(20):
                if (free := gpu.free_vram_mb() or 0) >= need_fp16:
                    break
                time.sleep(0.5)
    if free < need_fp16 and cfg.free_gpu_for_whisper:
        from .llm import unload_ollama
        if freed := unload_ollama():          # Ollama loads the model again by itself on the next request
            log(f"Freed the GPU for Whisper: Ollama unloaded {', '.join(freed)}")
            for _ in range(20):
                if (free := gpu.free_vram_mb() or 0) >= need_fp16:
                    break
                time.sleep(0.5)
    if free >= need_fp16:
        return "cuda", "float16", paused
    if free >= need_int8:
        return "cuda", "int8_float16", paused
    tip = ("Close other programs that use the graphics card (games, other AI apps) to transcribe faster."
           if sys.platform == "win32" else "Tip: set free_gpu_for_whisper = true and llama_service in config.toml.")
    log(f"Only {free} MB of graphics memory free, so transcribing on the CPU (slower). {tip}")
    return "cpu", "int8", paused


def short_path(path: str) -> str:
    """Windows' old-style 8.3 name for a path (C:\\Users\\JRG~1\\…), in plain letters. The path itself when there's
    none."""
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    return buf.value if 0 < n < len(buf) else str(path)


def load_whisper(name: str, device: str, compute: str, root: Path | None = None):
    """faster-whisper's model from Clippy's folder (downloaded the first time). CTranslate2 can't open a path with
    letters like ö or 测 on Windows (C:\\Users\\Jörg\\…), so there it gets the short path, or else the files from
    memory."""
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    root = root or ROOT / "models" / "whisper"
    path = name if os.path.isdir(name) else download_model(name, cache_dir=str(root))
    opts = dict(device=device, compute_type=compute, cpu_threads=max(2, (os.cpu_count() or 4) // 2))
    if sys.platform == "win32" and not str(path).isascii():
        if (short := short_path(path)).isascii():
            path = short
        else:                                          # no short names on this drive: hand the files over
            files = {f.name: f.read_bytes() for f in Path(path).iterdir() if f.is_file()}
            return WhisperModel(str(path), files=files, **opts)
    return WhisperModel(str(path), **opts)


def audio_only(media: Path, workdir: Path, progress=lambda p, m: None) -> dict:
    """For videos without talking: just the loudness envelope, no Whisper (and the GPU stays untouched)."""
    env_file = workdir / "envelope.npy"
    if env_file.exists():
        duration = len(np.load(env_file)) / ENV_HZ
    else:
        progress(0.1, "Reading the audio…")
        audio = load_audio(media)
        duration = len(audio) / SR
        np.save(env_file, loudness_envelope(audio))
    progress(1.0, "No talking — skipped transcription")
    return {"language": None, "duration": duration, "words": [], "segments": [], "device": "skipped"}


def transcribe(cfg: Settings, media: Path, workdir: Path, progress=lambda p, m: None, log=print) -> dict:
    cache = workdir / "transcript.json"
    env_file = workdir / "envelope.npy"
    if cache.exists() and env_file.exists():
        progress(1.0, "Transcript cached")
        return json.loads(cache.read_text(encoding="utf-8"))

    progress(0.0, "Extracting audio…")
    audio = load_audio(media)
    duration = len(audio) / SR
    np.save(env_file, loudness_envelope(audio))

    from faster_whisper import BatchedInferencePipeline

    device, compute, paused = _pick_device(cfg, log)
    model = None
    try:
        for attempt in range(2):
            try:
                log(f"Whisper {cfg.whisper_model} on {device.upper()} ({compute})")
                progress(0.02, f"Loading Whisper on {device.upper()}…")
                model = load_whisper(cfg.whisper_model, device, compute)
                common = dict(word_timestamps=True, vad_filter=True,
                              vad_parameters={"min_silence_duration_ms": 500})
                if device == "cuda":
                    segs, info = BatchedInferencePipeline(model).transcribe(audio, batch_size=8, beam_size=5, **common)
                else:
                    segs, info = model.transcribe(audio, beam_size=1, condition_on_previous_text=False, **common)
                words, segments = [], []
                for s in segs:
                    progress(min(0.99, s.end / max(duration, 1)), f"Transcribing on {device.upper()}… {s.end / 60:.1f}/{duration / 60:.1f} min")
                    seg_words = []
                    for w in s.words or []:
                        txt = w.word.strip()
                        if not txt:
                            continue
                        seg_words.append({"w": txt, "s": round(float(w.start), 3), "e": round(float(w.end), 3),
                                          "p": round(float(w.probability), 3)})
                    if seg_words:
                        segments.append({"s": seg_words[0]["s"], "e": seg_words[-1]["e"], "text": s.text.strip(),
                                         "i0": len(words), "i1": len(words) + len(seg_words)})
                        words.extend(seg_words)
                break
            except RuntimeError as e:
                if device == "cuda" and attempt == 0 and ("CUDA" in str(e) or "cuDNN" in str(e) or "cublas" in str(e).lower()):
                    log(f"GPU transcription failed ({e}); retrying on CPU")
                    del model
                    gc.collect()
                    device, compute = "cpu", "int8"
                    continue
                raise
    finally:
        model = None
        gc.collect()
        if paused:
            gpu.start_service(paused, log)

    result = {"language": info.language, "duration": duration, "words": words, "segments": segments,
              "device": device}
    config.write_atomic(cache, json.dumps(result, ensure_ascii=False))
    progress(1.0, f"Transcribed {len(words)} words ({info.language})")
    return result
