"""Clips for videos without talking (music, gameplay, sports, nature, satisfying videos…).

No transcript, so we look for the moments with the most going on:
  sound     loudness + sudden jumps (drops, crowd roars, impacts)
  replays   YouTube's "Most replayed" graph, when the video has one
  picture   on-screen motion and camera-cut pace — checked only on the best candidates, so it stays fast
Clips start/end on camera cuts, the teaser flashes forward to the climax, and zoom punches land on audio hits.
"""
from __future__ import annotations

import numpy as np

from .config import Settings
from .picker import tidy_post
from .transcribe import ENV_HZ


# ───────────────────────── is there talking? ─────────────────────────

def speech_stats(tr: dict) -> tuple[int, float, float]:
    """(words, share of the video that is speech, words per minute)."""
    words = tr.get("words") or []
    dur = float(tr.get("duration") or 0) or (words[-1]["e"] if words else 0.0)
    talk = sum(max(0.0, min(w["e"] - w["s"], 2.0)) for w in words)
    mins = max(dur / 60, 1e-6)
    return len(words), (talk / dur if dur else 0.0), len(words) / mins


def has_speech(tr: dict) -> bool:
    n, cover, per_min = speech_stats(tr)
    return n >= 40 and (cover >= 0.12 or per_min >= 25)


# ───────────────────────── signals ─────────────────────────

def _robust_z(x: np.ndarray) -> np.ndarray:
    med = float(np.median(x))
    q75, q25 = np.percentile(x, [75, 25])
    scale = (q75 - q25) / 1.35 or float(np.std(x)) or 1.0
    return np.clip((x - med) / scale, -3, 3)


def loudness_per_second(env: np.ndarray, duration: float) -> np.ndarray:
    n = max(1, int(np.ceil(duration)))
    padded = np.full(n * ENV_HZ, -90.0, np.float32)
    m = min(len(env), len(padded))
    padded[:m] = env[:m]
    return np.percentile(padded.reshape(n, ENV_HZ), 90, axis=1)


def heat_per_second(heatmap: list[dict] | None, n: int) -> np.ndarray:
    out = np.zeros(n)
    if not heatmap:
        return out
    from .finder import heat_bumps
    pts = sorted((h["s"], h["e"], h["v"]) for h in heatmap if h.get("s") is not None and h.get("v") is not None)
    if len(pts) < 10:
        return out
    for (a, b, _), v in zip(pts, heat_bumps([p[2] for p in pts])):
        out[int(a): int(np.ceil(b))] = np.maximum(out[int(a): int(np.ceil(b))], v)
    return out


def audio_hits(env: np.ndarray, start: float, end: float) -> list[float]:
    """Times of strong audio hits (beats, impacts, drops) between start and end — for zoom punches."""
    a, b = int(start * ENV_HZ), int(end * ENV_HZ)
    seg = env[max(0, a - 50): b].astype(np.float32)
    if len(seg) < 60:
        return []
    off = a - max(0, a - 50)
    k = np.ones(50) / 50
    prev = np.convolve(seg, k, mode="full")[: len(seg)]          # mean of the previous 0.5 s
    rise = seg - np.concatenate([[seg[0]], prev[:-1]])
    thr = max(6.0, float(np.percentile(rise[off:], 97)))
    hits = []
    for i in range(off + 15, len(seg) - 15):
        if rise[i] >= thr and rise[i] == rise[i - 15: i + 16].max():
            t = (max(0, a - 50) + i) / ENV_HZ
            if not hits or t - hits[-1] > 0.5:
                hits.append(round(t, 3))
    return hits


def _visual_profile(src: str, start: float, dur: float, fps: float = 4.0):
    """Motion level and camera cuts in [start, start+dur] from tiny low-fps frames."""
    import cv2

    from .reframe import FrameStream, frame_reader
    w, h = 160, 90
    n = max(2, int(dur * fps))
    prev, diffs = None, []
    for f in FrameStream(frame_reader(src, max(0.0, start), n, f"{fps:g}", (w, h)), w, h):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            diffs.append(float(np.mean(np.abs(g - prev))))
        prev = g
    d = np.array(diffs) if diffs else np.zeros(1)
    cuts = []
    for i in range(1, len(d) - 1):
        base = (np.median(d[max(0, i - 6): i]) if i > 1 else d[0]) + 1e-3
        if d[i] > 28 and d[i] > 3 * base:
            cuts.append(round(max(0.0, start) + (i + 1) / fps, 2))
    motion = float(np.median(d))
    return motion, cuts


