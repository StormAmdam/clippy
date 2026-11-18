"""Start Clippy automatically at login, so scheduled Autopilot runs happen without anyone opening it.

Linux: a systemd *user* service (no root, easy to undo). Windows: an entry in the current user's Run list that starts
Clippy.exe in the background; the uninstaller removes it again. Both start Clippy at the next login, not now.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ROOT

UNIT = "clippy.service"
WIN = sys.platform == "win32"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"   # Task Manager's switch
RUN_NAME = "Clippy"


def status() -> dict:
    return _win_status() if WIN else _linux_status()


def enable() -> dict:
    """Turn it on. Clippy starts at the next login (not now, so it can't clash with the Clippy already running)."""
    return _win_enable() if WIN else _linux_enable()


def disable() -> dict:
    return _win_disable() if WIN else _linux_disable()


# ───────────────────────── Windows ─────────────────────────

def exe() -> Path:
    return ROOT / "Clippy.exe"


def win_command(app: Path | None = None) -> str:
    return f'"{app or exe()}" --background'


def _reg(write: bool = False, key: str = RUN_KEY):
    import winreg
    access = winreg.KEY_READ | (winreg.KEY_SET_VALUE if write else 0)
    if write:
        return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, access)
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, access)


def _reg_get(name: str, key: str = RUN_KEY):
    import winreg
    try:
        with _reg(key=key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _reg_delete(name: str, key: str = RUN_KEY) -> None:
    import winreg
    try:
        with _reg(write=True, key=key) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _turned_off_in_task_manager() -> bool:
    """Task Manager's Startup tab can switch a Run entry off without removing it (odd first byte = off)."""
    v = _reg_get(RUN_NAME, APPROVED_KEY)
    return isinstance(v, bytes) and len(v) > 0 and v[0] % 2 == 1


def _win_status() -> dict:
    cmd = _reg_get(RUN_NAME)
    mine = isinstance(cmd, str) and os.path.normcase(cmd.strip()) == os.path.normcase(win_command())
    return {"supported": exe().exists(), "installed": cmd is not None,
            "enabled": bool(mine and not _turned_off_in_task_manager()),
            "how": "windows" if exe().exists() else "windows-source"}


def _win_enable() -> dict:
    import winreg
    if not exe().exists():
        raise RuntimeError("Start at login works in the Clippy app (Clippy.exe), not when running from the source code.")
    with _reg(write=True) as k:
        winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, win_command())
    _reg_delete(RUN_NAME, APPROVED_KEY)                 # undo an earlier "Disable" in Task Manager
    return status()


def _win_disable() -> dict:
    cmd = _reg_get(RUN_NAME)
    if cmd is None or str(exe()).lower() in str(cmd).lower():    # leave another Clippy folder's entry alone
        _reg_delete(RUN_NAME)
        _reg_delete(RUN_NAME, APPROVED_KEY)
    return status()


# ───────────────────────── Linux (systemd) ─────────────────────────

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


def _linux_status() -> dict:
    supported = shutil.which("systemctl") is not None
    installed = unit_path().exists()
    enabled = supported and installed and _systemctl("is-enabled", UNIT)[1] == "enabled"
    return {"supported": supported, "installed": installed, "enabled": bool(enabled), "how": "systemd"}


def _linux_enable() -> dict:
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(ROOT), encoding="utf-8")
    _systemctl("daemon-reload")
    code, out = _systemctl("enable", UNIT)
    if code != 0:
        raise RuntimeError(f"systemctl could not enable Clippy: {out}")
    return status()


def _linux_disable() -> dict:
    _systemctl("disable", UNIT)
    unit_path().unlink(missing_ok=True)
    _systemctl("daemon-reload")
    return status()
