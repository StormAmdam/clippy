"""Videos people upload from their own computer, instead of a YouTube link.

The browser streams the file straight into Clippy's folder (output/_uploads/…part while it arrives), then it becomes a
project like any downloaded video: output/up-<fingerprint>/source.<ext> with an info.json. Storage, deleting and
re-editing work the same way, and uploading the same file again reuses its transcript and picks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from . import config

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".ts", ".3gp"}
SPARE = 1_000_000_000                 # bytes of free disk space to keep on top of the video


class UploadError(ValueError):
    """Said to the person uploading."""


def _human(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def check(name: str, size: int, out_root: Path) -> str:
    """The file's extension, or UploadError before anything is written."""
    ext = Path(name).suffix.lower()
    if ext not in VIDEO_EXT:
        raise UploadError("That isn't a video file Clippy can read. Use mp4, mov, mkv, webm, avi or a similar video.")
    out_root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out_root).free
    if size and size + SPARE > free:
        raise UploadError(f"Not enough free disk space: this video needs {_human(size)} plus 1 GB to spare, and "
                          f"{_human(free)} is free.")
    return ext


def part_file(out_root: Path, ext: str) -> Path:
    d = out_root / "_uploads"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.part"):                         # left over from an upload that was cut off long ago
        try:
            if time.time() - old.stat().st_mtime > 86400:
                old.unlink()
        except OSError:
            pass
    return d / f"{uuid.uuid4().hex}{ext}.part"


def _probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json",
                        str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    kinds = {s.get("codec_type") for s in data.get("streams") or []}
    return {"video": "video" in kinds, "duration": float((data.get("format") or {}).get("duration") or 0)}


def finish(part: Path, name: str, digest: str, out_root: Path) -> dict:
    """Turn a fully received file into a project. Returns what the app needs to start making clips from it."""
    if not shutil.which("ffprobe"):
        raise UploadError("Clippy's video tools aren't set up yet. Open AI & Tools and press Set Up Everything.")
    vid = "up-" + digest[:10]
    d = out_root / vid
    src = next((f for f in d.glob("source.*") if f.suffix.lower() in VIDEO_EXT and f.is_file()), None)
    meta = _probe(src or part)
    if not meta["video"]:
        raise UploadError("Clippy couldn't find a video in that file. Is it a video, and does it play?")
    if src is None:                                      # new: keep it. Same file again: reuse the earlier copy
        d.mkdir(parents=True, exist_ok=True)
        src = d / f"source{Path(name).suffix.lower()}"
        os.replace(part, src)
    title = Path(name).stem.strip()[:120] or "My video"
    info = {"id": vid, "title": title, "duration": meta["duration"], "uploader": "", "local_path": str(src),
            "webpage_url": "", "uploaded": True}
    config.write_atomic(d / "info.json", json.dumps(info, ensure_ascii=False, indent=2))
    return {"path": str(src), "id": vid, "title": title, "duration": meta["duration"]}


async def receive(request, name: str, out_root: Path) -> dict:
    """Stream the request body into Clippy's folder, then make it a project (see finish)."""
    from starlette.concurrency import run_in_threadpool
    size = int(request.headers.get("content-length") or 0)
    ext = check(name, size, out_root)
    part = part_file(out_root, ext)
    h, n = hashlib.sha1(), 0
    try:
        with open(part, "wb") as f:
            async for chunk in request.stream():
                if chunk:
                    f.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
        if n == 0:
            raise UploadError("That file is empty.")
        if size and n < size:
            raise UploadError("The upload was cut off. Try again.")
        return await run_in_threadpool(finish, part, name, h.hexdigest(), out_root)
    finally:
        part.unlink(missing_ok=True)
