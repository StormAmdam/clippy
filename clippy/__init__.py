import os
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

from .quiet import hide_console_windows  # noqa: E402

hide_console_windows()          # Windows: programs Clippy starts don't each pop up a console window
