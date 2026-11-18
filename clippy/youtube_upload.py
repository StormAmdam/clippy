"""Upload to YouTube with the official YouTube Data API v3 (free; ~6 uploads/day on the default quota).

One-time setup (the app walks you through it):
  1. console.cloud.google.com → new project → enable "YouTube Data API v3"
  2. OAuth consent screen → External → add yourself as a test user
  3. Credentials → Create OAuth client ID → "Desktop app" → download JSON → upload it in Clippy
  4. In Clippy press "Connect YouTube" on a profile and sign in with that channel's Google account

Note: Google keeps videos uploaded by *unverified* API projects private until the project passes
their (free) API audit. Uploads still work; you then publish them in YouTube Studio, or apply for the audit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .autopilot import auto_dir

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REVOKE = "https://oauth2.googleapis.com/revoke"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"

_PENDING: dict[str, dict] = {}


def _private_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    for attempt in range(40):          # Windows: retry while something has the file open for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.1)


def client_path() -> Path:
    return auto_dir() / "google_client.json"


def has_client() -> bool:
    return client_path().exists()


def save_client(data: dict) -> None:
    c = data.get("installed") or data.get("web")
    if not c or not c.get("client_id") or not c.get("client_secret"):
        raise ValueError("That isn't an OAuth client file. Download the JSON of a 'Desktop app' OAuth client.")
    _private_write(client_path(), data)


def _client() -> tuple[str, str]:
    data = json.loads(client_path().read_text(encoding="utf-8"))
    c = data.get("installed") or data.get("web")
    return c["client_id"], c["client_secret"]


def _token_path(pid: str) -> Path:
    return auto_dir() / "tokens" / f"youtube-{pid}.json"


def auth_url(pid: str, redirect_uri: str) -> str:
    if not has_client():
        raise RuntimeError("Upload your Google OAuth client file first (see the setup guide).")
    cid, _ = _client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(18)
    _PENDING[state] = {"pid": pid, "verifier": verifier, "redirect": redirect_uri, "t": time.time()}
    q = {"client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES,
         "access_type": "offline", "prompt": "consent select_account", "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256"}
    return AUTH + "?" + urllib.parse.urlencode(q)


def is_pending(state: str) -> bool:
    return state in _PENDING


def handle_callback(state: str, code: str) -> str:
    p = _PENDING.pop(state, None)
    if not p or time.time() - p["t"] > 900:
        raise RuntimeError("Sign-in link expired — press Connect YouTube again.")
    cid, secret = _client()
    r = httpx.post(TOKEN, data={"code": code, "client_id": cid, "client_secret": secret,
                                "redirect_uri": p["redirect"], "grant_type": "authorization_code",
                                "code_verifier": p["verifier"]}, timeout=30)
    tok = r.json()
    if r.status_code != 200 or "access_token" not in tok:
        raise RuntimeError(f"Google sign-in failed: {tok.get('error_description') or tok.get('error') or r.text[:200]}")
    if "refresh_token" not in tok:
        raise RuntimeError("Google didn't return a refresh token — remove Clippy's access at "
                           "myaccount.google.com/permissions and connect again.")
    tok["obtained"] = time.time()
    ch = httpx.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                   headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30).json()
    items = ch.get("items") or []
    if items:
        sn = items[0]["snippet"]
        tok["channel"] = {"id": items[0]["id"], "title": sn.get("title"),
                          "thumb": ((sn.get("thumbnails") or {}).get("default") or {}).get("url")}
    _private_write(_token_path(p["pid"]), tok)
    return p["pid"]


def status(pid: str) -> dict:
    f = _token_path(pid)
    if not f.exists():
        return {"connected": False, "client": has_client()}
    tok = json.loads(f.read_text(encoding="utf-8"))
    return {"connected": True, "client": True, "channel": tok.get("channel")}


def disconnect(pid: str) -> None:
    f = _token_path(pid)
    if f.exists():
        try:
            tok = json.loads(f.read_text(encoding="utf-8"))
            httpx.post(REVOKE, params={"token": tok.get("refresh_token")}, timeout=15)
        except Exception:
            pass
        f.unlink()


def _access_token(pid: str) -> str:
    f = _token_path(pid)
    if not f.exists():
        raise RuntimeError("This profile isn't connected to YouTube yet.")
    tok = json.loads(f.read_text(encoding="utf-8"))
    if time.time() < tok.get("obtained", 0) + tok.get("expires_in", 0) - 120:
        return tok["access_token"]
    cid, secret = _client()
    r = httpx.post(TOKEN, data={"client_id": cid, "client_secret": secret, "refresh_token": tok["refresh_token"],
                                "grant_type": "refresh_token"}, timeout=30)
    new = r.json()
    if r.status_code != 200 or "access_token" not in new:
        raise RuntimeError("YouTube login expired — press Connect YouTube on the profile again.")
    tok.update(access_token=new["access_token"], expires_in=new.get("expires_in", 3600), obtained=time.time())
    _private_write(f, tok)
    return tok["access_token"]


def _api_error(r: httpx.Response) -> str:
    try:
        err = r.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", r.text[:200])
    except Exception:
        reason, msg = "", r.text[:200]
    if reason in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"):
        return "YouTube's daily upload limit is reached (≈6/day on the free quota). It resets at midnight Pacific time."
    if reason == "youtubeSignupRequired":
        return "That Google account has no YouTube channel yet — create one first."
    return f"YouTube error {r.status_code}: {msg}"


def upload(pid: str, path: Path, title: str, description: str, tags: list[str], privacy: str = "public",
           publish_at: float | None = None, category: str = "24", progress=lambda f: None) -> dict:
    token = _access_token(pid)
    st: dict = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        st["privacyStatus"] = "private"  # YouTube requires private + publishAt for scheduling
        st["publishAt"] = datetime.fromtimestamp(publish_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    clean_tags, total = [], 0
    for t in tags:
        t = t.lstrip("#").strip()
        if t and total + len(t) < 450:
            clean_tags.append(t)
            total += len(t) + 1
    meta = {"snippet": {"title": title.replace("<", "").replace(">", "")[:100] or "Short",
                        "description": description.replace("<", "").replace(">", "")[:4900],
                        "tags": clean_tags, "categoryId": str(category)},
            "status": st}
    size = path.stat().st_size
    r = httpx.post(UPLOAD, json=meta, timeout=60,
                   headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                            "X-Upload-Content-Length": str(size)})
    if r.status_code != 200 or "location" not in r.headers:
        raise RuntimeError(_api_error(r))
    loc = r.headers["location"]
    chunk = 8 * 1024 * 1024
    offset, vid, tries = 0, None, 0
    with open(path, "rb") as fh:
        while offset < size:
            fh.seek(offset)
            data = fh.read(chunk)
            end = offset + len(data) - 1
            try:
                r = httpx.put(loc, content=data, timeout=600,
                              headers={"Authorization": f"Bearer {token}", "Content-Length": str(len(data)),
                                       "Content-Range": f"bytes {offset}-{end}/{size}"})
            except httpx.HTTPError:
                tries += 1
                if tries > 5:
                    raise RuntimeError("Upload kept failing (network).")
                time.sleep(3 * tries)
                q = httpx.put(loc, headers={"Authorization": f"Bearer {token}", "Content-Range": f"bytes */{size}"},
                              timeout=60)
                rng = q.headers.get("range")
                offset = int(rng.split("-")[1]) + 1 if rng else 0
                continue
            if r.status_code in (200, 201):
                vid = r.json()["id"]
                break
            if r.status_code == 308:
                rng = r.headers.get("range")
                offset = int(rng.split("-")[1]) + 1 if rng else 0
                progress(offset / size)
                continue
            raise RuntimeError(_api_error(r))
    if not vid:
        raise RuntimeError("Upload finished without a video id")
    progress(1.0)
    return {"id": vid, "url": f"https://youtube.com/shorts/{vid}", "publish_at": publish_at,
            "privacy": st["privacyStatus"]}
