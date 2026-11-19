"""Review on a phone: a small, separate server on the Wi-Fi for watching, approving and saving shorts.

Clippy itself stays private to this PC. Turning phone review on (Review → Review on Your Phone) starts a second
server that phones on the same network can reach, and it can only do what reviewing on a phone needs: list the
shorts waiting, play them, approve, reject or undo, and save a video to the phone. Nothing else: no settings,
extensions, YouTube logins, making clips or deleting.

- A secret in the QR code lets a phone in; the phone keeps it as a cookie. Without it, nothing is shown.
- Only devices on the local network (private addresses) get an answer, and only for Clippy's own pages.
- It's off until someone turns it on at this PC, and turning it off (or restarting Clippy) makes old links stop
  working."""
from __future__ import annotations

import ipaddress
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from . import config

PORTS = range(7880, 7890)
COOKIE = "clippy_phone"
STATIC = Path(__file__).parent / "static" / "phone"
_state: dict = {"server": None, "thread": None, "port": None, "token": None, "devices": {}}
_lock = threading.Lock()


class PhoneError(RuntimeError):
    """Said to the person turning phone review on."""


def private(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def lan_ip() -> str | None:
    """The address other devices on this network reach this PC at (no packet is sent to find it)."""
    for probe in ("10.254.254.254", "192.168.254.254", "172.31.254.254"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 1))
                ip = s.getsockname()[0]
            if private(ip) and not ipaddress.ip_address(ip).is_loopback:
                return ip
        except OSError:
            continue
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return ip if private(ip) and not ipaddress.ip_address(ip).is_loopback else None
    except OSError:
        return None


def _wsl() -> bool:
    try:
        from .llm import wsl
        return wsl()
    except Exception:
        return False


def status() -> dict:
    on = _state["server"] is not None
    ip = lan_ip()
    out = {"on": on, "ip": ip, "port": _state["port"], "wsl": _wsl(), "windows": sys.platform == "win32",
           "devices": [{"ip": k, **v} for k, v in sorted(_state["devices"].items(), key=lambda kv: -kv[1]["seen"])]}
    if on and ip:
        out["address"] = f"http://{ip}:{_state['port']}"
        out["url"] = f"{out['address']}/pair?key={_state['token']}"
    if not ip:
        out["problem"] = "This PC doesn't seem to be on a network, so a phone can't reach it."
    return out


def start() -> dict:
    """Open phone review (or say where it already is)."""
    import uvicorn
    with _lock:
        if _state["server"] is None:
            port = next((p for p in PORTS if _free(p)), None)
            if port is None:
                raise PhoneError("Ports 7880 to 7889 are all taken by other programs, so phone review can't open.")
            _state.update(token=secrets.token_urlsafe(18), port=port, devices={})
            srv = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
            th = threading.Thread(target=srv.run, daemon=True, name="phone-review")
            th.start()
            _state.update(server=srv, thread=th)
            for _ in range(50):
                if srv.started or not th.is_alive():
                    break
                time.sleep(0.1)
            if not srv.started:                         # the port was taken after all, or it couldn't start
                srv.should_exit = True
                _state.update(server=None, thread=None, port=None, token=None)
                raise PhoneError("Phone review couldn't open (another program may be using its port). Try again.")
    return status()


def stop() -> dict:
    with _lock:
        srv, th = _state["server"], _state["thread"]
        if srv is not None:
            srv.should_exit = True
            if th:
                th.join(5)
        _state.update(server=None, thread=None, port=None, token=None, devices={})
    return status()


def _free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def qr_svg(text: str) -> str:
    """A standalone SVG (with its namespace, so an <img> can show it)."""
    import io

    import segno
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=6, border=2, dark="#0f1320", light="#ffffff",
                                     xmldecl=False)
    return buf.getvalue().decode("utf-8")


# ───────────────────────── the phone's server ─────────────────────────

