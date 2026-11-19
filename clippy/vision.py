"""The AI's eyes: when the AI that picks the clips can also see images, Clippy shows it frames of the video.

- Framing (reframe.analyze): for each shot it says what kind of shot it is and where the important thing is, so a
  9:16 crop never cuts it off: a streamer's webcam goes on top with the game's action below, a crop that would
  miss the action moves or shows the whole picture, an animal or object gets followed instead of a stray face.
- Picking (rerank): it looks at a few frames of each candidate clip and rates how it looks on a phone (something
  happening, a clear subject, not a blank or static screen), and that counts toward which clips are made.

A model can see when it's a vision model: Qwen3.5/3.6 in llama.cpp or the built-in AI with its mmproj file, or a
vision model in Ollama (Gemma 3, Qwen2.5-VL, LLaVA…). Without one, nothing here runs and Clippy frames and picks
as before. Settings → "Let the AI look at the video" can turn it off."""
from __future__ import annotations

import dataclasses
import subprocess

import cv2
import numpy as np

KINDS = ("talking", "stream", "scene", "screen")
CACHE_VERSION = 2                   # bump when SHOTS_PROMPT changes: remembered answers then count as new
MAX_IMAGES = 10                     # per request: enough for a clip's shots, small enough for a local model

SHOTS_SYSTEM = """You frame shots for vertical 9:16 phone videos (TikTok, YouTube Shorts). You look at frames from a \
landscape video and say where the important things are, so a tall crop never cuts them off. Coordinates are on a \
0-1000 scale: x from the left edge, y from the top edge, boxes as [x0, y0, x1, y1]."""

SHOTS_PROMPT = """Here are {n} frames from one video, numbered 1 to {n} in the order shown.
For each frame give:
- kind: "talking" (people talking to the camera or each other), "stream" (gameplay or a screen with a streamer's \
webcam overlay on top of it), "scene" (action, animals, sport, a place or an object), or "screen" (slides, text, a \
website, a game menu with no action).
- subject: one box around everything a viewer must see in that frame to get the moment: the person speaking, the \
main character AND what they are reacting to or dealing with (the boat and the crocodile next to it, the player and \
the enemy), the animal, the object being shown. Not a small webcam overlay, a logo, a minimap or other screen HUD.
- cam: the box of a webcam/facecam overlay showing a person on top of the picture, or [] if there is none.
- wide: true if the important things are spread so far apart left to right that a narrow tall crop would lose some.
Return JSON."""

SHOTS_SCHEMA = {
    "type": "object",
    "properties": {"frames": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "kind": {"type": "string", "enum": list(KINDS)},
                       "subject": {"type": "array", "items": {"type": "integer"}},
                       "cam": {"type": "array", "items": {"type": "integer"}},
                       "wide": {"type": "boolean"}},
        "required": ["n", "kind", "subject", "cam", "wide"], "additionalProperties": False}}},
    "required": ["frames"], "additionalProperties": False,
}

RATE_SYSTEM = """You judge how good a clip will look as a vertical short on a phone. You only see a few frames; \
someone else judges what is said."""

RATE_PROMPT = """These are {n} frames from one candidate clip, in order{about}.
Rate 1-10 how good it looks as a short: something visibly happening, a clear subject that is big enough to see on a \
phone, variety from frame to frame. Low scores: black or blank frames, one static slide or screen, a tiny or \
unclear subject, nothing happening, heavy text or menus.
In "why", one short sentence. Return JSON."""

RATE_SCHEMA = {"type": "object", "properties": {"score": {"type": "integer"}, "why": {"type": "string"}},
               "required": ["score", "why"], "additionalProperties": False}


