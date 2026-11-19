"""Render one clip.

  [teaser: the clip's best line] ─whoosh─▶ [main clip]
  → reframe 9:16 → jump-cut silences → motion FX (intro slam, push-ins, zoom punches, zoom-blur transition)
  → animated captions / title / emoji / progress bar → SFX → two-pass loudness → NVENC (x264 fallback)
"""
from __future__ import annotations

import bisect
import concurrent.futures as cf
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import gpu, sfx
from .config import Settings
from .overlay import Overlay
from .reframe import OUT_H, OUT_W, FrameStream, analyze, compose, finish_looks, frame_reader, layout_positions
from .transcribe import ENV_HZ

# threads that compose frames, and that ffmpeg's filters (sharpening) use: half the CPU, at most 4. Same frames as one
# thread, faster (sharpening on one thread was the slowest step of a render)
COMPOSE_WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))
FILTER_THREADS = COMPOSE_WORKERS


# ───────────────────────── silence → jump cuts ─────────────────────────

def keep_intervals(words: list[dict], clip_start: float, dur: float, fps: float, env: np.ndarray | None,
                   cfg: Settings) -> list[tuple[int, int]]:
    """Frame ranges [f0, f1) to keep after removing dead air between words."""
    nframes = int(round(dur * fps))
    if not cfg.remove_silences or len(words) < 2:
        return [(0, nframes)]
    speech_db = None
    if env is not None and len(env):
        a, b = int(clip_start * ENV_HZ), int((clip_start + dur) * ENV_HZ)
        seg = env[a:b]
        if len(seg):
            speech_db = float(np.percentile(seg, 80))
    keeps, cur = [], 0.0
    for p, q in zip(words[:-1], words[1:]):
        if q["s"] - p["e"] <= cfg.max_pause:
            continue
        g0, g1 = p["e"] - clip_start + 0.16, q["s"] - clip_start - 0.10
        if g1 - g0 < 0.12:
            continue
        if speech_db is not None:
            a, b = int((clip_start + g0) * ENV_HZ), int((clip_start + g1) * ENV_HZ)
            gseg = env[a:b]
            if len(gseg) and float(np.percentile(gseg, 90)) > speech_db - 15:
                continue  # not actually quiet (music, laughter, crowd) – keep it
        keeps.append((cur, g0))
        cur = g1
    keeps.append((cur, dur))
    out = []
    for t0, t1 in keeps:
        f0, f1 = int(round(t0 * fps)), min(nframes, int(round(t1 * fps)))
        if f1 - f0 >= 2:
            out.append((f0, f1))
    return out or [(0, nframes)]


def _map_time(t: float, keeps_s: list[tuple[float, float]]) -> float:
    acc = 0.0
    for a, b in keeps_s:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


# ───────────────────────── clip structure ─────────────────────────

@dataclass
class Part:
    kind: str                   # "teaser" | "main" | "moment" (one of a countdown's)
    start: float                # source seconds
    words: list
    shots: list
    keeps: list                 # local frame ranges
    nframes: int
    out0: int = 0
    entries: list = field(default_factory=list)  # (out_idx, src_local_idx, shot_idx, keep_idx)


def _build_entries(part: Part, fps: float, out0: int) -> None:
    shots = part.shots
    starts = [s.f0 for s in shots]
    # a camera cut a split second after the start / before the end would flash another angle → freeze instead
    lead_end = shots[1].f0 if len(shots) > 1 and shots[0].f1 - shots[0].f0 < 0.5 * fps else 0
    tail_start = shots[-1].f0 if len(shots) > 1 and shots[-1].f1 - shots[-1].f0 < 0.4 * fps else part.nframes
    o = out0
    part.out0 = out0
    part.entries = []
    for k, (a, b) in enumerate(part.keeps):
        for f in range(a, min(b, part.nframes)):
            src = min(max(f, lead_end), tail_start - 1)
            si = max(0, bisect.bisect_right(starts, src) - 1)
            part.entries.append((o, src, si, k))
            o += 1


def _ease_out(x):
    x = np.clip(x, 0, 1)
    return 1 - (1 - x) ** 3


