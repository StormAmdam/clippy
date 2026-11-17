"""Find the best moments with a local (or any OpenAI-compatible) LLM.

Two passes:
  1. scout  – read the whole transcript, propose candidate ranges with a virality score
  2. refine – for each top candidate, look closely at the surrounding sentences and tighten
              start (hook) and end (payoff), then write the title / caption / hashtags.
"""
from __future__ import annotations

import json
import re
import time

import httpx
import numpy as np

from .config import Settings

# ───────────────────────── transcript → sentences ─────────────────────────

END_PUNCT = tuple(".?!。！？…")


def build_sentences(words: list[dict], max_gap: float = 1.0, max_words: int = 40) -> list[dict]:
    sents, cur = [], []

    def flush():
        if cur:
            i0, i1 = cur[0], cur[-1] + 1
            sents.append({"id": len(sents), "i0": i0, "i1": i1, "s": words[i0]["s"], "e": words[i1 - 1]["e"],
                          "text": " ".join(words[i]["w"] for i in range(i0, i1))})
            cur.clear()

    for i, w in enumerate(words):
        if cur and w["s"] - words[i - 1]["e"] > max_gap:
            flush()
        cur.append(i)
        if w["w"].endswith(END_PUNCT) or len(cur) >= max_words:
            flush()
    flush()
    return sents


