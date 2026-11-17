"""Settings. Defaults live here; override them in config.toml, env vars (CLIPPY_<NAME>) or per job."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    # ── AI that picks the clips (any OpenAI-compatible server: llama.cpp, Ollama, Groq, Gemini…)
    llm_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = ""            # empty = whatever model the server has loaded
    llm_api_key: str = ""
    llm_thinking: bool = False     # let the model "think" first (slower, sometimes smarter)
    llm_chunk_chars: int = 60000   # transcript size per request (~15k tokens)

    # ── GPU
    llama_service: str = "llama-coder"   # systemd --user service to pause while Whisper uses the GPU ("" = never)
    free_gpu_for_whisper: bool = True
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "auto"         # auto | cuda | cpu

    # ── Download
    max_height: int = 1440            # 1440p gives sharper 9:16 crops than 1080p
    auto_cleanup_days: int = 0           # delete downloaded source videos after N days without activity (0 = never)

    # ── Clips
    clips: int = 5
    min_seconds: int = 20
    max_seconds: int = 60

    # ── Look
    caption_style: str = "beast"         # beast | hormozi | box | clean
    caption_scale: float = 1.0           # bigger/smaller captions
    caption_color: str = "#FFFFFF"
    highlight_color: str = "#FFE135"     # the word being spoken
    emphasis_color: str = "#3DFF7A"      # key words picked by the AI
    words_per_caption: int = 0           # 0 = style default
    caption_y: float = 0.68              # 0 = top, 1 = bottom
    title_seconds: float = 3.5           # hook title at the top: seconds shown (0 = off, -1 = whole clip)
    title_scale: float = 1.0
    emojis: bool = True                  # AI-picked emojis pop above the captions
    progress_bar: bool = True

    # ── Editing / energy
    teaser: bool = True                  # flash-forward: open with the clip's best line, whoosh, then start
    motion: bool = True                  # intro slam, slow push-ins, zoom punches on key words
    punch_in: bool = True                # zoom alternation on jump cuts
    sfx: bool = True                     # whoosh / pop / impact sound effects
    sfx_volume: float = 1.0
    split_screen: bool = True            # two people in a wide shot -> stack them
    voice_polish: bool = True            # trim low rumble + gentle compression so voices sound clear on phones
    speech: str = "auto"                 # auto = detect talking | on = always use the transcript | off = no talking, skip Whisper
    remove_silences: bool = True
    max_pause: float = 0.45              # pauses longer than this get cut (lower = faster pacing)
    loudness: float = -14.0              # LUFS, what TikTok/Shorts/Reels normalize to
    video_quality: int = 19              # NVENC CQ / x264 CRF (lower = better, bigger)
    output_dir: str = "output"

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce(value, current):
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(current, int):
        return int(float(value))
    if isinstance(current, float):
        return float(value)
    return str(value)


def settings_file() -> Path:
    """Where the app's Settings page saves its choices (overridable so tests never touch the real one)."""
    return Path(os.environ.get("CLIPPY_SETTINGS_FILE") or ROOT / "settings.json")


def _read_ui_settings() -> dict:
    try:
        data = json.loads(settings_file().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ui_settings(changes: dict) -> "Settings":
    """Validate and store settings chosen in the app. Unknown keys reject the whole change."""
    defaults = Settings()
    names = {f.name for f in fields(Settings)}
    unknown = [k for k in changes if k not in names]
    if unknown:
        raise ValueError("Unknown setting: " + ", ".join(sorted(unknown)))
    merged = {**_read_ui_settings(), **{k: _coerce(v, getattr(defaults, k)) for k, v in changes.items()}}
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    os.replace(tmp, path)
    return load()


def load(overrides: dict | None = None) -> Settings:
    s = Settings()
    names = {f.name for f in fields(Settings)}
    cfg_file = ROOT / "config.toml"
    layers: list[dict] = []
    if cfg_file.exists():
        layers.append(tomllib.loads(cfg_file.read_text()))
    layers.append(_read_ui_settings())  # saved from the app's Settings page
    layers.append({k[7:].lower(): v for k, v in os.environ.items() if k.startswith("CLIPPY_")})
    if overrides:
        layers.append({k: v for k, v in overrides.items() if v is not None and v != ""})
    for layer in layers:
        for k, v in layer.items():
            if k in names:
                setattr(s, k, _coerce(v, getattr(s, k)))
    return s


# Clippy's own data folders inside output/. Everything else is a project (one per source video) —
# note real YouTube ids can start with "_" or "-", so a name prefix can't tell them apart.
INTERNAL_DIRS = frozenset({"_auto", "_finder"})


def output_root(s: Settings) -> Path:
    p = Path(s.output_dir)
    return p if p.is_absolute() else ROOT / p
