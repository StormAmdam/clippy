"""Watch one recording folder: every new recording that lands there becomes shorts, made with a saved style.

- Only finished recordings: a file counts once its size and time have stayed the same for a minute (a recorder
  or a copy still writing it changes them), it isn't named like a partial download, and it can be opened.
- Never twice: each recording is remembered by name, size and time in output/_watch.json, also across restarts.
  The same name with new content (OBS's "Replay.mp4" again) is a new recording.
- Recordings already in the folder when it's chosen are left alone: only new ones are made into shorts.
- Each one is brought in like an upload (output/up-<fingerprint>/, a hard link where possible, else a copy), so two
  recordings with the same name never share a transcript, and the original can be moved or deleted afterwards."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from . import config, uploads

STABLE = 60.0              # seconds a recording's size and time must stay the same before it counts as finished
POLL = 20.0                # seconds between looks at the folder
RETRY = 300.0              # a recording that couldn't be brought in is tried again after this long…
TRIES = 5                  # …this many times (disk full, tools missing), then it's left alone
PARTIAL = (".part", ".tmp", ".crdownload", ".download", ".partial", ".!ut")
_pending: dict[str, tuple[int, float, float]] = {}       # path -> (size, mtime, unchanged since)
_wait_until: dict[str, float] = {}                        # path -> don't try before (after a failure)


class WatchError(ValueError):
    """Said to the person choosing the folder."""


def _state_file() -> Path:
    return config.output_root(config.load()) / "_watch.json"


def _read_state() -> dict:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    _state_file().parent.mkdir(parents=True, exist_ok=True)
    config.write_atomic(_state_file(), json.dumps(state, ensure_ascii=False, indent=1))


def check_folder(path: str) -> Path | None:
    """The folder to watch, or None for "don't watch"; WatchError says what's wrong with it."""
    path = str(path or "").strip().strip('"')
    if not path:
        return None
    d = Path(path).expanduser()
    if not d.is_dir():
        raise WatchError(f"Clippy can't find the folder {path}. Check the spelling, or copy it from the address bar "
                         "of a folder window.")
    out = config.output_root(config.load()).resolve()
    dd = d.resolve()
    if dd == out or out in dd.parents or dd in out.parents:
        raise WatchError("Pick a folder outside Clippy's own folder for your shorts.")
    return d


def _recording(f: Path) -> bool:
    n = f.name.lower()
    return f.suffix.lower() in uploads.VIDEO_EXT and not n.startswith((".", "~")) and not n.endswith(PARTIAL)


def _key(f: Path, st: os.stat_result) -> str:
    return f"{f.name}|{st.st_size}|{int(st.st_mtime)}"


def _import(f: Path) -> dict:
    """Bring a recording into Clippy like an upload: output/up-<fingerprint>/source.<ext>."""
    out = config.output_root(config.load())
    ext = uploads.check(f.name, f.stat().st_size, out)
    part = uploads.part_file(out, ext)
    try:
        os.link(f, part)                                  # same disk: no copy, no extra space
    except OSError:
        shutil.copy2(f, part)
    h = hashlib.sha1()
    with open(part, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    try:
        return uploads.finish(part, f.name, h.hexdigest(), out)
    finally:
        part.unlink(missing_ok=True)                      # the same recording again: the earlier copy is used


def scan_once(queue_job, now: float | None = None, log=print, job_state=None) -> list[str]:
    """One look at the folder. queue_job(path, title, preset) starts making shorts. Returns the files queued.
    job_state(job id) → its state: a job Clippy was closed in the middle of is queued again."""
    cfg = config.load()
    try:
        d = check_folder(cfg.watch_folder)
    except WatchError:
        return []
    if d is None:
        return []
    now = time.time() if now is None else now
    state = _read_state()
    seen = state.setdefault("seen", {})
    files = [f for f in sorted(d.iterdir()) if f.is_file() and _recording(f)]
    if state.get("folder") != str(d.resolve()):           # a new folder: what's there already stays untouched
        for f in files:
            try:
                seen[_key(f, f.stat())] = {"file": f.name, "at": now, "skipped": "was there before"}
            except OSError:
                pass
        state["folder"] = str(d.resolve())
        _write_state(state)
        return []
    queued = []
    if job_state is not None:                          # closed while making shorts from a recording: again
        for v in seen.values():
            if v.get("job") and v.get("path") and job_state(v["job"]) == "interrupted" and Path(v["path"]).exists():
                v["job"] = queue_job(v["path"], v.get("title") or Path(v["path"]).stem, cfg.watch_preset)
                _write_state(state)
                log(f"  watch folder: {v.get('file')} was interrupted when Clippy closed; making its shorts again")
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        key = _key(f, st)
        if key in seen or st.st_size == 0 or now < _wait_until.get(str(f), 0):
            continue
        sig = (st.st_size, st.st_mtime)
        prev = _pending.get(str(f))
        if prev is None or prev[:2] != sig:
            _pending[str(f)] = (*sig, now)                # new, or still growing: look again later
            continue
        if now - prev[2] < STABLE:
            continue
        try:
            with open(f, "rb"):                           # a recorder still holding it (Windows) can't be read yet
                pass
        except OSError:
            continue                                      # not finished after all: look again next time
        try:
            item = _import(f)
        except (OSError, uploads.UploadError) as e:
            fails = state.setdefault("failed", {})
            fails[key] = fails.get(key, 0) + 1
            if fails[key] >= TRIES:                       # tried enough: leave it, and say why in Settings
                seen[key] = {"file": f.name, "at": now, "error": str(e)[:200]}
                log(f"  watch folder: gave up on {f.name}: {e}")
            else:
                _wait_until[str(f)] = now + RETRY
                log(f"  watch folder: couldn't bring in {f.name} ({e}); trying again in a few minutes")
            _write_state(state)
            continue
        jid = queue_job(item["path"], item["title"], cfg.watch_preset)
        state.get("failed", {}).pop(key, None)
        seen[key] = {"file": f.name, "at": now, "video": item["id"], "job": jid, "path": item["path"],
                     "title": item["title"]}
        _pending.pop(str(f), None)
        _write_state(state)
        queued.append(f.name)
        log(f"  watch folder: {f.name} is ready, making shorts")
    return queued


def status() -> dict:
    """What Settings shows: the folder, and the recordings it made shorts from lately."""
    cfg = config.load()
    try:
        d, problem = check_folder(cfg.watch_folder), ""
    except WatchError as e:
        d, problem = None, str(e)
    seen = _read_state().get("seen", {})
    recent = sorted((v for v in seen.values() if not v.get("skipped")), key=lambda v: -v.get("at", 0))[:5]
    return {"folder": cfg.watch_folder, "watching": d is not None, "problem": problem, "preset": cfg.watch_preset,
            "waiting": [Path(p).name for p in _pending if Path(p).parent == d] if d else [], "recent": recent}
