"""Saved editing styles: a named look a creator reuses, like clean captions and calm edits for a podcast, or bright
captions and strong effects for a gaming channel. Make Clips, Find a Quote and Autopilot channels all use the same
styles: a job names one ("preset": id) and expand() turns it into the settings it holds. What a job sets itself
still wins, and each short remembers the expanded settings, so a style changed later doesn't change old shorts.

Stored in presets.json next to the app's settings file, so styles move with the settings."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import config

# the look and the edit: settings Clippy already has, but not what to pick (clip count, length, format)
KEYS = ("caption_style", "caption_scale", "caption_color", "highlight_color", "emphasis_color", "words_per_caption",
        "caption_y", "title_seconds", "title_scale", "emojis", "progress_bar", "teaser", "motion", "punch_in", "sfx",
        "sfx_volume", "split_screen", "voice_polish", "remove_silences", "max_pause")
COLORS = ("caption_color", "highlight_color", "emphasis_color")
LOCK = threading.Lock()


class PresetError(ValueError):
    """Said to the person saving a style."""


def path() -> Path:
    return config.settings_file().with_name("presets.json")


def _read() -> list[dict]:
    try:
        data = json.loads(path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, dict) and p.get("id") and isinstance(p.get("settings"), dict)] \
        if isinstance(data, list) else []


def _write(items: list[dict]) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    config.write_atomic(path(), json.dumps(items, ensure_ascii=False, indent=2))


def list_presets() -> list[dict]:
    return sorted(_read(), key=lambda p: p["name"].lower())


def get(pid: str) -> dict | None:
    return next((p for p in _read() if p["id"] == pid), None)


def clean(settings: dict) -> dict:
    """Only style settings, each the right kind of value."""
    defaults = config.Settings()
    out = {}
    for k, v in (settings or {}).items():
        if k not in KEYS or v is None:
            continue
        try:
            v = config._coerce(v, getattr(defaults, k))
        except (TypeError, ValueError):
            raise PresetError(f"{k} isn't a valid value for a style.") from None
        if k in COLORS and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(v)):
            raise PresetError("Colors look like #FFE135.")
        out[k] = v
    return out


def save(name: str, settings: dict, pid: str | None = None) -> dict:
    """Create or update a style. Saving under a name that exists updates that style. Settings it doesn't name come
    from the current settings, so every style is complete."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:40]
    if not name:
        raise PresetError("Give the style a name, like Podcast or Gaming.")
    with LOCK:
        items = _read()
        same = next((p for p in items if p["name"].lower() == name.lower()), None)
        if pid and not any(p["id"] == pid for p in items):
            raise PresetError("That style was deleted.")
        if pid and same and same["id"] != pid:
            raise PresetError(f"There's already a style called “{same['name']}”.")
        pid = pid or (same["id"] if same else uuid.uuid4().hex[:8])
        old = next((p for p in items if p["id"] == pid), None)
        current = config.load()
        base = old["settings"] if old else {k: getattr(current, k) for k in KEYS}
        preset = {"id": pid, "name": name, "settings": {**base, **clean(settings)},
                  "created": old.get("created", time.time()) if old else time.time(), "updated": time.time()}
        _write([p for p in items if p["id"] != pid] + [preset])
        return preset


def delete(pid: str) -> None:
    with LOCK:
        _write([p for p in _read() if p["id"] != pid])


def expand(overrides: dict | None) -> dict:
    """A job's settings with its style filled in: the style first, then what the job sets itself."""
    overrides = dict(overrides or {})
    pid = overrides.get("preset")
    if not pid:
        return overrides
    p = get(str(pid))
    if p is None:                                    # deleted since: the job's own settings still apply
        overrides.pop("preset", None)
        return overrides
    return {**clean(p["settings"]), **overrides, "preset_name": p["name"]}
