# Local AI server (llama.cpp)

Clippy finds any running llama.cpp, Ollama, LM Studio, Jan, KoboldCpp or vLLM server by itself (see the main
README, "Use your own AI"). This folder has a llama.cpp launcher and systemd user service.

**The easy way:** `bash setup.sh --ai llamacpp` does everything below by itself: it downloads the right prebuilt
llama.cpp (CUDA, Vulkan or CPU), picks a model that fits your graphics memory, RAM and free disk space, writes
`~/.config/llama-coder.env`, and starts the service. The steps below are for doing it by hand.

The launcher reads `~/.config/llama-coder.env` (`LLAMA_CODER_MODEL`, `LLAMA_CODER_FREE_MB`, `LLAMA_CODER_THREADS`,
`LLAMA_CODER_CTX`); change it and run `systemctl --user restart llama-coder`.

## Setup by hand on Linux with an NVIDIA GPU (no compiling)

1. Download a prebuilt llama.cpp from <https://github.com/ggml-org/llama.cpp/releases>: the
   `llama-<build>-bin-ubuntu-cuda-12.8-x64.tar.gz` **and** the matching `cudart-llama-…-cuda-12.8-x64.tar.gz`
   (the CUDA runtime libraries). The CUDA 12.8 build runs on any driver that supports CUDA 12.x (≥ 525).
   Unpack both into the same folder and point `current` at it:
   ```
   mkdir -p ~/.local/opt/llama.cpp/b12475
   tar xzf llama-b12475-bin-ubuntu-cuda-12.8-x64.tar.gz        -C ~/.local/opt/llama.cpp/b12475 --strip-components=1
   tar xzf cudart-llama-b12475-bin-ubuntu-cuda-12.8-x64.tar.gz -C ~/.local/opt/llama.cpp/b12475 --strip-components=1
   ln -sfn b12475 ~/.local/opt/llama.cpp/current
   ~/.local/opt/llama.cpp/current/llama-server --list-devices    # should list your GPU
   ```
   No NVIDIA card? Use the `ubuntu-vulkan-x64` (AMD/Intel GPUs) or plain `ubuntu-x64` (CPU) build instead.
2. Download a model into `~/models/` (the default one is linked at the top of `llama-coder`, 18.7 GB).
   Smaller GPUs/RAM: pick a smaller quant (IQ3_XXS ≈ 13.6 GB) and set `LLAMA_CODER_MODEL`.
3. Install the launcher and service:
   ```
   install -Dm755 tools/ai-server/llama-coder ~/.local/bin/llama-coder
   install -Dm644 tools/ai-server/llama-coder.service ~/.config/systemd/user/llama-coder.service
   systemctl --user daemon-reload && systemctl --user enable --now llama-coder
   curl -s http://127.0.0.1:8080/health          # {"status":"ok"} once the model has loaded
   ```

Clippy pauses the service named in `llama_service` (default `llama-coder`) while Whisper transcribes, but only
if the GPU doesn't have ~2.6 GB free at that moment, and restarts it right after.
