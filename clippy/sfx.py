"""Sound effects, synthesised from scratch (royalty-free by construction).

Drop your own files into <project>/sfx/ to override, named like whoosh*.wav, pop*.wav, impact*.wav
(any format ffmpeg reads). One is picked at random per use.
"""
from __future__ import annotations

import functools
import random
import subprocess
import wave
from pathlib import Path

import numpy as np

from .config import ROOT

SR = 48000
USER_DIR = ROOT / "sfx"


def _bandpass_sweep(x: np.ndarray, fc: np.ndarray, q: float) -> np.ndarray:
    """Chamberlin state-variable filter with a time-varying centre frequency."""
    out = np.empty_like(x)
    low = band = 0.0
    damp = 1.0 / q
    f = 2.0 * np.sin(np.pi * np.clip(fc, 20, SR / 6) / SR)
    for i in range(len(x)):
        high = x[i] - low - damp * band
        band += f[i] * high
        low += f[i] * band
        out[i] = band
    return out


def _norm(a: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(a))) or 1.0
    return (a / m * peak).astype(np.float32)


def whoosh(dur: float = 0.55, seed: int = 0, bright: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.linspace(0, 1, n, endpoint=False)
    noise = rng.standard_normal(n)
    peak = 0.58
    up = np.clip(t / peak, 0, 1)
    down = np.clip((t - peak) / (1 - peak), 0, 1)
    # pitch rises as it "approaches", falls as it passes (doppler-ish)
    fc = np.where(t < peak, 350 + (2600 * bright - 350) * up ** 1.6,
                  2600 * bright - (2600 * bright - 900) * down ** 0.8)
    body = _bandpass_sweep(noise, fc, q=2.2)
    air = _bandpass_sweep(noise, fc * 2.2, q=4.0) * 0.35
    env = np.where(t < peak, up ** 2.2, np.exp(-down * 4.2))
    mono = (body + air) * env
    pan = np.clip(t * 1.3 - 0.15, 0, 1)  # sweep left → right
    stereo = np.stack([mono * np.cos(pan * np.pi / 2), mono * np.sin(pan * np.pi / 2)], axis=1)
    return _norm(stereo, 0.9)


def pop(dur: float = 0.11, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 380 + 1100 * np.exp(-t * 55)
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = np.minimum(1, t / 0.002) * np.exp(-t * 38)
    tone = np.sin(phase) * env
    click = rng.standard_normal(n) * np.exp(-t * 400) * 0.25
    mono = tone + click
    return _norm(np.stack([mono, mono], axis=1), 0.8)


def impact(dur: float = 1.1, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 34 + 40 * np.exp(-t * 9)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.0)
    noise = rng.standard_normal(n)
    # low-passed noise burst (one-pole)
    lp = np.empty(n)
    acc = 0.0
    a = 0.08
    for i in range(n):
        acc += a * (noise[i] - acc)
        lp[i] = acc
    burst = lp * np.exp(-t * 22) * 3.0
    mono = np.tanh((sub * 1.4 + burst) * 1.6)
    env = np.minimum(1, t / 0.003)
    mono *= env
    return _norm(np.stack([mono, mono], axis=1), 0.95)


def _decode(path: Path) -> np.ndarray | None:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()


@functools.cache
def _user_files(name: str) -> tuple[Path, ...]:
    """Your own sounds in sfx/, then the ones switched-on extensions bring."""
    from . import extensions
    kinds = (".wav", ".mp3", ".ogg", ".flac", ".m4a")
    mine = sorted(p for p in USER_DIR.glob(f"{name}*") if p.suffix.lower() in kinds) if USER_DIR.exists() else []
    return tuple(mine or extensions.sounds(name))


def forget_user_sounds() -> None:
    """Extensions changed: look for sound files again."""
    _user_files.cache_clear()
    _cached.cache_clear()


@functools.cache
def _cached(name: str, variant: int) -> np.ndarray:
    files = _user_files(name)
    if files:
        snd = _decode(files[variant % len(files)])
        if snd is not None:
            return snd
    if name == "whoosh":
        return whoosh(seed=variant, dur=0.5 + 0.08 * (variant % 3), bright=0.85 + 0.1 * (variant % 3))
    if name == "pop":
        return pop(seed=variant)
    if name == "impact":
        return impact(seed=variant)
    raise ValueError(name)


def build_track(events: list[tuple[float, str, float]], duration: float, seed: int = 0) -> np.ndarray:
    """events: (time_seconds, name, gain). Sounds are centred so a whoosh peaks at `time`."""
    rng = random.Random(seed)
    n = int(duration * SR) + 1
    track = np.zeros((n, 2), np.float32)
    for t, name, gain in events:
        snd = _cached(name, rng.randrange(6))
        # whooshes peak ~58% in → start early so the peak lands on the cut
        lead = int(len(snd) * 0.58) if name == "whoosh" else 0
        a = int(t * SR) - lead
        b = a + len(snd)
        sa, sb = max(0, -a), len(snd) - max(0, b - n)
        a, b = max(0, a), min(n, b)
        if b > a and sb > sa:
            track[a:b] += snd[sa:sb] * gain
    return track


def write_wav(path: Path, track: np.ndarray) -> None:
    pcm = (np.clip(track, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
