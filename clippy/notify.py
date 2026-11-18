"""Desktop notifications ("3 new shorts are waiting for your review"), with nothing extra to install.

Linux: notify-send. Windows: a toast through Windows PowerShell, which every Windows 10/11 PC has. It shows as
"Clippy" when the installer's Start-menu shortcut is there (it carries Clippy's app id); otherwise, as with the
portable zip, it shows as Windows PowerShell."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

APP_ID = "StormAmdam.Clippy"                       # the AppUserModelID on the Start-menu shortcut (clippy.iss)
POWERSHELL_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

# reads the toast from environment variables, so no title can break out of the script
TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:CLIPPY_TOAST_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:CLIPPY_TOAST_APP).Show($toast)
"""


def toast_xml(title: str, body: str) -> str:
    return ('<toast><visual><binding template="ToastGeneric">'
            f"<text>{escape(title)}</text><text>{escape(body)}</text>"
            "</binding></visual></toast>")


def windows_app_id() -> str:
    start_menu = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Clippy.lnk")
    return APP_ID if os.path.exists(start_menu) else POWERSHELL_ID


def windows_toast(title: str, body: str, app_id: str | None = None) -> subprocess.CompletedProcess:
    script = base64.b64encode(TOAST_SCRIPT.encode("utf-16-le")).decode()
    env = {**os.environ, "CLIPPY_TOAST_XML": toast_xml(title, body), "CLIPPY_TOAST_APP": app_id or windows_app_id()}
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-EncodedCommand", script], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)


def send(title: str, body: str) -> bool:
    """Show a notification. False when this PC can't (it never raises)."""
    try:
        if sys.platform == "win32":
            return windows_toast(title, body).returncode == 0
        if shutil.which("notify-send"):
            return subprocess.run(["notify-send", "-a", "Clippy", title, body], timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    return False
