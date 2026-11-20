<div align="center">

<img src="docs/media/logo.svg" width="72" height="72" alt="">

# Clippy

Turn long videos into ready-to-post vertical shorts, on your own PC.<br>
Local AI picks the moments, then Clippy reframes, captions and edits them.<br>
Free and open source, for Windows and Linux. No subscriptions, no API bills.

<a href="https://github.com/StormAmdam/clippy/releases/latest"><img src="https://img.shields.io/badge/Download%20for%20Windows-ffe135?style=for-the-badge" alt="Download for Windows"></a>
<a href="#linux"><img src="https://img.shields.io/badge/Install%20on%20Linux-232429?style=for-the-badge" alt="Install on Linux"></a>

[![tests](https://github.com/StormAmdam/clippy/actions/workflows/tests.yml/badge.svg)](https://github.com/StormAmdam/clippy/actions/workflows/tests.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-ffe135?labelColor=232429)](LICENSE)
[![Windows and Linux](https://img.shields.io/badge/runs%20on-Windows%20%7C%20Linux-ffe135?labelColor=232429)](#requirements)

</div>

<img src="docs/media/demo.webp" width="100%" alt="A 3-minute 4K NASA interview on the left, its timeline below with three highlighted moments, each linked to one of three finished vertical shorts playing on the right">

<sub>Real output, nothing edited by hand. A public-domain NASA interview went in; Clippy picked the three moments
marked on the timeline and turned them into the shorts on the right in 2 min 47 s on an RTX 3080.
The only settings changed: 3 clips, 15–40 s each.</sub>

## What you get

Paste a YouTube link, or upload a video from your computer (drag it onto the page), and Clippy:

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

**Top countdowns.** Instead of separate shorts, Clippy can make one short that ranks a video's best moments of a
kind, #3, #2 and then #1, each with a big rank card: the funniest, craziest, most shocking or most wholesome moments.
For the funniest, laughter and loud reactions count too. Extensions add more kinds.

<img src="docs/media/countdown.jpg" width="100%" alt="Four frames of one countdown short made from a NASA video: the title Top 3 Craziest Moments, then rank cards #3 Billion Galaxies Survey, #2 Rogue Planets Drifting and #1 Universe Speeding Up, each above word-by-word captions">

<sub>A real countdown, made by Clippy from a public-domain NASA Goddard video.</sub>

**Extensions.** The Extensions page installs caption styles, countdown themes, sound effects and Find Videos topics
that other people made, from the community list or a link. Extensions with code stay off until you say you trust
them. [Make your own](docs/extensions.md).

**The AI looks at the video.** With a model that can see images (press **Add Vision** in AI & Tools, or a vision model
in Ollama or llama.cpp), the AI checks every shot so the important thing stays in the picture: a streamer's webcam
goes on top with the game's action below, a crop that would miss the action moves or shows the whole picture, and an
animal or object gets followed instead of a stray face. It also looks at a few frames of each candidate and keeps the
clips that look best on a phone. Without one, streams still get the webcam-on-top layout.

**Fix an almost-good short without another editor.** Quick Fix (in Review, the Library and Make Clips) shows the short
beside its source video: move where it starts and ends, tap a misspelled word in the transcript to fix it (it keeps
its timing), change the title, and only that short is rendered again. Nothing is picked again and the other shorts
stay as they are.

**Find a Quote.** For the line the AI skipped: open a video in the Library, search what's said, pick the first and
last line, and Clippy makes it a short with the usual captions and framing.

**Saved styles.** Save a look as a style (clean captions and calm edits for a podcast, bright captions and big effects
for a gaming channel) and use it in Make Clips, Find a Quote and Autopilot channels.

**Tell the AI what to look for.** An optional line on Make Clips, like "practical advice about pricing", makes it pick
only moments about that.

**Watch a recording folder.** Point Settings at one folder (OBS's recordings, for example) and every new recording
that finishes there becomes shorts by itself, with a saved style.

**Review on your phone.** Review → Review on Your Phone shows a QR code. Scan it on the same Wi-Fi to watch, approve
and save shorts from the couch. The phone gets a separate, limited page: it can't change settings or make clips.

## Install

### Windows

1. Download **Clippy-Setup-x.y.z-win64.exe** (x.y.z is the version) from the [latest release](https://github.com/StormAmdam/clippy/releases/latest)
   and run it. No admin rights needed. (Prefer no installer? The portable zip works from any folder.)
   Windows may say **"Windows protected your PC"** because the installer isn't code-signed yet: click
   **More info**, then **Run anyway**. ([Why](docs/code-signing.md).)
2. Clippy opens in its own window. On **AI & Tools**, press **Set Up Everything**: it downloads the video tools,
   the speech model and an AI model that fits your PC, or uses Ollama or LM Studio if you already run one.
3. Paste a YouTube link and press **Make Clips**.

Everything Clippy downloads stays inside its own folder, so uninstalling removes all of it. The uninstaller
offers to move your finished shorts to `Videos\Clippy` first. When a new version is out, Clippy tells you and updates
itself if you say so (or run a newer installer over it): downloaded models, settings and shorts stay. Turn on **Start at login** in Settings to keep Clippy running in the background for
scheduled Autopilot runs; it tells you with a Windows notification when new shorts are waiting.

### Linux

```
curl -fsSL https://raw.githubusercontent.com/StormAmdam/clippy/main/install.sh | bash
```

Setup puts Clippy in `~/clippy` and walks you through the rest (Python packages, ffmpeg, an emoji font, and a
local AI that fits your PC). Then start it with `clippy app` for its own window, or `clippy web` for a browser tab.
Run the install line again any time to update.

To remove it, run `clippy uninstall`. It removes the Clippy folder, the `clippy` command and Start at login, and moves
your finished shorts to `~/Videos/Clippy shorts` unless you say otherwise. It also offers to remove the AI and the
system packages setup installed for Clippy (never ones that were on your PC before). `clippy uninstall --help` lists
the options.

<details>
<summary><b>Windows with WSL instead</b></summary>

The Linux version also runs inside Ubuntu on Windows:

1. Right-click **Start**, open **Terminal (Admin)**, and run `wsl --install`. Restart when it asks.
2. Ubuntu opens after the restart. Choose a username and password.
3. With an NVIDIA card, keep its normal Windows driver up to date; don't install one inside Ubuntu.
4. In Ubuntu, paste the Linux install line. `clippy web` then opens in your Windows browser.
</details>

## Choose your AI

The **AI & Tools** page is where you control the AI. Download any of these and switch between them whenever you
like; the one that fits your PC best is marked. You can also paste a link to any `.gguf` model on Hugging Face.

| Model | Size | Good for |
|---|---|---|
| Qwen3.6 35B-A3B | 17.7 GB | Best picks. Runs partly from RAM, so it needs about 24 GB of RAM |
| Qwen3.5 9B | 5.7 GB | Good picks with an 8 GB graphics card or 16 GB of RAM |
| Qwen3.5 4B | 2.7 GB | Any PC, even without a graphics card |

Clippy runs the model itself: it starts it when it's time to pick clips, pauses it while Whisper needs the
graphics card, and frees the memory after 10 minutes without use. Prefer an AI app you already have? Choose
**Another App** and Clippy uses Ollama, LM Studio, llama.cpp, Jan, KoboldCpp or vLLM (see below).

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

**Two looks.** Caption print (above) sets titles like the captions in your shorts; Classic is calmer. Switch under
Settings → Theme.

## Requirements

- **Windows 10/11**: the app above brings everything it needs.
- **Linux** (Ubuntu, Debian, Arch, Fedora…), also inside WSL. Python 3.11+ is all you need beforehand; setup installs
  the rest.
- **An NVIDIA graphics card** is recommended, for fast transcribing and encoding. Everything also runs on the
  CPU, just slower.
- **Disk space:** about 3 GB for Clippy, plus 3–23 GB for a local AI model, plus your videos.

Already cloned the repo? `bash setup.sh` does the same as the install line. It's safe to run again any time, for
example to update yt-dlp when YouTube changes something, or to add an AI later: `bash setup.sh --ai ollama`.

## Use an AI app you already have

Clippy needs a local AI model to read the transcript and pick the moments. **It finds one by itself:** whatever
is running on this PC (or, from WSL, on the Windows side) on these apps' usual ports.

| App | Usual address | Notes |
|---|---|---|
| [Ollama](https://ollama.com) | `127.0.0.1:11434` | Easiest. Clippy asks it for a 16k-token context, so long videos aren't cut off |
| [LM Studio](https://lmstudio.ai) | `127.0.0.1:1234` | Start the server in the Developer tab; load the model with a context of 16384 or more |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | `127.0.0.1:8080` | Fastest with big models. [`tools/ai-server/`](tools/ai-server/README.md) has a ready launcher |
| [Jan](https://jan.ai), [KoboldCpp](https://github.com/LostRuins/koboldcpp), [vLLM](https://github.com/vllm-project/vllm) | `:1337`, `:5001`, `:8000` | Turn on the app's local API server |
| Anything else OpenAI-compatible | your address | Enter it under **Settings → AI**, with an API key for cloud services |

**Which model:** Clippy prefers a Qwen 3 model (its instructions are written for it). On Ollama that's any Qwen 3 you
downloaded; on apps that only serve what's loaded, the loaded model comes first. Models made for one job (embeddings,
translation, code) are only used when nothing else is there.
Pick another one under **Settings → AI**, which lists every server and model it found. In the terminal,
`clippy ai` shows the same, and `clippy ai test` sends a real request and times it.

**Short on context?** If a server's context window is small, Clippy reads the video in smaller pieces, and splits
any piece the server refuses. Bigger windows (16k or more) are faster and pick better.

**Which model fits your PC:** bigger models pick better clips. Setup picks one for you; these are its choices.

| Your PC | Ollama | llama.cpp |
|---|---|---|
| 22 GB+ graphics memory | `qwen3.6:35b-a3b` | Qwen3.6-35B-A3B, 17.7 GB |
| 7–21 GB graphics memory | `qwen3.5:9b` | Qwen3.6-35B-A3B with 24 GB+ RAM (it runs partly from RAM), otherwise Qwen3.5-9B |
| Less than 7 GB, or no GPU | `qwen3.5:4b` | Qwen3.5-4B (Qwen3.5-9B with 12 GB+ RAM) |

Models that "think" are told not to, which is faster; turn on *Let the AI think first* in Settings to allow it.

<details>
<summary><b>Using an AI that runs on Windows (from WSL)</b></summary>

Clippy looks for the AI on the Windows side too, but Windows apps only listen to Windows itself by default.
Make yours reachable in one of these ways, then run `clippy ai` to check:

- **Ollama for Windows:** add the environment variable `OLLAMA_HOST` = `0.0.0.0` (Start → "Edit environment
  variables for your account"), then quit Ollama from the tray and start it again.
- **LM Studio:** Developer → Settings → turn on **Serve on Local Network**.
- **Any app:** turn on WSL's mirrored networking. Create `%UserProfile%\.wslconfig` containing
  `[wsl2]` and `networkingMode=mirrored` on two lines, then run `wsl --shutdown` in PowerShell. Windows apps are
  then on `127.0.0.1` inside Ubuntu.

Windows Firewall may ask once whether to allow the connection. Running the AI inside Ubuntu instead (the Ollama or
llama.cpp option in setup) avoids all this and uses the same graphics card.
</details>

<details>
<summary><b>Command line</b></summary>

```
./clippy.sh web                      # the web app (Review → Review on Your Phone opens Review on your phone)
./clippy.sh "https://youtu.be/…"     # or straight from the terminal
./clippy.sh "https://youtu.be/…" -n 8 --max 45
./clippy.sh "https://youtu.be/…" --reuse --style box --color "#3DFF7A"   # same picks, new look (skips the AI)
./clippy.sh "https://youtu.be/…" --no-sfx --no-teaser                    # calmer edit
./clippy.sh "https://youtu.be/…" --no-talking                            # music / gameplay / sport: skip Whisper
./clippy.sh ~/Videos/my-video.mp4    # local files work too
./clippy.sh "https://youtu.be/…" --top funny            # one Top 3 countdown (crazy, shocking, wholesome…)
./clippy.sh auto all                 # run every Autopilot channel now (results go to Review)
./clippy.sh ai                       # which AI servers and models Clippy can see, and which it will use
./clippy.sh ai test                  # send the AI a real request and time it
```

After setup, `clippy` works as a shortcut for `./clippy.sh` from any folder.

Clips land in `output/<video-id>/clips/`, with `result.json` holding titles, captions and hashtags.
Re-running a video reuses its download and transcript.
</details>

<details>
<summary><b>Settings</b></summary>

Everything is optional and documented in [`config.toml`](config.toml): AI server, number and length of clips,
caption style, colours and size, hook title, split screen, silence cutting, sound effects, loudness and more.
The **Settings** page in the app covers the common ones, plus storage cleanup and *Start at login*.
Environment variables `CLIPPY_<NAME>` override both, e.g. `CLIPPY_OUTPUT_DIR=/data/clips`.

**Sharing the GPU with the AI:** Whisper needs about 2.6 GB of free graphics memory. If the AI leaves less, Clippy
pauses its systemd service (`llama_service`, default `llama-coder`) or asks Ollama to unload its model while
transcribing; the AI comes back by itself right after. Set `free_gpu_for_whisper = false` to never touch it.
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

## Privacy

Clippy runs on your PC. It has no accounts, ads, analytics or telemetry, and your videos, transcripts and shorts stay
on your computer. It connects to the internet only for these:

- **When you ask:**
  - downloading a YouTube video you give it, and finding videos or watching the channels you add to Autopilot (YouTube)
  - downloading the AI models, AI engine and tools you pick in AI & Tools (Hugging Face, GitHub)
  - browsing and installing extensions (GitHub)
  - uploading shorts to your own YouTube channel after you sign in with Google (the login stays on your PC)
  - an AI app you connect yourself gets the transcript text it picks clips from
  - Review on your phone opens a page on your own network (not the internet) while it's on, for the phone that
    scanned its code
- **By itself:**
  - when it opens, it asks GitHub whether there's a newer version (Settings → Updates turns this off)
  - the Windows app refreshes its YouTube download tool (yt-dlp) from PyPI every few days, because YouTube changes
    often (`CLIPPY_NO_UPDATES=1` turns this off)

  These two send nothing about you or your videos, only what any web request carries (your IP address).

Those services have their own privacy policies: [YouTube and Google](https://policies.google.com/privacy),
[GitHub](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement),
[Hugging Face](https://huggingface.co/privacy) and [PyPI](https://policies.python.org/pypi.org/Privacy-Notice/).

## Code signing policy

Windows releases aren't code-signed yet, which is why Windows warns about the installer ([why](docs/code-signing.md)).
Clippy applied to [SignPath Foundation](https://signpath.org)'s free signing for open-source projects in November
2026; they sign projects once they're more widely known, so Clippy will apply again later.

- Committers and reviewers: [StormAmdam](https://github.com/StormAmdam)
- Approvers: [StormAmdam](https://github.com/StormAmdam)

Every Windows release is built from this repository's source by GitHub Actions
([`windows-app.yml`](.github/workflows/windows-app.yml)), with a SHA-256 checksum on the release page that Clippy's
own updater checks. Changes from others (pull requests) are reviewed before they're merged. Clippy can be removed
completely: the Windows uninstaller (Settings → Apps), or `clippy uninstall` on Linux.

## Copyright

Platforms don't pay for reposted content you don't have the rights to, and it gets claimed. Clip your own videos,
creators who've given permission, paid clipping campaigns, or properly licensed material, and credit the source.

## License

[MIT](LICENSE) © 2026 Storm Amdam. You're free to use, change and share Clippy, as long as you keep the
copyright notice and credit the original project.

## Credits

- Windows app testing: [goofymyt-hash](https://github.com/goofymyt-hash)
- Demo footage: [*Meet NASA Astronaut Christina Koch*](https://www.youtube.com/watch?v=942n6DsJIRw) (NASA Johnson)
  and NASA Goddard videos in the screenshots. NASA material is public domain; NASA does not endorse this project.
- Fonts: [Montserrat](https://github.com/JulietaUla/Montserrat) and [Barlow](https://github.com/jpt/barlow)
  (SIL Open Font License 1.1), [Luckiest Guy](https://fonts.google.com/specimen/Luckiest+Guy) (Apache 2.0).
  Face detection: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (MIT).
  License texts are in [`LICENSES/`](LICENSES).
- Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [yt-dlp](https://github.com/yt-dlp/yt-dlp),
  [FFmpeg](https://ffmpeg.org), [OpenCV](https://opencv.org), [FastAPI](https://fastapi.tiangolo.com) and
  [llama.cpp](https://github.com/ggml-org/llama.cpp).