def mmss(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


# ───────────────────────── LLM client ─────────────────────────

class LLM:
    def __init__(self, cfg: Settings, log=print):
        self.cfg = cfg
        self.base = cfg.llm_url.rstrip("/")
        self.local = any(h in self.base for h in ("127.0.0.1", "localhost", "0.0.0.0"))
        self.log = log
        self.model = cfg.llm_model
        self.headers = {"Content-Type": "application/json"}
        if cfg.llm_api_key:
            self.headers["Authorization"] = f"Bearer {cfg.llm_api_key}"
        self._schema_ok = True
        self._kwargs_ok = True

    def wait_ready(self, timeout: float = 300, progress=lambda m: None) -> None:
        t0 = time.time()
        last_err = ""
        while time.time() - t0 < timeout:
            try:
                r = httpx.get(self.base + "/models", headers=self.headers, timeout=10)
                if r.status_code == 200:
                    data = r.json().get("data") or r.json().get("models") or []
                    if not self.model and data:
                        self.model = data[0].get("id") or data[0].get("name") or ""
                    return
                last_err = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last_err = type(e).__name__
            progress(f"Waiting for the AI server to be ready ({int(time.time() - t0)}s)…")
            time.sleep(2)
        raise RuntimeError(f"AI server at {self.base} is not reachable ({last_err}). "
                           f"Start it (e.g. `systemctl --user start llama-coder` or `ollama serve`) or change llm_url in config.toml.")

    def json(self, system: str, user: str, schema: dict, max_tokens: int = 3000, temperature: float = 0.4) -> dict:
        body: dict = {"model": self.model or "default", "temperature": temperature, "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        for attempt in range(3):
            b = dict(body)
            if self._schema_ok:
                b["response_format"] = {"type": "json_schema",
                                        "json_schema": {"name": "result", "schema": schema, "strict": True}}
            else:
                b["response_format"] = {"type": "json_object"}
            if self.local and self._kwargs_ok:
                b["chat_template_kwargs"] = {"enable_thinking": bool(self.cfg.llm_thinking)}
            try:
                r = httpx.post(self.base + "/chat/completions", headers=self.headers, json=b, timeout=1200)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise RuntimeError(f"AI request failed: {e}")
                time.sleep(3)
                continue
            if r.status_code == 400 and (self._schema_ok or self._kwargs_ok):
                # provider doesn't support json_schema or chat_template_kwargs → degrade gracefully
                if self._kwargs_ok and "chat_template_kwargs" in b:
                    self._kwargs_ok = False
                else:
                    self._schema_ok = False
                continue
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"AI server error {r.status_code}: {r.text[:300]}")
            msg = r.json()["choices"][0]["message"]
            content = msg.get("content") or ""
            try:
                return parse_json(content)
            except ValueError:
                if attempt == 2:
                    raise RuntimeError(f"AI returned invalid JSON: {content[:300]}")
        raise RuntimeError("AI request failed after retries")


_HASHTAG = re.compile(r"#\w+")
_TRAILING_HASHTAGS = re.compile(r"(?:\s*#\w+)+\s*$")


def tidy_post(caption: str, hashtags, limit: int = 6) -> tuple[str, list[str]]:
    """Keep the post text and its hashtags apart. The AI often ends the caption with hashtags as well, which then
    show up twice under the short. Hashtags at the end of the caption or on lines of their own move to the list;
    ones used inside a sentence stay. The list gets '#' prefixes, loses repeats (any case) and is capped."""
    moved, kept = [], []
    for line in (caption or "").strip().splitlines():
        if line.split() and all(tok.startswith("#") for tok in line.split()):
            moved += _HASHTAG.findall(line)
        else:
            kept.append(line)
    text = "\n".join(kept).strip()
    if m := _TRAILING_HASHTAGS.search(text):
        moved = _HASHTAG.findall(m.group()) + moved
        text = text[:m.start()].rstrip()
    out, seen = [], set()
    for h in [*(hashtags or []), *moved]:
        h = re.sub(r"\s+", "", str(h))
        h = h if h.startswith("#") else "#" + h
        if len(h) > 1 and h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    return text, out[:limit]


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise ValueError("no json")


# ───────────────────────── prompts ─────────────────────────

SYSTEM = """You are the best short-form video editor in the world. You cut long videos (podcasts, interviews, talks, streams, vlogs) into vertical clips for TikTok, YouTube Shorts and Instagram Reels that get millions of views.

What makes a clip go viral:
- HOOK: the first sentence grabs attention instantly — a bold or controversial claim, a surprising fact, raw emotion, a provocative question, the start of a story with stakes, or a funny line. Viewers decide in 1–2 seconds whether to keep watching.
- STANDALONE: someone who never saw the video understands it. No references to earlier parts ("like I said", "that guy", "this thing") unless explained inside the clip.
- PAYOFF: it ends on a punchline, conclusion, lesson, twist or strong statement — never mid-thought.
- VALUE or EMOTION: it teaches something useful, reveals something, is funny, inspiring, shocking, relatable, or sparks debate in the comments.
- DENSITY: lots of substance, little rambling.

Avoid: intros/outros, sponsor reads, "like and subscribe", small talk, moments that only make sense with visuals, and anything that needs outside context."""

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "why": {"type": "string", "maxLength": 300},
            "start_id": {"type": "integer"},
            "end_id": {"type": "integer"},
            "hook": {"type": "string", "maxLength": 200},
            "score": {"type": "integer"},
        },
        "required": ["why", "start_id", "end_id", "hook", "score"],
        "additionalProperties": False,
    }}},
    "required": ["clips"],
    "additionalProperties": False,
}

REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "thoughts": {"type": "string", "maxLength": 500},
        "start_id": {"type": "integer"},
        "end_id": {"type": "integer"},
        "title": {"type": "string", "maxLength": 80},
        "caption": {"type": "string", "maxLength": 400},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "emphasis": {"type": "array", "items": {"type": "string"}},
        "emoji": {"type": "array", "items": {
            "type": "object",
            "properties": {"word": {"type": "string"}, "emoji": {"type": "string"}},
            "required": ["word", "emoji"], "additionalProperties": False}},
        "teaser_id": {"type": "integer"},
        "score": {"type": "integer"},
    },
    "required": ["thoughts", "start_id", "end_id", "title", "caption", "hashtags", "emphasis", "emoji",
                 "teaser_id", "score"],
    "additionalProperties": False,
}


