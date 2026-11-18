"""Telling people about new versions, and updating the Windows app in place.

When Clippy opens it asks GitHub for the latest release (at most every few hours; Settings can switch it off). If
it's newer, the app says so and recommends updating. Windows (installed): Update Now downloads the new installer into
Clippy's folder and runs it; the installer closes Clippy, updates it, keeps models, settings and shorts, and opens
it again. The portable zip gets the download page, Linux the install line to run again."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from . import components, config
from .version import VERSION

REPO = "StormAmdam/clippy"
FEED = os.environ.get("CLIPPY_UPDATE_FEED") or f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"
INSTALL_LINE = "curl -fsSL https://raw.githubusercontent.com/StormAmdam/clippy/main/install.sh | bash"
CHECK_EVERY = 6 * 3600
SETUP = re.compile(r"Clippy-Setup-([\d.]+)-win64\.exe$")
_cache: dict = {"t": 0.0, "release": None, "error": ""}


class UpdateError(RuntimeError):
    """Said to the person updating."""


def parse(v: str) -> tuple:
    """'v0.2.1' → (0, 2, 1, 1); a pre-release like '0.2.1-dev.5' sorts before its release: (0, 2, 1, 0)."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?(.*)$", str(v).strip())
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), 0 if m.group(4) else 1)


def how() -> str:
    """How this Clippy gets updated: the Windows installer, a portable copy, or the Linux install line."""
    if sys.platform == "win32":
        return "installer" if (config.ROOT / "unins000.exe").exists() else "portable"
    return "install-line"


def _release(force: bool = False) -> dict | None:
    if not force and _cache["release"] is not None and time.time() - _cache["t"] < CHECK_EVERY:
        return _cache["release"]
    try:
        r = httpx.get(FEED, timeout=8, follow_redirects=True, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or not data.get("tag_name"):
            raise ValueError("no release in the answer")
        _cache.update(t=time.time(), release=data, error="")
    except (httpx.HTTPError, ValueError) as e:
        _cache.update(t=time.time(), error=str(e)[:200])
        return _cache["release"]                      # the last good answer, if any
    return _cache["release"]


def _setup_asset(rel: dict) -> dict | None:
    return next((a for a in rel.get("assets") or [] if SETUP.search(str(a.get("name", "")))), None)


def status(force: bool = False) -> dict:
    """What the app shows: this version, the latest, whether it's newer, and how to get it."""
    out = {"current": VERSION, "how": how(), "enabled": config.load().check_updates, "releases": RELEASES,
           "install_line": INSTALL_LINE, "newer": False, "task": _task()}
    if not out["enabled"] and not force:
        return out
    rel = _release(force)
    if rel is None:
        return {**out, "error": _cache["error"] or "Couldn't reach GitHub"}
    latest = str(rel.get("tag_name", "")).lstrip("v")
    newer = parse(latest) > parse(VERSION)
    if not newer:
        _tidy()
    return {**out, "latest": latest, "newer": newer, "url": rel.get("html_url") or RELEASES,
            "notes": str(rel.get("body") or "")[:3000], "published": rel.get("published_at", ""),
            "can_install": newer and out["how"] == "installer" and _setup_asset(rel) is not None}


def _task() -> dict | None:
    t = components.TASKS.get("update")
    return t.to_dict() if t else None


def _tidy() -> None:
    """Installers downloaded for earlier updates aren't needed once Clippy is up to date."""
    for f in components.DOWNLOADS.glob("Clippy-Setup-*-win64.exe") if components.DOWNLOADS.exists() else []:
        m = SETUP.search(f.name)
        if m and parse(m.group(1)) <= parse(VERSION):
            f.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_installer(setup: Path) -> None:
    """Start the installer on its own (not tied to Clippy: it closes Clippy, updates it and opens it again)."""
    from .quiet import plain_popen
    detached = 0x00000008 | 0x00000200                 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    plain_popen()([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLIPPYRESTART=1"],
                  creationflags=detached, close_fds=True, cwd=str(setup.parent),
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install() -> dict:
    """Windows (installed): download the new installer, check it, run it. Returns the update task."""
    if how() != "installer":
        raise UpdateError("This copy of Clippy updates from the download page" if how() == "portable"
                          else "Update by running the install line again")
    rel = _release(force=True)
    if rel is None:
        raise UpdateError(f"Couldn't reach GitHub to download the update ({_cache['error']}).")
    asset = _setup_asset(rel)
    if asset is None or parse(str(rel.get("tag_name"))) <= parse(VERSION):
        raise UpdateError("There's no newer installer to download.")
    name, link = str(asset["name"]), str(asset["browser_download_url"])
    digest = str(asset.get("digest") or "")

    def go(t: components.Task):
        dest = components.fetch(link, components.DOWNLOADS / name, t, f"Clippy {rel['tag_name'].lstrip('v')}")
        if digest.startswith("sha256:") and _sha256(dest) != digest.split(":", 1)[1].lower():
            dest.unlink(missing_ok=True)
            raise UpdateError("The download doesn't match the release (it may have been cut off). Try again.")
        t.step = "Installing: Clippy closes and opens again by itself…"
        run_installer(dest)

    return components.run_task("update", "Update", go).to_dict()


def feed_for_test(path: Path, version: str, setup: Path, url: str) -> None:
    """Write a release feed like GitHub's (for CI: update to an installer served from the build machine)."""
    path.write_text(json.dumps({"tag_name": f"v{version}", "html_url": url, "body": "Test update",
                                "assets": [{"name": f"Clippy-Setup-{version}-win64.exe", "browser_download_url": url,
                                            "digest": "sha256:" + _sha256(setup)}]}), encoding="utf-8")
