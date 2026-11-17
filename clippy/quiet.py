"""No console windows on Windows.

Clippy.exe runs Clippy without a console. Windows then gives every command-line program Clippy starts (ffmpeg, ffprobe,
yt-dlp, nvidia-smi, llama-server…) a console window of its own: black windows flashing up all the time, one every
few seconds just from the status check. This makes every program start without a window, unless the code starting it
asked for something else on purpose."""
from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def make_quiet(base):
    class QuietPopen(base):
        _clippy_quiet = True

        def __init__(self, *args, **kwargs):
            if "creationflags" not in kwargs:
                kwargs["creationflags"] = CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    QuietPopen.__name__ = QuietPopen.__qualname__ = "Popen"
    return QuietPopen


def hide_console_windows() -> None:
    if sys.platform == "win32" and not getattr(subprocess.Popen, "_clippy_quiet", False):
        subprocess.Popen = make_quiet(subprocess.Popen)      # subprocess.run/call/check_output all go through it
