"""GPU helpers: load the pip-installed CUDA libs, check VRAM, pause/resume the local LLM service."""
from __future__ import annotations

import ctypes
import functools
import glob
import os
import shutil
import subprocess
import sys
import time

_loaded = False


def nvidia_smi() -> str | None:
    """nvidia-smi, also inside WSL where it lives in /usr/lib/wsl/lib and isn't always on PATH."""
    return shutil.which("nvidia-smi") or next((p for p in ("/usr/lib/wsl/lib/nvidia-smi",) if os.access(p, os.X_OK)), None)


def preload_cuda_libs() -> None:
    """CTranslate2 (faster-whisper) needs cuBLAS 12 + cuDNN 9. They come from pip
    (nvidia-cublas-cu12 / nvidia-cudnn-cu12); preload them so no system CUDA install is needed."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    site = next((p for p in sys.path if p.endswith("site-packages") and os.path.isdir(os.path.join(p, "nvidia"))), None)
    if not site:
        return
    for pkg in ("cuda_nvrtc", "cublas", "cudnn"):
        libdir = os.path.join(site, "nvidia", pkg, "lib")
        files = sorted(glob.glob(os.path.join(libdir, "lib*.so*")),
                       key=lambda f: ("Lt" in f, "_" in os.path.basename(f), f))
        for f in files:
            if any(x in f for x in ("alt", "builtins", "nvblas")):
                continue
            try:
                ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def free_vram_mb() -> int | None:
    smi = nvidia_smi()
    if not smi:
        return None
    try:
        out = subprocess.run([smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        return int(out[0]) if out else None
    except Exception:
        return None


@functools.cache
def has_nvenc() -> bool:
    """Actually try a tiny NVENC encode (listing the encoder isn't proof it works)."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


@functools.cache
def has_cuda_decode() -> bool:
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-hwaccel", "cuda", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
             "-f", "null", "-"], capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


# ── systemd --user service control (to borrow the GPU from llama-server for a minute) ──

def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)


def service_known(name: str) -> bool:
    """Is there a systemd user service by this name (running or not)?"""
    if not name or not shutil.which("systemctl"):
        return False
    try:
        return _systemctl("cat", name).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def service_active(name: str) -> bool:
    if not name or not shutil.which("systemctl"):
        return False
    return _systemctl("is-active", name).stdout.strip() == "active"


def stop_service(name: str, want_free_mb: int, log=print, timeout: float = 30) -> bool:
    log(f"Pausing '{name}' so Whisper can use the GPU…")
    r = _systemctl("stop", name)
    if r.returncode != 0:
        log(f"Could not stop {name}: {r.stderr.strip()}")
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        free = free_vram_mb()
        if free is None or free >= want_free_mb:
            break
        time.sleep(0.5)
    return True


def start_service(name: str, log=print) -> None:
    r = _systemctl("start", "--no-block", name)
    if r.returncode == 0:
        log(f"Restarted '{name}'.")
    else:
        log(f"WARNING: could not restart {name}: {r.stderr.strip()} — run: systemctl --user start {name}")