def _motion(n: int, fps: float, segs: list[tuple[int, int, str]], punches: list[int], boundaries: list[int],
            cfg: Settings):
    """Per-output-frame zoom, zoom-blur amount and white-flash amount."""
    t = np.arange(n) / fps
    z = np.ones(n)
    alt = 0
    for o0, o1, kind in segs:
        alt = alt ^ 1 if kind == "cut" else 0
        if cfg.punch_in and alt:
            z[o0:o1] *= 1.08
        if cfg.motion:  # slow push-in keeps static shots alive
            L = (o1 - o0) / fps
            rate = min(0.014, 0.05 / max(L, 1e-3))
            z[o0:o1] *= 1 + rate * np.arange(o1 - o0) / fps
    blur = np.zeros(n)
    flash = np.zeros(n)
    if cfg.motion:
        m = t < 0.38  # intro slam: start zoomed in, snap out
        z[m] *= 1 + 0.17 * (1 - _ease_out(t[m] / 0.38))
        for p in punches:  # zoom punch on key words
            dt = t - p / fps
            m = (dt >= 0) & (dt < 0.7)
            env = np.where(dt < 0.05, dt / 0.05, np.exp(-(dt - 0.05) * 7.5))
            z[m] *= 1 + 0.085 * env[m]
    for B in boundaries:  # teaser → main: zoom-blur whoosh + flash
        tb = B / fps
        pre = (t >= tb - 0.14) & (t < tb)
        x = (t[pre] - (tb - 0.14)) / 0.14
        z[pre] *= 1 + 0.28 * x ** 2
        blur[pre] = x
        post = (t >= tb) & (t < tb + 0.22)
        x = (t[post] - tb) / 0.22
        z[post] *= 1 + 0.28 * (1 - x) ** 2
        blur[post] = (1 - x)
        f = (t >= tb) & (t < tb + 0.13)
        flash[f] = 0.6 * (1 - (t[f] - tb) / 0.13)
    return np.minimum(z, 1.32), blur, flash


def _zoom_frame(img: np.ndarray, z: float, cx: float = OUT_W / 2, cy: float = OUT_H / 2) -> np.ndarray:
    if z <= 1.002:
        return img
    M = np.array([[z, 0, (1 - z) * cx], [0, z, (1 - z) * cy]], dtype=np.float32)
    return cv2.warpAffine(img, M, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# ───────────────────────── audio ─────────────────────────

def _voice_filters(cfg: Settings) -> str:
    """Speech polish applied before loudness normalisation: cut rumble below ~70 Hz, gently even out levels."""
    if not cfg.voice_polish:
        return ""
    return "highpass=f=70,acompressor=threshold=0.125:ratio=2:attack=20:release=250,"


def _part_chain(idx: int, part: Part, fps: float, label: str, teaser: bool) -> str:
    keeps_s = [(a / fps, b / fps) for a, b in part.keeps]
    if len(keeps_s) == 1:
        a, b = keeps_s[0]
        d = b - a
        fo = 0.08 if teaser else 0.02
        return (f"[{idx}:a]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:d=0.015,afade=t=out:st={max(0.0, d - fo):.4f}:d={fo}[{label}]")
    k = len(keeps_s)
    parts = [f"[{idx}:a]asplit={k}" + "".join(f"[{label}s{i}]" for i in range(k))]
    for i, (a, b) in enumerate(keeps_s):
        d = b - a
        fade = min(0.012, d / 4)
        parts.append(f"[{label}s{i}]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={fade:.4f},afade=t=out:st={d - fade:.4f}:d={fade:.4f}[{label}c{i}]")
    parts.append("".join(f"[{label}c{i}]" for i in range(k)) + f"concat=n={k}:v=0:a=1[{label}]")
    return ";".join(parts)


def _speech_graph(parts: list[Part], fps: float, first_input: int) -> str:
    chains = [_part_chain(first_input + i, p, fps, f"p{i}", p.kind == "teaser") for i, p in enumerate(parts)]
    if len(parts) == 1:
        return chains[0] + ";[p0]anull[sp]"
    return ";".join(chains) + ";" + "".join(f"[p{i}]" for i in range(len(parts))) + \
        f"concat=n={len(parts)}:v=0:a=1[sp]"


def _part_inputs(src: str, parts: list[Part], fps: float) -> list[str]:
    args = []
    for p in parts:
        args += ["-ss", f"{p.start:.3f}", "-t", f"{p.nframes / fps:.3f}", "-i", src]
    return args


def _measure_loudness(src: str, parts: list[Part], fps: float, target: float, voice: str = "") -> dict | None:
    fc = _speech_graph(parts, fps, 0) + f";[sp]{voice}loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json[a]"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", *_part_inputs(src, parts, fps),
                        "-filter_complex", fc, "-map", "[a]", "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def _encoder_args(cfg: Settings, nvenc: bool) -> list[str]:
    q = str(cfg.video_quality)
    if nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", q, "-b:v", "0",
                "-maxrate", "16M", "-bufsize", "32M", "-profile:v", "high", "-bf", "3",
                "-spatial-aq", "1", "-temporal-aq", "1", "-aq-strength", "8"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(max(14, int(q) - 1)), "-profile:v", "high"]


