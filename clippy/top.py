"""Top countdowns: one short that ranks a video's best moments of one kind, "#3 … #2 … #1".

The AI reads the transcript and scores candidate moments for a theme (funniest, craziest…). Laughter, loud reactions
and YouTube's "Most replayed" graph add points, then the best few become a countdown with the best one last. Videos
without talking get their moments from sound and action instead. Themes can come from extensions too."""
from __future__ import annotations

import re
import time
from types import SimpleNamespace

from .config import Settings
from .picker import _energy_flags, _finalize, _heat_by_sentence, _overlap, build_sentences, mmss, tidy_post

THEMES: dict[str, dict] = {
    "funny": {"name": "Funniest", "emoji": "😂", "title": "Top {n} Funniest Moments", "word": "funny",
              "look_for": "the funniest moments: jokes that land, punchlines, comebacks, absurd or awkward situations, "
                          "and people cracking up laughing",
              "hashtags": ["#funny", "#funnymoments", "#comedy"], "laughter": True},
    "crazy": {"name": "Craziest", "emoji": "🤯", "title": "Top {n} Craziest Moments", "word": "crazy",
              "look_for": "the craziest, most unbelievable moments: wild stories, insane claims, chaos, things that "
                          "make viewers say \"no way\"",
              "hashtags": ["#crazy", "#insane", "#unbelievable"]},
    "shocking": {"name": "Most shocking", "emoji": "😱", "title": "Top {n} Most Shocking Moments", "word": "shocking",
                 "look_for": "the most shocking moments: jaw-dropping confessions, reveals, plot twists and statements "
                             "nobody expected",
                 "hashtags": ["#shocking", "#plottwist", "#omg"]},
    "wholesome": {"name": "Most wholesome", "emoji": "🥹", "title": "Top {n} Most Wholesome Moments",
                  "word": "wholesome",
                  "look_for": "the most wholesome moments: kind, heartwarming, touching or emotional moments that make "
                              "people smile",
                  "hashtags": ["#wholesome", "#heartwarming", "#feelgood"]},
}

LAUGH = re.compile(r"\b(?:ha(?:ha)+h?|hah|lol|lmao|lmfao)\b|laugh|😂|🤣", re.I)

SYSTEM = """You are a top short-form video editor. You make countdown shorts ("Top 3 funniest moments") for TikTok, YouTube Shorts and Instagram Reels from long videos. Each moment must work on its own in a few seconds: a quick setup and the payoff, nothing else."""

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {"moments": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "why": {"type": "string", "maxLength": 200},
            "start_id": {"type": "integer"},
            "end_id": {"type": "integer"},
            "label": {"type": "string", "maxLength": 40},
            "score": {"type": "integer"},
        },
        "required": ["why", "start_id", "end_id", "label", "score"],
        "additionalProperties": False,
    }}},
    "required": ["moments"],
    "additionalProperties": False,
}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string", "maxLength": 300},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "moments": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "maxLength": 40},
                "emphasis": {"type": "array", "items": {"type": "string"}},
                "emoji": {"type": "array", "items": {
                    "type": "object", "properties": {"word": {"type": "string"}, "emoji": {"type": "string"}},
                    "required": ["word", "emoji"], "additionalProperties": False}},
            },
            "required": ["label", "emphasis", "emoji"], "additionalProperties": False}},
    },
    "required": ["caption", "hashtags", "moments"],
    "additionalProperties": False,
}


def themes() -> dict[str, dict]:
    """Built-in themes plus the ones extensions add."""
    from . import extensions
    return {**THEMES, **extensions.top_themes()}


def theme(tid: str) -> dict:
    t = themes()
    return {"id": tid if tid in t else "funny", **t.get(tid, THEMES["funny"])}


def title_for(th: dict, n: int) -> str:
    return str(th.get("title") or "Top {n} Moments").replace("{n}", str(n))


def _limits(cfg: Settings):
    lo = max(3, int(cfg.top_min or 5))
    return SimpleNamespace(min_seconds=lo, max_seconds=max(lo + 2, int(cfg.top_max or 15)))


def _fit(sents, a, b, lim) -> tuple[int, int]:
    n = len(sents)
    a, b = max(0, min(a, n - 1)), max(0, min(b, n - 1))
    if b < a:
        a, b = b, a
    while sents[b]["e"] - sents[a]["s"] > lim.max_seconds and b > a:
        b -= 1
    while sents[b]["e"] - sents[a]["s"] < lim.min_seconds and b + 1 < n and \
            sents[b + 1]["e"] - sents[a]["s"] <= lim.max_seconds:
        b += 1
    return a, b


MIN_APART = 10.0     # seconds between two moments: back-to-back ones play as one clip, in a confusing order


def _gap(x: dict, y: dict) -> float:
    return max(x["start"] - y["end"], y["start"] - x["end"])


