"""URL in → finished clips out."""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np

from . import config, extensions
from .download import cached_info, download, have_tools, install_hint, probe, video_stream_info
from .highlights import has_speech, pick_visual_clips, speech_stats
from .picker import pick_clips
from .render import render_clip
from .storage import FileInUse, remove_file
from .transcribe import audio_only, transcribe

STAGES = [("download", 0.10), ("transcribe", 0.25), ("pick", 0.20), ("render", 0.45)]


def _slug(t: str) -> str:
    s = re.sub(r"[^\w\s-]", "", t.lower(), flags=re.U)
    return re.sub(r"[\s_-]+", "-", s).strip("-")[:40] or "clip"


def _looks_like_a_file(url: str) -> bool:
    return bool(re.match(r"^([A-Za-z]:[\\/]|[\\/]|~|\.\.?[\\/])", url)) and "://" not in url


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


SIDECAR = ".clip.json"      # next to each short: the pick and settings it was made with (clippy/quickfix.py)


def sidecar(out: Path) -> Path:
    return out.with_name(out.stem + SIDECAR)


def render_settings(cfg, visual: bool, countdown: bool):
    """The settings a short renders with. No talking: no captions, the music untouched, every frame kept, the hook
    title the whole time. A countdown builds up by itself, so no teaser."""
    rcfg = dataclasses.replace(cfg, voice_polish=False, remove_silences=False,
                               title_seconds=-1 if cfg.title_seconds != 0 else 0) if visual else cfg
    return dataclasses.replace(rcfg, teaser=False) if countdown else rcfg