app = FastAPI(title="Clippy phone review", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def only_phones_here(request: Request, call_next):
    """Devices on this network only, at an IP address or .local name (no other website can point here)."""
    from .server import _trusted_host
    client = request.client.host if request.client else ""
    if not private(client) or not _trusted_host(request.headers.get("host", "")):
        return JSONResponse({"detail": "Not here."}, status_code=403)
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin is not None \
            and urlsplit(origin).netloc != request.headers.get("host", ""):
        return JSONResponse({"detail": "Only Clippy's phone page can do that."}, status_code=403)
    return await call_next(request)


def _authed(request: Request) -> bool:
    token, got = _state["token"], request.cookies.get(COOKIE, "")
    ok = bool(token) and secrets.compare_digest(got, token)
    if ok:
        ua = request.headers.get("user-agent", "")
        kind = "iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android phone" if "Android" in ua \
            else "A device"
        _state["devices"][request.client.host] = {"seen": time.time(), "kind": kind}
    return ok


def _need(request: Request) -> None:
    if not _authed(request):
        raise HTTPException(401, "Scan the code in Clippy on your PC again (Review → Review on Your Phone).")


def _page(title: str, text: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1"><title>{title}</title><link rel="stylesheet" href="/phone.css"></head>
<body><main class="msg"><h1>{title}</h1><p>{text}</p></main></body></html>""", status_code=status_code)


@app.get("/pair")
def pair(key: str = ""):
    token = _state["token"]
    if not token or not secrets.compare_digest(key, token):
        return _page("This link has run out", "Open <b>Review → Review on Your Phone</b> in Clippy on your PC and "
                     "scan the new code.", 403)
    r = RedirectResponse("/", status_code=303)            # the secret leaves the address bar
    r.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=12 * 3600)
    return r


@app.get("/")
def home(request: Request):
    if not _authed(request):
        return _page("Scan the code first", "In Clippy on your PC, open <b>Review → Review on Your Phone</b> and scan "
                     "the code with this phone's camera.", 401)
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/phone.css")
def css():
    return FileResponse(STATIC / "phone.css", media_type="text/css")


@app.get("/phone.js")
def js():
    return FileResponse(STATIC / "phone.js", media_type="text/javascript")


def _items() -> list[dict]:
    from . import autopilot
    return [i for i in autopilot.review_items() if i.get("status") in ("pending", "approved", "uploading", "failed")]


@app.get("/api/review")
def review(request: Request):
    _need(request)
    keys = ("id", "status", "title", "description", "duration", "profile_name", "source_title", "source_channel",
            "file", "thumb", "created", "error", "upload_pct")
    root = config.output_root(config.load())
    return [{k: i.get(k) for k in keys} for i in _items() if (root / str(i.get("file", ""))).is_file()]


class Act(BaseModel):
    action: str


@app.post("/api/review/{iid}")
def review_act(iid: str, body: Act, request: Request):
    """Approve, reject or undo, exactly as Review on the PC does."""
    _need(request)
    if body.action not in ("approve", "reject", "restore"):
        raise HTTPException(400, "Not possible from a phone.")
    from .server import ReviewAction
    from .server import review_act as act
    return act(iid, ReviewAction(action=body.action))


@app.get("/media/{path:path}")
def media(path: str, request: Request, download: int = 0):
    """Only the videos and thumbnails of shorts in Review."""
    _need(request)
    want = path.replace("\\", "/")
    item = next((i for i in _items() if want in (str(i.get("file", "")).replace("\\", "/"),
                                                  str(i.get("thumb", "")).replace("\\", "/"))), None)
    if item is None:
        raise HTTPException(404, "Not found")
    f = config.output_root(config.load()) / want
    if not f.is_file():
        raise HTTPException(404, "Not found")
    name = f"{(item.get('title') or 'short')[:60].strip()}{f.suffix}" if download else None
    return FileResponse(f, filename=name, content_disposition_type="attachment" if download else "inline")
