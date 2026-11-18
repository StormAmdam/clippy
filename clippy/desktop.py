"""Clippy as a desktop app: the web interface in its own window (Edge on Windows, Chrome/Chromium elsewhere, in
app mode), with that window's profile kept inside Clippy's folder too. Clippy quits a little while after the window
is closed, unless a video is still being made or "Start at login" keeps it running in the background.

    clippy app                 start Clippy and open its window (or just the window, when Clippy already runs)
    clippy app --background    start Clippy without a window (what "Start at login" runs on Windows)"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from . import config

# 7860 unless another program has it. Only the first few are tried before any free port: the window keeps its
# choices per address, so a steady one keeps them.
PORTS = [int(os.environ["CLIPPY_PORT"])] if os.environ.get("CLIPPY_PORT") else list(range(7860, 7870))
PORT_FILE = config.ROOT / "data" / "port.txt"     # where this Clippy runs, for the next start to find it
IDLE_QUIT = 45          # seconds without the window asking for status before Clippy quits


def _browser() -> list[str] | None:
    if os.environ.get("CLIPPY_BROWSER"):
        return [os.environ["CLIPPY_BROWSER"]]
    if sys.platform == "win32":
        env = os.environ.get
        for base in (env("ProgramFiles(x86)"), env("ProgramFiles"), env("LOCALAPPDATA")):
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                if base and os.path.exists(p := os.path.join(base, rel)):
                    return [p]
        return None
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge", "brave-browser"):
        if p := shutil.which(name):
            return [p]
    return None


def open_window(url: str) -> subprocess.Popen | None:
    """A chromeless app window; falls back to a normal browser tab."""
    from .quiet import CREATE_NO_WINDOW, plain_popen
    b = _browser()
    if not b:
        webbrowser.open(url)
        return None
    profile = config.ROOT / "data" / "window"
    profile.mkdir(parents=True, exist_ok=True)
    args = b + [f"--app={url}", f"--user-data-dir={profile}", "--window-size=1360,900", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate,msEdgeSidebarV2"]
    extra = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}
    # plain Popen: the window isn't tied to this process (a second start opens it, then exits straight away)
    return plain_popen()(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)


def _message(text: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Clippy", 0x10)
    else:
        print(text, file=sys.stderr)


def probe(port: int) -> str:
    """What's on this port: "ours" (this Clippy), "other" (another program, or a Clippy in another folder) or "free"."""
    import httpx
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=1.5)
        j = r.json()
        if r.status_code == 200 and isinstance(j, dict) and "llm" in j:
            return "ours" if j.get("folder", str(config.ROOT)) == str(config.ROOT) else "other"
        return "other"
    except httpx.ConnectError:
        pass
    except (httpx.HTTPError, ValueError):
        return "other"
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return "free"
        except OSError:
            return "other"


def _saved_port() -> int | None:
    try:
        return int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def find_port() -> tuple[int, bool]:
    """(port, already running): where this Clippy already runs, else the first free port of 7860–7869, else any."""
    saved = _saved_port()
    if saved and probe(saved) == "ours":
        return saved, True
    for port in PORTS:
        state = probe(port)
        if state != "other":
            return port, state == "ours"
    with socket.socket() as s:                         # all taken by other programs: any free port
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1], False


def _keep_running() -> bool:
    """Windows with Start at login on: Clippy stays in the background when its window closes, for scheduled Autopilot
    runs. (On Linux, Start at login is a separate service, so the app window's Clippy can quit.)"""
    if sys.platform != "win32":
        return False
    try:
        from . import autostart
        return autostart.status()["enabled"]
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    background = "--background" in argv
    # started from Clippy.exe (pythonw): there's no console, so keep a log in Clippy's folder
    logs = config.ROOT / "data"
    logs.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(logs / "clippy.log", "a", buffering=1, encoding="utf-8", errors="replace")
    from . import server
    from .engine import ENGINE
    port, running = find_port()
    url = f"http://127.0.0.1:{port}"
    if running:                                        # second start: just show the window
        if not background:
            open_window(url)
        return 0
    try:
        import uvicorn
        srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
        server.BIND_HOST = "127.0.0.1"
        th = threading.Thread(target=srv.run, daemon=True, name="web")
        th.start()
        t0 = time.time()
        while not server._already_running(url):
            if not th.is_alive() or time.time() - t0 > 60:
                raise RuntimeError(f"The Clippy server didn't start on port {port} (see {logs / 'clippy.log'}).")
            time.sleep(0.3)
    except Exception as e:                             # a visible message beats a silent nothing
        if not background:
            _message(f"Clippy couldn't start: {e}")
        print(f"Clippy couldn't start: {e}", flush=True)
        return 1
    try:
        PORT_FILE.write_text(str(port), encoding="utf-8")
    except OSError:
        pass
    print(f"Clippy is running at {url}" + (" (in the background)" if background else ""), flush=True)
    server.UI_SEEN["t"] = time.time()
    server.APP["desktop"] = True
    win = None if background else open_window(url)
    try:
        tick = 0
        while not server.APP["quit"]:                  # the Quit button in Settings
            time.sleep(1)
            tick += 1
            if background or tick % 5:
                continue
            window_gone = win is None or win.poll() is not None
            idle = time.time() - server.UI_SEEN["t"] > IDLE_QUIT
            if window_gone and idle and not server.work_in_progress() and not _keep_running():
                break
    except KeyboardInterrupt:
        pass
    srv.should_exit = True
    th.join(15)
    ENGINE.stop()
    return 0
