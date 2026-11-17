"""Set up a local AI server for Clippy (setup.sh calls this): choose a model that fits the PC, install llama.cpp.

    python -m clippy.aisetup recommend            what fits this PC (JSON)
    python -m clippy.aisetup ollama-model         just the Ollama model name for this PC
    python -m clippy.aisetup llamacpp [--size big|medium|small]
                                                  download a prebuilt llama.cpp + a model, install the launcher
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import httpx

from . import gpu

GIB = 1024                                         # MiB per GiB
ROOT = Path(__file__).resolve().parent.parent

# Ollama library tags, biggest first: (min graphics memory in MiB, tag, download GB)
OLLAMA_MODELS = [(22 * GIB, "qwen3.6:35b-a3b", 22.6), (7 * GIB, "qwen3.5:9b", 6.6), (0, "qwen3.5:4b", 3.3)]

# GGUF files for llama.cpp, biggest first. The 35B model is a mixture of experts (3B active): its experts can sit in
# system RAM while attention runs on the GPU, so it needs RAM more than VRAM.
GGUF_MODELS = [
    {"size": "big", "repo": "unsloth/Qwen3.6-35B-A3B-GGUF", "file": "Qwen3.6-35B-A3B-UD-IQ4_XS.gguf", "gb": 17.7,
     "fits": lambda vram, ram: (ram >= 22 * GIB and vram >= 6 * GIB) or ram >= 28 * GIB},
    {"size": "medium", "repo": "unsloth/Qwen3.5-9B-GGUF", "file": "Qwen3.5-9B-Q4_K_M.gguf", "gb": 5.7,
     "fits": lambda vram, ram: ram >= 12 * GIB or vram >= 7 * GIB},
    {"size": "small", "repo": "unsloth/Qwen3.5-4B-GGUF", "file": "Qwen3.5-4B-Q4_K_M.gguf", "gb": 2.7,
     "fits": lambda vram, ram: True},
]
MODELS_DIR = Path.home() / "models"
LLAMA_DIR = Path.home() / ".local/opt/llama.cpp"
ENV_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "llama-coder.env"


# ───────────────────────── what fits ─────────────────────────

def ram_mb() -> int:
    """Installed RAM in MiB (Linux and Windows)."""
    if sys.platform == "win32":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        return int(m.ullTotalPhys // (1024 * 1024)) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) else 0
    try:
        return int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1)) // 1024
    except (OSError, AttributeError):
        return 0


def vram_mb() -> int:
    """Graphics memory of the first NVIDIA card in MiB, 0 without one."""
    if smi := gpu.nvidia_smi():
        try:
            out = subprocess.run([smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True,
                                 text=True, timeout=10, **_hidden()).stdout.split()
            return int(out[0]) if out else 0
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0
    return 0


def _hidden() -> dict:
    """subprocess options that keep a console window from flashing up on Windows."""
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def hardware(models_dir: Path | None = None) -> dict:
    vram = vram_mb()
    where = models_dir or MODELS_DIR
    where.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(where).free // (1024 * 1024)
    return {"vram_mb": vram, "ram_mb": ram_mb(), "disk_free_mb": disk, "threads": physical_cores(),
            "arch": platform.machine(), "os": "windows" if sys.platform == "win32" else "linux",
            "nvidia": vram > 0, "vulkan": _has_vulkan()}


def physical_cores() -> int:
    if sys.platform != "win32":
        try:
            out = subprocess.run(["lscpu", "-p=CORE,SOCKET"], capture_output=True, text=True, timeout=10).stdout
            cores = {ln for ln in out.splitlines() if ln and not ln.startswith("#")}
            if cores:
                return max(1, min(len(cores), 16))
        except (OSError, subprocess.SubprocessError):
            pass
    return max(1, min((os.cpu_count() or 2) // 2, 16))


def vulkan_gpu(drm: Path = Path("/sys/class/drm"), has_loader: bool | None = None) -> bool:
    """An AMD or Intel graphics card that llama.cpp's Vulkan build can use. Mesa installs driver files for every
    brand, so only a card actually listed in /sys/class/drm counts (NVIDIA cards get the faster CUDA build)."""
    vendors = set()
    for f in drm.glob("card*/device/vendor"):
        try:
            vendors.add(f.read_text().strip().lower())
        except OSError:
            pass
    if has_loader is None:
        has_loader = any(Path(d, "libvulkan.so.1").exists() for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib"))
    return bool(vendors & {"0x1002", "0x8086"}) and has_loader


def _has_vulkan() -> bool:
    if sys.platform == "win32":                # AMD or Intel graphics: llama.cpp's Vulkan build runs well there
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True,
                                 timeout=20, **_hidden()).stdout.lower()
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(re.search(r"\b(amd|radeon|intel)\b", out)) and "nvidia" not in out
    from .llm import wsl
    return not wsl() and vulkan_gpu()          # WSL's Vulkan layer isn't something llama.cpp runs well on


def human(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def ollama_model(vram_mb: int, ram_mb: int) -> str:
    return next(tag for need, tag, _ in OLLAMA_MODELS if vram_mb >= need)


def gguf_model(vram_mb: int, ram_mb: int, disk_free_mb: int, size: str = "auto") -> dict | None:
    """The biggest model that fits in memory and on disk (with 2 GB to spare), or the size you asked for."""
    for m in GGUF_MODELS:
        if size not in ("auto", m["size"]):
            continue
        if size == "auto" and not m["fits"](vram_mb, ram_mb):
            continue
        if disk_free_mb < (m["gb"] + 2) * 1000:
            if size != "auto":
                return None
            continue
        return {k: v for k, v in m.items() if k != "fits"}
    return None


def llama_assets(names: list[str], nvidia: bool, arch: str, vulkan: bool, system: str = "") -> list[str]:
    """Which files of a llama.cpp release to download: the server build, plus the CUDA runtime for NVIDIA cards.
    CUDA 12.x builds run on any driver from 525 up (13.x needs a very new one), so 12.x is always the choice."""
    a = "arm64" if arch.lower() in ("aarch64", "arm64") else "x64"
    win = (system or ("windows" if sys.platform == "win32" else "linux")) == "windows"

    def find(pattern: str) -> str | None:
        return next((n for n in sorted(names, reverse=True) if re.fullmatch(pattern, n)), None)

    if win:
        if nvidia and a == "x64":
            main = find(r"llama-b\d+-bin-win-cuda-12\.\d+-x64\.zip")
            runtime = find(r"cudart-llama-(?:b\d+-)?bin-win-cuda-12\.\d+-x64\.zip")
            if main and runtime and main.split("cuda-")[1] == runtime.split("cuda-")[1]:
                return [main, runtime]
        if vulkan and (v := find(rf"llama-b\d+-bin-win-vulkan-{a}\.zip")):
            return [v]
        cpu = find(rf"llama-b\d+-bin-win-cpu-{a}\.zip")
        return [cpu] if cpu else []
    if nvidia and a == "x64":
        main = find(r"llama-b\d+-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz")
        runtime = find(r"cudart-llama-b\d+-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz")
        if main and runtime and main.split("cuda-")[1] == runtime.split("cuda-")[1]:
            return [main, runtime]
    if vulkan and a == "x64" and (v := find(r"llama-b\d+-bin-ubuntu-vulkan-x64\.tar\.gz")):
        return [v]
    cpu = find(rf"llama-b\d+-bin-ubuntu-{a}\.tar\.gz")
    return [cpu] if cpu else []


def write_env(path: Path, model: str, vram_mb: int, threads: int, ctx: int = 32768) -> Path:
    """Settings for tools/ai-server/llama-coder. On a 10 GB+ card it leaves room for Whisper next to it;
    on smaller ones it takes more of the GPU and Clippy pauses it while transcribing."""
    free = 4500 if vram_mb >= 10 * GIB else 1024
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Written by Clippy's setup. Change it, then: systemctl --user restart llama-coder\n"
                    f'LLAMA_CODER_MODEL="{model}"\nLLAMA_CODER_FREE_MB={free}\nLLAMA_CODER_THREADS={threads}\n'
                    f"LLAMA_CODER_CTX={ctx}\n")
    return path


# ───────────────────────── installing ─────────────────────────

class Cancelled(Exception):
    """A download was stopped on purpose."""


def download(url: str, dest: Path, label: str, progress=None, cancelled=lambda: False) -> Path:
    """Resumable download; the file only gets its real name once complete. progress(done, total) replaces the
    terminal progress line; cancelled() is checked between chunks (the partial file stays for resuming)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if progress is None:
            print(f"  ✓ {label} already downloaded", flush=True)
        return dest
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
        if r.status_code == 416:                                   # already complete
            os.replace(part, dest)
            return dest
        r.raise_for_status()
        if r.status_code != 206:
            have = 0
        total = have + int(r.headers.get("Content-Length") or 0)
        t0, last = time.time(), 0.0
        with open(part, "ab" if have else "wb") as f:
            done = have
            for chunk in r.iter_bytes(1 << 20):
                if cancelled():
                    raise Cancelled(label)
                f.write(chunk)
                done += len(chunk)
                if time.time() - last > 0.5:
                    last = time.time()
                    if progress:
                        progress(done, total)
                    else:
                        speed = (done - have) / max(time.time() - t0, 0.1) / 1e6
                        pct = f"{100 * done / total:5.1f}%" if total else ""
                        print(f"\r  {label}: {pct} {human(done)} of {human(total)}  {speed:.0f} MB/s   ", end="", flush=True)
    if progress is None:
        print(f"\r  ✓ {label}: {human(part.stat().st_size)}" + " " * 30, flush=True)
    os.replace(part, dest)
    return dest


