"""Quick fixes for a finished short, without another editor: move where it starts and ends, correct caption words
(each keeps its timing) and the hook title, then render only that short again.

Everything is in the source video's time: start and end are seconds into the source, like the AI's picks, and
cutting pauses or the teaser happen inside that range when it renders, the same as the first time. Nothing is
picked again and the other shorts aren't touched. The new render gets its own name (01-title-r2.mp4), so the current
short stays playable until it's ready; then the Library and Review point at the new one and the old one goes."""
from __future__ import annotations

import copy
import json
import re
import threading
import time
from pathlib import Path

from . import config
from .storage import FileInUse, remove_file

MIN_SECONDS, MAX_SECONDS = 3.0, 180.0         # YouTube Shorts can be up to 3 minutes
CONTEXT = 30.0                                # transcript shown around the short, seconds each side
REV = re.compile(r"-r(\d+)$")


class FixError(RuntimeError):
    """Said to the person fixing the short."""


def _root() -> Path:
    return config.output_root(config.load())


def _norm(file: str) -> str:
    return str(file).replace("\\", "/")


def _short(file: str) -> Path:
    root = _root().resolve()
    p = (root / _norm(file)).resolve()
    try:
        rel = p.relative_to(root)
    except ValueError:
        raise FixError("That isn't one of Clippy's shorts.") from None
    if p.suffix.lower() != ".mp4" or len(rel.parts) != 3 or not rel.parts[1].startswith("clips") \
            or rel.parts[0] in config.INTERNAL_DIRS:
        raise FixError("That isn't one of Clippy's shorts.")
    if not p.is_file():
        raise FixError("This short isn't there anymore (it was deleted or replaced).")
    return p


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def words_in(words: list[dict], start: float, end: float) -> tuple[int, int]:
    """The words that fall inside start–end, as (i0, i1) like the AI's picks."""
    idx = [i for i, w in enumerate(words) if w["s"] >= start - 0.05 and w["e"] <= end + 0.05]
    if idx:
        return idx[0], idx[-1] + 1
    i = next((i for i, w in enumerate(words) if w["s"] >= start), len(words))
    return i, i


def _profile_overrides(folder: str) -> dict:
    """An Autopilot short made before shorts remembered their settings: its channel's look."""
    if not folder.startswith("clips-"):
        return {}
    try:
        from . import autopilot
        p = autopilot.get_profile(folder[len("clips-"):])
    except (KeyError, OSError, ValueError):
        return {}
    return {k: p[k] for k in ("caption_style", "highlight_color") if p.get(k)}


def load(file: str) -> dict:
    """Everything about one short: its pick, the settings it was made with, the transcript and its earlier fixes."""
    from .pipeline import sidecar
    out = _short(file)
    root, workdir = _root(), out.parent.parent
    words = (_read(workdir / "transcript.json", {}) or {}).get("words") or []
    result = _read(workdir / "result.json", {}) or {}
    me = _norm(out.relative_to(root.resolve()))
    entry = next((c for c in result.get("clips") or [] if isinstance(c, dict) and _norm(c.get("file", "")) == me), {})
    side = _read(sidecar(out), None)
    if isinstance(side, dict) and isinstance(side.get("pick"), dict):
        pick, overrides = side["pick"], side.get("overrides") or {}
        visual, countdown, edits = bool(side.get("visual")), bool(side.get("countdown")), side.get("edits") or {}
    else:                                       # made before shorts remembered their pick
        countdown = entry.get("format") == "top" or out.parent.name.startswith("clips-top")
        picks = _read(workdir / ("picks-top.json" if countdown else "picks.json"), []) or []
        s, e = entry.get("start"), entry.get("end")
        pick = next((c for c in picks if isinstance(c, dict) and s is not None and e is not None
                     and abs(c.get("start", -1) - s) < 0.05 and abs(c.get("end", -1) - e) < 0.05), None)
        if pick is None and countdown and len(picks) == 1:
            pick = picks[0]
        if pick is None:
            if s is None or e is None:
                raise FixError("Clippy doesn't know where this short came from in the video, so it can't fix it. "
                               "Make shorts from the video again.")
            i0, i1 = words_in(words, s, e)
            pick = {"start": s, "end": e, "i0": i0, "i1": i1, "title": entry.get("title") or ""}
        overrides = {"clips_dir": out.parent.name, **_profile_overrides(out.parent.name)}
        visual, edits = result.get("mode") == "visual", {}
    return {"out": out, "rel": me, "root": root, "workdir": workdir, "words": words, "pick": pick, "entry": entry,
            "result": result, "overrides": overrides, "visual": visual, "countdown": countdown, "edits": edits}


