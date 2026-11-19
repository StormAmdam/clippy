"""Animated overlays drawn straight onto frames: word-by-word captions, hook title, emoji, progress bar.

Text is rasterised with Pillow (FreeType) into sprites once, then scaled/blended per frame with OpenCV,
so every element can bounce, pop, tilt and slide.
"""
from __future__ import annotations

import math
import random
import re
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ROOT, Settings

FONTS = ROOT / "fonts"
OUT_W, OUT_H = 1080, 1920
EMOJI_FONTS = [str(FONTS / "NotoColorEmoji.ttf"),          # downloaded into Clippy's folder (AI & Tools)
               "/usr/share/fonts/noto/NotoColorEmoji.ttf", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
               "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf"]


def find_emoji_font() -> str | None:
    """A color emoji font Pillow can draw (bitmap Noto Color Emoji), or None."""
    import os
    return next((f for f in EMOJI_FONTS if os.path.exists(f)), None)

STYLES: dict[str, dict] = {
    # MrBeast / gaming-edit look: chunky comic font, 2 words at a time, tilted bouncing words
    "beast": dict(font="LuckiestGuy-Regular.ttf", size=118, upper=True, words=2, stroke=12, shadow=10,
                  active="color", tilt=3, pop=1.2, rest=1.07, emph_always=True, title="beast"),
    # Hormozi look: heavy sans, 3 words, coloured keywords
    "hormozi": dict(font="Montserrat-Black.ttf", size=100, upper=True, words=3, stroke=10, shadow=9,
                    active="color", tilt=0, pop=1.16, rest=1.06, emph_always=True, title="box"),
    # Highlight box behind the spoken word
    "box": dict(font="Montserrat-Black.ttf", size=94, upper=True, words=3, stroke=8, shadow=9,
                active="box", tilt=2, pop=1.12, rest=1.04, emph_always=False, title="box"),
    # Calm, mixed case, soft shadow
    "clean": dict(font="Montserrat-ExtraBold.ttf", size=82, upper=False, words=4, stroke=0, shadow=14,
                  active="color", tilt=0, pop=1.05, rest=1.0, emph_always=False, title="box"),
}


# ───────────────────────── helpers ─────────────────────────

def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lum(rgb) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def clean_word(w: str, upper: bool) -> str:
    w = re.sub(r"[\"“”«»]", "", w)
    w = re.sub(r"[.,;:…]+$", "", w)
    w = re.sub(r"^[.,;:¿¡]+", "", w)
    return w.upper() if upper else w


def norm_word(w: str) -> str:
    return re.sub(r"[^\w'$%]", "", w.lower())


