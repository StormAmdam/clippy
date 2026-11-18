"""Local web app:  ./clippy.sh web   →  http://127.0.0.1:7860"""
from __future__ import annotations

import argparse
import ipaddress
import json
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .jobs import Cancelled, JobStore

STATIC = Path(__file__).parent / "static"
OUT = config.output_root(config.load())
OUT.mkdir(parents=True, exist_ok=True)

STORE = JobStore(OUT / "_jobs.json")
QUEUE: "queue.Queue[str]" = queue.Queue()


@asynccontextmanager
async def lifespan(app):
    # background workers start with the web server (not on import, so tests stay quiet)
    for target in (_worker, _scheduler, _publisher):
        threading.Thread(target=target, daemon=True).start()
    yield


app = FastAPI(title="Clippy", lifespan=lifespan)

BIND_HOST = "127.0.0.1"     # main() sets this to --host, so a hostname you serve on is trusted too
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _trusted_host(host: str) -> bool:
    """IP addresses, localhost and *.local can't be pointed here by another website (DNS rebinding)."""
    name = (urlsplit("//" + host).hostname or "").rstrip(".")
    if name in ("localhost", BIND_HOST) or name.endswith((".localhost", ".local")):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


@app.middleware("http")
async def only_own_pages(request: Request, call_next):
    """Clippy can publish to your channels, so only its own pages may use it."""
    host = request.headers.get("host", "")
    if not _trusted_host(host):
        return JSONResponse({"detail": "Open Clippy at http://127.0.0.1 instead."}, status_code=403)
    origin = request.headers.get("origin")
    if request.method not in SAFE_METHODS and origin is not None and urlsplit(origin).netloc != host:
        return JSONResponse({"detail": "Only Clippy's own pages can do that."}, status_code=403)
    return await call_next(request)


class JobIn(BaseModel):
    url: str
    options: dict = {}


def _new_job(**fields) -> dict:
    job = STORE.create(position=QUEUE.qsize(), **fields)
    QUEUE.put(job["id"])
    return job


def _run_job(jid: str) -> None:
    """Run one job to completion (or cancel/error) and record the outcome."""
    from . import pipeline
    if not STORE.start(jid):                  # gone, or cancelled while waiting
        return
    job = STORE.get(jid)
    prog, log = STORE.progress_fn(jid), STORE.log_fn(jid)
    on_info = lambda info: STORE.update(jid, title=info.get("title") or "")   # history shows a name, not a URL
    try:
        if job["kind"] == "auto":
            from .autopilot import run_profile
            result = run_profile(job["profile_id"], pipeline.run, prog, log)
        else:
            result = pipeline.run(job["url"], job["options"], prog, log, on_info=on_info)
        STORE.update(jid, state="done", result=result, finished=time.time())
    except Cancelled:
        STORE.update(jid, state="cancelled", msg="Cancelled", finished=time.time())
    except Exception as e:
        log(traceback.format_exc())
        STORE.update(jid, state="error", error=str(e), finished=time.time())


def _worker():
    """One job at a time: the GPU, CPU and the local LLM are shared resources."""
    while True:
        _run_job(QUEUE.get())

ALLOWED = {"clips", "min_seconds", "max_seconds", "highlight_color", "title_seconds", "remove_silences",
           "split_screen", "punch_in", "reuse_picks", "words_per_caption", "caption_y", "caption_style",
           "caption_scale", "sfx", "sfx_volume", "motion", "teaser", "emojis", "progress_bar", "speech",
           "format", "top_theme", "top_count", "top_min", "top_max"}


@app.post("/api/jobs")
def create_job(body: JobIn):
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "Paste a YouTube link first")
    job = _new_job(url=url, options={k: v for k, v in body.options.items() if k in ALLOWED})
    return {"id": job["id"]}


