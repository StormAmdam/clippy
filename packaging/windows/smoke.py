"""Windows smoke test, part 2 (build.ps1 -SmokeTest runs it with the app's own Python, against the running app):

  1. speech: Windows' built-in voice reads a short story into a WAV file, ffmpeg turns it into a video
  2. transcription: Whisper (the small "tiny" model, on the CPU) must hear the story's words
  3. a real clip: with a fixed transcript, the app makes a short through its own web API: the built-in AI picks the
     moment, then reframing, captions, emoji, sound effects, encoding. The result must be a playable 1080x1920 video.

Everything lives in the app folder, which build.ps1 puts in a folder named like a non-English Windows user's
(C:\\Users\\Jörg…). Finished files and a few frames go to --out, for a person to look at.

    python smoke.py --app <app folder> --api http://127.0.0.1:7860 --out <folder>
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STORY = ("Jörg thought his café would fail in a week. He had no money, no customers, and a coffee machine that "
         "exploded on the very first day. Then something crazy happened. A famous food critic walked in by mistake, "
         "looking for the train station. She ordered the only thing on the menu, a naïve little cinnamon bun. Two days "
         "later, her review went viral. Four hundred people stood in line outside his door. The secret was not the "
         "coffee. It was the story. Every bun came with a handwritten note about why he started. People did not buy "
         "coffee. They bought the reason behind it. Today he runs twelve cafés across the country, and he still writes "
         "every single note by hand. So here is the lesson. Nobody cares about your product until they care about "
         "you. Tell them why you started, and they will tell everyone else.")

SPEAK = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
"Voices: " + (($s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }) -join ', ')
$s.Rate = 0
$s.SetOutputToWaveFile($env:SMOKE_WAV)
$s.Speak($env:SMOKE_TEXT)
$s.Dispose()
"""

RESULTS: list[tuple[str, str]] = []


def step(name: str):
    print(f"\n--- {name}", flush=True)


