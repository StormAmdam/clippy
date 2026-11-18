"""Preview pictures for caption styles, drawn by Clippy's own caption renderer (like the ones on Make Clips).

    python tools/style_preview.py community/extra-caption-styles     one picture per style in an extension
    python tools/style_preview.py --builtin clippy/static/styles      the four built-in ones

Each style's picture is written to the "preview" file its extension.json names (360x640 JPEG)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clippy import extensions  # noqa: E402
from clippy.config import Settings  # noqa: E402
from clippy.overlay import OUT_H, OUT_W, STYLES, Overlay  # noqa: E402

WORDS = [("I", 0.0, 0.3), ("made", 0.3, 0.6), ("$10,000", 0.6, 1.3), ("in", 1.3, 1.5), ("one", 1.5, 1.7),
         ("day", 1.7, 2.1)]


def background() -> np.ndarray:
    """Soft colour blobs and a person-shaped silhouette, so the captions are seen as they would be on a video."""
    img = Image.new("RGB", (OUT_W, OUT_H), (52, 46, 70))
    d = ImageDraw.Draw(img)
    for (x, y, r, col) in ((150, 250, 700, (120, 70, 140)), (950, 1700, 800, (60, 140, 90)),
                           (1000, 300, 500, (150, 90, 110)), (100, 1500, 600, (70, 90, 140))):
        d.ellipse((x - r, y - r, x + r, y + r), fill=col)
    img = img.filter(ImageFilter.GaussianBlur(160))
    person = Image.new("L", img.size, 0)
    p = ImageDraw.Draw(person)
    p.ellipse((340, 520, 740, 960), fill=255)
    p.rounded_rectangle((150, 1000, 930, 1700), radius=330, fill=255)
    person = person.filter(ImageFilter.GaussianBlur(6))
    img.paste((34, 34, 40), mask=person.point(lambda v: int(v * 0.9)))
    img = img.filter(ImageFilter.GaussianBlur(4))
    return np.array(img)[:, :, ::-1].copy()            # BGR, as the renderer draws on video frames


def draw(style: dict | str, out: Path, cfg: Settings | None = None) -> None:
    cfg = cfg or Settings()
    words = [{"w": w, "s": s, "e": e} for w, s, e in WORDS]
    ov = Overlay(cfg, words, 3.0, "How He Made $10K In One Day", ["$10,000"], [{"word": "made", "emoji": "💰"}],
                 lambda t: {"caption_y": int(OUT_H * cfg.caption_y), "title_y": 220}, style=style)
    frame = background()
    ov.draw(frame, 0.45)                              # while "made" is said: highlighted, with its emoji
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame[:, :, ::-1]).resize((360, 640), Image.LANCZOS).save(out, quality=88)
    print(f"wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--builtin", action="store_true", help="draw the built-in styles into this folder")
    a = ap.parse_args()
    if a.builtin:
        for name in STYLES:
            draw(name, a.folder / f"{name}.jpg")
        return 0
    m = extensions.read_manifest(a.folder)
    styles = extensions.styles_in(a.folder, m)
    for s in m.get("caption_styles") or []:
        if s.get("id") in styles and s.get("preview"):
            draw(styles[s["id"]], a.folder / s["preview"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
