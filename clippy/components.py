"""Everything Clippy downloads for itself, kept inside the Clippy folder: video tools, the AI engine, the speech and
AI models. Delete the folder (or uninstall the app) and all of it is gone. Downloads run in the background with
progress, and can be cancelled and resumed."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from . import aisetup, config

ROOT = config.ROOT
WIN = sys.platform == "win32"
EXE = ".exe" if WIN else ""
BIN = ROOT / "bin"                      # ffmpeg, ffprobe
ENGINE_DIR = ROOT / "engine"            # llama.cpp builds
LLM_DIR = ROOT / "models" / "llm"       # AI models (.gguf)
WHISPER_DIR = ROOT / "models" / "whisper"
DOWNLOADS = ROOT / "downloads"          # partial downloads, so they can resume
EMOJI_FONT = ROOT / "fonts" / "NotoColorEmoji.ttf"
EMOJI_URL = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/2D/fonts/NotoColorEmoji.ttf"  # bitmap version: Pillow can draw it
FFMPEG_RELEASES = "https://api.github.com/repos/FFmpeg-Builds/FFmpeg-Builds/releases?per_page=1"
LLAMA_RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
# NVIDIA libraries Whisper needs on the GPU. Windows wheels lag behind Linux ones, so the versions differ.
GPU_PACKAGES = (["nvidia-cublas-cu12==12.9.2.10", "nvidia-cudnn-cu12>=9.28,<10"] if WIN
                else ["nvidia-cublas-cu12==12.9.3.13", "nvidia-cudnn-cu12==9.28.0.42"])
WHISPER_GB = {"large-v3-turbo": 1.62, "large-v3": 3.09, "medium": 1.53, "small": 0.48}


def hidden() -> dict:
    return aisetup._hidden()


# ───────────────────────── background tasks ─────────────────────────

class Task:
    def __init__(self, tid: str, label: str):
        self.id, self.label = tid, label
        self.done = self.total = 0
        self.state, self.error, self.step = "running", "", ""
        self._cancel = False

    def progress(self, done: int, total: int) -> None:
        self.done, self.total = done, total

    def cancelled(self) -> bool:
        return self._cancel

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "state": self.state, "done": self.done, "total": self.total,
                "step": self.step, "error": self.error}


TASKS: dict[str, Task] = {}
_LOCK = threading.Lock()


def run_task(tid: str, label: str, fn) -> Task:
    """Run fn(task) in the background, once per id at a time."""
    with _LOCK:
        t = TASKS.get(tid)
        if t and t.state == "running":
            return t
        t = TASKS[tid] = Task(tid, label)

    def go():
        try:
            fn(t)
            t.state = "done"
        except aisetup.Cancelled:
            t.state = "cancelled"
        except Exception as e:                           # shown to the person in the app
            t.state, t.error = "failed", str(e)[:400]

    threading.Thread(target=go, daemon=True, name=f"task-{tid}").start()
    return t


def cancel(tid: str) -> None:
    if (t := TASKS.get(tid)) and t.state == "running":
        t._cancel = True


def tasks() -> dict:
    return {k: v.to_dict() for k, v in TASKS.items()}


def fetch(url: str, dest: Path, task: Task, label: str) -> Path:
    return aisetup.download(url, dest, label, progress=task.progress, cancelled=task.cancelled)


def _github(url: str):
    import os
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):                 # CI machines share IPs and hit the anonymous rate limit
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    r = httpx.get(url, timeout=30, follow_redirects=True, headers=headers)
    r.raise_for_status()
    return r.json()


_hw = {"t": 0.0, "v": None}


def hardware() -> dict:
    """What this PC has (remembered for a minute: on Windows, asking about the graphics card is slow)."""
    if _hw["v"] is None or time.time() - _hw["t"] > 60:
        LLM_DIR.mkdir(parents=True, exist_ok=True)
        _hw.update(t=time.time(), v=aisetup.hardware(LLM_DIR))
    return _hw["v"]


def folder_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink()) if p.exists() else 0


def ensure_path() -> None:
    """Tools in Clippy's own folder win over anything else on the PC."""
    import os
    for d in (BIN,):
        if str(d) not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


# ───────────────────────── the parts ─────────────────────────

def _ffmpeg_status(cfg) -> dict:
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ff and fp:
        mine = Path(ff).resolve().parent == BIN.resolve()
        return {"installed": True, "removable": mine,
                "detail": "In Clippy's folder" if mine else "Already on this PC"}
    return {"installed": False, "detail": "Needed to read, cut and encode video"}


