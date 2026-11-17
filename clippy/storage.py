"""Disk usage of the output folder, and safe ways to free space.

A project is one folder per source video: output/<video-id>/ with source.*, transcript, picks and
clips*/ folders. Folders starting with "_" (autopilot data, finder data) are internal, never projects.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from .config import INTERNAL_DIRS

VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov"}
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


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
            title = json.loads((d / "info.json").read_text()).get("title") or d.name
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
        freed += f.stat().st_size
        f.unlink()
    return freed


def delete_project(root: Path, vid: str) -> int:
    d = _project_dir(root, vid)
    freed = _size(_files(d))
    shutil.rmtree(d)
    return freed


def cleanup_sources(root: Path, older_than_days: int, keep: set[str] = frozenset()) -> int:
    """Delete downloaded videos of projects with no activity for `older_than_days` days. Clips stay."""
    cutoff = time.time() - older_than_days * 86400
    freed = 0
    for p in usage(root)["projects"]:
        if p["has_source"] and p["id"] not in keep and p["modified"] < cutoff:
            freed += delete_source(root, p["id"])
    return freed