@app.post("/api/upload")
async def upload_video(request: Request, name: str = ""):
    """A video from this computer: the browser sends the file itself as the request body (?name=its file name)."""
    from . import uploads
    try:
        return await uploads.receive(request, name, OUT)
    except uploads.UploadError as e:
        raise HTTPException(400, str(e))


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = STORE.get(jid)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    job = STORE.get(jid)
    if not job:
        raise HTTPException(404, "Unknown job")
    ok = STORE.request_cancel(jid)
    return {"ok": ok, "state": STORE.get(jid)["state"]}


@app.get("/api/jobs")
def list_jobs():
    return [{k: v for k, v in j.items() if k != "log"} for j in STORE.all()]


@app.get("/api/library")
def library():
    items = []
    for res in OUT.glob("*/result.json"):
        if res.parent.name in config.INTERNAL_DIRS:
            continue
        try:
            data = json.loads(res.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["clips"] = [c for c in data.get("clips", []) if (OUT / c["file"]).exists()]
        if data["clips"]:
            items.append(data)
    return sorted(items, key=lambda d: -d.get("created", 0))


# ───────────────────────── storage ─────────────────────────

BUSY_REVIEW = ("pending", "approved", "uploading")


@app.get("/api/storage")
def storage_usage():
    from . import storage
    return storage.usage(OUT)


def _job_live() -> bool:
    return any(j["state"] in ("queued", "running") for j in STORE.all())


@app.post("/api/storage/{vid}/source/delete")
def storage_delete_source(vid: str):
    from . import storage
    if _job_live():   # the job may be re-rendering from this very download
        raise HTTPException(409, "A job is running — try again when it has finished.")
    try:
        return {"freed": storage.delete_source(OUT, vid)}
    except storage.FileInUse as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/storage/{vid}")
def storage_delete_project(vid: str):
    from . import autopilot, storage
    if any(i["file"].startswith(vid + "/") for i in autopilot.review_items(",".join(BUSY_REVIEW))):
        raise HTTPException(409, "Shorts from this video are still waiting or publishing — finish or reject them first.")
    if _job_live():
        raise HTTPException(409, "A job is running — try again when it has finished.")
    try:
        return {"freed": storage.delete_project(OUT, vid)}
    except storage.FileInUse as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


class CleanupIn(BaseModel):
    days: int = 7


@app.post("/api/storage/cleanup")
def storage_cleanup(body: CleanupIn):
    from . import storage
    if any(j["state"] == "running" for j in STORE.all()):
        raise HTTPException(409, "A job is running — try again when it has finished.")
    return {"freed": storage.cleanup_sources(OUT, max(0, body.days))}


def _public_settings() -> dict:
    d = config.load().to_dict()
    d["has_llm_api_key"] = bool(d.pop("llm_api_key", ""))
    return d


@app.get("/api/settings")
def settings():
    return _public_settings()


@app.post("/api/settings")
def save_settings(body: dict):
    try:
        config.save_ui_settings(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return _public_settings()


@app.get("/api/autostart")
def autostart_status():
    from . import autostart
    return {**autostart.status(), "can_quit": APP["desktop"]}


class AutostartIn(BaseModel):
    enabled: bool


@app.post("/api/autostart")
def autostart_set(body: AutostartIn):
    from . import autostart
    try:
        return autostart.enable() if body.enabled else autostart.disable()
    except Exception as e:
        raise HTTPException(500, str(e))


# ───────────────────────── status & overview (dashboard) ─────────────────────────

_llm_cache = {"t": 0.0, "ok": False, "model": "", "server": "", "error": ""}


UI_SEEN = {"t": 0.0}            # the app window polls /api/status; desktop.py quits when it stops
APP = {"desktop": False, "quit": False}     # desktop.py: Clippy runs as the app, and can quit when asked


def this_computer_only(request: Request) -> None:
    """Some things only the person at this PC may do, even when Clippy is open to the Wi-Fi (--host 0.0.0.0) for a
    phone: installing or trusting extensions (their code would run on this PC) and quitting Clippy."""
    host = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not local:
        raise HTTPException(403, "Only possible on the computer Clippy runs on, not from another device.")


@app.post("/api/quit")
def quit_app(request: Request):
    """The app's Quit button: with Start at login on, closing the window leaves Clippy running in the background."""
    this_computer_only(request)
    if not APP["desktop"]:
        raise HTTPException(400, "Clippy was started from a terminal: stop it there (Ctrl+C).")
    APP["quit"] = True
    return {"ok": True}


def work_in_progress() -> bool:
    """A video being made or waiting its turn (closing the window shouldn't cut it off)."""
    return any(j["state"] in ("queued", "running") for j in STORE.all())


@app.get("/api/status")
def status():
    from . import gpu, llm
    UI_SEEN["t"] = time.time()
    cfg = config.load()
    if time.time() - _llm_cache["t"] > 10:
        try:
            s = llm.resolve(cfg)
            _llm_cache.update(ok=True, model=llm.choose_model(s, cfg.llm_model), server=s.label, error="")
        except RuntimeError as e:
            _llm_cache.update(ok=False, model="", server="", error=str(e))
        _llm_cache["t"] = time.time()
    jobs = STORE.all()
    running = next((j for j in jobs if j["state"] == "running"), None)
    return {"llm": _llm_cache["ok"], "model": _llm_cache["model"], "ai": _llm_cache["server"],
            "folder": str(config.ROOT), "os": "windows" if sys.platform == "win32" else "linux",
            "ai_error": _llm_cache["error"], "vram_free": gpu.free_vram_mb(),
            "queued": sum(1 for j in jobs if j["state"] == "queued"),
            "running": {k: running.get(k) for k in ("id", "kind", "url", "stage", "pct", "msg", "profile_id")} if running else None}


@app.get("/api/ai")
def ai_servers():
    """Every AI server Clippy can see right now, and the one (and model) it would use."""
    from . import llm
    cfg = config.load()
    found = llm.detect()
    using, error = None, ""
    try:
        llm._cache.clear()
        s = llm.resolve(cfg)
        using = {**s.to_dict(), "model": llm.choose_model(s, cfg.llm_model)}
        if all(f.base != s.base for f in found):
            found.insert(0, s)
    except RuntimeError as e:
        error = str(e)
    _llm_cache["t"] = 0.0
    return {"auto": (cfg.llm_url or "auto").lower() == "auto", "servers": [f.to_dict() for f in found],
            "using": using, "error": error, "wsl": llm.wsl()}


class SetupIn(BaseModel):
    id: str = ""
    url: str = ""
    file: str = ""
    mode: str = ""


@app.get("/api/setup")
def setup_status():
    """Everything the AI & Tools page shows: parts, AI models, what's missing, space used."""
    from . import components, engine
    cfg = config.load()
    out = config.output_root(cfg)
    run = engine.ENGINE
    return {"hardware": components.hardware(), "components": components.components(cfg), "models": engine.models(cfg),
            "mode": (cfg.ai_mode or "auto").lower(), "missing": components.missing(cfg), "folder": str(config.ROOT),
            "engine": {"running": run.running(), "model": run.model.stem if run.running() and run.model else ""},
            "everything": components.TASKS["everything"].to_dict() if "everything" in components.TASKS else None,
            "space": {"models": components.folder_size(components.LLM_DIR) + components.folder_size(components.WHISPER_DIR),
                      "tools": components.folder_size(components.BIN) + components.folder_size(components.ENGINE_DIR),
                      "clips": components.folder_size(out)}}


@app.post("/api/setup/install")
def setup_install(body: SetupIn):
    from . import components, engine
    cfg = config.load()
    try:
        if body.url:
            t = engine.install_model(url=body.url)
        elif body.id == "everything":
            t = engine.setup_everything(cfg)
        elif body.id.startswith("model:"):
            t = engine.install_model(body.id[6:])
        else:
            t = components.install(body.id, cfg)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError:
        raise HTTPException(404, "Unknown part")
    return t.to_dict()


@app.post("/api/setup/cancel")
def setup_cancel(body: SetupIn):
    from . import components
    components.cancel(body.id)
    return {"ok": True}


@app.post("/api/setup/remove")
def setup_remove(body: SetupIn):
    from . import components, engine
    cfg = config.load()
    try:
        if body.file:
            engine.remove_model(body.file)
            if cfg.ai_model == Path(body.file).name:
                config.save_ui_settings({"ai_model": ""})
        elif body.id in components.PARTS:
            components.remove(body.id, cfg)
        else:
            raise HTTPException(404, "Unknown part")
    except PermissionError:                     # Windows: a running program has it open
        raise HTTPException(409, "Couldn't remove it because it's in use right now (by a video being made, or "
                                 "another AI app). Try again when Clippy is idle.")
    _llm_cache["t"] = 0.0
    return {"ok": True}


@app.post("/api/setup/use")
def setup_use(body: SetupIn):
    """Use this downloaded model for the built-in AI (it loads the next time clips are picked)."""
    from . import components, engine
    name = Path(body.file).name
    if not (components.LLM_DIR / name).exists():
        raise HTTPException(404, "That model isn't downloaded")
    config.save_ui_settings({"ai_model": name, "ai_mode": "builtin" if config.load().ai_mode == "external" else config.load().ai_mode})
    if engine.ENGINE.running() and engine.ENGINE.model and engine.ENGINE.model.name != name:
        engine.ENGINE.stop()
    _llm_cache["t"] = 0.0
    return {"ok": True}


@app.post("/api/setup/mode")
def setup_mode(body: SetupIn):
    from . import engine
    if body.mode not in ("auto", "builtin", "external"):
        raise HTTPException(400, "mode is auto, builtin or external")
    config.save_ui_settings({"ai_mode": body.mode})
    if body.mode == "external":
        engine.ENGINE.stop()
    _llm_cache["t"] = 0.0
    return {"ok": True}


@app.get("/api/overview")
def overview():
    from . import autopilot
    items = autopilot.review_items()
    week = time.time() - 7 * 86400
    profiles = autopilot.list_profiles()
    nexts = [p["last_run"] + p["auto_every_hours"] * 3600 for p in profiles if p["auto_every_hours"] > 0]
    jobs = STORE.all()[:8]
    return {
        "review": {s: sum(1 for i in items if i["status"] == s)
                   for s in ("pending", "approved", "uploading", "uploaded", "failed", "rejected")},
        "published_week": sum(1 for i in items if i["status"] == "uploaded" and (i.get("uploaded") or 0) > week),
        "profiles": len(profiles), "profiles_auto": sum(1 for p in profiles if p["auto_every_hours"] > 0),
        "next_run": max(min(nexts), time.time()) if nexts else None,
        "library": sum(1 for r in OUT.glob("*/result.json") if r.parent.name not in config.INTERNAL_DIRS),
        "jobs": [{"id": j["id"], "kind": j["kind"], "url": j["url"], "state": j["state"], "created": j["created"],
                  "finished": j.get("finished"), "error": j.get("error"), "msg": j.get("msg"), "pct": j.get("pct"),
                  "title": ((j.get("result") or {}).get("title") or j.get("title")) if j["kind"] == "clip" else None,
                  "clips": len((j.get("result") or {}).get("clips") or []) if j["kind"] == "clip"
                  else (j.get("result") or {}).get("clips")} for j in jobs],
        "uploads": [{k: i.get(k) for k in ("id", "title", "profile_name", "uploaded", "youtube", "thumb")}
                    for i in sorted((i for i in items if i["status"] == "uploaded"),
                                    key=lambda i: -(i.get("uploaded") or 0))[:5]],
    }


# ───────────────────────── updates ─────────────────────────

@app.get("/api/update")
def update_status(request: Request, force: bool = False):
    from . import updates
    try:
        this_computer_only(request)
        local = True
    except HTTPException:
        local = False
    return {**updates.status(force=force), "local": local}


@app.post("/api/update/install")
def update_install(request: Request):
    from . import updates
    this_computer_only(request)
    if work_in_progress() or any(j["state"] == "running" for j in SCANS.values()):   # the update closes Clippy
        raise HTTPException(409, "Clippy is making a video or scanning right now. Update when it's done "
                                 "(the update closes Clippy for a moment).")
    try:
        return updates.install()
    except updates.UpdateError as e:
        raise HTTPException(400, str(e))


# ───────────────────────── looks, countdown themes, extensions ─────────────────────────

BUILTIN_STYLES = [("beast", "Beast", "Comic, bouncy, tilted"), ("hormozi", "Hormozi", "Bold, colored keywords"),
                  ("box", "Box", "Highlight box"), ("clean", "Clean", "Calm and minimal")]


@app.get("/api/styles")
def caption_styles():
    """Every caption style: the built-in ones, then those extensions add."""
    from . import extensions
    out = [{"id": k, "name": n, "about": a, "preview": f"/static/styles/{k}.jpg", "extension": ""}
           for k, n, a in BUILTIN_STYLES]
    out += [{"id": k, "name": v["name"], "about": v["about"], "preview": v["preview"], "extension": v["extension"]}
            for k, v in extensions.caption_styles().items()]
    return out


@app.get("/api/top-themes")
def top_themes():
    from . import top
    return [{"id": k, "name": v["name"], "emoji": v.get("emoji", ""), "title": v.get("title", ""),
             "extension": v.get("extension", "")} for k, v in top.themes().items()]


class ExtensionIn(BaseModel):
    id: str = ""
    url: str = ""
    on: bool = True
    trust: bool = False


def _ext_call(fn, *args, **kwargs):
    from . import extensions
    try:
        return fn(*args, **kwargs)
    except extensions.ExtensionError as e:
        raise HTTPException(400, str(e))
    except OSError as e:                     # e.g. Windows: a file of it is open somewhere
        raise HTTPException(409, f"Couldn't change the extension's files: {e}")


@app.get("/api/extensions")
def extensions_list():
    from . import extensions
    extensions.changed()                     # an extension dropped into the folder by hand shows up
    return {"installed": extensions.installed(), "folder": str(extensions.EXT_DIR)}


@app.get("/api/extensions/catalog")
def extensions_catalog():
    from . import extensions
    return extensions.catalog()


@app.post("/api/extensions/install")
def extensions_install(body: ExtensionIn, request: Request):
    from . import extensions
    this_computer_only(request)
    if body.url:
        return _ext_call(extensions.install_from_url, body.url)
    return _ext_call(extensions.install_from_catalog, body.id)


@app.post("/api/extensions/{ext_id}/enable")
def extensions_enable(ext_id: str, body: ExtensionIn, request: Request):
    from . import extensions
    this_computer_only(request)
    return _ext_call(extensions.set_enabled, ext_id, body.on, body.trust)


@app.delete("/api/extensions/{ext_id}")
def extensions_remove(ext_id: str, request: Request):
    from . import extensions
    this_computer_only(request)
    _ext_call(extensions.remove, ext_id)
    return {"ok": True}


@app.get("/ext/{ext_id}/{rel:path}")
def extension_picture(ext_id: str, rel: str):
    from . import extensions
    f = extensions.file_for_page(ext_id, rel)
    if f is None:
        raise HTTPException(404, "Not found")
    return FileResponse(f)


# ───────────────────────── Video Finder (leaderboard) ─────────────────────────

SCANS: dict[str, dict] = {}


class ScanIn(BaseModel):
    niches: list[str] = []
    keywords: str = ""
    window: str = "week"
    duration: str = "long"
    cc_only: bool = False
    lang: str = "en"
    use_watchlist: bool = True


@app.get("/api/finder/niches")
def finder_niches():
    from .finder import all_niches
    return list(all_niches())


@app.get("/api/finder/latest")
def finder_latest():
    from .finder import latest
    return latest() or {}


@app.post("/api/finder/scan")
def finder_scan(body: ScanIn):
    from .finder import scan
    if any(j["state"] == "running" for j in SCANS.values()):
        raise HTTPException(409, "A scan is already running")
    sid = uuid.uuid4().hex[:8]
    job = {"id": sid, "state": "running", "pct": 0.0, "msg": "Starting…", "result": None, "error": None}
    SCANS[sid] = job

    def work():
        try:
            job["result"] = scan(body.niches, body.keywords, body.window, body.duration, body.cc_only,
                                 body.use_watchlist, lang=body.lang,
                                 progress=lambda p, m: job.update(pct=round(p, 3), msg=m))
            job["state"] = "done"
        except Exception as e:
            job["state"] = "error"
            job["error"] = str(e)

    threading.Thread(target=work, daemon=True).start()
    return {"id": sid}


@app.get("/api/finder/scan/{sid}")
def finder_scan_status(sid: str):
    if sid not in SCANS:
        raise HTTPException(404, "Unknown scan")
    return SCANS[sid]


class WatchIn(BaseModel):
    channels: list[str]


@app.get("/api/finder/watchlist")
def get_watchlist():
    from .finder import load_watchlist
    return load_watchlist()


@app.post("/api/finder/watchlist")
def set_watchlist(body: WatchIn):
    from .finder import save_watchlist
    return save_watchlist(body.channels)


# ───────────────────────── Autopilot: profiles ─────────────────────────

def _auto_job_for(pid: str) -> dict | None:
    for j in STORE.all():
        if j["kind"] == "auto" and j.get("profile_id") == pid and j["state"] in ("queued", "running"):
            return j
    return None


@app.get("/api/auto/profiles")
def auto_profiles():
    from . import autopilot, youtube_upload
    out = []
    items = autopilot.review_items()
    pending = [i for i in items if i["status"] == "pending"]
    for p in autopilot.list_profiles():
        job = _auto_job_for(p["id"])
        last_job = max((j for j in STORE.all() if j.get("profile_id") == p["id"]),
                       key=lambda j: j["created"], default=None)
        nxt = p["last_run"] + p["auto_every_hours"] * 3600 if p["auto_every_hours"] > 0 else None
        out.append({**p, "used_count": len(p.get("used", [])), "used": None,
                    "youtube_status": youtube_upload.status(p["id"]),
                    "pending": sum(1 for i in pending if i["profile_id"] == p["id"]),
                    "published": sum(1 for i in items if i["profile_id"] == p["id"] and i["status"] == "uploaded"),
                    "failed": sum(1 for i in items if i["profile_id"] == p["id"] and i["status"] == "failed"),
                    "job": {k: job[k] for k in ("id", "state", "pct", "msg")} if job else None,
                    "last_error": last_job["error"] if last_job and last_job["state"] == "error" else None,
                    "next_run": max(nxt, time.time()) if nxt else None})
    return out


@app.post("/api/auto/profiles")
def auto_save_profile(body: dict):
    from . import autopilot
    return autopilot.save_profile(body)


@app.delete("/api/auto/profiles/{pid}")
def auto_delete_profile(pid: str):
    from . import autopilot, youtube_upload
    youtube_upload.disconnect(pid)
    autopilot.delete_profile(pid)
    return {"ok": True}


@app.post("/api/auto/profiles/{pid}/run")
def auto_run(pid: str):
    from . import autopilot
    try:
        p = autopilot.get_profile(pid)
    except KeyError:
        raise HTTPException(404, "Unknown profile")
    if _auto_job_for(pid):
        raise HTTPException(409, "This profile is already running")
    job = _new_job(kind="auto", profile_id=pid, url=p["name"], msg="Waiting for the GPU…")
    return {"id": job["id"]}


def _profile_due(p: dict, now: float) -> bool:
    """A scheduled profile whose interval has passed since its last run."""
    h = float(p.get("auto_every_hours") or 0)
    return h > 0 and now - float(p.get("last_run") or 0) >= h * 3600


def _scheduler():
    """Run profiles on their schedule while the app is open; tidy old downloads if enabled."""
    from . import autopilot, storage
    last_cleanup = 0.0
    while True:
        time.sleep(60)
        try:
            days = config.load().auto_cleanup_days
            idle = not any(j["state"] in ("queued", "running") for j in STORE.all())
            if days > 0 and idle and time.time() - last_cleanup > 6 * 3600:
                last_cleanup = time.time()
                storage.cleanup_sources(OUT, days)
        except Exception:
            traceback.print_exc()
        try:
            for p in autopilot.list_profiles():
                if _profile_due(p, time.time()) and not _auto_job_for(p["id"]):
                    _new_job(kind="auto", profile_id=p["id"], url=p["name"], msg="Scheduled run — waiting…")
        except Exception:
            traceback.print_exc()



# ───────────────────────── Review queue + publishing ─────────────────────────

class ReviewAction(BaseModel):
    action: str                 # approve | reject | save | retry | restore
    title: str | None = None
    description: str | None = None


@app.get("/api/review")
def review_list(status: str = "pending"):
    from . import autopilot
    items = autopilot.review_items(status)
    return [i for i in items if (OUT / i["file"]).exists() or i["status"] not in ("pending", "approved")]


# the statuses each action may start from (matches the buttons the Review page shows)
ACTION_FROM = {"approve": ("pending", "failed"), "retry": ("failed",),
               "reject": ("pending", "approved", "failed"), "restore": ("approved", "rejected")}


@app.post("/api/review/{iid}")
def review_act(iid: str, body: ReviewAction):
    from . import autopilot
    with autopilot.LOCK:     # check and change in one step: the publisher claims uploads under this lock too
        try:
            item = autopilot.get_item(iid)
        except KeyError:
            raise HTTPException(404, "Unknown clip")
        allowed = ACTION_FROM.get(body.action)
        if allowed and item["status"] not in allowed:
            if item["status"] == "uploading":
                raise HTTPException(409, "This short is already uploading, so it can't be changed now.")
            raise HTTPException(409, f"Clip is already {item['status']}")
        fields = {}
        if body.title is not None:
            fields["title"] = body.title.strip()[:100]
        if body.description is not None:
            fields["description"] = body.description.strip()[:4900]
        if body.action == "approve":
            fields.update(status="approved", approved=time.time(), error=None)
        elif body.action == "retry":
            fields.update(status="approved", error=None)
        elif body.action == "reject":
            fields.update(status="rejected")
        elif body.action == "restore":
            fields.update(status="pending")
        return autopilot.update_item(iid, **fields)


UNDO_SECONDS = 10   # an approval can be undone this long before the upload starts


def _due_for_upload(items: list[dict], now: float, grace: float = UNDO_SECONDS) -> dict | None:
    """The oldest approved short whose undo window has passed, or None."""
    ready = [i for i in items if i.get("status") == "approved" and now - (i.get("approved") or 0) >= grace]
    return min(ready, key=lambda i: i.get("approved") or 0) if ready else None


def _claim_next_upload(now: float) -> dict | None:
    """Take the oldest approved short whose undo window has passed and mark it uploading.
    Holds the review lock throughout, so an Undo either lands first or is refused — never lost."""
    from . import autopilot
    with autopilot.LOCK:
        item = _due_for_upload(autopilot.review_items("approved"), now)
        return autopilot.update_item(item["id"], status="uploading", upload_pct=0) if item else None


def _publisher():
    """Uploads approved clips one at a time (network-bound, runs alongside rendering)."""
    from . import autopilot, youtube_upload
    for i in autopilot.review_items("uploading"):  # interrupted last time → try again
        autopilot.update_item(i["id"], status="approved")
    while True:
        time.sleep(4)
        try:
            item = _claim_next_upload(time.time())
            if not item:
                continue
            try:
                profile = autopilot.get_profile(item["profile_id"])
            except KeyError:
                autopilot.update_item(item["id"], status="failed", error="Profile was deleted")
                continue
            result = {}
            errors = []
            if profile.get("tiktok") and not item.get("tiktok"):
                try:
                    result["tiktok"] = {"file": autopilot.export_tiktok(item, profile), "at": time.time()}
                except Exception as e:
                    errors.append(f"TikTok export: {e}")
            if profile.get("youtube") and not item.get("youtube"):
                try:
                    slot = autopilot.next_publish_slot(profile)
                    result["youtube"] = youtube_upload.upload(
                        profile["id"], OUT / item["file"], item["title"], item["description"],
                        item.get("hashtags") or [], privacy=profile.get("privacy", "public"), publish_at=slot,
                        category=profile.get("category_id", "24"),
                        progress=lambda f, iid=item["id"]: autopilot.update_item(iid, upload_pct=round(f, 3)))
                except Exception as e:
                    errors.append(str(e))
            if errors:
                autopilot.update_item(item["id"], status="failed", error=" · ".join(errors), **result)
            else:
                autopilot.update_item(item["id"], status="uploaded", uploaded=time.time(), **result)
        except Exception:
            traceback.print_exc()



# ───────────────────────── YouTube account connection ─────────────────────────

@app.get("/api/youtube/client")
def yt_client():
    from . import youtube_upload
    return {"has_client": youtube_upload.has_client()}


@app.post("/api/youtube/client")
def yt_save_client(body: dict):
    from . import youtube_upload
    try:
        youtube_upload.save_client(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"has_client": True}


@app.get("/api/youtube/connect/{pid}")
def yt_connect(pid: str, request: Request):
    from . import youtube_upload
    try:
        return RedirectResponse(youtube_upload.auth_url(pid, str(request.base_url)))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/youtube/disconnect/{pid}")
def yt_disconnect(pid: str):
    from . import youtube_upload
    youtube_upload.disconnect(pid)
    return {"ok": True}


app.mount("/media", StaticFiles(directory=OUT), name="media")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index(state: str | None = None, code: str | None = None, error: str | None = None):
    if state:  # Google sends the user back here after "Connect YouTube"
        from . import youtube_upload
        if youtube_upload.is_pending(state):
            if error or not code:
                return RedirectResponse("/?yt=cancelled#autopilot")
            try:
                youtube_upload.handle_callback(state, code)
                return RedirectResponse("/?yt=connected#autopilot")
            except Exception as e:
                from urllib.parse import quote
                return RedirectResponse("/?yt=error&msg=" + quote(str(e)[:300]) + "#autopilot")
    return HTMLResponse(page_html())


THEMES = {"caption": ("/static/app.css", "#0f1320"), "classic": ("/static/themes/classic.css", "#1b1c21")}


def page_html() -> str:
    """The app's page, with the chosen theme's stylesheet already in it (so it never shows the other one first)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css, colour = THEMES.get(config.load().ui_theme, THEMES["caption"])
    html = html.replace('href="/static/app.css" data-theme-css', f'href="{css}" data-theme-css', 1)
    return html.replace('<meta name="theme-color" content="#0f1320">', f'<meta name="theme-color" content="{colour}">', 1)


def _already_running(url: str) -> bool:
    """True if a Clippy server already answers at `url` (e.g. the start-at-login service)."""
    import httpx
    try:
        r = httpx.get(url.rstrip("/") + "/api/status", timeout=1.5)
        return r.status_code == 200 and "llm" in r.json()
    except (httpx.HTTPError, ValueError):
        return False


def _open_browser(url: str) -> None:
    """Open the app; inside WSL that means the Windows browser (WSL forwards localhost to Windows)."""
    from .llm import wsl
    if wsl():
        for cmd in (["wslview", url], ["cmd.exe", "/c", "start", "", url], ["explorer.exe", url]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd="/")
                    return
                except OSError:
                    continue
        print(f"  Open {url} in your Windows browser.", flush=True)
        return
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    ap = argparse.ArgumentParser(prog="clippy web")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv or [])
    global BIND_HOST
    BIND_HOST = a.host
    url = f"http://{a.host}:{a.port}"
    if _already_running(url):
        print(f"\n  Clippy is already running →  {url}\n", flush=True)
        if not a.no_browser:
            _open_browser(url)
        return 0
    print(f"\n  Clippy is running →  {url}\n  (Ctrl+C to stop)\n", flush=True)
    if not a.no_browser:
        threading.Timer(1.2, lambda: _open_browser(url)).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    return 0
