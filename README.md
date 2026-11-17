<div align="center">

<img src="docs/media/logo.svg" width="72" height="72" alt="">

# Clippy

Turn long videos into ready-to-post vertical shorts, on your own PC.<br>
Local AI picks the moments, then Clippy reframes, captions and edits them. No subscriptions, no API bills.

[![tests](https://github.com/StormAmdam/clippy/actions/workflows/tests.yml/badge.svg)](https://github.com/StormAmdam/clippy/actions/workflows/tests.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-ffe135?labelColor=232429)](LICENSE)
[![Linux](https://img.shields.io/badge/runs%20on-Linux%20%2F%20WSL2-ffe135?labelColor=232429)](#requirements)

</div>

<img src="docs/media/demo.webp" width="100%" alt="A 3-minute 4K NASA interview on the left, its timeline below with three highlighted moments, each linked to one of three finished vertical shorts playing on the right">

<sub>Real output, nothing edited by hand. A public-domain NASA interview went in; Clippy picked the three moments
marked on the timeline and turned them into the shorts on the right in 2 min 47 s on an RTX 3080.
The only settings changed: 3 clips, 15–40 s each.</sub>

## What you get

Paste a YouTube link (or drop in a video file) and Clippy:

1. **finds the moments worth posting.** Whisper transcribes the video, then a local LLM reads the whole thing,
   picks the strongest stories and tightens each clip so it opens on a hook and ends on the payoff.
   YouTube's "Most replayed" graph is used when the video has one.
2. **reframes them to 9:16.** Face tracking keeps the speaker in frame and only moves the camera when they do.
   Two people get a split screen; slides and wide shots get a blurred background.
3. **edits for retention.** Dead air is cut, the clip opens with a flash-forward of its best line, captions pop in
   word by word with key words coloured, emojis land on the right words, and whooshes and zoom punches mark the beats.
4. **hands you a finished file** (1080×1920, −14 LUFS, H.264) with a title, caption and hashtags.

Music, gameplay and sports videos work too. Without speech, Clippy picks moments from the sound, the replay graph
and the picture instead.

## Quick start

```
git clone https://github.com/StormAmdam/clippy.git
cd clippy
bash setup.sh       # installs everything into .venv, checks your GPU and AI server, runs the tests
./clippy.sh web     # opens the app at http://127.0.0.1:7860
```

Clippy needs an AI server to pick clips. Any OpenAI-compatible one works: see [AI server](#ai-server).

## Caption styles

The same moment of the same short in each style:

<table>
<tr>
<td align="center"><img src="docs/media/style-beast.jpg" width="200" alt="Beast style: big comic-book captions, the active word in yellow"><br><b>Beast</b><br><sub>comic, bouncy, tilted</sub></td>
<td align="center"><img src="docs/media/style-hormozi.jpg" width="200" alt="Hormozi style: heavy uppercase captions, active word in yellow"><br><b>Hormozi</b><br><sub>bold, coloured key words</sub></td>
<td align="center"><img src="docs/media/style-box.jpg" width="200" alt="Box style: the active word sits in a yellow highlight box"><br><b>Box</b><br><sub>highlight box</sub></td>
<td align="center"><img src="docs/media/style-clean.jpg" width="200" alt="Clean style: smaller sentence-case captions"><br><b>Clean</b><br><sub>calm and minimal</sub></td>
</tr>
</table>

Colours, size, position and words per line are all adjustable.

## The app

**Review.** Watch each short, fix the title or description, then approve or reject. Nothing is published without you.

<img src="docs/media/app-review.jpg" width="100%" alt="Review page: a short waiting for approval, with its title, description, hashtags and source credit">

**Find videos.** Ranks YouTube videos by growth, engagement, length and replay peaks. No API key needed.

<img src="docs/media/app-find.jpg" width="100%" alt="Find videos leaderboard: videos ranked by score, views, views per day, breakout, engagement, length and age, each with a Clip it button">

**Autopilot.** Give it a channel and its sources; it finds a good video, makes the shorts and queues them for you.

<img src="docs/media/app-auto.jpg" width="100%" alt="Autopilot channel card: find, pick best, make shorts, you review, publish">

Approved shorts upload to YouTube (optionally spaced out, e.g. one every 4 hours) or are exported with a caption
file for posting to TikTok from your phone.

## Requirements

- **Linux** (Debian/Ubuntu, Arch, Fedora…). On Windows, use WSL2 with Ubuntu.
- **Python 3.11+** and **ffmpeg**. `setup.sh` offers to install ffmpeg if it's missing.
- **An NVIDIA GPU** is recommended, for Whisper and NVENC encoding. Everything also runs on the CPU, just slower.
- Optional: an emoji font for caption emojis (`fonts-noto-color-emoji` on Debian/Ubuntu, `noto-fonts-emoji` on Arch).

`setup.sh` is safe to run again any time, for example to update yt-dlp when YouTube changes something.
It only uses `sudo` after asking.

## AI server

Clippy sends the transcript to an OpenAI-compatible chat server (default `http://127.0.0.1:8080/v1`).

- **llama.cpp** (what the demo used): a prebuilt CUDA build and a Qwen3.6-35B-A3B model. Setup steps, a launcher
  and a systemd service are in [`tools/ai-server/`](tools/ai-server/README.md). No compiling.
- **Ollama:** set `llm_url = "http://127.0.0.1:11434/v1"` and a model, e.g. `llm_model = "qwen3:8b"`.
- **Free cloud tiers** (Groq, Gemini): examples are in [`config.toml`](config.toml).

Change it in the app under **Settings**, or in `config.toml`.

<details>
<summary><b>Command line</b></summary>

```
./clippy.sh web                      # the web app (add --host 0.0.0.0 to open it from your phone on the same Wi-Fi)
./clippy.sh "https://youtu.be/…"     # or straight from the terminal
./clippy.sh "https://youtu.be/…" -n 8 --max 45
./clippy.sh "https://youtu.be/…" --reuse --style box --color "#3DFF7A"   # same picks, new look (skips the AI)
./clippy.sh "https://youtu.be/…" --no-sfx --no-teaser                    # calmer edit
./clippy.sh "https://youtu.be/…" --no-talking                            # music / gameplay / sport: skip Whisper
./clippy.sh ~/Videos/my-video.mp4    # local files work too
./clippy.sh auto all                 # run every Autopilot channel now (results go to Review)
```

Clips land in `output/<video-id>/clips/`, with `result.json` holding titles, captions and hashtags.
Re-running a video reuses its download and transcript.
</details>

<details>
<summary><b>Settings</b></summary>

Everything is optional and documented in [`config.toml`](config.toml): AI server, number and length of clips,
caption style, colours and size, hook title, split screen, silence cutting, sound effects, loudness and more.
The **Settings** page in the app covers the common ones, plus storage cleanup and *Start at login*.
Environment variables `CLIPPY_<NAME>` override both, e.g. `CLIPPY_OUTPUT_DIR=/data/clips`.

**Sharing the GPU with the AI server:** Whisper needs about 2.6 GB of free VRAM. If your AI server leaves less,
Clippy pauses its systemd service (`llama_service`, default `llama-coder`) while transcribing and starts it again
right after. Set `free_gpu_for_whisper = false` to never touch it.
</details>

<details>
<summary><b>How Autopilot picks videos</b></summary>

1. Create a channel in **Autopilot**: niches, keywords, source channels, language, caption look, shorts per run,
   schedule, and where to publish.
2. Press **Run now**, let it run on its schedule while the app is open, or call `./clippy.sh auto all` from cron.
   It scans YouTube, picks the best video it hasn't used yet and makes the shorts.
3. Review them. Approved shorts upload to YouTube or export for TikTok.

By default a channel only clips videos from the **source channels you list** (creators who allow clipping, or
clipping campaigns) and **Creative Commons** videos, and every description gets a credit line. "Creative Commons"
is what the uploader declares; re-uploaders sometimes mislabel.

YouTube uploading takes a one-time, free setup (guided in the app). Google allows about 6 uploads a day on the free
quota, and uploads from an unverified Google Cloud project stay private until it passes Google's free API audit.
TikTok direct posting needs an approved TikTok developer app, so Clippy exports ready-to-post files instead.
</details>

<details>
<summary><b>How Find videos ranks</b></summary>

| Signal | What it measures |
|---|---|
| Views per day | how fast the video is growing right now |
| Breakout | views divided by channel subscribers; outliers point to a topic that's spreading |
| Engagement | (likes + 4 × comments) divided by views |
| Length | long videos (podcasts, interviews, streams) hold the most clippable moments |
| Replay peaks | spikes in YouTube's "Most replayed" graph |
| Licence | Creative Commons means reuse is allowed |

Filter by niche, keywords, a channel watchlist, upload date, length and language, then press **Clip it** on any row.
Each scan is saved in `output/_finder/` so you can compare over time.
</details>

## Development

```
.venv/bin/python -m pytest -q        # no GPU, network or AI server needed
```

FastAPI server (`clippy/server.py`) with a vanilla-JS front end (`clippy/static/`). Each step is its own module:
`download → transcribe → picker / highlights → reframe → overlay → render`.
To move an install with all its data to another PC, see [MOVING.md](MOVING.md).

## Copyright

Platforms don't pay for reposted content you don't have the rights to, and it gets claimed. Clip your own videos,
creators who've given permission, paid clipping campaigns, or properly licensed material, and credit the source.

## License

[MIT](LICENSE) © 2026 Storm Amdam. You're free to use, change and share Clippy, as long as you keep the
copyright notice and credit the original project.

## Credits

- Demo footage: [*Meet NASA Astronaut Christina Koch*](https://www.youtube.com/watch?v=942n6DsJIRw) (NASA Johnson)
  and NASA Goddard videos in the screenshots. NASA material is public domain; NASA does not endorse this project.
- Fonts: [Montserrat](https://github.com/JulietaUla/Montserrat) and [Barlow](https://github.com/jpt/barlow)
  (SIL Open Font License 1.1), [Luckiest Guy](https://fonts.google.com/specimen/Luckiest+Guy) (Apache 2.0).
  Face detection: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (MIT).
  License texts are in [`LICENSES/`](LICENSES).
- Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  [FFmpeg](https://ffmpeg.org), [OpenCV](https://opencv.org), [FastAPI](https://fastapi.tiangolo.com) and
  [llama.cpp](https://github.com/ggml-org/llama.cpp).
