"""On Windows, programs Clippy starts (ffmpeg, yt-dlp, nvidia-smi…) must not each open a console window."""
import subprocess
import sys

import pytest

from clippy import quiet


def test_programs_get_no_console_window_unless_the_caller_chose_otherwise():
    seen = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs.get("creationflags"))

    Quiet = quiet.make_quiet(FakePopen)
    Quiet(["ffmpeg", "-version"])
    assert seen[-1] == quiet.CREATE_NO_WINDOW
    Quiet(["python", "-m", "clippy"], creationflags=0)        # an explicit choice is kept (the UTF-8 restart
    assert seen[-1] == 0                                       # shares the terminal so its output shows)
    Quiet(["x"], creationflags=0x00000200)                     # other flags are left alone too
    assert seen[-1] == 0x00000200


@pytest.mark.skipif(sys.platform != "win32", reason="checks the flag Windows itself receives")
def test_on_windows_every_started_program_is_windowless(monkeypatch):
    import _winapi

    import clippy  # noqa: F401  (importing Clippy switches it on)
    flags = []
    real = _winapi.CreateProcess

    def spy(*a):
        flags.append(a[5])
        return real(*a)

    monkeypatch.setattr(_winapi, "CreateProcess", spy)
    subprocess.run(["cmd", "/c", "exit"], capture_output=True)
    assert flags and flags[-1] & quiet.CREATE_NO_WINDOW
