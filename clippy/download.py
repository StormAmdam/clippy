"""Fetch a video with yt-dlp (or accept a local file)."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def ytdlp() -> list[str]:
    """How to start yt-dlp: as a module of Clippy's own Python when it's installed there. The yt-dlp.exe that pip makes
    on Windows remembers the full path of the Python it was installed with (the PC the app was built on), so it
    can't run anywhere else."""
    if importlib.util.find_spec("yt_dlp") is None:
        return ["yt-dlp"]
    py = Path(sys.executable)
    if py.name.lower() == "pythonw.exe" and py.with_name("python.exe").exists():
        py = py.with_name("python.exe")    # a console program, so the ffmpeg it starts gets no window either
    return [str(py), "-m", "yt_dlp"]


def _why(r: subprocess.CompletedProcess) -> str:
    """The last line yt-dlp printed about its failure, or what little there is to go on."""
    for text in (r.stderr, r.stdout):
        if text and text.strip():
            return text.strip().splitlines()[-1]
    return f"it stopped with code {r.returncode} without saying why"


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")
    return s[:60] or "video"


def probe(url: str) -> dict:
    """Return basic info: id, title, duration, uploader. Works for URLs and local files."""
    p = Path(url).expanduser()
    if p.exists():
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
        return {"id": "local-" + _slug(p.stem), "title": p.stem, "duration": float(dur or 0),
                "uploader": "", "local_path": str(p.resolve()), "webpage_url": str(p.resolve())}
    r = subprocess.run([*ytdlp(), "-J", "--no-playlist", "--no-warnings", url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp could not read that link: {_why(r)}")
    info = json.loads(r.stdout)
    return {"id": _slug(info.get("id", "video")), "title": info.get("title", ""),
            "duration": float(info.get("duration") or 0), "uploader": info.get("uploader") or info.get("channel") or "",
            "webpage_url": info.get("webpage_url", url),
            "description": (info.get("description") or "")[:2000], "tags": (info.get("tags") or [])[:20],
            # YouTube's "Most replayed" graph (only on videos with enough watch history)
            "heatmap": [{"s": h.get("start_time"), "e": h.get("end_time"), "v": h.get("value")}
                        for h in (info.get("heatmap") or []) if isinstance(h, dict)]}


_YT_ID = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
SOURCE_EXT = (".mp4", ".mkv", ".webm", ".mov")


def cached_info(url: str, out_root: Path) -> dict | None:
    """The info saved by an earlier run, but only if that video is fully downloaded. Lets re-renders
    work offline or while YouTube blocks yt-dlp ("Sign in to confirm you're not a bot")."""
    m = _YT_ID.search(url)
    if not m:
        return None
    d = Path(out_root) / _slug(m.group(1))
    try:
        info = json.loads((d / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or info.get("id") != d.name:
        return None
    return info if any(f.suffix in SOURCE_EXT and f.is_file() for f in d.glob("source.*")) else None


def download(url: str, info: dict, workdir: Path, max_height: int, progress=lambda p, m: None) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    if info.get("local_path"):
        return Path(info["local_path"])
    existing = sorted(workdir.glob("source.*"))
    existing = [f for f in existing if f.suffix in SOURCE_EXT]
    if existing:
        progress(1.0, "Already downloaded")
        return existing[0]
    h = int(max_height)
    cmd = [
        *ytdlp(), "--no-playlist", "--no-warnings", "--newline",
        "-f", f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
        "-S", "res,fps,vcodec:avc1",  # prefer highest res/fps, then h264 when equal (fastest to decode)
        "--merge-output-format", "mp4", "--remux-video", "mp4",
        "--progress-template", "download:PROG %(progress._percent_str)s",
        "-o", str(workdir / "source.%(ext)s"), url,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    part, last = 0, 0.0
    tail: list[str] = []
    assert proc.stdout
    for line in proc.stdout:
        line = line.strip()
        tail = (tail + [line])[-8:]
        m = re.search(r"PROG\s+([\d.]+)%", line)
        if m:
            pct = float(m.group(1)) / 100
            if pct < last - 0.5:  # second stream (audio) started
                part += 1
            last = pct
            overall = min(0.99, (part + pct) / 2) if part < 2 else 0.99
            progress(overall, f"Downloading… {pct * 100:.0f}%")
    if proc.wait() != 0:
        raise RuntimeError("Download failed:\n" + "\n".join(tail))
    files = [f for f in workdir.glob("source.*") if f.suffix in (".mp4", ".mkv", ".webm", ".mov")]
    if not files:
        raise RuntimeError("Download finished but no video file was found")
    progress(1.0, "Downloaded")
    return files[0]


def video_stream_info(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,avg_frame_rate:stream_side_data=rotation",
                        "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    data = json.loads(r.stdout or "{}")
    st = (data.get("streams") or [{}])[0]

    def fr(s):
        try:
            a, b = s.split("/")
            return float(a) / float(b) if float(b) else 0.0
        except Exception:
            return 0.0

    # r_frame_rate is the clean nominal rate (24/1, 30000/1001); avg_frame_rate can be a messy ratio
    fps_str = next((x for x in (st.get("r_frame_rate"), st.get("avg_frame_rate")) if x and 0 < fr(x) <= 120), "30/1")
    fps = fr(fps_str)
    if fps > 60.5:
        fps_str, fps = "60/1", 60.0
    has_audio = bool(json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout or "{}").get("streams"))
    return {"width": int(st.get("width", 0)), "height": int(st.get("height", 0)),
            "fps": fps, "fps_str": fps_str, "duration": float(data.get("format", {}).get("duration", 0) or 0),
            "has_audio": has_audio}


def have_tools() -> list[str]:
    missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
    if importlib.util.find_spec("yt_dlp") is None and not shutil.which("yt-dlp"):
        missing.append("yt-dlp")
    return missing


SETUP_HINT = "Open Clippy, go to AI & Tools and press Set Up Everything."


def install_hint(windows: bool | None = None) -> str:
    """How to get ffmpeg/yt-dlp: in the Windows app Clippy downloads them itself; on Linux, the distro's package
    manager (setup.sh puts a current yt-dlp in .venv)."""
    if windows if windows is not None else sys.platform == "win32":
        return SETUP_HINT
    if shutil.which("pacman"):
        return "sudo pacman -S ffmpeg yt-dlp"
    for pm, cmd in (("apt-get", "sudo apt-get install ffmpeg"), ("dnf", "sudo dnf install ffmpeg"),
                    ("zypper", "sudo zypper install ffmpeg")):
        if shutil.which(pm):
            return cmd + "   (yt-dlp: ./setup.sh installs it)"
    return "install ffmpeg with your package manager, then run ./setup.sh"