def run(url: str, overrides: dict | None = None, on_progress=lambda stage, pct, msg: None, log=print,
        on_info=None) -> dict:
    from . import presets
    overrides = presets.expand(overrides)               # a saved style: its settings, then the job's own
    cfg = config.load(overrides)
    local = Path(url.strip()).expanduser().exists()
    if not local and _looks_like_a_file(url.strip()):
        raise RuntimeError(f"Clippy can't find the video file {url.strip()} anymore. "
                           "If it was uploaded, upload it again.")
    if missing := [t for t in have_tools() if not (t == "yt-dlp" and local)]:
        raise RuntimeError(f"Clippy's video tools ({', '.join(missing)}) aren't set up yet. {install_hint()}")
    reuse = bool((overrides or {}).get("reuse_picks")) and not cfg.focus   # a new instruction needs new picks
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
    config.write_atomic(workdir / "info.json", json.dumps(info, ensure_ascii=False, indent=2))
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

    from . import vision
    p = pr.stage("pick")
    countdown = cfg.format == "top"
    picks_file = workdir / ("picks-top.json" if countdown else "picks.json")
    needs_ai = not visual and not (reuse and picks_file.exists())   # picking uses the AI anyway
    eyes = vision.eyes_for(cfg, log, start=needs_ai)    # None unless the AI can see (and it's allowed)
    if reuse and picks_file.exists():
        clips = json.loads(picks_file.read_text(encoding="utf-8"))
        visual = bool(clips) and all(c.get("mode") == "visual" for c in clips)
        p(1, "Reusing previous picks")
    else:
        if countdown:
            from . import top
            if visual:
                many = dataclasses.replace(cfg, clips=max(cfg.top_count * 2, 4), min_seconds=cfg.top_min,
                                           max_seconds=cfg.top_max)
                clips = [top.from_visual(cfg, pick_visual_clips(many, info, src, vinfo, env, progress=p, log=log))]
            else:
                clips = [top.pick_top(cfg, info, tr, progress=p, log=log, env=env)]
        elif visual:
            clips = pick_visual_clips(vision.with_extra(cfg, eyes), info, src, vinfo, env, progress=p, log=log)
            clips = vision.rerank(eyes, clips, src, cfg.clips, log)      # a few extra, the best-looking kept
        else:                                           # rated before finalizing: no wasted finishing passes
            clips = pick_clips(cfg, info, tr, progress=p, log=log, env=env, rank=vision.ranker(eyes, src, log))
        config.write_atomic(picks_file, json.dumps(clips, ensure_ascii=False, indent=2))

    rcfg = render_settings(cfg, visual, countdown)
    words = [] if visual else tr["words"]
    made_with = {k: v for k, v in (overrides or {}).items() if k != "reuse_picks"}

    p = pr.stage("render")
    out_dir = workdir / re.sub(r"[^\w-]", "", str((overrides or {}).get("clips_dir") or
                                                   ("clips-top" if countdown else "clips")))
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*"):
        if old.is_file():
            try:
                remove_file(old)
            except FileInUse:
                raise RuntimeError(f"Couldn't replace the earlier short {old.name}: it's open in another program "
                                   "(a video player, perhaps). Close it and try again.") from None
    results = []
    # while one clip renders, the next one is planned (faces, cuts, the AI's look at its shots): same shorts, sooner
    import threading
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    from .jobs import Cancelled
    from .render import plan
    ahead = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plan-next")
    stop_ahead = threading.Event()

    def ahead_progress(q, msg=""):                      # the look-ahead stops at its next step after a cancel
        if stop_ahead.is_set():
            raise Cancelled()
    plan_of = lambda c: ahead.submit(plan, rcfg, src, vinfo, c, words, env, eyes, log, ahead_progress)
    nxt = None
    try:
        for i, clip in enumerate(clips):
            sub = lambda q, msg="", i=i: p((i + q) / len(clips), f"Clip {i + 1}/{len(clips)}: {msg}")
            parts = None                                # the first clip plans here, with progress and Cancel
            if nxt is not None:
                while True:
                    try:
                        parts = nxt.result(timeout=1)
                        break
                    except FutureTimeout:
                        sub(0.0, "Finding faces & camera cuts…")    # Cancel works while it's still being planned
            nxt = plan_of(clips[i + 1]) if i + 1 < len(clips) else None
            name = f"{_slug(clip.get('title') or 'top')}.mp4" if countdown else \
                f"{i + 1:02d}-{_slug(clip.get('title') or 'clip')}.mp4"
            out = out_dir / name
            log(f"  rendering {name}")
            stats = render_clip(rcfg, src, vinfo, clip, words, env, out, progress=sub, log=log, eyes=eyes, parts=parts)
            config.write_atomic(sidecar(out), json.dumps({"pick": clip, "overrides": made_with, "visual": visual,
                                                          "countdown": countdown}, ensure_ascii=False))
            extra = {"format": "top", "ranks": [{"rank": s["rank"], "label": s["label"], "start": s["start"],
                                                "end": s["end"]} for s in clip["segments"]]} if clip.get("segments") else {}
            results.append({**{k: clip.get(k) for k in ("title", "caption", "hashtags", "score", "why", "start", "end",
                                                         "look", "look_why")},
                            **stats, **extra, "file": str(out.relative_to(config.output_root(cfg))),
                            "thumb": str(out.with_suffix(".jpg").relative_to(config.output_root(cfg)))})
            extensions.run_hook("clip_rendered", log=log, path=out, clip=dict(results[-1]), video=dict(info))
    finally:                                            # a failed or cancelled render: the look-ahead stops
        stop_ahead.set()
        ahead.shutdown(wait=False, cancel_futures=True)

    summary = {"id": info["id"], "title": info["title"], "url": info.get("webpage_url", url),
               "uploader": info.get("uploader", ""), "language": tr.get("language"),
               "mode": "visual" if visual else "speech",
               "transcribed_on": tr.get("device"), "created": int(time.time()),
               "seconds": round(time.time() - t_start), "clips": results}
    # the Library shows every short of this video: keep earlier ones from other folders (countdown, Autopilot…)
    root, mine = config.output_root(cfg), out_dir.relative_to(config.output_root(cfg)).as_posix() + "/"
    try:
        earlier = json.loads((workdir / "result.json").read_text(encoding="utf-8")).get("clips") or []
    except (OSError, ValueError, AttributeError):
        earlier = []
    kept = [c for c in earlier if isinstance(c, dict) and not str(c.get("file", "")).replace("\\", "/").startswith(mine)
            and (root / str(c.get("file", ""))).is_file()]
    config.write_atomic(workdir / "result.json",
                        json.dumps({**summary, "clips": results + kept}, ensure_ascii=False, indent=2))
    extensions.run_hook("video_done", log=log, result=dict(summary), folder=workdir)
    on_progress("done", 1.0, f"{len(results)} clips ready")
    return summary