def _scout_prompt(info, lines, n, cfg, wps):
    by = f' by {info["uploader"]}' if info.get("uploader") else ""
    return f"""Video: "{info.get("title", "")}"{by}

Transcript. One sentence per line: [sentence_id] start-time text
(🔊 = noticeably louder / more energetic: shouting, excitement, crowd.  📈 = YouTube viewers re-watch this part the most — a very strong signal, prefer clips that contain these.)
{lines}

Find the {n} best clip candidates in this transcript. A clip is a continuous range of sentences from start_id to end_id (inclusive). It must last {cfg.min_seconds}–{cfg.max_seconds} seconds — use the start-times to estimate (speaking pace here is ~{wps:.1f} words/second, so roughly {int(cfg.min_seconds * wps)}–{int(cfg.max_seconds * wps)} words).
Pick different topics; ranges must not overlap. In "why" explain briefly what the hook and payoff are. In "hook" quote the opening line.
Score each 1–100 for viral potential. Be critical: 90+ only for truly exceptional moments.
Return JSON."""


def _refine_prompt(ctx_lines, a, b, dur, why, cfg, used_titles):
    avoid = ""
    if used_titles:
        avoid = ("\nTitles already used for other clips: " + "; ".join(used_titles) +
                 "\nYours must be clearly different — different angle AND different structure/first word "
                 "(don't start every title with \"Why\" or \"How\").")
    return f"""You are finalizing one clip.
Sentences around the candidate (id | start | duration | text):
{ctx_lines}

Current pick: sentences {a} to {b} ({dur:.0f}s). Reason it was picked: {why}

Make it the best possible standalone clip of {cfg.min_seconds}–{cfg.max_seconds} seconds:
1. start_id — the very first words must hook. Drop warm-up, filler, greetings and openers that depend on earlier context. Never start on a sentence whose subject is an unexplained "they/he/she/it/this/that". Start on the strongest line if you can.
2. end_id — end right after the payoff/punchline/conclusion. Drop trailing rambling.
3. Keep the total duration within {cfg.min_seconds}–{cfg.max_seconds}s (add up the durations).
Then write, in the SAME LANGUAGE as the transcript:
- title: on-screen hook text, max 7 words. It must be SPECIFIC to what is said in this clip (a concrete detail, number, claim or story) and make people curious — truthful, no emojis, hashtags or quotes. Good: "She Quit Google to Sell Socks", "I Slept 4 Hours a Night for a Year", "The $5 Rule That Fixed My Spending". Bad (too generic): "The Truth About Success", "Why This Matters", "This Changed Everything".{avoid}
- caption: the post description — 1–2 short sentences plus a question that makes people comment.
- hashtags: 4–6 relevant hashtags (with #, no spaces).
- emphasis: up to 6 single words from the clip that carry the most meaning (they get highlighted in the captions).
Keep "thoughts" to 2–3 short sentences.
- emoji: up to 4 items {{"word", "emoji"}} — a word from the clip and ONE emoji that pops up when it is said (money → 💰, fire → 🔥, shocked → 😱). Only where it adds punch.
- teaser_id: the single most shocking/funny/intriguing sentence INSIDE your range (not the first one, ideally from the second half) that we show as a 2–4 second flash-forward before the clip starts, to hook viewers. -1 if the opening line is already the strongest.
- score: final viral potential 1–100.
Return JSON."""


# ───────────────────────── selection logic ─────────────────────────

FILLER_PAIRS_EN = {("i", "mean"), ("you", "know"), ("kind", "of"), ("sort", "of")}
FILLERS_EN = {"so", "and", "um", "uh", "umm", "uhh", "yeah", "well", "okay", "ok", "like", "anyway", "right", "oh", "now"}


def _norm(w: str) -> str:
    return re.sub(r"[^\w']", "", w.lower())