def _version(name: str) -> tuple:
    m = re.search(r"-n(\d+)\.(\d+)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _ffmpeg_install(task: Task, cfg) -> None:
    rel = _github(FFMPEG_RELEASES)[0]
    plat = "win64" if WIN else "linux64"
    assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
    builds = [n for n in assets if re.fullmatch(rf"ffmpeg-n(\d+)\.(\d+)-latest-{plat}-gpl-\1\.\2\.(zip|tar\.xz)", n)]
    if not builds:
        raise RuntimeError("Couldn't find an ffmpeg build to download.")
    name = max(builds, key=_version)
    archive = fetch(assets[name], DOWNLOADS / name, task, "ffmpeg")
    task.step = "Unpacking…"
    aisetup.extract(archive, BIN, only=lambda n: Path(n).name in (f"ffmpeg{EXE}", f"ffprobe{EXE}"))
    for n in ("ffmpeg", "ffprobe"):
        (BIN / f"{n}{EXE}").chmod(0o755)
    archive.unlink(missing_ok=True)
    ensure_path()


def _ffmpeg_remove(cfg) -> None:
    for n in ("ffmpeg", "ffprobe"):
        (BIN / f"{n}{EXE}").unlink(missing_ok=True)


def _whisper_repo(name: str) -> str:
    try:
        from faster_whisper.utils import _MODELS
        return _MODELS.get(name, name)
    except ImportError:
        return name


def _whisper_dir(cfg) -> Path:
    return WHISPER_DIR / ("models--" + _whisper_repo(cfg.whisper_model).replace("/", "--"))


def _whisper_status(cfg) -> dict:
    d = _whisper_dir(cfg)
    ok = any(d.glob("snapshots/*/model.bin"))
    return {"installed": ok, "removable": ok, "size": folder_size(d) if ok else int(WHISPER_GB.get(cfg.whisper_model, 1.6) * 1e9),
            "detail": f"Whisper {cfg.whisper_model}" + ("" if ok else ": downloads by itself on the first video, or now")}


def _whisper_install(task: Task, cfg) -> None:
    from faster_whisper import download_model
    total = int(WHISPER_GB.get(cfg.whisper_model, 1.6) * 1e9)
    d = _whisper_dir(cfg)
    stop = threading.Event()

    def watch():                                       # the downloader has no progress hook: watch the folder grow
        while not stop.wait(1):
            task.progress(min(folder_size(d), total), total)

    threading.Thread(target=watch, daemon=True).start()
    try:
        download_model(cfg.whisper_model, cache_dir=str(WHISPER_DIR))
    finally:
        stop.set()


def _whisper_remove(cfg) -> None:
    shutil.rmtree(_whisper_dir(cfg), ignore_errors=True)


def engine_exe() -> Path | None:
    cur = ENGINE_DIR / "current.txt"                   # a text file, not a symlink: Windows needs admin for those
    if not cur.exists():
        return None
    exe = ENGINE_DIR / cur.read_text(encoding="utf-8").strip() / f"llama-server{EXE}"
    return exe if exe.exists() else None


def _engine_status(cfg) -> dict:
    exe = engine_exe()
    if not exe:
        return {"installed": False, "detail": "Runs the AI model on this PC (no extra app needed)"}
    tag, _, variant = exe.parent.name.partition("-")
    how = {"cuda": "NVIDIA graphics card", "vulkan": "AMD/Intel graphics card", "cpu": "processor"}.get(variant, variant)
    return {"installed": True, "removable": True, "size": folder_size(exe.parent),
            "detail": f"llama.cpp {tag}, runs on your {how}"}


def _engine_install(task: Task, cfg, hw: dict | None = None) -> None:
    hw = hw or hardware()
    for rel in _github(LLAMA_RELEASES):
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        picks = aisetup.llama_assets(list(assets), hw["nvidia"], hw["arch"], hw["vulkan"])
        if picks:
            break
    else:
        raise RuntimeError("Couldn't find a llama.cpp build for this PC.")
    variant = "cuda" if "cuda" in picks[0] else "vulkan" if "vulkan" in picks[0] else "cpu"
    target = ENGINE_DIR / f"{rel['tag_name']}-{variant}"
    if not (target / f"llama-server{EXE}").exists():
        for name in picks:
            archive = fetch(assets[name], DOWNLOADS / name, task, f"AI engine ({variant})")
            task.step = "Unpacking…"
            aisetup.extract(archive, target)
            archive.unlink(missing_ok=True)
    exe = target / f"llama-server{EXE}"
    if not exe.exists():
        raise RuntimeError("The AI engine download didn't contain llama-server.")
    if not WIN:
        exe.chmod(0o755)
    out = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=120, cwd=target, **hidden())
    if variant == "cuda" and "CUDA0" not in out.stdout + out.stderr:
        task.step = "Your graphics driver is too old for the GPU build; getting the processor build…"
        return _engine_install(task, cfg, {**hw, "nvidia": False, "vulkan": False})
    (ENGINE_DIR / "current.txt").write_text(target.name, encoding="utf-8")
    for old in ENGINE_DIR.iterdir():                   # keep only the build in use
        if old.is_dir() and old != target and old.name != "downloads":
            shutil.rmtree(old, ignore_errors=True)