def laugh_flags(sents) -> set[int]:
    """Sentences where someone laughs (Whisper writes "haha", "(laughs)", "[Laughter]"…), or right before that."""
    hits = {s["id"] for s in sents if LAUGH.search(s["text"])}
    return hits | {i - 1 for i in hits if i > 0}


def _scout_prompt(info, lines, k, th, n, lim):
    by = f' by {info["uploader"]}' if info.get("uploader") else ""
    return f"""Video: "{info.get("title", "")}"{by}

Transcript. One sentence per line: [sentence_id] start-time text
(😂 = someone laughs here.  🔊 = louder / more energetic.  📈 = YouTube viewers re-watch this part the most.)
{lines}

We're making a "{title_for(th, n)}" countdown. Find up to {k} candidates: {th["look_for"]}.
Each moment is a continuous range of sentences from start_id to end_id (inclusive) lasting {lim.min_seconds}–{lim.max_seconds} seconds: just the setup and the payoff.
label: 2–5 words of on-screen text naming the moment, in the SAME LANGUAGE as the transcript (e.g. "The Burnt Turkey").
score: 1–100 for how {th.get("word", "good")} it is to someone who never saw the video. Be strict: 90+ only for the very best.
Moments must not overlap. Return JSON."""


def _post_prompt(info, th, title, moments):
    rows = "\n\n".join(f"#{m['rank']} ({m['end'] - m['start']:.0f}s), label \"{m['label']}\":\n{m['text']}"
                       for m in moments)
    return f"""Video: "{info.get("title", "")}". We made the countdown short "{title}" from these moments (in the order shown):

{rows}

Write, in the SAME LANGUAGE as the moments:
- caption: the post description, 1–2 short sentences plus a question that makes people comment (which one was best?).
- hashtags: 4–6 relevant hashtags (with #).
- moments: one item per moment, in the same order: label (2–5 words, punchy, specific to that moment), emphasis (up to
  3 single words from it that carry the punch) and emoji (up to 2 items {{"word", "emoji"}}: a word from it and ONE
  emoji that pops up when it is said).
Return JSON."""


