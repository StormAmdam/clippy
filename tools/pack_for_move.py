#!/usr/bin/env python3
"""Pack Clippy into zip files for moving to another PC.  Run:  python3 tools/pack_for_move.py

Makes, next to the Clippy folder (or in --dest):
  Clippy.zip         everything you need to continue: code, settings, Autopilot profiles, review queue,
                     Find-videos scans, transcripts, AI picks, finished clips, fonts, face model, and a
                     move-kit/ folder (Claude Code memory + your llama-coder AI-server launcher)
  Clippy-extras.zip  optional: downloaded source videos + the Whisper model. Without it they download
                     again by themselves when needed. Unzip it into the same place as Clippy.zip.

Never packed: .venv (Python environments don't survive a move; setup.sh rebuilds it) and caches.
Standard library only, so it runs with any python3 ≥ 3.9.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "Clippy"                                     # folder name inside the zips
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", "move-kit", ".mypy_cache", ".ruff_cache"}
SKIP_SUFFIX = {".pyc", ".tmp", ".part"}
VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".opus"}
NO_COMPRESS = VIDEO | {".jpg", ".jpeg", ".png", ".webp", ".gif", ".zip", ".gz", ".woff2", ".bin", ".onnx"}


def is_extra(rel: Path) -> bool:
    """Big things that come back on their own: the Whisper model and downloaded source videos."""
    parts = rel.parts
    if parts[:2] == ("models", "whisper"):
        return True
    return (len(parts) == 3 and parts[0] == "output" and parts[2].startswith("source.")
            and rel.suffix.lower() in VIDEO)


def project_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        d = Path(dirpath)
        rel_dir = d.relative_to(ROOT)
        keep = []
        for name in sorted(dirnames):
            p = d / name
            if name in SKIP_DIRS or (name == ".locks" and "whisper" in rel_dir.parts):
                continue
            if p.is_symlink():                     # e.g. .claude/skills/* → ../../.agents/skills/*
                yield p, rel_dir / name
            else:
                keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            p = d / name
            if p.suffix in SKIP_SUFFIX:
                continue
            yield p, rel_dir / name


def claude_memory_dir() -> Path:
    key = re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))     # how Claude Code names a project folder
    return Path.home() / ".claude" / "projects" / key / "memory"


def move_kit_files():
    """Things that live outside the Clippy folder but belong to it."""
    mem = claude_memory_dir()
    if mem.is_dir():
        for f in sorted(mem.glob("*.md")):
            yield f, Path("move-kit/claude-memory") / f.name
    for src in (Path.home() / ".local/bin/llama-coder", Path.home() / ".config/systemd/user/llama-coder.service"):
        if src.is_file():
            yield src, Path("move-kit/llama-coder") / src.name


MOVE_KIT_README = """\
move-kit: things from the old PC that live outside the Clippy folder
=====================================================================

claude-memory/   Claude Code's notes about you and this project. setup.sh copies them to
                 ~/.claude/projects/<this folder>/memory/ (never overwrites existing notes).
                 Some notes describe the old PC (6 GB RTX 3060, llama-coder); tell Claude if the
                 new PC is different.

llama-coder/     The launcher script and systemd unit of the local AI server Clippy uses to pick
                 clips. They expect llama.cpp in ~/.local/opt/llama.cpp/current/ and the model in
                 ~/models/. Neither is packed (big, GPU-specific). See MOVING.md, "The AI server".
"""


class Packer:
    def __init__(self, path: Path):
        self.path = path
        self.tmp = path.with_name(path.name + ".part")
        self.zf = zipfile.ZipFile(self.tmp, "w", allowZip64=True)
        self.files = 0
        self.bytes = 0

    def add(self, src: Path, rel: Path):
        arc = f"{TOP}/{rel.as_posix()}"
        if src.is_symlink():
            zi = zipfile.ZipInfo(arc, time.localtime(src.lstat().st_mtime)[:6])
            zi.create_system = 3
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            self.zf.writestr(zi, os.readlink(src))
        else:
            method = zipfile.ZIP_STORED if src.suffix.lower() in NO_COMPRESS else zipfile.ZIP_DEFLATED
            self.zf.write(src, arc, compress_type=method, compresslevel=None if method == zipfile.ZIP_STORED else 6)
            self.bytes += src.stat().st_size
        self.files += 1

    def add_text(self, rel: str, text: str):
        zi = zipfile.ZipInfo(f"{TOP}/{rel}", time.localtime()[:6])
        zi.create_system = 3
        zi.external_attr = 0o644 << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        self.zf.writestr(zi, text)
        self.files += 1

    def finish(self, verify: bool):
        self.zf.close()
        if verify:
            with zipfile.ZipFile(self.tmp) as z:
                bad = z.testzip()                   # re-reads every byte and checks the CRCs
            if bad:
                raise SystemExit(f"✗ {self.path.name} is damaged at {bad}; nothing was replaced")
        os.replace(self.tmp, self.path)


def gb(n: float) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.1f} MB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dest", type=Path, default=ROOT.parent, help="where to put the zips (default: next to Clippy)")
    ap.add_argument("--no-extras", action="store_true", help="only make Clippy.zip")
    ap.add_argument("--no-verify", action="store_true", help="skip the read-back CRC check")
    a = ap.parse_args()
    a.dest.mkdir(parents=True, exist_ok=True)
    if a.dest.resolve().is_relative_to(ROOT):
        raise SystemExit("--dest must be outside the Clippy folder")

    main_zip, extras = Packer(a.dest / "Clippy.zip"), None if a.no_extras else Packer(a.dest / "Clippy-extras.zip")
    print(f"Packing {ROOT} …")
    for src, rel in project_files():
        if is_extra(rel):
            if extras:
                extras.add(src, rel)
        else:
            main_zip.add(src, rel)
    kit = list(move_kit_files())
    for src, rel in kit:
        main_zip.add(src, rel)
    main_zip.add_text("move-kit/README.txt", MOVE_KIT_README)

    for p in (main_zip, extras):
        if p:
            print(f"  writing {p.path.name}: {p.files} files, {gb(p.bytes)} …" + ("" if a.no_verify else " (then checking it)"))
            p.finish(verify=not a.no_verify)
            print(f"  ✓ {p.path}  ({gb(p.path.stat().st_size)})")
    print(f"  move-kit: {sum(1 for _, r in kit if 'claude-memory' in r.parts)} Claude memory note(s), "
          f"{'llama-coder launcher' if any('llama-coder' in r.parts for _, r in kit) else 'no llama-coder launcher found'}")
    print("\nOn the new PC: unzip Clippy.zip (and Clippy-extras.zip into the same place), then:\n"
          "    cd Clippy && bash setup.sh\nFull guide: MOVING.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