# ───────────────────────── main entry ─────────────────────────

def render_clip(cfg: Settings, src: Path, vinfo: dict, clip: dict, words_all: list[dict], env: np.ndarray | None,
                out_path: Path, progress=lambda p, m: None, log=print, eyes=None, parts=None) -> dict:
    """Render one clip. On any failure or cancel, leaves no partial video, thumbnail or temp folder behind.
    eyes: clippy.vision.Eyes when the AI can see, so the framing keeps what matters in the picture."""
    tmp = Path(tempfile.mkdtemp(prefix="clippy-", dir=out_path.parent))
    try:
        return _render(cfg, src, vinfo, clip, words_all, env, out_path, tmp, progress, log, eyes, parts)
    except BaseException:
        for f in (out_path, out_path.with_suffix(".jpg")):
            f.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def plan(cfg: Settings, src: Path, vinfo: dict, clip: dict, words_all: list[dict], env: np.ndarray | None,
         eyes=None, log=print, progress=lambda p, m="": None) -> list:
    """A clip's parts and their shots (faces, cuts, framing, the AI's look): everything before the frames are made.
    pipeline.run plans the next clip while this one renders; render_clip(parts=…) then skips it."""
    fps, fps_str = vinfo["fps"], vinfo.get("fps_str") or f'{vinfo["fps"]:.6f}'
    W, H = vinfo["width"], vinfo["height"]
    srcs = str(src)

    # parts: optional flash-forward teaser + the main clip, or a countdown's moments (#3, #2, #1)
    specs = []
    moments = clip.get("segments") or []
    tz = clip.get("teaser")
    if moments:
        specs = [("moment", m["start"], m["end"], words_all[m.get("i0", 0): m.get("i1", 0)]) for m in moments]
    elif cfg.teaser and tz and tz.get("end", 0) > tz.get("start", 0):
        specs.append(("teaser", tz["start"], tz["end"], words_all[tz["i0"]: tz["i1"]]))
    if not moments:
        specs.append(("main", clip["start"], clip["end"], words_all[clip["i0"]: clip["i1"]]))

    parts: list[Part] = []
    looks: list = []                               # what to ask the AI, for all parts in one go (finish_looks)
    for k, (kind, s, e, words) in enumerate(specs):
        n = int(round((e - s) * fps))
        lo, hi = k / len(specs), (k + 1) / len(specs)
        shots = analyze(srcs, s, n, fps, W, H, cfg.split_screen, fps_str=fps_str, no_captions=not words_all,
                        progress=lambda p, lo=lo, hi=hi: progress(0.2 * (lo + (hi - lo) * p), "Finding faces & camera cuts…"),
                        eyes=eyes, log=log, look_later=looks)
        n = shots[-1].f1
        keeps = keep_intervals(words, s, n / fps, fps, env, cfg) if kind != "teaser" else [(0, n)]
        parts.append(Part(kind, s, words, shots, keeps, n))
    finish_looks(eyes, looks, log)                 # the teaser and the clip: one request, then every shot framed
    return parts


