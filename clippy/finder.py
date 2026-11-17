"""Video Finder: scrape YouTube (via yt-dlp, no API key) and rank videos by how good they are to clip.

Signals per video:
  views/day       – how fast it's blowing up right now
  breakout ×      – views vs. the channel's subscriber count (outliers = viral topics)
  engagement      – (likes + 4×comments) / views
  length fit      – long-form (podcasts, interviews, streams) has the most clippable moments
  replay peaks    – YouTube's "Most replayed" heatmap, when it exists: sharp peaks = obvious clip moments
  license         – Creative Commons = reuse explicitly allowed
"""
from __future__ import annotations

import base64
import json
import math
import subprocess
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config

NICHES: dict[str, list[str]] = {
    "podcasts": ["podcast full episode", "podcast interview"],
    "interviews": ["interview", "exclusive interview"],
    "challenges": ["challenge video", "last to leave wins", "$10,000 challenge"],
    "streamers": ["stream highlights", "irl stream", "kick stream"],
    "sports": ["sports podcast", "nba podcast", "football podcast"],
    "business": ["business podcast", "entrepreneur interview", "how i made money"],
    "comedy": ["comedy podcast", "stand up comedy special"],
    "motivation": ["motivational speech", "life advice"],
    "debate": ["debate", "heated debate"],
    "true crime": ["true crime podcast", "true crime story"],
    "tech & ai": ["ai podcast", "tech interview"],
    "gaming": ["gaming podcast", "gaming video"],
}

WINDOWS = {"today": 2, "week": 3, "month": 4, "year": 5}
DURATIONS = {"any": None, "short": 1, "medium": 3, "long": 2}

FIELDS = ("id,title,upload_date,timestamp,view_count,like_count,comment_count,channel_follower_count,duration,"
          "channel,channel_id,channel_url,uploader_id,license,heatmap,categories,thumbnail,live_status,age_limit,language")


def finder_dir() -> Path:
    d = config.output_root(config.load()) / "_finder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sp_param(sort: str = "views", window: str | None = "week", duration: str | None = "long", cc: bool = False) -> str:
    """Encode YouTube's search-filter protobuf (the `sp=` URL parameter)."""
    f = bytearray()
    if window in WINDOWS:
        f += bytes([0x08, WINDOWS[window]])
    f += bytes([0x10, 0x01])  # type: video
    if DURATIONS.get(duration or "any"):
        f += bytes([0x18, DURATIONS[duration]])
    if cc:
        f += bytes([0x30, 0x01])  # Creative Commons
    msg = bytearray()
    s = {"relevance": 0, "date": 2, "views": 3}.get(sort, 3)
    if s:
        msg += bytes([0x08, s])
    msg += bytes([0x12, len(f)]) + f
    return base64.b64encode(bytes(msg)).decode()


def search_url(query: str, **kw) -> str:
    return ("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
            + "&sp=" + urllib.parse.quote(sp_param(**kw)))


def _flat(url: str, limit: int) -> list[dict]:
    r = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", "--playlist-end", str(limit), url],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    try:
        return [e for e in json.loads(r.stdout).get("entries") or [] if e and e.get("id")]
    except json.JSONDecodeError:
        return []