def extract(archive: Path, into: Path, only=None) -> None:
    """Unpack a .zip or .tar.* into `into`. A single top folder shared by every entry is dropped (like
    tar --strip-components=1). only(name) can limit which files are kept, which then land flat in `into`."""
    import zipfile
    into.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            tops = {n.split("/", 1)[0] for n in names}
            strip = len(tops) == 1 and all("/" in n for n in names)
            for n in names:
                parts = Path(n).parts[1:] if strip else Path(n).parts
                if not parts or ".." in parts or (only and not only(n)):
                    continue
                target = into / (parts[-1] if only else Path(*parts))
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return
    with tarfile.open(archive) as tf:
        members = [m for m in tf.getmembers() if m.isfile() or m.issym()]
        tops = {Path(m.name).parts[0] for m in members if Path(m.name).parts}
        strip = len(tops) == 1 and all(len(Path(m.name).parts) > 1 for m in members)
        for m in members:
            parts = Path(m.name).parts[1:] if strip else Path(m.name).parts
            if not parts or ".." in parts or (only and not only(m.name)):
                continue
            m.name = parts[-1] if only else str(Path(*parts))
            tf.extract(m, into, filter="data")


def _extract(tgz: Path, into: Path) -> None:
    extract(tgz, into)


def install_llamacpp(hw: dict) -> Path:
    """Newest prebuilt llama.cpp for this machine → ~/.local/opt/llama.cpp/current. No compiling, no sudo."""
    rels = httpx.get("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8", timeout=30,
                     follow_redirects=True).json()
    for rel in rels:
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        picks = llama_assets(list(assets), hw["nvidia"], hw["arch"], hw["vulkan"])
        if picks:
            break
    else:
        raise RuntimeError("Couldn't find a prebuilt llama.cpp for this machine on GitHub.")
    tag = rel["tag_name"]
    variant = "cuda" if "cuda" in picks[0] else "vulkan" if "vulkan" in picks[0] else "cpu"
    target = LLAMA_DIR / f"{tag}-{variant}"
    if not (target / "llama-server").exists():
        tmp = LLAMA_DIR / "downloads"
        for name in picks:
            _extract(download(assets[name], tmp / name, f"llama.cpp {tag} ({name.split('-bin-')[1].removesuffix('.tar.gz')})"), target)
        shutil.rmtree(tmp, ignore_errors=True)
    current = LLAMA_DIR / "current"
    if current.is_symlink() or current.exists():
        current.unlink()
    current.symlink_to(target.name)
    out = subprocess.run([str(current / "llama-server"), "--list-devices"], capture_output=True, text=True, timeout=60)
    if variant == "cuda" and "CUDA0" not in out.stdout + out.stderr:
        print("  ! The CUDA build can't see your GPU (driver too old?). Using the CPU build instead.", flush=True)
        return install_llamacpp({**hw, "nvidia": False, "vulkan": False})
    print(f"  ✓ llama.cpp {tag} ({variant}) in {target}", flush=True)
    return current


