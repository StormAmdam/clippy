import os
import sys
from pathlib import Path

if sys.platform == "win32" and not sys.flags.utf8_mode:
    # Windows defaults to a legacy code page, which breaks titles, captions and emoji (and even "→" in a log line).
    # Restart in UTF-8 mode; tools Clippy runs (yt-dlp) inherit it through PYTHONUTF8.
    import subprocess
    os.environ["PYTHONUTF8"] = "1"
    sys.exit(subprocess.call([sys.executable, "-X", "utf8", "-m", "clippy", *sys.argv[1:]]))

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