def _fit(sents, a, b, cfg) -> tuple[int, int]:
    n = len(sents)
    a, b = max(0, min(a, n - 1)), max(0, min(b, n - 1))
    if b < a:
        a, b = b, a
    dur = lambda: sents[b]["e"] - sents[a]["s"]
    while dur() > cfg.max_seconds and b > a:  # trim the end, keep the hook
        b -= 1
    while dur() < cfg.min_seconds and b + 1 < n and sents[b + 1]["e"] - sents[a]["s"] <= cfg.max_seconds:
        b += 1
    return a, b


def _overlap(x, y) -> float:
    inter = max(0.0, min(x["end"], y["end"]) - max(x["start"], y["start"]))
    return inter / max(1e-6, min(x["end"] - x["start"], y["end"] - y["start"]))


def _finalize(sents, words, a, b, cfg, lang) -> dict:
    i0, i1 = sents[a]["i0"], sents[b]["i1"]
    if lang == "en":  # drop leading filler ("So, um, I mean, ...")
        for _ in range(4):
            if i0 + 2 < i1 and (_norm(words[i0]["w"]), _norm(words[i0 + 1]["w"])) in FILLER_PAIRS_EN:
                i0 += 2
            elif i0 + 1 < i1 and _norm(words[i0]["w"]) in FILLERS_EN:
                i0 += 1
            else:
                break
    # hard cap at max_seconds at word level (single very long sentence)
    while i1 - 1 > i0 and words[i1 - 1]["e"] - words[i0]["s"] > cfg.max_seconds + 2:
        i1 -= 1
    start = words[i0]["s"] - 0.12
    if i0 > 0:
        start = max(start, words[i0 - 1]["e"] + 0.02)
    end = words[i1 - 1]["e"] + 0.45
    if i1 < len(words):
        end = min(end, words[i1]["s"] - 0.03)
    end = max(end, words[i1 - 1]["e"] + 0.05)
    return {"i0": i0, "i1": i1, "start": round(max(0.0, start), 3), "end": round(end, 3)}


def _energy_flags(sents, env) -> set[int]:
    if env is None or not len(env):
        return set()
    vals = []
    for s in sents:
        seg = env[int(s["s"] * 100): int(s["e"] * 100) + 1]
        vals.append(float(np.percentile(seg, 75)) if len(seg) else -99.0)
    if len(vals) < 8:
        return set()
    thr = float(np.percentile(vals, 85))
    med = float(np.median(vals))
    return {i for i, v in enumerate(vals) if v >= thr and v > med + 3}


def _heat_by_sentence(sents, heatmap) -> list[float]:
    """Max 'Most replayed' value (0..1) overlapping each sentence; [] if the video has no heatmap."""
    if not heatmap:
        return []
    from .finder import heat_bumps
    hm = sorted((h["s"], h["e"], h["v"]) for h in heatmap if h.get("s") is not None and h.get("v") is not None)
    hm = [(a, b, v) for (a, b, _), v in zip(hm, heat_bumps([x[2] for x in hm]))]
    out = []
    j = 0
    for s in sents:
        while j < len(hm) and hm[j][1] < s["s"]:
            j += 1
        k, best = j, 0.0
        while k < len(hm) and hm[k][0] <= s["e"]:
            best = max(best, hm[k][2])
            k += 1
        out.append(best)
    return out


def _teaser(sents, words, tid, a, b) -> dict | None:
    if tid is None or not (a < tid <= b):
        return None
    s = sents[tid]
    if s["s"] - sents[a]["s"] < 4.0:  # too close to the start to be a flash-forward
        return None
    i0, i1 = s["i0"], s["i1"]
    if words[i1 - 1]["e"] - words[i0]["s"] < 1.2 and tid + 1 <= b:
        i1 = sents[tid + 1]["i1"]
    while i1 - 1 > i0 and words[i1 - 1]["e"] - words[i0]["s"] > 5.0:
        i1 -= 1
    dur = words[i1 - 1]["e"] - words[i0]["s"]
    if dur < 0.9:
        return None
    end = words[i1 - 1]["e"] + 0.12
    if i1 < len(words):
        end = min(end, words[i1]["s"] - 0.02)
    return {"i0": i0, "i1": i1, "start": round(max(0.0, words[i0]["s"] - 0.06), 3), "end": round(end, 3)}


