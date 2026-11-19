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


LOW_VRAM_MB = 1000                    # free graphics memory below this: the CPU
# on the GPU, from the fastest to the leanest (out of memory → the next one, the CPU only after the last).
# Batch size doesn't change what's heard, only how many pieces go through the GPU at once.
GPU_STEPS = [("float16", 8), ("int8_float16", 8), ("int8_float16", 4), ("int8_float16", 2)]


def _gpu_trouble(e: Exception) -> bool:
    t = str(e)
    return "CUDA" in t or "cuDNN" in t or "cublas" in t.lower() or "out of memory" in t.lower()


def gpu_steps(compute: str, free_mb: int) -> list[tuple[str, int]]:
    """The GPU settings to try, starting where this much free memory allows."""
    steps = [st for st in GPU_STEPS if compute == "float16" or st[0] == compute]
    if compute != "float16" and free_mb < 1400:          # very little free: start with small batches
        steps = [st for st in steps if st[1] <= 2]
    return steps


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

    need_fp16 = 2600
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
    if free >= LOW_VRAM_MB:                   # small or busy card: 8-bit, small batches (see GPU_STEPS), still the GPU
        return "cuda", "int8_float16", paused
    tip = ("Close other programs that use the graphics card (games, other AI apps) to transcribe faster."
           if sys.platform == "win32" else "Tip: set free_gpu_for_whisper = true and llama_service in config.toml.")
    log(f"Only {free} MB of graphics memory free, so transcribing on the CPU (slower). {tip}")
    return "cpu", "int8", paused


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

    from faster_whisper import BatchedInferencePipeline, WhisperModel

    device, compute, paused = _pick_device(cfg, log)
    tries = [("cuda", c, b) for c, b in gpu_steps(compute, gpu.free_vram_mb() or 0)] if device == "cuda" else []
    tries.append(("cpu", "int8", 0))
    model = None
    try:
        for attempt, (device, compute, batch) in enumerate(tries):
            try:
                log(f"Whisper {cfg.whisper_model} on {device.upper()} ({compute})")
                progress(0.02, f"Loading Whisper on {device.upper()}…")
                # (folders like C:\Users\Jörg 测试 work: the Windows smoke test transcribes from one)
                model = WhisperModel(cfg.whisper_model, device=device, compute_type=compute,
                                     cpu_threads=max(2, (os.cpu_count() or 4) // 2),
                                     download_root=str(ROOT / "models" / "whisper"))
                common = dict(word_timestamps=True, vad_filter=True,
                              vad_parameters={"min_silence_duration_ms": 500})
                if device == "cuda":
                    segs, info = BatchedInferencePipeline(model).transcribe(audio, batch_size=batch, beam_size=5,
                                                                            **common)
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
                if device == "cuda" and attempt + 1 < len(tries) and _gpu_trouble(e):
                    nxt = tries[attempt + 1]
                    log(f"GPU transcription failed ({str(e)[:120]}); trying "
                        + (f"the GPU with less memory ({nxt[1]}, {nxt[2]} at a time)" if nxt[0] == "cuda" else "the CPU"))
                    model = None
                    gc.collect()
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
