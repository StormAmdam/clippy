"""Clippy as a desktop app: the web interface in its own window (Edge on Windows, Chrome/Chromium elsewhere, in
app mode), with that window's profile kept inside Clippy's folder too. Clippy quits a little while after the window
is closed, unless a video is still being made."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from . import config

PORT = int(os.environ.get("CLIPPY_PORT", "7860"))
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
    b = _browser()
    if not b:
        webbrowser.open(url)
        return None
    profile = config.ROOT / "data" / "window"
    profile.mkdir(parents=True, exist_ok=True)
    args = b + [f"--app={url}", f"--user-data-dir={profile}", "--window-size=1360,900", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate,msEdgeSidebarV2"]
    extra = {"creationflags": 0x08000000} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)


def _message(text: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Clippy", 0x10)
    else:
        print(text, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    # started from Clippy.exe (pythonw): there's no console, so keep a log in Clippy's folder
    logs = config.ROOT / "data"
    logs.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(logs / "clippy.log", "a", buffering=1, encoding="utf-8")
    from . import server
    from .engine import ENGINE
    url = f"http://127.0.0.1:{PORT}"
    if server._already_running(url):                   # second start: just show the window
        open_window(url)
        return 0
    try:
        import uvicorn
        srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=PORT, log_level="warning"))
        server.BIND_HOST = "127.0.0.1"
        th = threading.Thread(target=srv.run, daemon=True, name="web")
        th.start()
        t0 = time.time()
        while not server._already_running(url):
            if not th.is_alive() or time.time() - t0 > 60:
                raise RuntimeError(f"The Clippy server didn't start (see {logs / 'clippy.log'}).")
            time.sleep(0.3)
    except Exception as e:                             # a visible message beats a silent nothing
        _message(f"Clippy couldn't start: {e}")
        return 1
    print(f"Clippy is running at {url}", flush=True)
    server.UI_SEEN["t"] = time.time()
    win = open_window(url)
    try:
        while True:
            time.sleep(5)
            window_gone = win is None or win.poll() is not None
            idle = time.time() - server.UI_SEEN["t"] > IDLE_QUIT
            if window_gone and idle and not server.work_in_progress():
                break
    except KeyboardInterrupt:
        pass
    srv.should_exit = True
    th.join(15)
    ENGINE.stop()
    return 0