def _engine_remove(cfg) -> None:
    from . import engine
    engine.ENGINE.stop()
    shutil.rmtree(ENGINE_DIR, ignore_errors=True)


def gpu_libs_installed() -> bool:
    for p in sys.path:
        if p.endswith("site-packages") and Path(p, "nvidia", "cublas").is_dir() and Path(p, "nvidia", "cudnn").is_dir():
            return True
    return False


def _gpu_status(cfg) -> dict:
    ok = gpu_libs_installed()
    return {"installed": ok, "removable": ok, "size": int(1.5e9) if not ok else None,
            "detail": "Speech-to-text about 10× faster on your NVIDIA card" if not ok else "Whisper runs on your NVIDIA card"}


def _pip(*args: str) -> None:
    r = subprocess.run([sys.executable, "-m", "pip", "--disable-pip-version-check", "--no-input", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", **hidden())
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-400:])


def _gpu_install(task: Task, cfg) -> None:
    task.step = "Downloading the NVIDIA libraries (about 1.5 GB)…"
    _pip("install", "--no-warn-script-location", *GPU_PACKAGES)


def _gpu_remove(cfg) -> None:
    _pip("uninstall", "-y", "nvidia-cublas-cu12", "nvidia-cudnn-cu12")


def _emoji_status(cfg) -> dict:
    from .overlay import find_emoji_font
    p = find_emoji_font()
    mine = p is not None and Path(p) == EMOJI_FONT
    return {"installed": p is not None, "removable": mine,
            "detail": ("In Clippy's folder" if mine else "Already on this PC") if p else "Lets captions show emojis"}


def _emoji_install(task: Task, cfg) -> None:
    fetch(EMOJI_URL, EMOJI_FONT, task, "Emoji font")


def _emoji_remove(cfg) -> None:
    EMOJI_FONT.unlink(missing_ok=True)


PARTS = {
    "ffmpeg": ("Video tools", "ffmpeg reads, cuts and encodes your videos.", _ffmpeg_status, _ffmpeg_install, _ffmpeg_remove, 0.2),
    "whisper": ("Speech-to-text", "Turns what people say into words with exact timing.", _whisper_status, _whisper_install, _whisper_remove, 1.6),
    "engine": ("AI engine", "Runs the AI model you pick below, right inside Clippy.", _engine_status, _engine_install, _engine_remove, 0.6),
    "gpu": ("NVIDIA acceleration", "Lets Whisper use your NVIDIA graphics card.", _gpu_status, _gpu_install, _gpu_remove, 1.5),
    "emoji": ("Emoji font", "Noto Color Emoji, for the emojis that pop up in captions.", _emoji_status, _emoji_install, _emoji_remove, 0.01),
}


def components(cfg) -> list[dict]:
    hw = hardware()
    rows = []
    for cid, (name, about, status, _, _, gb) in PARTS.items():
        if cid == "gpu" and not hw["nvidia"]:
            continue
        s = {"removable": False, "size": None, **status(cfg)}
        if s.get("size") is None:
            s["size"] = int(gb * 1e9)
        t = TASKS.get(cid)
        rows.append({"id": cid, "name": name, "about": about, **s,
                     "task": t.to_dict() if t and t.state != "done" else None})
    return rows


def install(cid: str, cfg) -> Task:
    if cid not in PARTS:
        raise KeyError(cid)
    name, _, _, fn, _, _ = PARTS[cid]
    return run_task(cid, name, lambda t: fn(t, cfg))


def remove(cid: str, cfg) -> None:
    PARTS[cid][4](cfg)


def missing(cfg) -> list[str]:
    """Parts Clippy can't work without (speech-to-text downloads by itself on first use)."""
    from . import engine
    need = [c["id"] for c in components(cfg) if c["id"] in ("ffmpeg",) and not c["installed"]]
    if not engine.has_ai(cfg):
        need.append("ai")
    return need
