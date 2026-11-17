#!/usr/bin/env bash
# Clippy setup: run once on a new PC (safe to run again any time, e.g. to update yt-dlp):
#     bash setup.sh            asks before anything that needs sudo
#     bash setup.sh --yes      don't ask    |    --no-tests   skip the self-test at the end
set -uo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR" || exit 1

YES=0; TESTS=1
for a in "$@"; do case "$a" in
  -y|--yes) YES=1 ;;
  --no-tests) TESTS=0 ;;
  -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
  *) echo "Unknown option: $a (try --help)"; exit 2 ;;
esac; done

WARN=0
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; WARN=$((WARN + 1)); }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }
ask()  {  # yes → 0
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  local r; read -r -p "  $1 [Y/n] " r; [[ -z "$r" || "$r" =~ ^[YyJj] ]]
}
pm_install() {
  if   command -v pacman  >/dev/null; then sudo pacman -S --needed --noconfirm "$@"
  elif command -v apt-get >/dev/null; then sudo apt-get update -q && sudo apt-get install -y "$@"
  elif command -v dnf     >/dev/null; then sudo dnf install -y "$@"
  elif command -v zypper  >/dev/null; then sudo zypper install -y "$@"
  else return 1; fi
}

[ "$(id -u)" = 0 ] && die "Run this as your normal user, not root (it asks for sudo itself when needed)."
[ "$(uname -s)" = Linux ] || die "Clippy runs on Linux. On Windows, use WSL2 (Ubuntu) and run setup.sh inside it."
chmod +x clippy.sh setup.sh 2>/dev/null   # unzip tools don't always keep the executable bit

# ── 1. Python ≥ 3.11 ─────────────────────────────────────────────────────────
step "1/5  Python"
find_python() {
  local c p
  for c in python3.14 python3.13 python3.12 python3.11 python3; do
    p=$(command -v "$c") || continue
    # ensurepip isn't required: Debian/Ubuntu leave it out unless python3-venv is installed (see step 2)
    "$p" -c 'import sys, venv; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && { echo "$p"; return 0; }
  done
  return 1
}
PY=$(find_python)
if [ -z "$PY" ]; then
  warn "Need Python 3.11 or newer with venv support."
  if ask "Install it now with sudo?"; then
    if command -v apt-get >/dev/null; then pm_install python3 python3-venv python3-pip
    elif command -v pacman >/dev/null; then pm_install python
    else pm_install python3; fi
  fi
  PY=$(find_python) || die "Still no Python ≥ 3.11 with venv. Install it (Debian/Ubuntu: python3-venv), then run: bash setup.sh"
fi
ok "$("$PY" -V) ($PY)"

# ── 2. Python packages in .venv ──────────────────────────────────────────────
step "2/5  Python packages (first time: ~3 GB download, takes a few minutes)"
VPY="$DIR/.venv/bin/python"
if [ -e .venv ] && [ "$("$VPY" -c 'import sys; print(sys.prefix)' 2>/dev/null)" != "$DIR/.venv" ]; then
  warn "The existing .venv was made on another PC or in another folder; making a fresh one."
  rm -rf .venv
fi
if [ ! -e .venv ]; then
  if "$PY" -c 'import ensurepip' 2>/dev/null; then
    "$PY" -m venv .venv || die "Could not create .venv"
  else
    # No python3-venv package (and so no ensurepip): make the venv without pip, then fetch pip from PyPI. No sudo needed.
    "$PY" -m venv --without-pip .venv || die "Could not create .venv"
    "$VPY" -c 'import urllib.request, sys; urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", sys.argv[1])' .venv/get-pip.py \
      && "$VPY" .venv/get-pip.py --quiet --disable-pip-version-check \
      || { rm -rf .venv; die "Could not install pip into .venv (no internet?). Or install python3-venv (Debian/Ubuntu: sudo apt install python3-venv), then run: bash setup.sh"; }
    rm -f .venv/get-pip.py
    ok "Made .venv without the python3-venv package (pip fetched from PyPI)"
  fi
fi
PIP=("$VPY" -m pip --disable-pip-version-check)
"${PIP[@]}" install --quiet --upgrade pip
if "${PIP[@]}" install -r requirements.txt -r requirements-dev.txt; then
  ok "Installed the exact versions Clippy was tested with"
else
  warn "Those exact versions aren't available for $("$VPY" -V); installing the newest compatible ones instead."
  sed 's/[=<>~!;].*//' requirements.txt requirements-dev.txt | grep -v '^\s*$' > .venv/requirements-unpinned.txt
  "${PIP[@]}" install -r .venv/requirements-unpinned.txt || die "pip could not install the packages (see the error above)."
fi

