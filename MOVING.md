# Moving Clippy to another PC

## On the new PC (Linux)

1. Unzip `Clippy.zip` wherever you like (any folder, spaces in the name are fine).
   If you brought `Clippy-extras.zip`, unzip it into the **same place**: it adds to the same `Clippy/` folder.
2. Open a terminal in that folder and run:
   ```
   bash setup.sh
   ```
   It installs everything Clippy needs into its own `.venv` folder (about 3 GB, a few minutes the first time),
   asks before anything that needs `sudo` (only ffmpeg, and Python if it's missing), restores Claude Code's
   memory for this folder, and runs the self-test. It's safe to run again any time.
3. Start it: `./clippy.sh web` → http://127.0.0.1:7860

Everything continues where you left off: Autopilot profiles, the Review queue, Find-videos scans,
finished clips, transcripts and AI picks, and your settings.

## What's in which zip

| | `Clippy.zip` | `Clippy-extras.zip` (optional) |
|---|---|---|
| Code, settings, `config.toml`, fonts, face model, tests, docs | ✓ | |
| `output/`: Autopilot + Review data, scans, transcripts, picks, finished clips | ✓ | |
| `move-kit/`: Claude Code memory + your llama-coder launcher | ✓ | |
| Downloaded source videos (`output/<id>/source.mp4`) | | ✓ (re-download from YouTube when needed) |
| Whisper model (`models/whisper/`, 1.6 GB) | | ✓ (downloads itself on the first transcription) |
| `.venv` | never: Python environments don't survive a move; `setup.sh` rebuilds it | |

`Clippy-extras.zip` is bigger than 4 GB, so it can't go on a FAT32 USB stick (exFAT/NTFS/ext4 are fine).
If YouTube uploading was set up, your Google login is inside `Clippy.zip` (`output/_auto/`), so don't share the zip.

## The AI server

Clippy picks clips with a local AI server (OpenAI-compatible, default `http://127.0.0.1:8080/v1`),
usually `llama-coder`: llama.cpp + Qwen3.6-35B-A3B as a systemd user service. It isn't packed (the model is
many GB and llama.cpp builds are GPU-specific), but your own launcher and service file travel in
`move-kit/llama-coder/`. Follow [tools/ai-server/README.md](tools/ai-server/README.md) to install a prebuilt
llama.cpp and the model (no compiling), then use either the launcher from `move-kit/llama-coder/` or the one
in `tools/ai-server/`. The launcher sizes itself to the GPU with `--fit`; `LLAMA_CODER_FREE_MB` sets how
much VRAM it leaves free for Whisper (default 4500 MiB).

Simpler alternatives: Ollama (`llm_url = "http://127.0.0.1:11434/v1"`) or a free cloud tier.
Change it in the app under **Settings**, or in `config.toml` (examples are in there).

## If the new PC is different

- **More VRAM (≥ 10 GB)**: with the launcher's default 4.5 GB margin, Whisper runs next to the AI server and
  Clippy doesn't need to pause it. Keep `free_gpu_for_whisper = true` anyway: it only pauses the server when
  VRAM is actually short at that moment (a game or browser holding memory), instead of falling back to CPU.
- **Smaller GPU (6–8 GB)**: start the launcher with `LLAMA_CODER_FREE_MB=1024` for AI speed; Clippy then
  pauses it for the minute Whisper needs.
- **AI server not called `llama-coder`**: set `llama_service` to its systemd service name, or `""`.
- **No NVIDIA GPU**: everything works on the CPU, just slower (transcription ~10×).
- **Start at login**: turn it on again under Settings (it's a per-PC service).
- **Windows**: Clippy is Linux-only (bash, systemd). Use WSL2 with Ubuntu and follow the steps above inside it.

## Moving again later

```
python3 tools/pack_for_move.py              # makes Clippy.zip + Clippy-extras.zip next to the Clippy folder
python3 tools/pack_for_move.py --no-extras  # just Clippy.zip
```