# ───────────────────────── picking ─────────────────────────

def _target_len(cfg: Settings) -> int:
    return int(min(cfg.max_seconds, max(cfg.min_seconds, 30)))


def _snap(t: float, cuts: list[float], lo: float, hi: float) -> float | None:
    near = [c for c in cuts if lo <= c <= hi]
    return min(near, key=lambda c: abs(c - t)) if near else None


def pick_visual_clips(cfg: Settings, info: dict, src, vinfo: dict, env: np.ndarray | None,
                      progress=lambda p, m: None, log=print) -> list[dict]:
    dur = float(vinfo.get("duration") or info.get("duration") or 0)
    if env is None or not len(env) or dur <= 0:
        raise RuntimeError("Couldn't read this video's audio to find the best moments.")
    want = max(1, int(cfg.clips))
    L = _target_len(cfg)

    if dur <= cfg.max_seconds + 5:  # short video: the whole thing is one clip
        log("Short video — using it as a single clip")
        clip = {"i0": 0, "i1": 0, "start": 0.0, "end": round(dur, 3), "score": 70, "why": "whole video",
                "mode": "visual", "teaser": None, "beats": audio_hits(env, 0, dur), "emphasis": [], "emoji": []}
        _write_titles(cfg, info, [clip], log)
        return [clip]

    progress(0.05, "Listening for the loudest, most intense moments…")
    loud = loudness_per_second(env, dur)
    n = len(loud)
    zl = _robust_z(loud)
    prev = np.array([loud[max(0, i - 6): i].mean() if i else loud[0] for i in range(n)])
    zn = _robust_z(np.maximum(0, loud - prev))
    heat = heat_per_second(info.get("heatmap"), n)
    if heat.any():
        log("  using YouTube's 'Most replayed' data")
    silent = loud < (np.median(loud) - 20)
    score = zl + 0.8 * zn + 2.5 * heat - 2.0 * silent

    # skip intros and end screens
    lo = int(max(3, 0.015 * dur))
    hi = int(n - max(8, 0.03 * dur))
    if hi - lo < L:
        lo, hi = 0, n
    cand = []
    climax_from = int(0.35 * L)
    for t0 in range(lo, max(lo + 1, hi - L)):
        w = score[t0: t0 + L]
        cand.append((0.55 * float(w.mean()) + 0.45 * float(w[climax_from:].max()), t0))
    cand.sort(reverse=True)
    picked: list[tuple[float, int]] = []
    k = min(max(3 * want, 6), 14)
    for s, t0 in cand:
        if all(abs(t0 - p) >= L + 3 for _, p in picked):  # different moments, never overlapping
            picked.append((s, t0))
        if len(picked) >= k:
            break

    # look at the picture for the shortlisted windows
    srcs = str(src)
    rows = []
    for i, (s, t0) in enumerate(picked):
        progress(0.15 + 0.6 * i / max(1, len(picked)), f"Checking the action in moment {i + 1}/{len(picked)}…")
        motion, cuts = _visual_profile(srcs, t0 - 3, L + 6)
        rows.append({"audio": s, "t0": t0, "motion": motion, "cuts": cuts})
    if not rows:
        raise RuntimeError("Couldn't find any usable moments in this video.")
    mz = _robust_z(np.array([r["motion"] for r in rows])) if len(rows) > 2 else np.zeros(len(rows))
    for r, m in zip(rows, mz):
        pace = min(3.0, len([c for c in r["cuts"] if r["t0"] <= c <= r["t0"] + L]) / max(1, L / 10))
        still = r["motion"] < 0.6  # basically a still image
        r["final"] = r["audio"] + 0.35 * float(m) + 0.12 * pace - (1.5 if still else 0)
    rows.sort(key=lambda r: -r["final"])
    rows = rows[:want]

    clips = []
    finals = sorted(r["final"] for r in rows)
    for r in sorted(rows, key=lambda r: -r["final"]):
        start, end = float(r["t0"]), float(r["t0"] + L)
        s2 = _snap(start, r["cuts"], start - 2.5, start + 2.5)
        e2 = _snap(end, r["cuts"], end - 2.5, end + 2.5)
        if s2 is not None:
            start = s2 + 0.04
        if e2 is not None and cfg.min_seconds <= (e2 - 0.04) - start <= cfg.max_seconds:
            end = e2 - 0.04
        end = min(end, dur - 0.1)
        # climax → flash-forward teaser + zoom punches on audio hits
        a, b = int(start + 0.4 * (end - start)), int(end - 1)
        teaser = None
        if end - start >= 15 and b > a:
            p = a + int(np.argmax(score[a:b]))
            if p - start >= 6:
                teaser = {"i0": 0, "i1": 0, "start": round(max(start, p - 1.2), 3), "end": round(min(end, p + 1.4), 3)}
        rank = finals.index(r["final"]) / max(1, len(finals) - 1) if len(finals) > 1 else 1.0
        reasons = [x for x, ok in (("loud peak", zl[int(start):int(end)].max() > 1.5),
                                   ("big build-up", zn[int(start):int(end)].max() > 1.5),
                                   ("most replayed", heat[int(start):int(end)].max() > 0.5),
                                   ("fast cuts", len(r["cuts"]) / max(1, L / 10) > 1.5)) if ok]
        clips.append({"i0": 0, "i1": 0, "start": round(start, 3), "end": round(end, 3), "mode": "visual",
                      "score": int(round(62 + 33 * rank)), "why": ", ".join(reasons) or "most going on",
                      "teaser": teaser, "beats": audio_hits(env, start, end), "emphasis": [], "emoji": []})
    clips.sort(key=lambda c: c["start"])
    progress(0.8, "Writing titles…")
    _write_titles(cfg, info, clips, log)
    clips.sort(key=lambda c: -c["score"])
    for c in clips:
        log(f"  ✓ {_mmss(c['start'])}–{_mmss(c['end'])} ({c['end'] - c['start']:.0f}s) score {c['score']}: {c.get('title', '')}  [{c['why']}]")
    return clips