def ok(name: str, detail: str = "") -> None:
    RESULTS.append((name, detail))
    print(f"  OK  {name}" + (f": {detail}" if detail else ""), flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed ({r.returncode}):\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r


def ffprobe(path: Path) -> dict:
    return json.loads(run(["ffprobe", "-v", "error", "-show_entries",
                           "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(path)]).stdout)


def make_video(folder: Path) -> Path:
    step("1. Speech and a video to clip")
    wav = folder / "speech.wav"
    script = base64.b64encode(SPEAK.encode("utf-16-le")).decode()
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", script],
            env={**os.environ, "SMOKE_WAV": str(wav), "SMOKE_TEXT": STORY}, timeout=300)
    print("  " + r.stdout.strip())
    video = folder / "Jörg’s café story 🎬.mp4"            # a file name Windows tools often get wrong
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
         "-i", str(wav), "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", str(video)], timeout=600)
    dur = float(ffprobe(video)["format"]["duration"])
    if dur < 30:
        raise RuntimeError(f"The spoken story is only {dur:.0f} s long")
    ok("Windows voice + ffmpeg made a video", f"{video.name}, {dur:.0f} s")
    return video


def words_of(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def test_transcription(app: Path, video: Path) -> None:
    step("2. Transcription on the CPU (Whisper tiny)")
    import cv2

    from clippy import config, reframe, transcribe
    try:                    # for the record: Clippy loads the face model from memory; could OpenCV open the path?
        cv2.FaceDetectorYN.create(str(reframe.FACE_MODEL), "", (320, 240))
        print("  (OpenCV can open the face model from this folder by itself too)")
    except cv2.error as e:
        print(f"  (OpenCV can't open the face model from this folder by itself: {str(e).strip()[:160]})")
    work = Path(tempfile.mkdtemp(prefix="whisper-", dir=app / "data"))
    try:
        cfg = config.load({"whisper_model": "tiny", "whisper_device": "cpu"})
        t0 = time.time()
        tr = transcribe.transcribe(cfg, video, work, log=lambda m: print("  " + m))
        secs = time.time() - t0
    finally:
        shutil.rmtree(work, ignore_errors=True)
    heard = " ".join(w["w"] for w in tr["words"])
    print(f"  heard: {heard[:300]}…")
    want = words_of(STORY)
    got = want & words_of(heard)
    share = len(got) / len(want)
    if tr["device"] != "cpu" or share < 0.6:
        raise RuntimeError(f"Whisper heard only {share:.0%} of the story's words (device {tr['device']})")
    ok("Whisper tiny transcribed on the CPU", f"{len(tr['words'])} words, {share:.0%} of the story, {secs:.0f} s")


def canned_transcript(duration: float) -> dict:
    """The story's words spread over the speech: a fixed transcript, so the clip test doesn't depend on Whisper."""
    tokens = STORY.split()
    t0, t1 = 0.4, duration - 0.4
    step_s = (t1 - t0) / len(tokens)
    words = [{"w": w, "s": round(t0 + i * step_s, 3), "e": round(t0 + (i + 0.85) * step_s, 3), "p": 0.99}
             for i, w in enumerate(tokens)]
    segments, start = [], 0
    for i, w in enumerate(words):
        if w["w"].endswith(".") or i == len(words) - 1:
            segments.append({"s": words[start]["s"], "e": w["e"], "text": " ".join(x["w"] for x in words[start:i + 1]),
                             "i0": start, "i1": i + 1})
            start = i + 1
    return {"language": "en", "duration": duration, "words": words, "segments": segments, "device": "canned"}


def test_clip(app: Path, api: str, video: Path, out: Path) -> None:
    step("3. A real clip, made by the app")
    import httpx
    import numpy as np

    from clippy import config, download, transcribe
    info = download.probe(str(video))
    work = config.output_root(config.load()) / info["id"]
    work.mkdir(parents=True, exist_ok=True)
    (work / "transcript.json").write_text(json.dumps(canned_transcript(info["duration"]), ensure_ascii=False),
                                          encoding="utf-8")
    np.save(work / "envelope.npy", transcribe.loudness_envelope(transcribe.load_audio(video)))
    opts = {"clips": 1, "min_seconds": 12, "max_seconds": 30, "caption_style": "beast", "emojis": True, "sfx": True,
            "teaser": True, "motion": True}
    jid = httpx.post(f"{api}/api/jobs", json={"url": str(video), "options": opts}, timeout=30).json()["id"]
    t0, last = time.time(), ""
    while True:
        job = httpx.get(f"{api}/api/jobs/{jid}", timeout=30).json()
        if job["msg"] != last:
            last = job["msg"]
            print(f"  [{time.time() - t0:5.0f}s] {job['stage']}: {last}", flush=True)
        if job["state"] in ("done", "error", "cancelled", "interrupted"):
            break
        if time.time() - t0 > 40 * 60:
            raise RuntimeError("Making the clip took more than 40 minutes")
        time.sleep(3)
    log = "\n".join(job.get("log") or [])
    if job["state"] != "done":
        raise RuntimeError(f"The clip job ended as {job['state']}: {job.get('error')}\n{log[-4000:]}")
    if "Traceback" in log:
        raise RuntimeError("The clip was made, but the job log has an error in it:\n" + log[-4000:])
    clip = job["result"]["clips"][0]
    root = config.output_root(config.load())
    mp4, jpg = root / clip["file"], root / clip["thumb"]
    meta = ffprobe(mp4)
    v = next(s for s in meta["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in meta["streams"])
    dur = float(meta["format"]["duration"])
    problems = [p for p, bad in (("not 1080x1920", (v["width"], v["height"]) != (1080, 1920)),
                                 ("not H.264", v["codec_name"] != "h264"), ("no sound", not has_audio),
                                 (f"{dur:.1f} s long", not 8 <= dur <= 45), ("no thumbnail", not jpg.exists()))
                if bad]
    leftovers = [p.name for p in mp4.parent.iterdir() if p.is_dir() or p.suffix in (".tmp", ".log")]
    if leftovers:
        problems.append(f"temp files left behind: {leftovers}")
    if problems:
        raise RuntimeError(f"The clip {mp4.name} is wrong: {', '.join(problems)}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mp4, out / "clip.mp4")
    shutil.copy2(jpg, out / "clip-thumb.jpg")
    for i, f in enumerate((0.15, 0.5, 0.85)):
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * f:.2f}", "-i", str(mp4), "-frames:v", "1",
             "-vf", "scale=540:-2", str(out / f"frame-{i + 1}.jpg")])
    (out / "clip.json").write_text(json.dumps({**clip, "log": job.get("log")}, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    ok("The app made a clip with the built-in AI",
       f"“{clip['title']}”, {dur:.1f} s, 1080x1920 H.264 with sound, in {time.time() - t0:.0f} s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True, type=Path)
    ap.add_argument("--api", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    app = a.app.resolve()
    sys.path.insert(0, str(app))                       # the app's own Clippy, not the source checkout
    os.environ["PATH"] = str(app / "bin") + os.pathsep + os.environ["PATH"]
    import clippy
    assert Path(clippy.__file__).resolve().parent == app / "clippy", clippy.__file__
    print(f"App folder: {app}")
    video = make_video(app.parent)
    test_transcription(app, video)
    test_clip(app, a.api, video, a.out)
    print("\nSmoke test, part 2:")
    for name, detail in RESULTS:
        print(f"  OK  {name}: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
