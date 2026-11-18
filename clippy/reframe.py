"""Turn a 16:9 shot into 9:16: shot detection + face tracking + a smooth virtual camera.

Per shot we choose a layout:
  crop  – follow the main face (locked off when they barely move, smooth pan when they do)
  split – two people far apart (podcast wide shot): stack them top/bottom
  fit   – no faces (screen recording, b-roll, gameplay): full frame over a blurred copy
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from .config import ROOT  # noqa: E402

FACE_MODEL = ROOT / "models" / "face_detection_yunet_2023mar.onnx"
OUT_W, OUT_H = 1080, 1920
ANALYSIS_W = 512


def even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def frame_reader(src: str, start: float, nframes: int, fps: str, size: tuple[int, int] | None = None,
                 hwaccel: bool = False):
    """ffmpeg command yielding BGR frames from src starting at `start`, exactly `nframes` at constant `fps`."""
    vf = f"fps={fps}"
    if size:
        vf += f",scale={size[0]}:{size[1]}:flags=area"
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if hwaccel:
        cmd += ["-hwaccel", "cuda"]
    cmd += ["-ss", f"{start:.3f}", "-i", src, "-an", "-sn", "-frames:v", str(nframes), "-vf", vf,
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    return cmd


class FrameStream:
    def __init__(self, cmd: list[str], w: int, h: int):
        self.w, self.h = w, h
        self.nbytes = w * h * 3
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=self.nbytes * 2)

    def __iter__(self):
        assert self.proc.stdout
        while True:
            buf = self.proc.stdout.read(self.nbytes)
            if len(buf) < self.nbytes:
                break
            yield np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
        self.close()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()


@dataclass
class Shot:
    f0: int
    f1: int                      # exclusive
    layout: str = "crop"
    cx: np.ndarray | None = None  # per-frame crop centre x (source px), crop layout
    cy: float = 0.0               # face centre y (source px) for zoomed crops
    fw: float = 0.0               # face width (source px)
    panels: list = field(default_factory=list)  # split: [(x0, y0, w, h), (x0, y0, w, h)]
    fit_crop: tuple | None = None  # fit: (x0, width) window in source px, or None = whole frame
    fit_mid: bool = False          # fit: centre the picture vertically (no captions need room below it)


def _smooth(x: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0 or len(x) < 3:
        return x
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(x, r, mode="edge")
    return np.convolve(pad, k, mode="valid")


def _tracks(samples: list[tuple[int, np.ndarray]], W: int) -> list[dict]:
    """Greedy-link face detections into tracks. samples: (frame, faces[N,5] = cx,cy,w,h,score in source px)."""
    tracks: list[dict] = []
    for fi, faces in samples:
        used = set()
        for f in sorted(faces, key=lambda r: -r[2] * r[3]):
            best, bd = None, 0.12 * W
            for t in tracks:
                if id(t) in used or fi - t["last"] > 45:
                    continue
                d = abs(t["pts"][-1][1] - f[0]) + 0.5 * abs(t["pts"][-1][2] - f[1])
                if d < bd:
                    best, bd = t, d
            if best is None:
                best = {"pts": [], "last": fi}
                tracks.append(best)
            best["pts"].append((fi, float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[4])))
            best["last"] = fi
            used.add(id(best))
    for t in tracks:
        p = np.array(t["pts"])
        t["n"] = len(p)
        # a "face" that never moves a single pixel is a graphic (icon, poster, thumbnail), not a person
        t["static"] = len(p) >= 8 and float(np.std(p[:, 1]) + np.std(p[:, 2])) < 0.004 * W
        t["area"] = float(np.mean(p[:, 3] * p[:, 4]))
        t["weight"] = float(np.sum(p[:, 3] * p[:, 4] * p[:, 5]))
        t["cx"] = float(np.median(p[:, 1]))
        t["cy"] = float(np.median(p[:, 2]))
        t["fh"] = float(np.median(p[:, 4]))
    return tracks


def fit_crop_for(col_energy: np.ndarray, W: int, H: int, aspect: float = 4 / 3,
                 edge_limit: float = 0.18) -> tuple[float, float] | None:
    """For a shot without faces: a 4:3 window around where the detail is, so the picture shows bigger
    (1080x810 instead of 1080x608). Keeps the whole frame when detail reaches the edges (slides, wide text).
    aspect=1 gives a square window (1080x1080) for clips without captions."""
    target_w = H * aspect
    e = np.asarray(col_energy, dtype=np.float64)
    total = float(e.sum())
    if W <= target_w * 1.05 or total <= 0:
        return None
    n = len(e)
    band_frac = 0.125 if aspect == 4 / 3 else max(0.125, (1 - target_w / W) / 2)
    band = max(1, int(round(n * band_frac)))
    if (e[:band].sum() + e[-band:].sum()) / total >= edge_limit:
        return None
    centre = float((np.arange(n) + 0.5) @ e / total) * W / n
    x0 = float(np.clip(centre - target_w / 2, 0, W - target_w))
    return round(x0, 1), round(target_w, 1)


def detect_cuts(scores: np.ndarray, corrs: np.ndarray, fps: float) -> list[int]:
    """Hard cuts = a sudden content jump relative to the neighbouring frames (adaptive, so dark
    scenes and fast motion both work), or a big colour change."""
    cuts = [0]
    min_gap = int(fps * 0.4)
    for i in range(1, len(scores)):
        s = scores[i]
        nb = np.concatenate([scores[max(1, i - 3): i], scores[i + 1: i + 4]])
        base = float(np.mean(nb)) if len(nb) else 0.0
        jump = s >= 12 and s >= 3.5 * base + 3
        colour = corrs[i] < 0.5 and s >= 6
        if (jump or colour) and (len(cuts) == 1 or i - cuts[-1] >= min_gap):
            cuts.append(i)
    return cuts


def _plan_crop(shot: Shot, main: dict, a: int, b: int, fps: float, W: int, cw: float) -> None:
    pts = np.array(main["pts"])
    frames = np.arange(a, b)
    target = _smooth(np.interp(frames, pts[:, 0], pts[:, 1]), 0.12 * fps)
    fw = float(np.median(pts[:, 3]))
    # how far the face centre may sit from the crop centre and still be fully in frame (with margin)
    slack = max(0.02 * cw, cw / 2 - 0.65 * fw)
    dz = min(0.12 * cw, slack)
    # camera-operator style: hold still, re-frame only when the subject leaves the comfort zone
    holds = np.empty(len(frames))
    i = 0
    while i < len(frames):
        lo = hi = target[i]
        j = i
        while j + 1 < len(frames):
            nlo, nhi = min(lo, target[j + 1]), max(hi, target[j + 1])
            if nhi - nlo > 2 * dz:
                break
            lo, hi, j = nlo, nhi, j + 1
        holds[i: j + 1] = (lo + hi) / 2
        i = j + 1
    cx = _smooth(holds, 0.28 * fps)                   # eased moves between holds
    cx = np.clip(cx, target - slack, target + slack)  # never lose the face
    cx = _smooth(cx, 0.06 * fps)
    shot.layout = "crop"
    shot.fw = fw
    shot.cx = np.clip(cx, cw / 2, W - cw / 2)
    shot.cy = main["cy"]


def _plan_split(shot: Shot, pair: list[dict], W: int, H: int) -> None:
    panels = []
    for t in sorted(pair, key=lambda t: t["cx"]):
        ph = float(np.clip(t["fh"] * 2.8, 0.35 * H, H))
        pw = ph * OUT_W / (OUT_H / 2)
        if pw > W:
            pw = W
            ph = pw * (OUT_H / 2) / OUT_W
        x0 = float(np.clip(t["cx"] - pw / 2, 0, W - pw))
        y0 = float(np.clip(t["cy"] - 0.42 * ph, 0, H - ph))
        panels.append((x0, y0, pw, ph))
    shot.layout, shot.panels = "split", panels


def face_detector(w: int, h: int, score: float = 0.38):
    """YuNet, loaded from memory: OpenCV can't open a file path with letters like ö or 测 on Windows
    (C:\\Users\\Jörg\\…), but Python can."""
    model = np.frombuffer(FACE_MODEL.read_bytes(), np.uint8)
    return cv2.FaceDetectorYN.create("onnx", model, np.zeros(0, np.uint8), (w, h), score, 0.3, 20)


def analyze(src: str, start: float, nframes: int, fps: float, W: int, H: int, split_screen: bool = True,
            progress=lambda p: None, fps_str: str | None = None, no_captions: bool = False) -> list[Shot]:
    aw = min(ANALYSIS_W, W)
    ah = even(H * aw / W)
    sx, sy = W / aw, H / ah
    # low threshold here; strong faces (>= 0.6) are preferred, weak ones are a fallback
    # (e.g. someone looking down at their notes)
    det = face_detector(aw, ah)
    step = max(1, round(fps / 10))

    scores, corrs = [0.0], [1.0]
    samples: list[tuple[int, np.ndarray]] = []
    energies: dict[int, np.ndarray] = {}   # per sampled frame: horizontal detail per column (for fit crops)
    prev_hsv = prev_hist = None
    n = 0
    for i, frame in enumerate(FrameStream(frame_reader(src, start, nframes, fps_str or f"{fps:.6f}", (aw, ah)), aw, ah)):
        n = i + 1
        small = cv2.resize(frame, (96, 54), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        if prev_hsv is not None:
            scores.append(float(np.mean(cv2.absdiff(hsv, prev_hsv))))
            corrs.append(float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)))
        prev_hsv, prev_hist = hsv, hist
        if i % step == 0:
            gx = cv2.Sobel(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_32F, 1, 0, ksize=3)
            energies[i] = cv2.resize(np.abs(gx).mean(axis=0, keepdims=True), (96, 1), interpolation=cv2.INTER_AREA)[0]
            _, faces = det.detect(frame)
            rows = []
            if faces is not None:
                for f in faces:
                    x, y, w, h, score = f[0], f[1], f[2], f[3], f[-1]
                    if w * h < (aw * ah) * 0.0015:  # ignore tiny background faces
                        continue
                    if (y + h / 2) > ah * 0.84:  # bottom HUD: scoreboards, webcam bubbles, lower thirds
                        continue
                    rows.append([(x + w / 2) * sx, (y + h / 2) * sy, w * sx, h * sy, score])
            samples.append((i, np.array(rows, dtype=np.float32).reshape(-1, 5)))
        if i % 30 == 0:
            progress(i / max(1, nframes))
    nframes = max(1, n)
    cuts = detect_cuts(np.array(scores[:nframes]), np.array(corrs[:nframes]), fps) + [nframes]

    portrait_src = W / H <= 9 / 16 + 0.02
    crop_w_full = min(W, H * 9 / 16)
    shots: list[Shot] = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b <= a:
            continue
        shot = Shot(a, b, layout="fit")
        shots.append(shot)
        sm = [(fi, f) for fi, f in samples if a <= fi < b]
        if portrait_src or not sm:
            continue
        shot_energy = [energies[fi] for fi, _ in sm if fi in energies]
        if shot_energy:
            col = np.mean(shot_energy, axis=0)
            if no_captions:  # nothing goes under the picture → bigger square window, centred
                shot.fit_crop = fit_crop_for(col, W, H, aspect=1.0, edge_limit=0.35) or fit_crop_for(col, W, H)
                shot.fit_mid = True
            else:
                shot.fit_crop = fit_crop_for(col, W, H)
        elif no_captions:
            shot.fit_mid = True
        tracks = []
        for thr, need in ((0.6, 0.3), (0.38, 0.4)):
            smx = [(fi, f[f[:, 4] >= thr]) for fi, f in sm]
            smx = [(fi, f) for fi, f in smx if len(f)]
            if len(smx) < need * len(sm):
                continue
            tracks = [t for t in _tracks(smx, W) if t["n"] >= max(2, need * 0.5 * len(sm)) and not t["static"]]
            if tracks:
                break
        if not tracks:
            continue  # no reliable face → full frame over blurred background
        tracks.sort(key=lambda t: -t["weight"])
        main = tracks[0]
        # two people side by side that can't share one 9:16 crop → split screen
        if split_screen and len(tracks) > 1:
            other = tracks[1]
            if (other["n"] >= 0.5 * len(sm) and other["area"] >= 0.35 * main["area"]
                    and abs(other["cx"] - main["cx"]) > crop_w_full * 0.75):
                shot.fit_crop = None
                _plan_split(shot, [main, other], W, H)
                continue
        shot.fit_crop = None
        _plan_crop(shot, main, a, b, fps, W, crop_w_full)
    progress(1.0)
    return shots


# ───────────────────────── compositing ─────────────────────────

def _warp(frame: np.ndarray, x0: float, y0: float, w: float, h: float, out_w: int, out_h: int) -> np.ndarray:
    """Crop (sub-pixel) + scale in one step — smooth pans with no 1px jitter."""
    s = out_w / w
    M = np.array([[s, 0, -x0 * s], [0, out_h / h, -y0 * out_h / h]], dtype=np.float32)
    # cubic, not Lanczos: 5x faster, and on footage the two are visually identical (~52 dB PSNR)
    interp = cv2.INTER_AREA if s < 0.95 else cv2.INTER_CUBIC
    if interp == cv2.INTER_AREA:  # warpAffine doesn't do AREA; crop then resize
        xi, yi = int(round(x0)), int(round(y0))
        return cv2.resize(frame[yi:yi + int(round(h)), xi:xi + int(round(w))], (out_w, out_h), interpolation=cv2.INTER_AREA)
    return cv2.warpAffine(frame, M, (out_w, out_h), flags=interp, borderMode=cv2.BORDER_REPLICATE)


def fit_geometry(W: int, H: int, mid: bool = False) -> tuple[int, int]:
    """(foreground height, top y) for the fit layout. mid=True centres it (no captions underneath)."""
    fh = even(OUT_W * H / W)
    if fh >= OUT_H:
        return OUT_H, 0
    top = int((OUT_H - fh) * (0.5 if mid else 0.40))
    return fh, top


def compose(frame: np.ndarray, shot: Shot, local_i: int, zoom: float) -> np.ndarray:
    H, W = frame.shape[:2]
    if shot.layout == "crop":
        cw0 = min(W, H * 9 / 16)
        ch0 = cw0 * 16 / 9
        if zoom > 1.001 and shot.fw > 0:
            zoom = min(zoom, max(1.0, cw0 * 0.62 / shot.fw))  # never zoom so far the face gets cut
        cw, ch = cw0 / zoom, ch0 / zoom
        cx = float(shot.cx[min(local_i, len(shot.cx) - 1)])
        x0 = float(np.clip(cx - cw / 2, 0, W - cw))
        y0 = float(np.clip(shot.cy - 0.40 * ch, 0, H - ch)) if zoom > 1.001 else (H - ch) / 2
        return _warp(frame, x0, y0, cw, ch, OUT_W, OUT_H)
    if shot.layout == "split":
        half = OUT_H // 2
        top = _warp(frame, *shot.panels[0], OUT_W, half)
        bot = _warp(frame, *shot.panels[1], OUT_W, half)
        out = np.vstack([top, bot])
        out[half - 3: half + 3] = 12
        return out
    # fit: the frame (or its 4:3 detail window) over a blurred, darkened, zoomed copy
    if shot.fit_crop:
        fx, fwid = shot.fit_crop
        fg_src = frame[:, int(round(fx)): int(round(fx + fwid))]
    else:
        fg_src = frame
    fh, top = fit_geometry(fg_src.shape[1], H, shot.fit_mid)
    if fh >= OUT_H:  # already vertical
        return _warp(frame, 0, max(0.0, (H - W * 16 / 9) / 2), W, min(H, W * 16 / 9), OUT_W, OUT_H)
    small = cv2.resize(frame, (max(16, W // 10), max(16, H // 10)), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    bw = sh * 9 / 16
    bx = int((sw - bw) / 2)
    bg = small[:, max(0, bx): max(0, bx) + max(1, int(bw))]
    # heavy blur done at quarter resolution, then upscaled: same look, ~13x cheaper than blurring 1080x1920
    bg = cv2.GaussianBlur(bg, (0, 0), 3)
    bg = cv2.resize(bg, (OUT_W // 4, OUT_H // 4), interpolation=cv2.INTER_LINEAR)
    bg = cv2.convertScaleAbs(cv2.GaussianBlur(bg, (0, 0), 4.5), alpha=0.55)
    bg = cv2.resize(bg, (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)
    fg = cv2.resize(fg_src, (OUT_W, fh), interpolation=cv2.INTER_AREA if fg_src.shape[1] > OUT_W else cv2.INTER_CUBIC)
    bg[top: top + fh] = fg
    return bg


def layout_positions(shot: Shot, W: int, H: int, caption_y: float) -> dict:
    if shot.layout == "split":
        return {"caption_y": OUT_H // 2, "title_y": 130}
    if shot.layout == "fit":
        fh, top = fit_geometry(int(round(shot.fit_crop[1])) if shot.fit_crop else W, H, shot.fit_mid)
        if fh >= OUT_H:
            return {"caption_y": int(OUT_H * caption_y), "title_y": 220}
        return {"caption_y": min(OUT_H - 260, top + fh + 150), "title_y": max(120, top - 230)}
    return {"caption_y": int(OUT_H * caption_y), "title_y": 220}