def _source(workdir: Path) -> Path | None:
    from .uploads import VIDEO_EXT                       # every kind an upload or a watched recording can be
    return next((f for f in sorted(workdir.glob("source.*")) if f.suffix.lower() in VIDEO_EXT and f.is_file()), None)


def info(file: str) -> dict:
    """What the Quick Fix editor shows: where the short sits in the source, the words around it, earlier fixes."""
    d = load(file)
    pick, words, fixed = d["pick"], d["words"], (d["edits"].get("words") or {})
    s, e = float(pick["start"]), float(pick["end"])
    vinfo = _read(d["workdir"] / "info.json", {}) or {}
    src = _source(d["workdir"])
    kind = "countdown" if pick.get("segments") else "visual" if d["visual"] else "speech"
    lo, hi = s - CONTEXT, e + CONTEXT
    if kind == "countdown":
        lo = min(m["start"] for m in pick["segments"]) - 2
        hi = max(m["end"] for m in pick["segments"]) + 2
    ctx = [{"i": i, "w": fixed.get(str(i), w["w"]), "orig": w["w"], "s": w["s"], "e": w["e"]}
           for i, w in enumerate(words) if w["e"] >= lo and w["s"] <= hi] if kind != "visual" else []
    url = str(vinfo.get("webpage_url") or d["result"].get("url") or "")
    tz = pick.get("teaser") if not d["countdown"] else None
    return {"file": d["rel"], "title": pick.get("title") or d["entry"].get("title") or "", "kind": kind,
            "start": s, "end": e, "i0": pick.get("i0", 0), "i1": pick.get("i1", 0),
            "duration": float(vinfo.get("duration") or (words[-1]["e"] if words else e)),
            "words": ctx, "fixed": fixed,
            "segments": [{"start": m["start"], "end": m["end"], "label": m.get("label", "")}
                         for m in pick.get("segments") or []],
            "teaser": {"start": tz["start"], "end": tz["end"]} if isinstance(tz, dict) and tz.get("end") else None,
            "source": _norm(src.relative_to(d["root"].resolve())) if src and src.is_relative_to(d["root"].resolve())
            else None, "redownload": src is None and url.startswith(("http://", "https://")),
            "short_duration": d["entry"].get("duration")}


def _ensure_source(workdir: Path, vinfo: dict, result: dict, overrides: dict, progress, log, what: str):
    """(source video, share of the progress bar its download took): a deleted YouTube download comes back."""
    from .download import download
    src = _source(workdir)
    if src is not None:
        return src, 0.0
    url = str(vinfo.get("webpage_url") or result.get("url") or "")
    if not url.startswith(("http://", "https://")):
        raise FixError(f"The original video isn't on this PC anymore (it was deleted), so {what}. "
                       "Upload the video again and make new shorts from it.")
    log("  the download was deleted earlier; downloading the video again")
    src = download(url, vinfo, workdir, config.load(overrides).max_height,
                   progress=lambda p, m="": progress(0.3 * p, m or "Downloading the video again…"))
    return src, 0.3


