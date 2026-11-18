"""No console windows on Windows, and nothing left running after Clippy ends.

Clippy.exe runs Clippy without a console. Windows then gives every command-line program Clippy starts (ffmpeg, ffprobe,
yt-dlp, nvidia-smi, llama-server…) a console window of its own: black windows flashing up all the time, one every
few seconds just from the status check. This makes every program start without a window, unless the code starting it
asked for something else on purpose.

It also puts every program Clippy starts into a Windows job that ends with Clippy. If Clippy crashes or is ended in
Task Manager, the AI engine (which holds gigabytes of memory), ffmpeg and yt-dlp end with it instead of running on
unseen. The app window is the one exception: it starts through plain_popen()."""
from __future__ import annotations

import subprocess
import sys
import threading

CREATE_NO_WINDOW = 0x08000000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_job = {"handle": None}
_job_lock = threading.Lock()


def kill_on_close_job():
    """A new Windows job whose processes all end when its last handle closes, i.e. when the process holding it ends.
    None when Windows won't make one."""
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = (ctypes.c_byte * 144)()                     # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (64-bit)
    ctypes.c_uint32.from_buffer(info, 16).value = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE   # BasicLimitInformation.LimitFlags
    if not k32.SetInformationJobObject(ctypes.c_void_p(job), 9, info, ctypes.sizeof(info)):   # 9 = extended limits
        k32.CloseHandle(ctypes.c_void_p(job))
        return None
    return job


def tie(proc) -> bool:
    """End this started program (and whatever it starts in turn) when Clippy ends. Windows only."""
    if sys.platform != "win32" or not getattr(proc, "_handle", None):
        return False
    import ctypes
    with _job_lock:
        if _job["handle"] is None:
            _job["handle"] = kill_on_close_job() or 0  # never closed: Windows closes it when Clippy ends
    if not _job["handle"]:
        return False
    return bool(ctypes.windll.kernel32.AssignProcessToJobObject(ctypes.c_void_p(_job["handle"]),
                                                                 ctypes.c_void_p(int(proc._handle))))


def make_quiet(base, tie_child=tie):
    class QuietPopen(base):
        _clippy_quiet = True
        _clippy_base = base

        def __init__(self, *args, **kwargs):
            if "creationflags" not in kwargs:
                kwargs["creationflags"] = CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)
            tie_child(self)

    QuietPopen.__name__ = QuietPopen.__qualname__ = "Popen"
    return QuietPopen


def plain_popen():
    """subprocess.Popen as Python made it: for a program that should outlive Clippy (the app window)."""
    return getattr(subprocess.Popen, "_clippy_base", subprocess.Popen)


def hide_console_windows() -> None:
    if sys.platform == "win32" and not getattr(subprocess.Popen, "_clippy_quiet", False):
        subprocess.Popen = make_quiet(subprocess.Popen)      # subprocess.run/call/check_output all go through it
