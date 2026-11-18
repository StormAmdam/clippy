import os
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("PYTHONUTF8", "1")     # Python tools Clippy runs (yt-dlp) write UTF-8, also on Windows

from .quiet import hide_console_windows  # noqa: E402

hide_console_windows()          # Windows: programs Clippy starts don't each pop up a console window
