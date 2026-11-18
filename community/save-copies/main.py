"""Save copies to Videos: a copy of every finished short goes to Videos/Clippy Shorts.

Clippy calls clip_rendered() after each short is made. `path` is the finished video, `clip` its title, caption and
so on, `video` the source video's details. See docs/extensions.md."""
import re
import shutil
from pathlib import Path


def clip_rendered(path, clip, video, **_):
    folder = Path.home() / "Videos" / "Clippy Shorts"
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", clip.get("title") or Path(path).stem).strip()[:80] or "short"
    target = folder / f"{name}.mp4"
    n = 2
    while target.exists():
        target = folder / f"{name} ({n}).mp4"
        n += 1
    shutil.copy2(path, target)