def _auto_teaser(sents, words, a, b, env, emphasis) -> dict | None:
    """Fallback flash-forward: the loudest / punchiest short line from the second half of the clip."""
    emph = {re.sub(r"[^\w'$%]", "", e.lower()) for x in emphasis for e in str(x).split()}
    t0 = sents[a]["s"]
    mid = (sents[a]["s"] + sents[b]["e"]) / 2
    best, best_score = None, -1e9
    for k in range(a + 1, b + 1):
        s = sents[k]
        d = s["e"] - s["s"]
        if s["s"] - t0 < 5.0 or not (1.2 <= d <= 4.5):
            continue
        score = 0.0
        if env is not None and len(env):
            seg = env[int(s["s"] * 100): int(s["e"] * 100) + 1]
            if len(seg):
                score += float(np.percentile(seg, 75)) / 3
        txt = s["text"]
        score += 2.0 * sum(1 for w in txt.split() if re.sub(r"[^\w'$%]", "", w.lower()) in emph)
        score += 1.5 if txt.rstrip().endswith(("!", "?")) else 0
        score += 1.0 if re.search(r"\$|\d", txt) else 0
        score += 0.5 if s["s"] >= mid else 0
        if score > best_score:
            best, best_score = k, score
    return _teaser(sents, words, best, a, b) if best is not None else None


