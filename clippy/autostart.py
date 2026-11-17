"""Start Clippy automatically at login (a systemd *user* service — no root, easy to undo).

With it on, scheduled Autopilot runs happen even when no terminal is open.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import ROOT

UNIT = "clippy.service"


def unit_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user" / UNIT


def _unit_path_value(p: Path) -> str:
    # systemd expands %-specifiers everywhere, so a literal % must be written %%
    return str(p).replace("%", "%%")


def unit_text(root: Path) -> str:
    python = _unit_path_value(root / ".venv" / "bin" / "python").replace("\\", "\\\\").replace('"', '\\"')
    return (
        "[Unit]\n"
        "Description=Clippy shorts studio (web app at http://127.0.0.1:7860)\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={_unit_path_value(root)}\n"
        f'ExecStart="{python}" -m clippy web --no-browser\n'   # quoted: the folder may contain spaces
        "Restart=on-failure\n"
        "RestartSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemctl(*args: str) -> tuple[int, str]:
    r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout or r.stderr).strip()


def status() -> dict:
    supported = shutil.which("systemctl") is not None
    installed = unit_path().exists()
    enabled = supported and installed and _systemctl("is-enabled", UNIT)[1] == "enabled"
    return {"supported": supported, "installed": installed, "enabled": bool(enabled)}


def enable() -> dict:
    """Install and enable the service. It starts at the next login (not now, so it can't clash
    with a Clippy you started by hand)."""
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(ROOT))
    _systemctl("daemon-reload")
    code, out = _systemctl("enable", UNIT)
    if code != 0:
        raise RuntimeError(f"systemctl could not enable Clippy: {out}")
    return status()


def disable() -> dict:
    _systemctl("disable", UNIT)
    unit_path().unlink(missing_ok=True)
    _systemctl("daemon-reload")
    return status()
