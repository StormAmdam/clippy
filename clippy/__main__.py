import os
import sys
from pathlib import Path

if sys.platform == "win32" and not sys.flags.utf8_mode:
    # Windows defaults to a legacy code page, which breaks titles, captions and emoji (and even "→" in a log line).
    # Restart in UTF-8 mode; tools Clippy runs (yt-dlp) inherit it through PYTHONUTF8.
    import ctypes
    import subprocess
    os.environ["PYTHONUTF8"] = "1"
    # creationflags=0 on purpose: the restarted Clippy shares this terminal, so its output still shows
    child = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "clippy", *sys.argv[1:]], creationflags=0)
    # tie the restarted Clippy (and the AI engine it starts) to this process: if this one is ended, so are they
    k32 = ctypes.windll.kernel32
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    job = k32.CreateJobObjectW(None, None)
    info = (ctypes.c_byte * 144)()                     # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (64-bit)
    ctypes.c_uint32.from_buffer(info, 16).value = 0x2000   # LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if job and k32.SetInformationJobObject(ctypes.c_void_p(job), 9, info, ctypes.sizeof(info)):
        k32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(int(child._handle)))
    while True:
        try:
            sys.exit(child.wait())
        except KeyboardInterrupt:                      # Ctrl+C reaches both; let the child finish shutting down
            continue

# tools setup.sh installs into .venv (yt-dlp, deno) must be found however Clippy is started
# (clippy.sh, the Start-at-login service, or .venv/bin/python -m clippy)
_bin = str(Path(sys.executable).parent)
# …and so must the tools Clippy downloads into its own folder (bin/), which win over everything else
_app_bin = str(Path(__file__).resolve().parent.parent / "bin")
_scripts = os.path.join(sys.prefix, "Scripts")          # Windows: where pip puts yt-dlp.exe and deno.exe
for _d in (_scripts, _bin, _app_bin):
    if os.path.isdir(_d) and _d not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")

from .cli import main  # noqa: E402

sys.exit(main())