def _next_name(out: Path) -> Path:
    m = REV.search(out.stem)
    base, n = (out.stem[:m.start()], int(m.group(1)) + 1) if m else (out.stem, 2)
    while (cand := out.with_name(f"{base}-r{n}.mp4")).exists():
        n += 1
    return cand


def _remove_later(paths: list[Path]) -> None:
    """The old render goes once nothing has it open (on Windows, the app window may still be playing it)."""
    def go():
        for _ in range(30):
            left = []
            for p in paths:
                try:
                    remove_file(p)
                except FileInUse:
                    left.append(p)
            if not left:
                return
            paths[:] = left
            time.sleep(2)
    threading.Thread(target=go, daemon=True, name="remove-old-short").start()


def apply(file: str, start: float | None = None, end: float | None = None, words: dict | None = None,
          title: str | None = None, progress=lambda p, m="": None, log=print) -> dict:
    """Render the short again with these fixes. Returns its new file, thumbnail and length."""
    import numpy as np

    from . import autopilot, extensions
    from .download import video_stream_info
    from .pipeline import render_settings, sidecar
    from .render import render_clip
    d = load(file)
    for item in autopilot.review_items():
        if _norm(item.get("file", "")) == d["rel"] and item.get("status") in ("approved", "uploading"):
            raise FixError("This short is being published right now, so it can't be changed. Undo the approval first.")
    pick, all_words = copy.deepcopy(d["pick"]), d["words"]
    vinfo_saved = _read(d["workdir"] / "info.json", {}) or {}
    changed = []

    if (start is not None or end is not None) and not pick.get("segments"):
        s = float(pick["start"] if start is None else start)
        e = float(pick["end"] if end is None else end)
        length = float(vinfo_saved.get("duration") or 0) or None
        if s < 0 or (length and e > length + 0.5):
            raise FixError("The start and end have to be inside the video.")
        if e - s < MIN_SECONDS:
            raise FixError(f"A short needs at least {MIN_SECONDS:.0f} seconds.")
        if e - s > MAX_SECONDS:
            raise FixError("A short can be at most 3 minutes long.")
        if abs(s - pick["start"]) > 0.01 or abs(e - pick["end"]) > 0.01:
            i0, i1 = words_in(all_words, s, e) if all_words else (0, 0)
            pick.update(start=round(s, 3), end=round(e, 3), i0=i0, i1=i1)
            tz = pick.get("teaser")
            if isinstance(tz, dict) and not (s <= tz.get("start", -1) and tz.get("end", 1e9) <= e):
                pick["teaser"] = None             # its flash-forward isn't in the short anymore
            changed.append("start and end")

    fixed = dict(d["edits"].get("words") or {})
    for k, v in (words or {}).items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            raise FixError("A caption word couldn't be matched to the transcript.") from None
        if not 0 <= i < len(all_words):
            raise FixError("A caption word couldn't be matched to the transcript.")
        v = re.sub(r"\s+", " ", str(v)).strip()[:60]
        if not v or v == all_words[i]["w"]:
            fixed.pop(str(i), None)               # empty, or back to what was said: the original
        else:
            fixed[str(i)] = v
    if fixed != (d["edits"].get("words") or {}):
        changed.append("caption words")
    if title is not None and title.strip() and title.strip()[:100] != (pick.get("title") or ""):
        pick["title"] = title.strip()[:100]
        changed.append("title")
    if not changed:
        raise FixError("Nothing changed, so there's nothing to render.")

    src, base = _ensure_source(d["workdir"], vinfo_saved, d["result"], d["overrides"], progress, log,
                               "this short can't be changed")

    words_all = [dict(w) for w in all_words]
    for k, v in fixed.items():
        words_all[int(k)]["w"] = v
    cfg = config.load(d["overrides"])
    rcfg = render_settings(cfg, d["visual"], d["countdown"])
    vinfo = video_stream_info(src)
    env_file = d["workdir"] / "envelope.npy"
    env = np.load(env_file) if env_file.exists() else None
    new = _next_name(d["out"])
    log(f"  rendering {new.name} ({', '.join(changed)} changed)")
    from . import vision
    stats = render_clip(rcfg, src, vinfo, pick, [] if d["visual"] else words_all, env, new,
                        progress=lambda p, m="": progress(base + (1 - base) * p, m), log=log,
                        eyes=vision.eyes_for(cfg, log, start=False))
    edits = {**d["edits"], "words": fixed}
    config.write_atomic(sidecar(new), json.dumps({"pick": pick, "overrides": d["overrides"], "visual": d["visual"],
                                                  "countdown": d["countdown"], "edits": edits}, ensure_ascii=False))
    root = d["root"].resolve()
    new_rel = str(new.relative_to(root))
    thumb_rel = str(new.with_suffix(".jpg").relative_to(root))

    # the Library and Review point at the new short from now on
    res_file = d["workdir"] / "result.json"
    result = _read(res_file, {}) or {}
    for c in result.get("clips") or []:
        if isinstance(c, dict) and _norm(c.get("file", "")) == d["rel"]:
            c.update(stats, file=new_rel, thumb=thumb_rel, title=pick.get("title") or c.get("title"),
                     start=pick["start"], end=pick["end"], fixed=int(time.time()))
    if result:
        config.write_atomic(res_file, json.dumps(result, ensure_ascii=False, indent=2))
    still_used = False
    with autopilot.LOCK:
        for item in autopilot.review_items():
            if _norm(item.get("file", "")) != d["rel"]:
                continue
            if item.get("status") in ("pending", "failed", "rejected"):
                autopilot.update_item(item["id"], file=new_rel, thumb=thumb_rel, duration=stats.get("duration"))
            else:
                still_used = True                   # published meanwhile: that one keeps the old file
    if not still_used:
        _remove_later([d["out"], d["out"].with_suffix(".jpg"), sidecar(d["out"])])
    extensions.run_hook("clip_rendered", log=log, path=new, clip={**d["entry"], **stats, "file": new_rel},
                        video=dict(vinfo_saved))
    progress(1.0, "Short updated")
    return {"file": new_rel, "thumb": thumb_rel, "duration": stats.get("duration"), "changed": changed,
            "title": pick.get("title") or ""}


