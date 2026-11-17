"""URL in → finished clips out."""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from . import config
from .download import cached_info, download, probe, video_stream_info
from .highlights import has_speech, pick_visual_clips, speech_stats
from .picker import pick_clips
from .render import render_clip
from .transcribe import audio_only, transcribe

STAGES = [("download", 0.10), ("transcribe", 0.25), ("pick", 0.20), ("render", 0.45)]


def _slug(t: str) -> str:
    s = re.sub(r"[^\w\s-]", "", t.lower(), flags=re.U)
    return re.sub(r"[\s_-]+", "-", s).strip("-")[:40] or "clip"


class Progress:
    def __init__(self, cb):
        self.cb = cb

    def stage(self, name: str):
        before = 0.0
        for n, w in STAGES:
            if n == name:
                return lambda p, msg="": self.cb(name, before + w * max(0.0, min(1.0, p)), msg)
            before += w
        return lambda p, msg="": self.cb(name, p, msg)


def run(url: str, overrides: dict | None = None, on_progress=lambda stage, pct, msg: None, log=print,
        on_info=None) -> dict:
    cfg = config.load(overrides)
    reuse = bool((overrides or {}).get("reuse_picks"))
    pr = Progress(on_progress)
    t_start = time.time()

    p = pr.stage("download")
    p(0, "Reading link…")
    try:
        info = probe(url.strip())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        info = cached_info(url.strip(), config.output_root(cfg))
        if not info:
            raise
        log(f"  YouTube didn't answer ({str(e)[:120]}); using the copy downloaded earlier")
    if on_info:
        on_info(info)
    log(f"▶ {info['title']}  ({info['duration'] / 60:.1f} min)")
    workdir = config.output_root(cfg) / info["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2))
    src = download(url.strip(), info, workdir, cfg.max_height, progress=p)
    vinfo = video_stream_info(src)
    log(f"  source {vinfo['width']}x{vinfo['height']} @ {vinfo['fps']:.2f} fps")

    p = pr.stage("transcribe")
    if cfg.speech == "off":
        log("  no-talking mode: skipping transcription")
        tr = audio_only(src, workdir, progress=p)
    else:
        tr = transcribe(cfg, src, workdir, progress=p, log=log)
    env_file = workdir / "envelope.npy"
    env = np.load(env_file) if env_file.exists() else None
    visual = cfg.speech == "off" or (cfg.speech == "auto" and not has_speech(tr))
    if visual and cfg.speech == "auto":
        n, cover, _ = speech_stats(tr)
        log(f"  no real talking found ({n} words, {cover:.0%} speech) → picking clips from sound, action and replays")

    p = pr.stage("pick")
    picks_file = workdir / "picks.json"
    if reuse and picks_file.exists():
        clips = json.loads(picks_file.read_text())
        visual = bool(clips) and all(c.get("mode") == "visual" for c in clips)
        p(1, "Reusing previous picks")
    else:
        if visual:
            clips = pick_visual_clips(cfg, info, src, vinfo, env, progress=p, log=log)
        else:
            clips = pick_clips(cfg, info, tr, progress=p, log=log, env=env)
        picks_file.write_text(json.dumps(clips, ensure_ascii=False, indent=2))

    # no talking: no captions, keep the music untouched, keep every frame, show the hook title the whole time
    rcfg = dataclasses.replace(cfg, voice_polish=False, remove_silences=False,
                               title_seconds=-1 if cfg.title_seconds != 0 else 0) if visual else cfg
    words = [] if visual else tr["words"]

    p = pr.stage("render")
    out_dir = workdir / re.sub(r"[^\w-]", "", str((overrides or {}).get("clips_dir") or "clips"))
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*"):
        if old.is_file():
            old.unlink()
    results = []
    for i, clip in enumerate(clips):
        name = f"{i + 1:02d}-{_slug(clip.get('title') or 'clip')}.mp4"
        out = out_dir / name
        log(f"  rendering {name}")
        sub = lambda q, msg="", i=i: p((i + q) / len(clips), f"Clip {i + 1}/{len(clips)}: {msg}")
        stats = render_clip(rcfg, src, vinfo, clip, words, env, out, progress=sub, log=log)
        results.append({**{k: clip.get(k) for k in ("title", "caption", "hashtags", "score", "why", "start", "end")},
                        **stats, "file": str(out.relative_to(config.output_root(cfg))),
                        "thumb": str(out.with_suffix(".jpg").relative_to(config.output_root(cfg)))})

    summary = {"id": info["id"], "title": info["title"], "url": info.get("webpage_url", url),
               "uploader": info.get("uploader", ""), "language": tr.get("language"),
               "mode": "visual" if visual else "speech",
               "transcribed_on": tr.get("device"), "created": int(time.time()),
               "seconds": round(time.time() - t_start), "clips": results}
    (workdir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    on_progress("done", 1.0, f"{len(results)} clips ready")
    return summary