def jpeg(frame: np.ndarray, max_w: int = 512) -> bytes:
    h, w = frame.shape[:2]
    if w > max_w:
        frame = cv2.resize(frame, (max_w, int(round(h * max_w / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes() if ok else b""


def _box(v, W: float, H: float) -> tuple[float, float, float, float] | None:
    """[x0, y0, x1, y1] on 0-1000 → source pixels; None when it isn't a sensible box."""
    try:
        x0, y0, x1, y1 = (float(a) for a in v[:4])
    except (TypeError, ValueError):
        return None
    if len(v) < 4 or max(x0, y0, x1, y1) > 1000.5 or min(x0, y0, x1, y1) < -0.5:
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return x0 * W / 1000, y0 * H / 1000, x1 * W / 1000, y1 * H / 1000


class Eyes:
    """Looks at frames with the AI that picks clips. Created only when that AI can see (see eyes_for)."""

    def __init__(self, llm, log=print):
        self.llm, self.log = llm, log

    def shots(self, frames: list[np.ndarray], keys: list[str] | None = None, cache=None) -> list[dict | None]:
        """For each frame: {"kind", "subject": box px | None, "cam": box px | None, "wide"}; None when unsure.
        keys/cache: answers remembered per frame (its time in the video) in a JSON file next to the video, so
        re-rendering a short (Quick Fix, a new look) doesn't ask again."""
        known = _read_cache(cache) if cache and keys else {}
        if keys and all(k in known for k in keys):
            return [known[k] for k in keys]
        ask = [i for i in range(len(frames)) if not keys or keys[i] not in known]
        got = self._ask_shots([frames[i] for i in ask])
        out: list[dict | None] = [known.get(k) for k in keys] if keys else [None] * len(frames)
        for i, v in zip(ask, got):
            out[i] = v
            if keys and v is not None:
                known[keys[i]] = v
        if cache and keys:
            _write_cache(cache, known)
        return out

    def _ask_shots(self, frames: list[np.ndarray]) -> list[dict | None]:
        out: list[dict | None] = []
        for i in range(0, len(frames), MAX_IMAGES):
            part = frames[i:i + MAX_IMAGES]
            views: list[dict | None] = [None] * len(part)
            try:
                r = self.llm.json(SHOTS_SYSTEM, SHOTS_PROMPT.format(n=len(part)), SHOTS_SCHEMA, max_tokens=1500,
                                  temperature=0.1, images=[jpeg(f) for f in part])
                for row in r.get("frames") or []:
                    k = int(row.get("n", 0)) - 1
                    if 0 <= k < len(part) and row.get("kind") in KINDS:
                        H, W = part[k].shape[:2]
                        views[k] = {"kind": row["kind"], "subject": _box(row.get("subject") or [], W, H),
                                    "cam": _box(row.get("cam") or [], W, H), "wide": bool(row.get("wide")),
                                    "scale": (W, H)}
            except Exception as e:                       # framing still works without it
                self.log(f"    the AI couldn't look at the frames ({str(e)[:120]}); framing by faces")
            out += views
        return out

    def rate(self, frames: list[np.ndarray], about: str = "") -> tuple[int, str] | None:
        try:
            r = self.llm.json(RATE_SYSTEM, RATE_PROMPT.format(n=len(frames), about=f" ({about})" if about else ""),
                              RATE_SCHEMA, max_tokens=300, temperature=0.2, images=[jpeg(f) for f in frames])
            return max(1, min(10, int(r.get("score", 5)))), str(r.get("why") or "")[:200]
        except Exception as e:
            self.log(f"    the AI couldn't rate the clip's look ({str(e)[:120]})")
            return None


def _read_cache(path) -> dict:
    try:
        import json
        data = json.loads(open(path, encoding="utf-8").read())
        if data.get("v") != CACHE_VERSION:
            return {}
        return {k: {**v, "subject": tuple(v["subject"]) if v.get("subject") else None,
                    "cam": tuple(v["cam"]) if v.get("cam") else None, "scale": tuple(v["scale"])}
                for k, v in (data.get("shots") or {}).items() if isinstance(v, dict) and v.get("scale")}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def _write_cache(path, shots: dict) -> None:
    import json

    from . import config
    try:
        config.write_atomic(path, json.dumps({"v": CACHE_VERSION, "shots": shots}))
    except OSError:
        pass


def eyes_for(cfg, log=print, start: bool = True) -> Eyes | None:
    """Eyes when the setting allows it and the AI can see; None otherwise (and nothing changes).
    start=False: only an AI that's already running (Quick Fix, no-talking videos, reused picks don't need the AI
    otherwise, so nothing is loaded or downloaded just to look)."""
    if str(getattr(cfg, "vision", "auto")).lower() == "off":
        return None
    try:
        from .llm import LLM, resolve
        llm = LLM(cfg, log=log)
        if start:
            llm.wait_ready(timeout=60)
        else:
            s = resolve(cfg)
            if not s.base:                               # the built-in AI isn't running
                return None
            llm._use(s)
        if llm.can_see():
            log(f"  the AI can see ({llm.model}): it checks the framing and how each clip looks")
            return Eyes(llm, log)
    except Exception as e:
        if start:
            log(f"  couldn't ask whether the AI can see ({str(e)[:120]})")
    return None


def frames_at(src, times: list[float], width: int = 512) -> list[np.ndarray]:
    """Single frames of the video at these times (seconds), small, for the AI to look at."""
    out = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
                            "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                           capture_output=True, timeout=60)
        img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR) if r.stdout else None
        if img is not None:
            out.append(img)
    return out


def rerank(eyes: Eyes | None, clips: list[dict], src, want: int, log=print) -> list[dict]:
    """Rate how each candidate looks and keep the best `want` (score: 75% what's said, 25% how it looks)."""
    if eyes is None or not clips:
        return clips[:want]
    for c in clips:
        s, e = float(c["start"]), float(c["end"])
        frames = frames_at(src, [s + (e - s) * f for f in (0.12, 0.38, 0.62, 0.88)])
        got = eyes.rate(frames, c.get("title") or "") if frames else None
        said = float(c["score"]) if c.get("score") is not None else 50.0
        look, why = got if got is not None else (5, "")  # couldn't rate it: an average look, same scale as the rest
        if got is not None:
            c["look"], c["look_why"] = look, why
            log(f"    looks {look}/10: {c.get('title') or ''} ({why})")
        c["score_said"] = c.get("score")
        c["score"] = int(round(0.75 * said + 2.5 * look))
    kept = sorted(clips, key=lambda c: -(c.get("score") or 0))[:want]
    dropped = [c for c in clips if c not in kept]
    if dropped:
        log(f"  kept the {len(kept)} best-looking of {len(clips)} candidates")
    return kept


def ranker(eyes: Eyes | None, src, log=print):
    """For picker.pick_clips: rates how each rough candidate looks and orders them by what's said and how it
    looks, before the picker finalizes any (None without eyes)."""
    if eyes is None:
        return None

    def rank(cands: list[dict]) -> list[dict]:
        for c in cands:
            s, e = float(c["start"]), float(c["end"])
            frames = frames_at(src, [s + (e - s) * f for f in (0.12, 0.38, 0.62, 0.88)])
            about = c.get("hook") or c.get("label") or ""
            got = eyes.rate(frames, about) if frames else None
            if got is not None:
                c["look"], c["look_why"] = got
                log(f"    looks {got[0]}/10: {about[:60]} ({got[1]})")
        said = lambda c: float(c["score"]) if c.get("score") is not None else 50.0
        out = sorted(cands, key=lambda c: -(0.75 * said(c) + 2.5 * (c["look"] if c.get("look") is not None else 5)))
        log(f"  rated how {len(cands)} candidates look; the best are finalized")
        return out
    return rank


def with_extra(cfg, eyes: Eyes | None):
    """Settings that ask the picker for a few more candidates when the AI can rate how they look."""
    if eyes is None:
        return cfg
    return dataclasses.replace(cfg, clips=int(cfg.clips) + min(3, max(1, int(cfg.clips) // 2)))