# ───────────────────────── a clip from the transcript ─────────────────────────
# for the quote the AI skipped: search what's said, pick the first and last line, and it renders like any short

MINE = "clips-mine"            # shorts made by hand: a new Make Clips run on the video doesn't replace them
_VIDEO = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _video(video: str) -> Path:
    if not _VIDEO.match(video or "") or video in config.INTERNAL_DIRS or video.startswith("_"):
        raise FixError("That isn't one of Clippy's videos.")
    d = _root() / video
    if not d.is_dir():
        raise FixError("That video isn't in Clippy anymore.")
    return d


def transcript(video: str) -> dict:
    """The video's transcript as sentences, for searching and picking a clip."""
    from .picker import build_sentences
    d = _video(video)
    words = (_read(d / "transcript.json", {}) or {}).get("words") or []
    vinfo = _read(d / "info.json", {}) or {}
    result = _read(d / "result.json", {}) or {}
    if not words:
        raise FixError("This video has no transcript (no talking was found), so there's nothing to search.")
    src = _source(d)
    url = str(vinfo.get("webpage_url") or result.get("url") or "")
    root = _root().resolve()
    return {"id": video, "title": vinfo.get("title") or result.get("title") or video,
            "duration": float(vinfo.get("duration") or words[-1]["e"]),
            "lines": [{"n": k, "s": x["s"], "e": x["e"], "i0": x["i0"], "i1": x["i1"], "text": x["text"]}
                      for k, x in enumerate(build_sentences(words))],
            "source": _norm(src.resolve().relative_to(root)) if src else None,
            "redownload": src is None and url.startswith(("http://", "https://"))}