def install_service() -> str:
    """Launcher in ~/.local/bin and, where systemd runs, a user service that starts it at login."""
    bin_dir = Path.home() / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tools/ai-server/llama-coder", bin_dir / "llama-coder")
    (bin_dir / "llama-coder").chmod(0o755)
    if not (shutil.which("systemctl") and subprocess.run(["systemctl", "--user", "show-environment"],
                                                         capture_output=True).returncode == 0):
        return "manual"
    unit_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tools/ai-server/llama-coder.service", unit_dir / "llama-coder.service")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    r = subprocess.run(["systemctl", "--user", "enable", "--now", "llama-coder"], capture_output=True, text=True)
    return "service" if r.returncode == 0 else "manual"


def setup_llamacpp(size: str = "auto") -> int:
    hw = hardware()
    model = gguf_model(hw["vram_mb"], hw["ram_mb"], hw["disk_free_mb"], size)
    if model is None:
        print(f"  ✗ Not enough free disk space in {MODELS_DIR} for a model ({hw['disk_free_mb'] / 1000:.0f} GB free).")
        return 1
    print(f"  Your PC: {hw['vram_mb'] / 1024:.0f} GB graphics memory, {hw['ram_mb'] / 1024:.0f} GB RAM → "
          f"{model['file']} ({model['gb']} GB)", flush=True)
    install_llamacpp(hw)
    path = download(f"https://huggingface.co/{model['repo']}/resolve/main/{model['file']}", MODELS_DIR / model["file"],
                    f"model {model['file']}")
    write_env(ENV_FILE, str(path), hw["vram_mb"], hw["threads"])
    how = install_service()
    if how == "service":
        print("  ✓ llama-coder runs as a background service and starts at login", flush=True)
    else:
        print("  ✓ No systemd here, so Clippy starts llama-coder by itself when it needs it (or run: llama-coder &)", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m clippy.aisetup")
    ap.add_argument("what", choices=["recommend", "ollama-model", "llamacpp"])
    ap.add_argument("--size", choices=["auto", "big", "medium", "small"], default=os.environ.get("CLIPPY_GGUF_SIZE", "auto"))
    a = ap.parse_args(argv)
    if a.what == "llamacpp":
        return setup_llamacpp(a.size)
    hw = hardware()
    if a.what == "ollama-model":
        print(os.environ.get("CLIPPY_OLLAMA_MODEL") or ollama_model(hw["vram_mb"], hw["ram_mb"]))
        return 0
    print(json.dumps({"hardware": hw, "ollama": ollama_model(hw["vram_mb"], hw["ram_mb"]),
                      "gguf": gguf_model(hw["vram_mb"], hw["ram_mb"], hw["disk_free_mb"])}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