def _render(cfg: Settings, src: Path, vinfo: dict, clip: dict, words_all: list[dict], env: np.ndarray | None,
            out_path: Path, tmp: Path, progress, log, eyes=None, parts=None) -> dict:
    fps, fps_str = vinfo["fps"], vinfo.get("fps_str") or f'{vinfo["fps"]:.6f}'
    W, H = vinfo["width"], vinfo["height"]
    srcs = str(src)

    moments = clip.get("segments") or []           # a countdown's moments (#3, #2, #1)
    # 1) parts (planned already when the pipeline looked ahead)
    if parts is None:
        parts = plan(cfg, src, vinfo, clip, words_all, env, eyes, log, progress)
    else:
        progress(0.2, "Finding faces & camera cuts…")

    out0 = 0
    for p in parts:
        _build_entries(p, fps, out0)
        out0 += len(p.entries)
    n_out = out0
    out_dur = n_out / fps
    main = parts[-1]
    removed = main.nframes / fps - len(main.entries) / fps
    if removed > 0.05:
        log(f"    cut {len(main.keeps) - 1} pauses (-{removed:.1f}s)")

    # 2) timeline: segments (jump cuts / camera cuts / teaser boundary)
    segs: list[tuple[int, int, str]] = []
    boundaries: list[int] = []
    prev = None
    seg_start, seg_kind = 0, "start"
    for pi, p in enumerate(parts):
        for (o, src_i, si, k) in p.entries:
            key = (pi, si, k)
            if prev is not None and key != prev:
                segs.append((seg_start, o, seg_kind))
                seg_kind = "part" if pi != prev[0] else ("cut" if k != prev[2] else "shot")
                if seg_kind == "part":
                    boundaries.append(o)
                seg_start = o
            prev = key
    segs.append((seg_start, n_out, seg_kind))

    # 3) captions in output time
    cap_words = []
    for p in parts:
        keeps_s = [(a / fps, b / fps) for a, b in p.keeps]
        base = p.out0 / fps
        for w in p.words:
            cap_words.append({"w": w["w"], "s": base + _map_time(w["s"] - p.start, keeps_s),
                              "e": base + _map_time(w["e"] - p.start, keeps_s)})

    flat = [(pi, e) for pi, p in enumerate(parts) for e in p.entries]

    def layout_at(t_out: float):
        o = min(n_out - 1, max(0, int(t_out * fps)))
        pi, (_, _, si, _) = flat[o]
        return layout_positions(parts[pi].shots[si], W, H, cfg.caption_y)

    ranks = [{"t0": p.out0 / fps, "t1": (p.out0 + len(p.entries)) / fps, "rank": m.get("rank", 0),
              "label": m.get("label", "")} for p, m in zip(parts, moments)]
    ov = Overlay(cfg, cap_words, out_dur, clip.get("title", ""), clip.get("emphasis", []),
                 clip.get("emoji", []), layout_at, ranks=ranks or None)

    # zoom punches on AI key words (spaced out, away from cuts)
    emph = {re.sub(r"[^\w'$%]", "", e.lower()) for x in clip.get("emphasis", []) for e in str(x).split()}
    cut_frames = [s for s, _, kind in segs if kind != "start"]
    punches: list[int] = []
    if cfg.motion:
        for w in cap_words[len(parts[0].words) if parts[0].kind == "teaser" else 0:]:
            if re.sub(r"[^\w'$%]", "", w["w"].lower()) not in emph:
                continue
            o = int(w["s"] * fps)
            if o < fps * 1.0 or any(abs(o - c) < fps * 0.5 for c in cut_frames):
                continue
            if punches and o - punches[-1] < fps * 2.8:
                continue
            punches.append(o)
        beat_parts = ([(p, m.get("beats")) for p, m in zip(parts, moments)] if moments
                      else [(parts[-1], clip.get("beats"))])
        for main_p, beats in beat_parts if not punches else []:   # no talking: punch on music / impact hits
            end = main_p.out0 + len(main_p.entries)
            for t in beats or []:
                o = main_p.out0 + int(round((t - main_p.start) * fps))
                if not (main_p.out0 + fps * 1.0 <= o < end - fps * 0.5):
                    continue
                if any(abs(o - c) < fps * 0.4 for c in cut_frames) or (punches and o - punches[-1] < fps * 2.8):
                    continue
                punches.append(o)
    zoom, blur, flash = _motion(n_out, fps, segs, punches, boundaries, cfg)

    # 4) sound effects
    sfx_file = None
    n_sfx = 0
    if cfg.sfx and cfg.sfx_volume > 0:
        g = cfg.sfx_volume
        ev = [(0.0, "impact", 0.42 * g)]
        if clip.get("title") and cfg.title_seconds != 0:
            ev.append((0.14, "whoosh", 0.3 * g))
        for b in boundaries:
            ev.append((b / fps, "whoosh", 0.6 * g))
            if moments:                                  # the next rank slams in
                ev.append((b / fps + 0.12, "impact", 0.36 * g))
        last = 0.0
        for s, _, kind in segs:
            ts = s / fps
            if kind == "cut" and ts - last >= 2.5 and all(abs(ts - b / fps) > 1 for b in boundaries):
                ev.append((ts, "whoosh", 0.2 * g))
                last = ts
        for p in punches:
            ev.append((p / fps, "pop", 0.32 * g))
        for te in ov.emoji_times():
            if all(abs(te - x[0]) > 0.4 for x in ev):
                ev.append((te, "pop", 0.26 * g))
        n_sfx = len(ev)
        sfx_file = tmp / "sfx.wav"
        sfx.write_wav(sfx_file, sfx.build_track(ev, out_dur + 0.5, seed=int(clip["start"] * 10)))

    # 5) audio graph
    has_audio = vinfo.get("has_audio", True)
    P = len(parts)
    afc = ""
    if has_audio:
        meas = _measure_loudness(srcs, parts, fps, cfg.loudness, _voice_filters(cfg))
        if meas and meas.get("input_i") not in (None, "-inf"):
            ln = (f"loudnorm=I={cfg.loudness}:TP=-1.5:LRA=11:measured_I={meas['input_i']}"
                  f":measured_TP={meas['input_tp']}:measured_LRA={meas['input_lra']}"
                  f":measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true")
        else:
            ln = f"loudnorm=I={cfg.loudness}:TP=-1.5:LRA=11"
        afc = _speech_graph(parts, fps, 1) + f";[sp]{_voice_filters(cfg)}{ln},aresample=48000,aformat=channel_layouts=stereo"
        if sfx_file:
            afc += (f"[speech];[{P + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo[fx];"
                    f"[speech][fx]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.89:level=0[a]")
        else:
            afc += "[a]"

    upscale = OUT_W / min(W, H * 9 / 16)
    sharpen = "" if upscale < 1.15 else f"unsharp=5:5:{0.3 if upscale < 1.5 else 0.5}:5:5:0,"
    vfc = f"[0:v]{sharpen}scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v]"
    fc = vfc + (";" + afc if afc else "")

    white = None

    def render_frame(frame, part: Part, si: int, src_i: int, o: int) -> np.ndarray:
        nonlocal white
        shot = part.shots[si]
        z = float(zoom[o])
        b = float(blur[o])
        local = src_i - shot.f0
        if shot.layout == "crop":
            img = compose(frame, shot, local, z)
            if b > 0.05:
                acc = img.astype(np.float32)
                for k in (1, 2):
                    acc += compose(frame, shot, local, z * (1 + 0.07 * k * b))
                img = (acc / 3).astype(np.uint8)
        else:
            base = compose(frame, shot, local, 1.0)
            img = _zoom_frame(base, z)
            if b > 0.05:
                acc = img.astype(np.float32)
                for k in (1, 2):
                    acc += _zoom_frame(base, z * (1 + 0.07 * k * b))
                img = (acc / 3).astype(np.uint8)
        f = float(flash[o])
        if f > 0.01:
            if white is None:
                white = np.full_like(img, 255)
            img = cv2.addWeighted(img, 1 - f, white, f, 0)
        ov.draw(img, o / fps)
        return img

    def encode(nvenc: bool) -> tuple[int, str]:
        hw = gpu.has_cuda_decode() and (gpu.free_vram_mb() or 0) > 2500
        cmd = ["ffmpeg", "-v", "error", "-y", "-nostdin", "-filter_complex_threads", str(FILTER_THREADS),
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}", "-r", fps_str, "-i", "-"]
        if has_audio:
            cmd += _part_inputs(srcs, parts, fps)
            if sfx_file:
                cmd += ["-i", str(sfx_file)]
        cmd += ["-filter_complex", fc, "-map", "[v]"] + (["-map", "[a]"] if afc else [])
        cmd += _encoder_args(cfg, nvenc) + ["-colorspace", "bt709", "-color_primaries", "bt709",
                                            "-color_trc", "bt709", "-c:a", "aac", "-b:a", "192k",
                                            "-movflags", "+faststart", "-frames:v", str(n_out), str(out_path)]
        err_log = tmp / "ffmpeg.log"
        written = 0
        # three stages so decoding, compositing and encoding overlap:
        #   reader thread (ffmpeg → frames_q) → this thread (compose + overlay) → writer thread (out_q → encoder)
        frames_q: queue.Queue = queue.Queue(maxsize=6)
        out_q: queue.Queue = queue.Queue(maxsize=6)
        stop = threading.Event()

        def put(q, item) -> bool:
            while not stop.is_set():
                try:
                    q.put(item, timeout=0.2)
                    return True
                except queue.Full:
                    continue
            return False

        def reader():
            try:
                for pi, part in enumerate(parts):
                    need = part.entries[-1][1] if part.entries else -1   # last source frame this part uses
                    stream = FrameStream(frame_reader(srcs, part.start, part.nframes, fps_str, None, hwaccel=hw), W, H)
                    try:
                        for i, frame in enumerate(stream):
                            if i > need or not put(frames_q, (pi, i, frame)):
                                break
                    finally:
                        stream.close()
                    if not put(frames_q, (pi, None, None)):            # end-of-part marker
                        return
            except BaseException as e:   # hand decoder errors to the main thread
                put(frames_q, ("error", e, None))

        def writer():
            while True:
                data = out_q.get()
                if data is None:
                    return
                try:
                    enc.stdin.write(data)
                except (BrokenPipeError, ValueError, OSError):   # encoder died (e.g. NVENC unavailable)
                    stop.set()
                    return

        with open(err_log, "w", encoding="utf-8", errors="replace") as ef:
            enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=ef)
            assert enc.stdin
            reader_t = threading.Thread(target=reader, daemon=True)
            writer_t = threading.Thread(target=writer, daemon=True)
            reader_t.start()
            writer_t.start()
            finished = False
            # frames are composed on a few threads (OpenCV and NumPy work outside Python's lock) and written in order
            pool = cf.ThreadPoolExecutor(max_workers=COMPOSE_WORKERS, thread_name_prefix="compose")
            pending: deque = deque()

            def drain(keep: int) -> bool:
                """Write finished frames in order, leaving at most `keep` still being composed."""
                nonlocal last, written
                while pending and (len(pending) > keep or pending[0].done()):
                    last = pending.popleft().result()
                    if not put(out_q, last):
                        return False
                    written += 1
                    if written % 12 == 0:
                        progress(0.2 + 0.8 * written / max(1, n_out), "Rendering…")
                return True
            try:
                ptr, last = 0, None
                while not stop.is_set():
                    try:
                        pi, i, frame = frames_q.get(timeout=0.2)
                    except queue.Empty:
                        continue          # re-check `stop`: the encoder may have died while we waited
                    if pi == "error":
                        raise i
                    ent = parts[pi].entries
                    if i is None:                                    # this part is fully decoded
                        if not drain(0):
                            break
                        while ptr < len(ent) and last is not None:   # source ended early: hold last frame
                            if not put(out_q, last):
                                break
                            written += 1
                            ptr += 1
                        if pi == len(parts) - 1:
                            break
                        ptr, last = 0, None
                        continue
                    while ptr < len(ent) and ent[ptr][1] == i:
                        o, src_i, si, _ = ent[ptr]
                        pending.append(pool.submit(lambda f=frame, p=parts[pi], si=si, src_i=src_i, o=o:
                                                   render_frame(f, p, si, src_i, o).tobytes()))
                        ptr += 1
                        if not drain(2 * COMPOSE_WORKERS):
                            break
                drain(0)
                finished = True
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
                if finished:
                    put(out_q, None)          # writer flushes everything still queued, then exits
                    writer_t.join()
                else:
                    enc.kill()                # failure/cancel: abandon the encode (output gets deleted)
                stop.set()
                reader_t.join(timeout=10)
                try:
                    enc.stdin.close()
                except (BrokenPipeError, ValueError, OSError):
                    pass
                rc = enc.wait()
                if not finished:
                    while not out_q.empty():
                        out_q.get_nowait()
                    out_q.put(None)
                    writer_t.join(timeout=10)
        return rc, err_log.read_text(encoding="utf-8", errors="replace")

    use_nvenc = gpu.has_nvenc()
    rc, err = encode(use_nvenc)
    if (rc != 0 or not out_path.exists()) and use_nvenc:
        log("    GPU encoder unavailable right now (VRAM busy) – encoding on CPU instead")
        rc, err = encode(False)
    if rc != 0 or not out_path.exists():
        raise RuntimeError("Encoding failed:\n" + err[-1500:])

    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(2.0, out_dur / 2):.2f}", "-i", str(out_path),
                    "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "3", str(out_path.with_suffix(".jpg"))])
    layouts = sorted({s.layout for p in parts for s in p.shots})
    progress(1.0, "Done")
    return {"duration": round(out_dur, 2), "layouts": layouts, "cuts": len(main.keeps) - 1,
            "shots": sum(len(p.shots) for p in parts), "teaser": len(parts) > 1, "sfx": n_sfx,
            "punches": len(punches)}
