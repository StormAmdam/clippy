"""Autopilot: channel profile → scrape YouTube → pick the best new video → make shorts → review queue → upload.

Everything is stored as JSON in output/_auto/ so it survives restarts.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import config, finder

LOCK = threading.RLock()

PROFILE_DEFAULTS: dict = {
    "name": "My channel",
    "niches": ["podcasts"],
    "keywords": "",
    "sources": [],                 # channels you have permission to clip (or clipping campaigns)
    "source_mode": "safe",         # safe = only your source channels + Creative Commons videos | any
    "language": "en",
    "window": "week",
    "duration": "long",
    "videos_per_run": 1,
    "clips_per_video": 3,
    "min_seconds": 20,
    "max_seconds": 60,
    "caption_style": "beast",
    "highlight_color": "#FFE135",
    "auto_every_hours": 0,         # 0 = only when you press Run
    "youtube": True,
    "tiktok": False,
    "privacy": "public",           # public | unlisted | private
    "spacing_hours": 0,            # 0 = publish right after approval; N = schedule one short every N hours
    "category_id": "24",           # 24 Entertainment, 22 People & Blogs, 17 Sports, 28 Science & Tech
    "extra_hashtags": "",
    "description_template": "{caption}\n\n{hashtags} #Shorts\n\n🎥 Credit: {source_channel} — {source_url}",
    "last_run": 0,
    "last_publish_at": 0,
    "used": [],
}


def auto_dir() -> Path:
    d = config.output_root(config.load()) / "_auto"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(name: str, default):
    f = auto_dir() / name
    try:
        return json.loads(f.read_text())
    except Exception:
        return default


def _write(name: str, data) -> None:
    f = auto_dir() / name
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, f)


# ───────────────────────── profiles ─────────────────────────

def list_profiles() -> list[dict]:
    with LOCK:
        return [{**PROFILE_DEFAULTS, **p} for p in _read("profiles.json", [])]


def get_profile(pid: str) -> dict:
    for p in list_profiles():
        if p["id"] == pid:
            return p
    raise KeyError(f"Unknown profile {pid}")


def save_profile(data: dict) -> dict:
    with LOCK:
        profiles = _read("profiles.json", [])
        pid = data.get("id") or uuid.uuid4().hex[:8]
        existing = next((p for p in profiles if p["id"] == pid), {})
        merged = {**PROFILE_DEFAULTS, **existing, **{k: v for k, v in data.items() if k in PROFILE_DEFAULTS}, "id": pid}
        merged["sources"] = _clean_channels(merged["sources"])
        merged["niches"] = [n for n in merged["niches"] if n in finder.NICHES]
        for k in ("videos_per_run", "clips_per_video", "min_seconds", "max_seconds"):
            merged[k] = max(1, int(merged[k]))
        merged["auto_every_hours"] = max(0.0, float(merged["auto_every_hours"]))
        merged["spacing_hours"] = max(0.0, float(merged["spacing_hours"]))
        profiles = [p for p in profiles if p["id"] != pid] + [merged]
        _write("profiles.json", profiles)
        return merged


def _clean_channels(items) -> list[str]:
    if isinstance(items, str):
        items = re.split(r"[\n,]", items)
    out = []
    for x in items or []:
        x = str(x).strip()
        if not x:
            continue
        if x.startswith("@"):
            x = "https://www.youtube.com/" + x
        if x not in out:
            out.append(x)
    return out


def _update_profile(pid: str, **fields) -> None:
    with LOCK:
        profiles = _read("profiles.json", [])
        for p in profiles:
            if p["id"] == pid:
                p.update(fields)
        _write("profiles.json", profiles)


def delete_profile(pid: str) -> None:
    with LOCK:
        _write("profiles.json", [p for p in _read("profiles.json", []) if p["id"] != pid])


# ───────────────────────── review queue ─────────────────────────

def review_items(status: str | None = None) -> list[dict]:
    with LOCK:
        items = _read("review.json", [])
    if status:
        wanted = set(status.split(","))
        items = [i for i in items if i["status"] in wanted]
    return sorted(items, key=lambda i: -i["created"])


def get_item(iid: str) -> dict:
    for i in review_items():
        if i["id"] == iid:
            return i
    raise KeyError(iid)


def update_item(iid: str, **fields) -> dict:
    with LOCK:
        items = _read("review.json", [])
        for i in items:
            if i["id"] == iid:
                i.update(fields)
                _write("review.json", items)
                return i
    raise KeyError(iid)


def _add_items(new: list[dict]) -> None:
    with LOCK:
        _write("review.json", _read("review.json", []) + new)


def render_description(profile: dict, item: dict) -> str:
    tags = " ".join(item.get("hashtags") or [])
    extra = " ".join(h if h.startswith("#") else "#" + h for h in profile.get("extra_hashtags", "").split() if h)
    text = profile.get("description_template") or PROFILE_DEFAULTS["description_template"]
    out = (text.replace("{caption}", item.get("caption") or "")
               .replace("{hashtags}", (tags + " " + extra).strip())
               .replace("{source_channel}", item.get("source_channel") or "")
               .replace("{source_url}", item.get("source_url") or "")
               .replace("{title}", item.get("title") or ""))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


# ───────────────────────── the run ─────────────────────────

def _eligible(row: dict, profile: dict) -> bool:
    if profile.get("source_mode") == "any":
        return True
    return bool(row.get("cc")) or row.get("niche") == "watchlist"


def _licence(row: dict) -> str:
    if row.get("cc"):
        return "cc"
    if row.get("niche") == "watchlist":
        return "source"
    return "unknown"


def run_profile(pid: str, run_pipeline, progress=lambda stage, pct, msg: None, log=print) -> dict:
    """Scrape → rank → pick the best unused video(s) → make shorts → add them to the review queue."""
    try:
        return _run_profile(pid, run_pipeline, progress, log)
    finally:
        _update_profile(pid, last_run=time.time())   # failed or cancelled runs also wait for the next slot


def _run_profile(pid: str, run_pipeline, progress, log) -> dict:
    p = get_profile(pid)
    log(f"🤖 Autopilot: {p['name']}")
    progress("scan", 0.0, "Scanning YouTube for the best videos…")
    res = finder.scan(p["niches"], p["keywords"], p["window"], p["duration"],
                      cc_only=p["source_mode"] == "safe", watchlist=p["sources"], lang=p["language"],
                      save_latest=False, progress=lambda f, m: progress("scan", 0.2 * f, m))
    rows = res.get("videos", [])
    used = set(p.get("used", []))
    cands = [r for r in rows if r["id"] not in used and _eligible(r, p) and 0 < (r.get("duration") or 0) <= 4 * 3600]
    log(f"  ranked {len(rows)} videos, {len(cands)} new & eligible")
    if not cands:
        hint = (" Add source channels to this profile or widen the time window."
                if p["source_mode"] == "safe" else " Try other niches or a wider time window.")
        raise RuntimeError("No new eligible videos found." + hint)
    chosen = cands[: p["videos_per_run"]]
    total_clips = 0
    root = config.output_root(config.load())
    for vi, r in enumerate(chosen):
        url = "https://www.youtube.com/watch?v=" + r["id"]
        log(f"  ▶ [{r['score']}] {r['title']}  ({r.get('channel')})")
        lo, span = 0.2 + 0.8 * vi / len(chosen), 0.8 / len(chosen)
        overrides = {"clips": p["clips_per_video"], "min_seconds": p["min_seconds"], "max_seconds": p["max_seconds"],
                     "caption_style": p["caption_style"], "highlight_color": p["highlight_color"],
                     "clips_dir": f"clips-{pid}"}
        summary = run_pipeline(url, overrides,
                               on_progress=lambda st, f, m: progress("render", lo + span * f,
                                                                    f"Video {vi + 1}/{len(chosen)}: {m}"),
                               log=log)
        items = []
        for c in summary["clips"]:
            item = {"id": uuid.uuid4().hex[:10], "profile_id": pid, "profile_name": p["name"], "status": "pending",
                    "created": time.time(), "video_id": r["id"], "source_title": r.get("title"),
                    "source_channel": r.get("channel") or summary.get("uploader"), "source_url": url,
                    "licence": _licence(r), "video_score": r.get("score"), "file": c["file"], "thumb": c.get("thumb"),
                    "duration": c.get("duration"), "score": c.get("score"), "title": c.get("title") or "",
                    "caption": c.get("caption") or "", "hashtags": c.get("hashtags") or [],
                    "youtube": None, "tiktok": None, "error": None}
            item["description"] = render_description(p, item)
            items.append(item)
        _add_items(items)
        total_clips += len(items)
        p = get_profile(pid)
        _update_profile(pid, used=(p.get("used", []) + [r["id"]])[-500:])
    notify("Clippy", f"{total_clips} new shorts for “{p['name']}” are waiting for your review")
    progress("done", 1.0, f"{total_clips} shorts ready for review")
    return {"profile": pid, "videos": [c["id"] for c in chosen], "clips": total_clips}


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "-a", "Clippy", title, body], timeout=5)
        except Exception:
            pass


# ───────────────────────── after approval ─────────────────────────

def next_publish_slot(profile: dict) -> float | None:
    """None = publish now. Otherwise a unix time, spaced `spacing_hours` apart."""
    hours = float(profile.get("spacing_hours") or 0)
    if hours <= 0:
        return None
    slot = max(time.time() + 15 * 60, float(profile.get("last_publish_at") or 0) + hours * 3600)
    _update_profile(profile["id"], last_publish_at=slot)
    return slot


def export_tiktok(item: dict, profile: dict) -> str:
    root = config.output_root(config.load())
    dest = auto_dir() / "tiktok" / re.sub(r"[^\w-]+", "-", profile["name"]).strip("-")
    dest.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w-]+", "-", item.get("title") or "short").strip("-").lower()[:50]
    target = dest / f"{time.strftime('%Y%m%d')}-{slug}-{item['id'][:4]}.mp4"
    shutil.copy2(root / item["file"], target)
    caption = (item.get("caption") or item.get("title") or "") + "\n\n" + " ".join(item.get("hashtags") or [])
    if item.get("source_channel"):
        caption += f"\n\nCredit: {item['source_channel']}"
    target.with_suffix(".txt").write_text(caption.strip() + "\n")
    return str(target.relative_to(root))