def pick_top(cfg: Settings, info: dict, transcript: dict, progress=lambda p, m: None, log=print, env=None,
             rank=None) -> dict:
    """The countdown: one clip whose "segments" are the ranked moments, worst first (#n … #1).
    rank: when the AI can see (vision.ranker), how the best candidates look counts in the order too."""
    from .llm import LLM, ContextTooSmall
    th, n, lim = theme(cfg.top_theme), max(2, min(10, int(cfg.top_count or 3))), _limits(cfg)
    from .picker import focus_of
    if focus_of(cfg):                                   # the creator's instruction narrows what counts
        th = {**th, "look_for": f'{th["look_for"]}, and only moments about: {focus_of(cfg)}'}
    words = transcript["words"]
    if not words:
        raise RuntimeError("No speech found in this video, so there's nothing to rank.")
    sents = build_sentences(words)
    loud, laughs = _energy_flags(sents, env), laugh_flags(sents)
    heat = _heat_by_sentence(sents, info.get("heatmap"))
    hot = set()
    if heat:
        hv = sorted(heat)
        thr = max(hv[int(len(hv) * 0.85)], 0.3)
        hot = {i for i, v in enumerate(heat) if v >= thr}
    if th.get("laughter") and laughs:
        log(f"  laughter in {len(laughs)} places")

    llm = LLM(cfg, log)
    llm.wait_ready(progress=lambda m: progress(0.02, m))
    log(f"AI: {llm.model or '(server default)'} at {llm.base}")
    k = max(n + 3, min(15, n * 4))
    limit = llm.budget_chars(out_tokens=180 * k + 400)
    chunks, cur, size = [], [], 0
    for s in sents:
        marks = ("😂 " if s["id"] in laughs else "") + ("🔊 " if s["id"] in loud else "") + \
                ("📈 " if s["id"] in hot else "")
        line = f"[{s['id']}] {mmss(s['s'])} {marks}{s['text']}"
        if cur and size + len(line) > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append(cur)

    cands, queue, done = [], list(chunks), 0
    per = max(3, min(k, round(k / len(chunks)) + 2))
    while queue:
        chunk = queue.pop(0)
        progress(0.05 + 0.6 * done / (done + len(queue) + 1),
                 f"AI is looking for the {th['name'].lower()} moments… ({done + 1}/{done + len(queue) + 1})")
        t0 = time.time()
        try:
            out = llm.json(SYSTEM, _scout_prompt(info, "\n".join(chunk), per, th, n, lim), SCOUT_SCHEMA,
                           max_tokens=180 * per + 400, temperature=0.4)
        except ContextTooSmall:
            if len(chunk) < 4:
                raise RuntimeError("The AI's context window is too small for even a few lines of transcript.")
            queue[:0] = [chunk[:len(chunk) // 2], chunk[len(chunk) // 2:]]
            continue
        done += 1
        log(f"Scout pass {done}: {len(out.get('moments', []))} candidates in {time.time() - t0:.0f}s")
        cands.extend(out.get("moments", []))

    scored = []
    for c in cands:
        try:
            a, b = _fit(sents, int(c["start_id"]), int(c["end_id"]), lim)
        except (KeyError, ValueError, TypeError):
            continue
        if sents[b]["e"] - sents[a]["s"] < lim.min_seconds * 0.5:
            continue
        ids = set(range(a, b + 2))                       # the sentence after: the laugh often comes right after
        bonus = (12 if th.get("laughter") and ids & laughs else 0) + (5 if ids & loud else 0)
        if heat:
            bonus += round(10 * max(heat[a: b + 1] or [0]))
        scored.append({"a": a, "b": b, "start": sents[a]["s"], "end": sents[b]["e"], "label": str(c.get("label", "")),
                       "why": str(c.get("why", "")), "score": int(c.get("score", 50)) + bonus})
    scored.sort(key=lambda x: -x["score"])
    if rank is not None and scored:           # a funny moment has to look funny too
        k = n + 2
        scored = rank(scored[:k]) + scored[k:]
    best: list[dict] = []
    for apart in (MIN_APART, 0.0):            # moments far apart first; neighbours only if there aren't enough
        for c in scored:
            if len(best) < n and c not in best and all(_overlap(c, b) < 0.15 and _gap(c, b) >= apart for b in best):
                best.append(c)
    if not best:
        raise RuntimeError(f"The AI didn't find any {th['name'].lower()} moments in this video. Try another theme.")
    if len(best) < n:
        log(f"  only found {len(best)} good moments, so it's a top {len(best)}")
    n = len(best)

    lang = transcript.get("language", "en")
    segs = []
    for rank, c in zip(range(n, 0, -1), reversed(best)):  # countdown: the best one comes last
        seg = _finalize(sents, words, c["a"], c["b"], lim, lang)
        seg.update(rank=rank, label=c["label"].strip().strip('"')[:40] or f"Number {rank}", score=c["score"],
                   why=c["why"], text=" ".join(w["w"] for w in words[seg["i0"]: seg["i1"]]))
        if c.get("look") is not None:
            seg["look"] = c["look"]
        segs.append(seg)
        log(f"  #{rank} {mmss(seg['start'])}–{mmss(seg['end'])} score {c['score']}: {seg['label']}")

    title = title_for(th, n)
    progress(0.8, "Writing the labels and the post…")
    caption, hashtags = "", list(th.get("hashtags") or [])
    try:
        post = llm.json(SYSTEM, _post_prompt(info, th, title, segs), POST_SCHEMA, max_tokens=1200, temperature=0.5)
        caption, hashtags = tidy_post(str(post.get("caption", "")), [*(post.get("hashtags") or []), *hashtags])
        for seg, m in zip(segs, post.get("moments") or []):
            if str(m.get("label", "")).strip():
                seg["label"] = str(m["label"]).strip().strip('"')[:40]
            seg["emphasis"] = [str(e) for e in m.get("emphasis") or []][:3]
            seg["emoji"] = [e for e in m.get("emoji") or [] if isinstance(e, dict)][:2]
    except Exception as e:                               # the countdown still works without them
        log(f"Couldn't write the post text ({e}); using the theme's")
    for seg in segs:
        seg.pop("text", None)
    return {"format": "top", "theme": th["id"], "segments": segs, "title": title, "caption": caption,
            "hashtags": hashtags, "score": round(sum(s["score"] for s in segs) / n),
            "why": f"{n} {th['name'].lower()} moments", "start": segs[0]["start"], "end": segs[-1]["end"],
            "i0": 0, "i1": 0, "teaser": None,
            "emphasis": [e for s in segs for e in s.get("emphasis", [])],
            "emoji": [e for s in segs for e in s.get("emoji", [])]}


def from_visual(cfg: Settings, picks: list[dict]) -> dict:
    """No talking (music, gameplay, sport): the strongest moments by sound and action become the countdown."""
    th, n = theme(cfg.top_theme), max(2, min(10, int(cfg.top_count or 3)))
    best = sorted(picks, key=lambda c: -c.get("score", 0))[:n]
    if not best:
        raise RuntimeError("Couldn't find any moments to rank in this video.")
    best = sorted(best, key=lambda c: c.get("score", 0))  # countdown: the best one comes last
    segs = [{"start": c["start"], "end": c["end"], "i0": 0, "i1": 0, "rank": len(best) - i, "beats": c.get("beats"),
             "label": f"Number {len(best) - i}", "score": c.get("score", 50), "emphasis": [], "emoji": []}
            for i, c in enumerate(best)]
    return {"format": "top", "theme": th["id"], "segments": segs, "title": title_for(th, len(segs)), "caption": "",
            "hashtags": list(th.get("hashtags") or []), "score": round(sum(s["score"] for s in segs) / len(segs)),
            "why": "moments picked by sound and action", "start": segs[0]["start"], "end": segs[-1]["end"],
            "i0": 0, "i1": 0, "teaser": None, "emphasis": [], "emoji": [], "mode": "visual"}