def pick_clips(cfg: Settings, info: dict, transcript: dict, progress=lambda p, m: None, log=print,
               env=None) -> list[dict]:
    words = transcript["words"]
    if not words:
        raise RuntimeError("No speech found in this video — nothing to clip.")
    sents = build_sentences(words)
    loud = _energy_flags(sents, env)
    heat = _heat_by_sentence(sents, info.get("heatmap"))
    hot: set[int] = set()
    if heat:
        hv = sorted(heat)
        thr = max(hv[int(len(hv) * 0.85)], 0.3)
        hot = {i for i, v in enumerate(heat) if v >= thr}
        log(f"Using YouTube's 'Most replayed' data: {len(hot)} hot sentences")
    lang = transcript.get("language", "en")
    speech = sum(w["e"] - w["s"] for w in words) or 1
    wps = max(1.5, min(4.5, len(words) / max(speech, 1) * 0.85))

    total = words[-1]["e"] - words[0]["s"]
    if total <= cfg.max_seconds + 5:  # short video: one clip, whole thing
        log("Video is short — using it as a single clip")
        c = _finalize(sents, words, 0, len(sents) - 1, cfg, lang)
        c.update(title=info.get("title", "")[:60], caption="", hashtags=[], emphasis=[], score=50, why="whole video")
        return [c]

    llm = LLM(cfg, log)
    llm.wait_ready(progress=lambda m: progress(0.02, m))
    log(f"AI: {llm.model or '(server default)'} at {llm.base}")

    # ── pass 1: scout (chunked if transcript is huge)
    chunks, cur, size = [], [], 0
    for s in sents:
        marks = ("📈 " if s["id"] in hot else "") + ("🔊 " if s["id"] in loud else "")
        line = f"[{s['id']}] {mmss(s['s'])} {marks}{s['text']}"
        if cur and size + len(line) > cfg.llm_chunk_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append(cur)

    want = cfg.clips
    per_chunk = max(3, min(15, round(want * 2 / len(chunks)) + 1))
    cands = []
    for ci, chunk in enumerate(chunks):
        progress(0.05 + 0.45 * ci / len(chunks), f"AI is watching the video for the best moments… ({ci + 1}/{len(chunks)})")
        t0 = time.time()
        out = llm.json(SYSTEM, _scout_prompt(info, "\n".join(chunk), per_chunk, cfg, wps), SCOUT_SCHEMA,
                       max_tokens=400 * per_chunk + 500, temperature=0.4)
        log(f"Scout pass {ci + 1}/{len(chunks)}: {len(out.get('clips', []))} candidates in {time.time() - t0:.0f}s")
        cands.extend(out.get("clips", []))

    # validate + rank
    scored = []
    for c in cands:
        try:
            a, b = _fit(sents, int(c["start_id"]), int(c["end_id"]), cfg)
        except (KeyError, ValueError, TypeError):
            continue
        dur = sents[b]["e"] - sents[a]["s"]
        if dur < cfg.min_seconds * 0.6:
            continue
        bonus = 0
        if heat:  # reward ranges that contain YouTube's most re-watched moments
            bonus = round(10 * max(heat[a: b + 1] or [0]))
        scored.append({"a": a, "b": b, "start": sents[a]["s"], "end": sents[b]["e"],
                       "score": int(c.get("score", 50)) + bonus, "why": c.get("why", ""), "hook": c.get("hook", "")})
    scored.sort(key=lambda x: -x["score"])
    uniq = []
    for c in scored:
        if all(_overlap(c, u) < 0.3 for u in uniq):
            uniq.append(c)
    if not uniq:
        raise RuntimeError("The AI didn't return any usable clips. Try again, or a different video.")

    # ── pass 2: refine the best ones
    final = []
    pool = uniq[: want + 3]
    for k, c in enumerate(pool):
        if len(final) >= want:
            break
        progress(0.5 + 0.5 * len(final) / want, f"Editing clip {len(final) + 1}/{want}: tightening hook & ending…")
        lo = max(0, c["a"] - 8)
        hi = min(len(sents) - 1, c["b"] + 8)
        ctx = "\n".join(f"[{s['id']}] {mmss(s['s'])} | {s['e'] - s['s']:.1f}s | {s['text']}" for s in sents[lo: hi + 1])
        try:
            r = llm.json(SYSTEM, _refine_prompt(ctx, c["a"], c["b"], c["end"] - c["start"], c["why"], cfg,
                                                [f["title"] for f in final if f.get("title")]),
                         REFINE_SCHEMA, max_tokens=2000, temperature=0.4)
            a, b = _fit(sents, int(r["start_id"]), int(r["end_id"]), cfg)
            if not (lo <= a <= hi and lo <= b <= hi) or sents[b]["e"] - sents[a]["s"] < cfg.min_seconds * 0.6:
                a, b = c["a"], c["b"]
            caption, hashtags = tidy_post(str(r.get("caption", "")), r.get("hashtags"))
            meta = {"title": str(r.get("title", "")).strip().strip('"'), "caption": caption, "hashtags": hashtags,
                    "emphasis": [str(e) for e in (r.get("emphasis") or [])][:6],
                    "emoji": [e for e in (r.get("emoji") or []) if isinstance(e, dict)][:4],
                    "teaser": _teaser(sents, words, int(r.get("teaser_id", -1)), a, b),
                    "score": int(r.get("score", c["score"]))}
        except Exception as e:
            log(f"Refine failed for a clip ({e}); using the raw pick")
            a, b = c["a"], c["b"]
            meta = {"title": c["hook"][:50], "caption": "", "hashtags": [], "emphasis": [], "emoji": [],
                    "teaser": None, "score": c["score"]}
        if not meta.get("teaser"):
            meta["teaser"] = _auto_teaser(sents, words, a, b, env, meta.get("emphasis", []))
        clip = _finalize(sents, words, a, b, cfg, lang)
        clip.update(meta, why=c["why"])
        if any(_overlap(clip, f) > 0.3 for f in final):
            continue
        final.append(clip)
        log(f"  ✓ {mmss(clip['start'])}–{mmss(clip['end'])} ({clip['end'] - clip['start']:.0f}s) "
            f"score {clip['score']}: {clip['title']}")

    final.sort(key=lambda x: -x["score"])
    return final