def ease_out_back(x: float, s: float = 1.9) -> float:
    x = min(max(x, 0.0), 1.0) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def ease_out_cubic(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def _to_premul(img: Image.Image) -> np.ndarray:
    """PIL RGBA → premultiplied float32 BGRA (0..1)."""
    a = np.asarray(img, dtype=np.float32) / 255.0
    out = np.empty_like(a)
    out[..., 0] = a[..., 2] * a[..., 3]
    out[..., 1] = a[..., 1] * a[..., 3]
    out[..., 2] = a[..., 0] * a[..., 3]
    out[..., 3] = a[..., 3]
    return out


def blit(frame: np.ndarray, spr: np.ndarray, cx: float, cy: float, scale: float = 1.0, alpha: float = 1.0) -> None:
    """Alpha-blend a premultiplied BGRA sprite onto a BGR uint8 frame, centred at (cx, cy)."""
    if alpha <= 0.003 or scale <= 0.02:
        return
    if abs(scale - 1.0) > 0.004:
        h, w = spr.shape[:2]
        spr = cv2.resize(spr, (max(1, int(w * scale)), max(1, int(h * scale))),
                         interpolation=cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA)
    h, w = spr.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    fx0, fy0 = max(0, x0), max(0, y0)
    fx1, fy1 = min(frame.shape[1], x0 + w), min(frame.shape[0], y0 + h)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    s = spr[fy0 - y0: fy1 - y0, fx0 - x0: fx1 - x0]
    reg = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    a = s[..., 3:4] * alpha
    reg = reg * (1 - a) + s[..., :3] * (255.0 * alpha)
    frame[fy0:fy1, fx0:fx1] = np.clip(reg, 0, 255).astype(np.uint8)


# ───────────────────────── data ─────────────────────────

@dataclass
class Word:
    text: str
    s: float
    e: float
    emph: bool = False
    emoji: str = ""


@dataclass
class Chunk:
    words: list[Word]
    s: float
    e: float
    y: int
    sprites: dict = field(default_factory=dict)


def make_chunks(words: list[Word], max_words: int, max_chars: int) -> list[list[Word]]:
    chunks, cur = [], []
    for w in words:
        if cur:
            prev = cur[-1]
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if (len(cur) >= max_words or chars > max_chars or w.s - prev.e > 0.4
                    or prev.text.endswith(("?", "!")) or getattr(prev, "_brk", False)):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


# ───────────────────────── renderer ─────────────────────────

class Overlay:
    def __init__(self, cfg: Settings, words: list[dict], duration: float, title: str, emphasis: list[str],
                 emojis: list[dict], layout_at, style: str | dict | None = None, ranks: list[dict] | None = None):
        self.cfg = cfg
        self._lock = threading.RLock()                  # making caption/emoji images (fonts can't draw in parallel)
        name = style or cfg.caption_style
        if isinstance(name, dict):                       # a style given whole (tools/style_preview.py)
            self.st = dict(name)
        elif name in STYLES:
            self.st = dict(STYLES[name])
        else:                                            # a style from an extension (or one that's gone: Beast)
            from . import extensions
            self.st = dict(extensions.caption_styles().get(name) or STYLES["beast"])
        st = self.st
        if cfg.words_per_caption > 0:
            st["words"] = cfg.words_per_caption
        size = int(st["size"] * cfg.caption_scale)
        self.font = ImageFont.truetype(st.get("font_path") or str(FONTS / st["font"]), size)
        self.size = size
        self.asc, self.desc = self.font.getmetrics()
        self.pad = st["stroke"] + st["shadow"] * 2 + int(size * 0.22)
        self.hi = hex_rgb(cfg.highlight_color)
        self.em = hex_rgb(cfg.emphasis_color)
        self.fill = hex_rgb(cfg.caption_color)
        self.duration = duration
        self.layout_at = layout_at
        self.max_w = OUT_W - 150

        emph_set = {norm_word(e) for x in emphasis for e in str(x).split() if e}
        emoji_map: dict[str, str] = {}
        for item in emojis or []:
            if isinstance(item, dict) and item.get("word") and item.get("emoji"):
                emoji_map.setdefault(norm_word(str(item["word"]).split()[0]), str(item["emoji"]).strip()[:4])
        used_emoji = set()
        ws: list[Word] = []
        # whisper splits numbers like "$10" ",000" → glue them back together
        merged: list[dict] = []
        for w in words:
            if merged and re.match(r"^[,.]\d", w["w"]) and re.search(r"\d$", merged[-1]["w"]):
                merged[-1] = {**merged[-1], "w": merged[-1]["w"] + w["w"], "e": w["e"]}
            else:
                merged.append(dict(w))
        words = merged
        for w in words:
            t = clean_word(w["w"], st["upper"])
            if not t:
                continue
            n = norm_word(w["w"])
            emo = ""
            if n in emoji_map and n not in used_emoji:
                emo = emoji_map[n]
                used_emoji.add(n)
            wd = Word(t, w["s"], w["e"], n in emph_set, emo)
            wd._brk = bool(re.search(r"[.?!,;:…]$", w["w"]))
            ws.append(wd)

        max_chars = max(6, int(1700 / size))
        self.chunks: list[Chunk] = []
        groups = make_chunks(ws, st["words"], max_chars)
        for gi, g in enumerate(groups):
            nxt = groups[gi + 1][0].s if gi + 1 < len(groups) else duration
            end = min(g[-1].e + 0.3, nxt)
            if nxt - g[-1].e < 0.4:
                end = nxt
            self.chunks.append(Chunk(g, g[0].s, end, layout_at(g[0].s)["caption_y"]))
        self._ci = 0

        self.emoji_font = None
        if cfg.emojis:
            for p in EMOJI_FONTS:
                if Path(p).exists():
                    try:
                        self.emoji_font = ImageFont.truetype(p, 109)
                    except OSError:
                        pass
                    break
        self._emoji_cache: dict[str, np.ndarray | None] = {}

        # title cards at the top: the hook title, or a countdown's intro title and then a rank card per moment
        self.title_end = duration if cfg.title_seconds < 0 else min(duration, cfg.title_seconds)
        self.cards: list[tuple[float, float, np.ndarray, float, bool]] = []   # t0, t1, sprite, y, slides out
        if ranks:
            start = 0.0
            if title and cfg.title_seconds != 0:
                start = min(2.2, max(0.0, ranks[0]["t1"] - 1.5))
                if start > 0.5:
                    self.cards.append((0.0, start, self._render_title(title), layout_at(0.0)["title_y"], True))
                else:
                    start = 0.0
            for r in ranks:
                t0 = max(r["t0"], start)
                if r["t1"] - t0 > 0.3:
                    self.cards.append((t0, r["t1"], self._render_rank(int(r["rank"]), str(r["label"] or "")),
                                       layout_at(t0)["title_y"], r["t1"] < duration - 0.05))
        elif title and cfg.title_seconds != 0:
            self.cards.append((0.0, self.title_end, self._render_title(title), layout_at(0.0)["title_y"],
                               cfg.title_seconds > 0))

    # ── text layout & sprites
    def _layout(self, texts: list[str]):
        f, st = self.font, self.st
        widths = [f.getlength(t) for t in texts]
        space = f.getlength(" ") * (1.0 + 0.9 * (st["pop"] - 1.0) / 0.22 * 0.5) + self.size * 0.06
        # the active word pops to st["pop"]× around its centre: leave room so its outline never
        # touches a neighbour (long words need more than the usual space)
        reach = lambda w: (st["pop"] - 1.0) * (w / 2 + st["stroke"])
        gaps = [max(space, 2 * st["stroke"] + self.size * 0.05 + reach(max(widths[i], widths[i + 1])))
                for i in range(len(texts) - 1)]

        def span(a: int, b: int) -> float:          # width of words a..b-1 set on one line
            return sum(widths[a:b]) + sum(gaps[a:b - 1])

        lines = [list(range(len(texts)))]
        if span(0, len(texts)) > self.max_w and len(texts) > 1:  # balance across two lines
            best, bi = 1e9, 1
            for i in range(1, len(texts)):
                worst = max(span(0, i), span(i, len(texts)))
                if worst < best:
                    best, bi = worst, i
            lines = [list(range(bi)), list(range(bi, len(texts)))]
        lh = self.asc + self.desc
        gap = int(self.size * 0.02)
        line_ws = [span(ln[0], ln[-1] + 1) for ln in lines]
        W = int(max(line_ws) + 2 * self.pad)
        H = int(len(lines) * lh + (len(lines) - 1) * gap + 2 * self.pad)
        pos = [None] * len(texts)
        for li, ln in enumerate(lines):
            x = (W - line_ws[li]) / 2
            y = self.pad + li * (lh + gap)
            for i in ln:
                pos[i] = (x, y)
                x += widths[i] + (gaps[i] if i < len(gaps) else 0.0)
        return pos, widths, W, H

    def _draw_text(self, canvas: Image.Image, items: list[tuple[float, float, str, tuple]], stroke: int):
        st = self.st
        if st["shadow"]:
            m = Image.new("L", canvas.size, 0)
            d = ImageDraw.Draw(m)
            for x, y, t, _ in items:
                d.text((x, y), t, font=self.font, fill=255, stroke_width=stroke)
            m = m.filter(ImageFilter.GaussianBlur(st["shadow"]))
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            sh.putalpha(m.point(lambda v: int(v * 0.75)))
            canvas.alpha_composite(sh, (0, int(st["shadow"] * 0.7)))
        d = ImageDraw.Draw(canvas)
        for x, y, t, col in items:
            d.text((x, y), t, font=self.font, fill=col + (255,), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))

    def _chunk_sprites(self, c: Chunk, j: int):
        """The caption line's images, made once. Frames are composed on several threads (render.py), and the font
        library can't draw from two at once, so making them is locked; using them isn't."""
        key = j
        spr = c.sprites.get(key)
        if spr is not None:
            return spr
        with self._lock:                       # (old states are dropped inside the lock; a dropped one is remade)
            spr = c.sprites.get(key)
            return spr if spr is not None else self._make_chunk_sprites(c, j)

    def _make_chunk_sprites(self, c: Chunk, j: int):
        key = j
        st = self.st
        texts = [w.text for w in c.words]
        pos, widths, W, H = self._layout(texts)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        items = []
        for i, w in enumerate(c.words):
            if i == j:
                continue
            col = self.em if (w.emph and st["emph_always"]) else self.fill
            items.append((pos[i][0], pos[i][1], w.text, col))
        self._draw_text(canvas, items, st["stroke"])
        line = _to_premul(canvas)
        word = None
        slot = (0.0, 0.0)
        if j >= 0:
            w = c.words[j]
            word, slot = self._word_sprite(w, widths[j], pos[j], W, H, j)
        c.sprites[key] = (line, word, slot, (W, H))
        # keep memory bounded: only this chunk's current/next states
        for k in list(c.sprites):
            if k < j - 1:
                del c.sprites[k]
        return c.sprites[key]

    def _word_sprite(self, w: Word, width: float, p, W, H, j):
        st = self.st
        boxpad_x, boxpad_y = int(self.size * 0.16), int(self.size * 0.10)
        padw = self.pad + boxpad_x
        lh = self.asc + self.desc
        cw, ch = int(width + 2 * padw), int(lh + 2 * self.pad)
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        col = self.em if w.emph else self.hi
        if st["active"] == "box":
            l, t, r, b = self.font.getbbox(w.text, anchor="la")
            box = (padw + l - boxpad_x, self.pad + t - boxpad_y, padw + r + boxpad_x, self.pad + b + boxpad_y)
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle(box, radius=int(self.size * 0.2), fill=(0, 0, 0, 150))
            sh = sh.filter(ImageFilter.GaussianBlur(8))
            canvas.alpha_composite(sh, (0, 6))
            ImageDraw.Draw(canvas).rounded_rectangle(box, radius=int(self.size * 0.2), fill=col + (255,))
            txt = (17, 17, 17) if _lum(col) > 0.55 else (255, 255, 255)
            ImageDraw.Draw(canvas).text((padw, self.pad), w.text, font=self.font, fill=txt + (255,))
        else:
            self._draw_text(canvas, [(padw, self.pad, w.text, col)], st["stroke"])
        if st["tilt"]:
            rnd = random.Random(zlib.crc32(f"{w.text}|{round(w.s, 2)}".encode()))   # the same tilt every render
            ang = rnd.uniform(-st["tilt"], st["tilt"])
            canvas = canvas.rotate(ang, resample=Image.BICUBIC, expand=False)
        # centre of the word slot relative to the line-sprite centre
        slot = (p[0] + width / 2 - W / 2, p[1] + lh / 2 - H / 2)
        return _to_premul(canvas), slot

    def _emoji(self, e: str):
        if e in self._emoji_cache:
            return self._emoji_cache[e]
        with self._lock:
            return self._emoji_cache[e] if e in self._emoji_cache else self._make_emoji(e)

    def _make_emoji(self, e: str):
        spr = None
        if self.emoji_font:
            try:
                im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
                ImageDraw.Draw(im).text((80, 80), e, font=self.emoji_font, embedded_color=True, anchor="mm")
                bb = im.getbbox()
                if bb:
                    im = im.crop(bb).resize((150, int(150 * (bb[3] - bb[1]) / max(1, bb[2] - bb[0]))), Image.LANCZOS)
                    spr = _to_premul(im)
            except Exception:
                spr = None
        self._emoji_cache[e] = spr
        return spr

    def _render_title(self, title: str) -> np.ndarray:
        img = self._title_image(title)
        if self.st["title"] == "beast":
            img = img.rotate(-2.5, resample=Image.BICUBIC, expand=False)
        return _to_premul(img)

    def _render_rank(self, rank: int, label: str) -> np.ndarray:
        """A countdown's rank card: a big "#3" over the moment's label (#1 a bit bigger)."""
        size = int((175 if rank == 1 else 150) * self.cfg.title_scale)
        font = ImageFont.truetype(str(FONTS / "LuckiestGuy-Regular.ttf"), size)
        text = f"#{rank}"
        l0, t0, r0, b0 = font.getbbox(text, anchor="la")
        nw, nh = int(r0 - l0 + 80), int(b0 - t0 + 70)
        num = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
        sh = Image.new("L", num.size, 0)
        ImageDraw.Draw(sh).text((40 - l0, 30 - t0), text, font=font, fill=255, stroke_width=14)
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        shadow = Image.new("RGBA", num.size, (0, 0, 0, 0))
        shadow.putalpha(sh.point(lambda v: int(v * 0.85)))
        num.alpha_composite(shadow, (0, 8))
        ImageDraw.Draw(num).text((40 - l0, 30 - t0), text, font=font, fill=self.hi + (255,), stroke_width=13,
                                 stroke_fill=(0, 0, 0, 255))
        lab = self._title_image(label) if label.strip() else Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        W = max(num.width, lab.width)
        canvas = Image.new("RGBA", (W, num.height + lab.height - 30), (0, 0, 0, 0))
        canvas.alpha_composite(num, ((W - num.width) // 2, 0))
        canvas.alpha_composite(lab, ((W - lab.width) // 2, num.height - 30))
        if self.st["title"] == "beast":
            canvas = canvas.rotate(-2.5, resample=Image.BICUBIC, expand=False)
        return _to_premul(canvas)

    def _title_image(self, title: str) -> Image.Image:
        beast = self.st["title"] == "beast"
        size = int((96 if beast else 72) * self.cfg.title_scale)
        font = ImageFont.truetype(str(FONTS / ("LuckiestGuy-Regular.ttf" if beast else "Montserrat-ExtraBold.ttf")), size)
        text = title.upper() if beast else title
        maxw = OUT_W - 160
        words = text.split()
        lines = [text]
        if font.getlength(text) > maxw and len(words) > 1:
            # fewest lines that fit, then balance them (no lonely last word)
            for n in (2, 3):
                best = None
                import itertools
                for cuts in itertools.combinations(range(1, len(words)), n - 1):
                    parts = [" ".join(words[a:b]) for a, b in zip((0,) + cuts, cuts + (len(words),))]
                    widest = max(font.getlength(x) for x in parts)
                    if widest <= maxw and (best is None or widest < best[0]):
                        best = (widest, parts)
                if best:
                    lines = best[1]
                    break
        lines = lines[:3]
        asc, desc = font.getmetrics()
        lh = asc + desc
        padx, pady = int(size * 0.35), int(size * 0.16)
        W = int(max(font.getlength(l) for l in lines) + 2 * padx + 60)
        H = int(len(lines) * (lh + pady * 2) + 60)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(canvas)
        y = 30
        for i, l in enumerate(lines):
            lw = font.getlength(l)
            x = (W - lw) / 2
            if beast:
                col = self.hi if i == len(lines) - 1 and len(lines) > 1 else (255, 255, 255)
                sh = Image.new("L", canvas.size, 0)
                ImageDraw.Draw(sh).text((x, y + pady), l, font=font, fill=255, stroke_width=12)
                sh = sh.filter(ImageFilter.GaussianBlur(9))
                shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                shadow.putalpha(sh.point(lambda v: int(v * 0.8)))
                canvas.alpha_composite(shadow, (0, 8))
                d = ImageDraw.Draw(canvas)
                d.text((x, y + pady), l, font=font, fill=col + (255,), stroke_width=11, stroke_fill=(0, 0, 0, 255))
            else:
                l0, t0, r0, b0 = font.getbbox(l, anchor="la")
                box = (x + l0 - padx, y + pady + t0 - pady, x + r0 + padx, y + pady + b0 + pady)
                d.rounded_rectangle(box, radius=int(size * 0.28), fill=(255, 255, 255, 255))
                d.text((x, y + pady), l, font=font, fill=(16, 16, 16, 255))
            y += lh + pady * 2 - (int(size * 0.12) if not beast else int(size * 0.25))
        return canvas

    # ── per frame
    def _chunk_at(self, t: float) -> Chunk | None:
        cs = self.chunks
        i = self._ci
        if i < len(cs) and cs[i].s > t:
            i = 0
        while i < len(cs) and cs[i].e <= t:
            i += 1
        self._ci = i
        if i < len(cs) and cs[i].s <= t < cs[i].e:
            return cs[i]
        return None

    def draw(self, frame: np.ndarray, t: float) -> None:
        st = self.st
        # title cards: slide down with a bounce, slide back up at the end
        for t0, t1, spr, ty, slides_out in self.cards:
            if not t0 <= t < t1:
                continue
            since = t - t0
            tin = since / 0.4
            k = ease_out_back(tin, 1.6) if tin < 1 else 1.0
            out = (t - (t1 - 0.28)) / 0.28 if slides_out else -1
            y = ty + spr.shape[0] / 2 - 30
            y += (1 - k) * -160
            a = min(1.0, since / 0.15)
            sc = 0.85 + 0.15 * k
            if out > 0:
                a *= 1 - ease_out_cubic(out)
                y -= 90 * ease_out_cubic(out)
            blit(frame, spr, OUT_W / 2, y, sc, a)
            break

        c = self._chunk_at(t)
        if c is not None:
            tc = t - c.s
            k = ease_out_back(tc / 0.17, 2.2)
            scale = 0.7 + 0.3 * k
            alpha = min(1.0, tc / 0.05)
            j = -1
            for i, w in enumerate(c.words):
                if w.s <= t:
                    j = i
            line, word, slot, (W, H) = self._chunk_sprites(c, j)
            cy = c.y
            blit(frame, line, OUT_W / 2, cy, scale, alpha)
            if word is not None:
                w = c.words[j]
                tw = t - w.s
                if tw < 0.07:
                    ws = 0.8 + (st["pop"] - 0.8) * ease_out_cubic(tw / 0.07)
                else:
                    ws = st["rest"] + (st["pop"] - st["rest"]) * math.exp(-(tw - 0.07) * 14)
                blit(frame, word, OUT_W / 2 + slot[0] * scale, cy + slot[1] * scale, scale * ws, alpha)
            # emoji above the line, pops in when its word is spoken, gently floats
            for w in c.words:
                if w.emoji and w.s <= t:
                    spr = self._emoji(w.emoji)
                    if spr is None:
                        continue
                    te = t - w.s
                    es = 0.3 + 0.7 * ease_out_back(te / 0.25, 2.6)
                    bob = math.sin(te * 5.0) * 6
                    ey = cy - H * scale / 2 - spr.shape[0] * 0.35 + bob
                    blit(frame, spr, OUT_W / 2, ey, es, min(1.0, te / 0.08))
                    break

        if self.cfg.progress_bar and self.duration > 0:
            h = 9
            frame[0:h] = (frame[0:h].astype(np.float32) * 0.45).astype(np.uint8)
            wfill = int(OUT_W * min(1.0, t / self.duration))
            if wfill > 0:
                frame[0:h, :wfill] = self.hi[::-1]

    def emoji_times(self) -> list[float]:
        return [w.s for c in self.chunks for w in c.words if w.emoji]
