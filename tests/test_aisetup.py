"""Choosing an AI model and llama.cpp build that fit the PC (used by setup.sh)."""
from clippy import aisetup

GB = 1024  # MiB


def test_ollama_model_grows_with_the_graphics_card():
    assert aisetup.ollama_model(vram_mb=24 * GB, ram_mb=64 * GB) == "qwen3.6:35b-a3b"
    assert aisetup.ollama_model(vram_mb=10 * GB, ram_mb=32 * GB) == "qwen3.5:9b"
    assert aisetup.ollama_model(vram_mb=8 * GB, ram_mb=16 * GB) == "qwen3.5:9b"
    assert aisetup.ollama_model(vram_mb=4 * GB, ram_mb=16 * GB) == "qwen3.5:4b"
    assert aisetup.ollama_model(vram_mb=0, ram_mb=8 * GB) == "qwen3.5:4b"


def test_gguf_model_uses_system_ram_for_the_big_mixture_of_experts_model():
    big = aisetup.gguf_model(vram_mb=10 * GB, ram_mb=31 * GB, disk_free_mb=200 * GB)
    assert big["file"] == "Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"                  # experts live in RAM, attention on the GPU
    assert aisetup.gguf_model(vram_mb=0, ram_mb=30 * GB, disk_free_mb=200 * GB)["file"] == big["file"]
    assert aisetup.gguf_model(vram_mb=8 * GB, ram_mb=16 * GB, disk_free_mb=200 * GB)["file"] == "Qwen3.5-9B-Q4_K_M.gguf"
    assert aisetup.gguf_model(vram_mb=0, ram_mb=8 * GB, disk_free_mb=200 * GB)["file"] == "Qwen3.5-4B-Q4_K_M.gguf"


def test_gguf_model_steps_down_when_the_disk_is_nearly_full():
    m = aisetup.gguf_model(vram_mb=10 * GB, ram_mb=31 * GB, disk_free_mb=12 * GB)
    assert m["file"] == "Qwen3.5-9B-Q4_K_M.gguf"
    assert aisetup.gguf_model(vram_mb=10 * GB, ram_mb=31 * GB, disk_free_mb=2 * GB) is None


RELEASE = ["cudart-llama-b12475-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-b12475-bin-ubuntu-cuda-13.5-x64.tar.gz",
           "llama-b12475-bin-ubuntu-cuda-12.8-x64.tar.gz", "llama-b12475-bin-ubuntu-cuda-13.5-x64.tar.gz",
           "llama-b12475-bin-ubuntu-vulkan-x64.tar.gz", "llama-b12475-bin-ubuntu-x64.tar.gz",
           "llama-b12475-bin-ubuntu-arm64.tar.gz", "llama-b12475-bin-win-cuda-12.4-x64.zip"]


def test_llama_build_matches_the_hardware():
    # CUDA 12.x runs on every driver from 525 up, 13.x needs a very new one: always take 12.x plus its runtime
    assert aisetup.llama_assets(RELEASE, nvidia=True, arch="x86_64", vulkan=False) == [
        "llama-b12475-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-b12475-bin-ubuntu-cuda-12.8-x64.tar.gz"]
    assert aisetup.llama_assets(RELEASE, nvidia=False, arch="x86_64", vulkan=True) == ["llama-b12475-bin-ubuntu-vulkan-x64.tar.gz"]
    assert aisetup.llama_assets(RELEASE, nvidia=False, arch="x86_64", vulkan=False) == ["llama-b12475-bin-ubuntu-x64.tar.gz"]
    assert aisetup.llama_assets(RELEASE, nvidia=True, arch="aarch64", vulkan=False) == ["llama-b12475-bin-ubuntu-arm64.tar.gz"]
    assert aisetup.llama_assets(["nightly-tag.txt"], nvidia=True, arch="x86_64", vulkan=False) == []


def test_env_file_tells_the_launcher_what_to_run(tmp_path):
    f = aisetup.write_env(tmp_path / "llama-coder.env", model="/m/x.gguf", vram_mb=10 * GB, threads=8)
    text = f.read_text()
    assert 'LLAMA_CODER_MODEL="/m/x.gguf"' in text
    assert "LLAMA_CODER_FREE_MB=4500" in text                               # 10 GB card: room for Whisper next to it
    assert "LLAMA_CODER_THREADS=8" in text
    small = aisetup.write_env(tmp_path / "b.env", model="/m/y.gguf", vram_mb=6 * GB, threads=4).read_text()
    assert "LLAMA_CODER_FREE_MB=1024" in small                              # small card: Clippy pauses it instead


def test_vulkan_build_only_for_a_real_amd_or_intel_card(tmp_path):
    # Mesa installs driver files for every brand, so only an actual card in /sys/class/drm counts
    drm = tmp_path / "drm"
    assert aisetup.vulkan_gpu(drm, has_loader=True) is False                     # no cards at all (containers, servers)
    (drm / "card0/device").mkdir(parents=True)
    (drm / "card0/device/vendor").write_text("0x10de\n")                         # NVIDIA: the CUDA build is better
    assert aisetup.vulkan_gpu(drm, has_loader=True) is False
    (drm / "card1/device").mkdir(parents=True)
    (drm / "card1/device/vendor").write_text("0x1002\n")                         # AMD
    assert aisetup.vulkan_gpu(drm, has_loader=True) is True
    assert aisetup.vulkan_gpu(drm, has_loader=False) is False                    # no Vulkan loader installed


def test_sizes_read_naturally():
    assert aisetup.human(36_400_000) == "36 MB"
    assert aisetup.human(2_700_000_000) == "2.7 GB"