def make_clip(video: str, i0: int, i1: int, title: str = "", overrides: dict | None = None,
              progress=lambda p, m="": None, log=print) -> dict:
    """Render words i0..i1 of a video's transcript as a new short, with the usual captions and framing."""
    import numpy as np

    from . import extensions
    from .download import video_stream_info
    from .picker import clip_span
    from .pipeline import _slug, render_settings, sidecar
    from .render import render_clip
    d = _video(video)
    words = (_read(d / "transcript.json", {}) or {}).get("words") or []
    if not words:
        raise FixError("This video has no transcript, so there's nothing to make a clip from.")
    i0, i1 = int(i0), int(i1)
    if i1 < i0:
        i0, i1 = i1, i0
    if not (0 <= i0 < i1 <= len(words)):
        raise FixError("Those lines aren't in this video's transcript.")
    span = clip_span(words, i0, i1)
    if span["end"] - span["start"] < MIN_SECONDS:
        raise FixError(f"A short needs at least {MIN_SECONDS:.0f} seconds: pick a later last line.")
    if span["end"] - span["start"] > MAX_SECONDS:
        raise FixError("A short can be at most 3 minutes long: pick an earlier last line.")
    title = re.sub(r"\s+", " ", title or "").strip()[:100] or " ".join(w["w"] for w in words[i0:i0 + 6]).strip(" ,.")
    vinfo = _read(d / "info.json", {}) or {}
    result = _read(d / "result.json", {}) or {}
    from . import presets
    expanded = presets.expand(overrides)                                # a saved style, if one was chosen
    look_now = config.load(expanded)
    made_with = {**{k: getattr(look_now, k) for k in presets.KEYS}, **expanded, "clips_dir": MINE}
    src, base = _ensure_source(d, vinfo, result, made_with, progress, log, "a clip can't be made from it")
    out_dir = d / MINE
    out_dir.mkdir(exist_ok=True)
    taken = [int(m.group(1)) for f in out_dir.glob("*.mp4") if (m := re.match(r"(\d+)-", f.name))]
    out = out_dir / f"{max(taken, default=0) + 1:02d}-{_slug(title)}.mp4"
    pick = {"start": span["start"], "end": span["end"], "i0": i0, "i1": i1, "title": title,
            "why": "Made from the transcript"}
    cfg = config.load(made_with)
    rcfg = render_settings(cfg, False, False)
    env_file = d / "envelope.npy"
    log(f"  rendering {out.name} from the transcript ({span['end'] - span['start']:.1f} s)")
    from . import vision
    stats = render_clip(rcfg, src, video_stream_info(src), pick, words, np.load(env_file) if env_file.exists() else None,
                        out, progress=lambda p, m="": progress(base + (1 - base) * p, m), log=log,
                        eyes=vision.eyes_for(cfg, log, start=False))
    config.write_atomic(sidecar(out), json.dumps({"pick": pick, "overrides": made_with, "visual": False,
                                                  "countdown": False}, ensure_ascii=False))
    root = _root().resolve()
    entry = {"title": title, "caption": "", "hashtags": [], "score": None, "why": pick["why"],
             "start": span["start"], "end": span["end"], **stats, "manual": True,
             "file": str(out.resolve().relative_to(root)), "thumb": str(out.with_suffix(".jpg").resolve().relative_to(root))}
    if not result:
        result = {"id": video, "title": vinfo.get("title") or video, "url": vinfo.get("webpage_url", ""),
                  "uploader": vinfo.get("uploader", ""), "mode": "speech", "created": int(time.time()), "clips": []}
    result["clips"] = [entry] + [c for c in result.get("clips") or [] if isinstance(c, dict)]
    config.write_atomic(d / "result.json", json.dumps(result, ensure_ascii=False, indent=2))
    extensions.run_hook("clip_rendered", log=log, path=out, clip=dict(entry), video=dict(vinfo))
    progress(1.0, "Clip ready")
    return {"id": video, "title": result.get("title"), "clips": [entry]}