def _mmss(t: float) -> str:
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


# ───────────────────────── titles (local AI, with a fallback) ─────────────────────────

TITLE_SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {"title": {"type": "string", "maxLength": 70}, "caption": {"type": "string", "maxLength": 300},
                       "hashtags": {"type": "array", "items": {"type": "string", "maxLength": 30}}},
        "required": ["title", "caption", "hashtags"], "additionalProperties": False}}},
    "required": ["clips"], "additionalProperties": False,
}


def _write_titles(cfg: Settings, info: dict, clips: list[dict], log) -> None:
    base = (info.get("title") or "Watch this").strip()
    for i, c in enumerate(clips):  # fallback first, so a missing AI never breaks a run
        c.setdefault("title", base[:60] if len(clips) == 1 else f"{base[:50]} · Part {i + 1}")
        c.setdefault("caption", base[:200])
        c.setdefault("hashtags", [])
    try:
        from .picker import LLM, SYSTEM
        llm = LLM(cfg, log)
        llm.wait_ready(timeout=90)
        desc = (info.get("description") or "").strip().replace("\n\n", "\n")[:1200]
        lines = "\n".join(f"- clip {i + 1}: {_mmss(c['start'])}–{_mmss(c['end'])} ({c['why']})" for i, c in enumerate(clips))
        prompt = f"""Video: "{info.get('title', '')}" by {info.get('uploader') or 'unknown'}
Description: {desc or '(none)'}
Tags: {", ".join((info.get('tags') or [])[:15]) or '(none)'}

There is NO talking in this video (music, gameplay, sport, action or visuals). We cut {len(clips)} vertical clips from it:
{lines}

For each clip, in the same order, write:
- title: on-screen hook text, max 6 words, builds curiosity and fits what this video is about (e.g. "Wait For The Ending", "The Drop Hits Different", "Nobody Expected This Save"). All titles must be clearly different. No emojis or hashtags.
- caption: the post description — 1 short sentence plus a question that makes people comment.
- hashtags: 4–6 relevant hashtags (with #).
Write in the language of the video title. Return JSON."""
        out = llm.json(SYSTEM, prompt, TITLE_SCHEMA, max_tokens=300 * len(clips) + 300, temperature=0.6)
        for c, t in zip(clips, out.get("clips") or []):
            if str(t.get("title", "")).strip():
                c["title"] = str(t["title"]).strip().strip('"')[:70]
            caption, c["hashtags"] = tidy_post(str(t.get("caption", "")), t.get("hashtags"))
            if caption:
                c["caption"] = caption
    except Exception as e:  # AI offline or slow: keep the fallback titles
        log(f"  (titles: AI not available — using the video title: {e})")