# ── 3. ffmpeg, yt-dlp, deno ──────────────────────────────────────────────────
step "3/5  ffmpeg + yt-dlp"
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  warn "ffmpeg is missing (Clippy needs it for every video)."
  if ask "Install ffmpeg now with sudo?"; then pm_install ffmpeg || warn "Couldn't install ffmpeg automatically."; fi
fi
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ok "ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3)"
else
  warn "Install ffmpeg with your package manager, then run setup again."
fi

# yt-dlp breaks whenever YouTube changes, so an old distro copy is no good: use the system one only if it's recent
SYS_YTDLP=$(type -ap yt-dlp | grep -v "^$DIR/.venv/" | head -1)
RECENT=$(date -d '-120 days' +%Y.%m.%d 2>/dev/null || echo 0000.00.00)
if [ -n "$SYS_YTDLP" ] && [[ ! "$("$SYS_YTDLP" --version 2>/dev/null)" < "$RECENT" ]]; then
  ok "yt-dlp $("$SYS_YTDLP" --version) (system)"
  # a copy in .venv wins over the system one (Clippy puts .venv/bin first on PATH), so keep it current
  [ -x .venv/bin/yt-dlp ] && "${PIP[@]}" install --quiet --upgrade "yt-dlp[default]"
elif "${PIP[@]}" install --quiet --upgrade "yt-dlp[default]"; then
  ok "yt-dlp $(.venv/bin/yt-dlp --version) (inside Clippy's .venv, no sudo needed)"
else
  warn "Couldn't install yt-dlp."
fi
# YouTube downloads need a JavaScript runtime for yt-dlp; deno is the one it uses by default
if [ -x .venv/bin/deno ]; then
  ok "deno $(.venv/bin/deno --version | head -1 | cut -d' ' -f2) (inside .venv)"
elif command -v deno >/dev/null; then
  ok "deno $(deno --version | head -1 | cut -d' ' -f2) (system)"
elif "${PIP[@]}" install --quiet deno; then
  ok "deno $(.venv/bin/deno --version | head -1 | cut -d' ' -f2) (inside .venv, no sudo needed)"
else
  warn "Couldn't install deno; some YouTube downloads may fail."
fi

# ── 4. GPU + AI server (information only; Clippy works without them, just slower / no AI picks) ──
step "4/5  GPU + AI server"
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
  ok "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
  if "$VPY" -c 'import ctranslate2, sys; sys.exit(ctranslate2.get_cuda_device_count() < 1)' 2>/dev/null; then
    ok "Whisper can use the GPU"
  else
    warn "Whisper can't see the GPU (check the NVIDIA driver); it'll transcribe on the CPU."
  fi
else
  warn "No NVIDIA GPU/driver found: Clippy still works, but transcribing and encoding run on the CPU (slower)."
fi
LLM=$("$VPY" -c 'from clippy import config; print(config.load().llm_url)' 2>/dev/null)
if "$VPY" -c 'import httpx, sys; httpx.get(sys.argv[1].rstrip("/") + "/models", timeout=3).raise_for_status()' "$LLM" 2>/dev/null; then
  ok "AI server answers at $LLM"
else
  warn "No AI server at $LLM yet, so Clippy can't pick clips. See MOVING.md, section \"The AI server\"."
fi
SVC=$("$VPY" -c 'from clippy import config; print(config.load().llama_service)' 2>/dev/null)
if [ -n "$SVC" ] && command -v systemctl >/dev/null && ! systemctl --user cat "$SVC" >/dev/null 2>&1; then
  printf '  · No systemd service called "%s" here; Clippy only pauses it to free the GPU, so this is fine.\n' "$SVC"
fi

# ── 5. Claude Code memory + self-test ───────────────────────────────────────
step "5/5  Finishing"
if [ -d move-kit/claude-memory ]; then
  KEY=$(printf '%s' "$DIR" | sed 's/[^A-Za-z0-9]/-/g')      # how Claude Code names a project folder
  DST="$HOME/.claude/projects/$KEY/memory"
  mkdir -p "$DST"
  n=0; for f in move-kit/claude-memory/*; do
    [ -e "$DST/$(basename "$f")" ] || { cp "$f" "$DST/"; n=$((n + 1)); }
  done
  if [ "$n" -gt 0 ]; then ok "Claude Code memory restored for this folder ($n notes → $DST)"
  else ok "Claude Code memory already in place"; fi
fi
if [ "$TESTS" = 1 ]; then
  if "$VPY" -m pytest -q -p no:cacheprovider tests 2>&1 | tail -2; then ok "Self-test passed"
  else warn "Some self-tests failed (output above). Clippy may still run; mention it if something breaks."; fi
fi

printf '\n\033[1mDone%s.\033[0m Start Clippy with:  ./clippy.sh web   (opens http://127.0.0.1:7860)\n' \
  "$([ "$WARN" -gt 0 ] && echo " with $WARN note(s) above")"
