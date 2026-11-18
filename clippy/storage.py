"""Disk usage of the output folder, and safe ways to free space.

A project is one folder per source video: output/<video-id>/ with source.*, transcript, picks and
clips*/ folders. Folders starting with "_" (autopilot data, finder data) are internal, never projects.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path

from .config import INTERNAL_DIRS

VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov"}
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class FileInUse(RuntimeError):
    """Windows won't delete a file while another program has it open."""


def in_use_message(path: Path, done: str = "") -> str:
    return (f"Couldn't delete {Path(path).name}: it's open in another program (a video player or a folder window, "
            f"perhaps). Close it and try again.{done}")


def remove_file(f: Path) -> None:
    try:
        f.unlink()
    except FileNotFoundError:
        pass
    except PermissionError:
        try:                                            # read-only (copied from a USB stick, say): allowed to go
            os.chmod(f, stat.S_IWRITE)
            f.unlink()
        except OSError as e:
            raise FileInUse(in_use_message(f)) from e


def remove_tree(d: Path) -> None:
    """Delete a folder. If a file in it is open elsewhere, the rest is deleted and FileInUse says what's left."""
    def retry(func, path, exc):
        if isinstance(exc, FileNotFoundError):
            return
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            raise FileInUse(in_use_message(Path(path), " Everything else in it is gone already.")) from e
    if sys.version_info >= (3, 12):
        shutil.rmtree(d, onexc=retry)
    else:                                               # Python 3.11
        shutil.rmtree(d, onerror=lambda func, path, info: retry(func, path, info[1]))


def _project_dir(root: Path, vid: str) -> Path:
    if not vid or not _ID.match(vid) or vid in INTERNAL_DIRS:
        raise ValueError(f"Not a project: {vid!r}")
    d = (root / vid).resolve()
    if d.parent != root.resolve() or not d.is_dir():
        raise ValueError(f"Not a project: {vid!r}")
    return d


def _sources(d: Path) -> list[Path]:
    return [f for f in d.glob("source.*") if f.suffix.lower() in VIDEO_EXT and f.is_file()]


def _size(paths) -> int:
    return sum(f.stat().st_size for f in paths if f.is_file())


def _files(d: Path) -> list[Path]:
    return [f for f in d.rglob("*") if f.is_file()]


def usage(root: Path) -> dict:
    projects = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in INTERNAL_DIRS) if root.exists() else []:
        files = _files(d)
        src = _size(_sources(d))
        clips = _size(f for f in files if f.relative_to(d).parts[0].startswith("clips"))
        try:
            title = json.loads((d / "info.json").read_text(encoding="utf-8")).get("title") or d.name
        except (OSError, ValueError):
            title = d.name
        others = [f for f in files if f not in _sources(d)]
        projects.append({"id": d.name, "title": title, "source_bytes": src, "clips_bytes": clips,
                         "total": _size(files), "has_source": src > 0,
                         "modified": max((f.stat().st_mtime for f in others), default=d.stat().st_mtime)})
    projects.sort(key=lambda p: -p["total"])
    return {"total": sum(p["total"] for p in projects), "sources": sum(p["source_bytes"] for p in projects),
            "clips": sum(p["clips_bytes"] for p in projects), "projects": projects}


def delete_source(root: Path, vid: str) -> int:
    """Delete only the downloaded video; transcript, picks and clips stay (it re-downloads if needed)."""
    d = _project_dir(root, vid)
    freed = 0
    for f in _sources(d):
        size = f.stat().st_size
        remove_file(f)
        freed += size
    return freed


def delete_project(root: Path, vid: str) -> int:
    d = _project_dir(root, vid)
    freed = _size(_files(d))
    remove_tree(d)
    return freed


def cleanup_sources(root: Path, older_than_days: int, keep: set[str] = frozenset()) -> int:
    """Delete downloaded videos of projects with no activity for `older_than_days` days. Clips stay."""
    cutoff = time.time() - older_than_days * 86400
    freed = 0
    for p in usage(root)["projects"]:
        if p["has_source"] and p["id"] not in keep and p["modified"] < cutoff:
            try:
                freed += delete_source(root, p["id"])
            except FileInUse:
                continue                                # open in a player right now: next time
    return freed
