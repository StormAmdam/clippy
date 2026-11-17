import os
import sys
from pathlib import Path

# tools setup.sh installs into .venv (yt-dlp, deno) must be found however Clippy is started
# (clippy.sh, the Start-at-login service, or .venv/bin/python -m clippy)
_bin = str(Path(sys.executable).parent)
if _bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _bin + os.pathsep + os.environ.get("PATH", "")

from .cli import main  # noqa: E402

sys.exit(main())