def _enrich(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    r = subprocess.run(["yt-dlp", "--skip-download", "--no-warnings", "--ignore-errors", "--no-playlist",
                        "--print", "%(.{" + FIELDS + "})j"] + [f"https://www.youtube.com/watch?v={i}" for i in ids],
                       capture_output=True, text=True, timeout=60 + 20 * len(ids))
    out = []
    for line in r.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _channel_subs(cids: list[str]) -> dict[str, int]:
    """Subscriber counts read from the channel page. yt-dlp sometimes drops the K/M suffix on the
    watch page ("21.5M" → 215), which would fake huge breakout scores — the channel page is reliable."""
    f = finder_dir() / "channels.json"
    try:
        cache = json.loads(f.read_text())
    except Exception:
        cache = {}
    now = time.time()
    todo = [c for c in dict.fromkeys(cids) if c and (c not in cache or now - cache[c]["t"] > 86400)]

    def one(cid):
        try:
            r = subprocess.run(["yt-dlp", "--flat-playlist", "--no-warnings", "--playlist-end", "1", "-J",
                                f"https://www.youtube.com/channel/{cid}"], capture_output=True, text=True, timeout=60)
            subs = json.loads(r.stdout).get("channel_follower_count") if r.returncode == 0 else None
        except Exception:
            subs = None
        return cid, subs

    if todo:
        with ThreadPoolExecutor(6) as ex:
            for cid, subs in ex.map(one, todo):
                if subs:
                    cache[cid] = {"subs": int(subs), "t": now}
        try:
            f.write_text(json.dumps(cache))
        except Exception:
            pass
    return {c: cache[c]["subs"] for c in cids if c in cache}


def _fix_subs(vids: list[dict]) -> None:
    sus = [v for v in vids if v.get("channel_id") and v.get("view_count")
           and (not v.get("channel_follower_count") or v["channel_follower_count"] < 2000
                or v["view_count"] / max(1, v["channel_follower_count"]) > 50)]
    if not sus:
        return
    real = _channel_subs([v["channel_id"] for v in sus])
    for v in sus:
        if real.get(v["channel_id"]):
            v["channel_follower_count"] = real[v["channel_id"]]


def _len_fit(sec: float) -> float:
    m = (sec or 0) / 60
    if m < 4:
        return 0.15
    if m < 10:
        return 0.55
    if m < 20:
        return 0.85
    if m <= 200:
        return 1.0
    return 0.75


def heat_bumps(vals: list[float]) -> list[float]:
    """Most-replayed values minus the natural drop-off curve (everyone watches the intro, then people leave),
    so only real re-watch spikes remain. Returns 0..1 per point (1 = biggest spike)."""
    n = len(vals)
    if n < 10:
        return [0.0] * n
    w = max(4, n // 12)
    bumps = []
    for i, v in enumerate(vals):
        window = sorted(vals[max(0, i - w): i + w + 1])
        trend = window[len(window) // 2]
        bumps.append(max(0.0, v - trend))
    skip = max(2, int(n * 0.04))  # intro is always "hot" — ignore it
    for i in range(min(skip, n)):
        bumps[i] = 0.0
    top = max(bumps) or 1.0
    return [b / top for b in bumps]


def _heat_peak(heat) -> float | None:
    """How 'spiky' the Most-replayed graph is (0..1). Sharp peaks = obvious viral moments."""
    if not heat:
        return None
    vals = [h.get("value", 0) for h in heat if isinstance(h, dict)]
    if len(vals) < 10:
        return None
    raw = [max(0.0, v - sorted(vals)[len(vals) // 2]) for v in vals]
    b = heat_bumps(vals)
    spike = max((r for r, x in zip(raw, b) if x >= 0.99), default=0.0)
    return max(0.0, min(1.0, spike / 0.35))


def _pct_rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    n = max(1, len(values) - 1)
    for r, i in enumerate(order):
        ranks[i] = r / n
    return ranks


def score_videos(vids: list[dict], now: float | None = None) -> list[dict]:
    now = now or time.time()
    rows = []
    for v in vids:
        views = v.get("view_count") or 0
        if not views or v.get("live_status") in ("is_live", "is_upcoming"):
            continue
        ts = v.get("timestamp")
        if not ts and v.get("upload_date"):
            try:
                ts = time.mktime(time.strptime(v["upload_date"], "%Y%m%d"))
            except ValueError:
                ts = None
        days = max(0.25, (now - ts) / 86400) if ts else None
        subs = v.get("channel_follower_count") or 0
        likes = v.get("like_count") or 0
        comments = v.get("comment_count") or 0
        rows.append({
            **{k: v.get(k) for k in ("id", "title", "channel", "channel_url", "duration", "thumbnail", "upload_date",
                                     "categories", "license", "niche", "query", "language")},
            "views": views, "likes": likes, "comments": comments, "subs": subs, "days": days,
            "vpd": views / days if days else views / 30,
            "breakout": views / max(subs, 1000) if subs else None,
            "engagement": (likes + 4 * comments) / views if views else 0,
            "len_fit": _len_fit(v.get("duration") or 0),
            "heat": _heat_peak(v.get("heatmap")),
            "cc": "creative commons" in str(v.get("license") or "").lower(),
            "heatmap": [round(h.get("value", 0), 3) for h in (v.get("heatmap") or [])][:120],
        })
    if not rows:
        return []
    pv = _pct_rank([math.log10(r["vpd"] + 1) for r in rows])
    pb = _pct_rank([math.log10((r["breakout"] or 0.05) + 0.01) for r in rows])
    pe = _pct_rank([r["engagement"] for r in rows])
    for i, r in enumerate(rows):
        heat = r["heat"] if r["heat"] is not None else 0.4
        s = 100 * (0.40 * pv[i] + 0.25 * pb[i] + 0.13 * pe[i] + 0.14 * r["len_fit"] + 0.08 * heat)
        if r["cc"]:
            s += 6
        r["score"] = int(round(max(0, min(100, s))))
        why = []
        if pv[i] >= 0.8:
            why.append(f"🔥 {fmt_num(r['vpd'])} views/day")
        if r["breakout"] and r["breakout"] >= 3:
            why.append(f"🚀 {r['breakout']:.0f}× channel size")
        if pe[i] >= 0.8:
            why.append("💬 very high engagement")
        if r["heat"] and r["heat"] >= 0.5:
            why.append("📈 sharp replay peaks")
        if r["cc"]:
            why.append("✅ CC licence: reuse allowed")
        if (r["duration"] or 0) >= 1200:
            why.append(f"⏱ {int(r['duration'] // 60)} min of material")
        r["why"] = why
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def fmt_num(n: float) -> str:
    n = float(n or 0)
    for unit, d in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= d:
            return f"{n / d:.1f}".rstrip("0").rstrip(".") + unit
    return str(int(n))


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {}
    by_niche: dict[str, list[int]] = {}
    by_channel: dict[str, list[dict]] = {}
    for r in rows:
        by_niche.setdefault(r.get("niche") or "custom", []).append(r["score"])
        by_channel.setdefault(r.get("channel") or "?", []).append(r)
    vpds = sorted(r["vpd"] for r in rows)
    niches = sorted(({"niche": k, "avg": round(sum(v) / len(v)), "count": len(v), "best": max(v)}
                     for k, v in by_niche.items()), key=lambda x: -x["avg"])
    channels = sorted(({"channel": k, "videos": len(v), "best": max(x["score"] for x in v),
                        "views": sum(x["views"] for x in v), "url": v[0].get("channel_url")}
                       for k, v in by_channel.items()), key=lambda x: (-x["best"], -x["views"]))[:10]
    return {"scanned": len(rows), "median_vpd": vpds[len(vpds) // 2], "top_vpd": vpds[-1],
            "cc_count": sum(1 for r in rows if r["cc"]), "breakouts": sum(1 for r in rows if (r["breakout"] or 0) >= 3),
            "niches": niches, "channels": channels}


def load_watchlist() -> list[str]:
    f = finder_dir() / "watchlist.json"
    try:
        return json.loads(f.read_text())
    except Exception:
        return []


def save_watchlist(items: list[str]) -> list[str]:
    clean = []
    for x in items:
        x = str(x).strip()
        if not x:
            continue
        if x.startswith("@"):
            x = "https://www.youtube.com/" + x
        if x not in clean:
            clean.append(x)
    (finder_dir() / "watchlist.json").write_text(json.dumps(clean, indent=2))
    return clean


def scan(niches: list[str], keywords: str = "", window: str = "week", duration: str = "long", cc_only: bool = False,
         use_watchlist: bool = True, per_query: int = 25, enrich_top: int = 60, lang: str = "en",
         progress=lambda p, m: None, watchlist: list[str] | None = None, save_latest: bool = True) -> dict:
    """Run a full scan and save it as the latest leaderboard."""
    queries: list[tuple[str, str]] = []
    for n in niches:
        for q in NICHES.get(n, []):
            queries.append((n, q))
    for kw in [k.strip() for k in (keywords or "").split(",") if k.strip()]:
        queries.append(("custom", kw))
    watch = list(watchlist) if watchlist is not None else (load_watchlist() if use_watchlist else [])
    if not queries and not watch:
        queries = [("podcasts", q) for q in NICHES["podcasts"]]
    if watchlist is not None and not niches and not keywords:
        queries = []  # profile with only source channels: don't search the rest of YouTube

    found: dict[str, dict] = {}
    lock = threading.Lock()
    done = [0]
    total = len(queries) + len(watch)

    def run_query(item):
        niche, q = item
        if niche == "_watch":
            url = q.rstrip("/") + ("/videos" if "/videos" not in q and "watch?" not in q else "")
            entries = _flat(url, 15)
        else:
            entries = _flat(search_url(q, sort="views", window=window, duration=duration, cc=cc_only), per_query)
        with lock:
            for e in entries:
                if e["id"] not in found:
                    found[e["id"]] = {**e, "niche": "watchlist" if niche == "_watch" else niche, "query": q}
            done[0] += 1
            progress(0.45 * done[0] / max(1, total), f"Searching YouTube… {done[0]}/{total} ({len(found)} videos)")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run_query, queries + [("_watch", w) for w in watch]))

    # cheap pre-filter on what the search page already tells us
    min_dur = {"long": 1200, "medium": 240}.get(duration, 180)
    cands = [e for e in found.values()
             if (e.get("duration") or 0) >= (min_dur if e.get("niche") != "watchlist" else min(min_dur, 240))
             and (e.get("view_count") or 0) > 0 and e.get("live_status") not in ("is_live", "is_upcoming")]
    cands.sort(key=lambda e: -(e.get("view_count") or 0))
    # keep variety: best few per niche first, then fill by views
    picked, per_niche = [], {}
    for e in cands:
        k = e["niche"]
        if per_niche.get(k, 0) < max(4, enrich_top // max(1, len(set(x["niche"] for x in cands)))):
            picked.append(e)
            per_niche[k] = per_niche.get(k, 0) + 1
        if len(picked) >= enrich_top:
            break
    for e in cands:
        if len(picked) >= enrich_top:
            break
        if e not in picked:
            picked.append(e)

    # full details (dates, likes, subs, heatmap) in 4 parallel yt-dlp workers
    progress(0.5, f"Reading stats for {len(picked)} videos…")
    batches = [picked[i::4] for i in range(4)]
    meta: dict[str, dict] = {}
    got = [0]

    def run_batch(batch):
        for i in range(0, len(batch), 4):
            part = batch[i:i + 4]
            for m in _enrich([e["id"] for e in part]):
                with lock:
                    meta[m["id"]] = m
                    got[0] += 1
                    progress(0.5 + 0.48 * got[0] / max(1, len(picked)), f"Reading stats… {got[0]}/{len(picked)}")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run_batch, batches))

    merged = []
    for e in picked:
        m = meta.get(e["id"])
        if m:
            merged.append({**e, **{k: v for k, v in m.items() if v not in (None, "NA")}})
    if lang and lang != "any":
        merged = [m for m in merged if not m.get("language") or str(m["language"]).lower().startswith(lang)]
    progress(0.97, "Double-checking channel sizes…")
    _fix_subs(merged)
    rows = score_videos(merged)
    lib = config.output_root(config.load())
    for r in rows:
        r["clipped"] = (lib / r["id"] / "result.json").exists()
    result = {"created": int(time.time()), "params": {"niches": niches, "keywords": keywords, "window": window,
                                                      "duration": duration, "cc_only": cc_only, "lang": lang},
              "stats": _stats(rows), "videos": rows}
    if save_latest:
        d = finder_dir()
        (d / "latest.json").write_text(json.dumps(result, ensure_ascii=False))
        (d / f"scan-{result['created']}.json").write_text(json.dumps(result, ensure_ascii=False))
    progress(1.0, f"Ranked {len(rows)} videos")
    return result


def latest() -> dict | None:
    f = finder_dir() / "latest.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text())
    lib = config.output_root(config.load())
    for r in data.get("videos", []):
        r["clipped"] = (lib / r["id"] / "result.json").exists()
    return data
