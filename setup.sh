#!/usr/bin/env bash
# Clippy setup: run once on a new PC (safe to run again any time, e.g. to update yt-dlp):
#     bash setup.sh                  asks before anything that needs sudo, and which AI to set up
#     bash setup.sh --yes            don't ask (installs ffmpeg; sets up an AI only with --ai)
#     bash setup.sh --ai ollama      set up Ollama (also: --ai llamacpp, --ai skip)    --no-tests  skip the self-test
set -uo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR" || exit 1

YES=0; TESTS=1; AI=""
while [ $# -gt 0 ]; do case "$1" in
  -y|--yes) YES=1 ;;
  --no-tests) TESTS=0 ;;
  --ai) AI="${2:-}"; shift ;;
  --ai=*) AI="${1#--ai=}" ;;
  -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
  *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
esac; shift; done
case "$AI" in ""|ollama|llamacpp|skip) ;; *) echo "--ai takes ollama, llamacpp or skip"; exit 2 ;; esac

WARN=0
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; WARN=$((WARN + 1)); }
note() { printf '    %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }
ask()  {  # yes → 0
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  local r; read -r -p "  $1 [Y/n] " r; [[ -z "$r" || "$r" =~ ^[YyJj] ]]
}
pm_run() {
  if   command -v apt-get >/dev/null; then sudo apt-get update -q && sudo apt-get install -y "$@"
  elif command -v pacman  >/dev/null; then sudo pacman -S --needed --noconfirm "$@"
  elif command -v dnf     >/dev/null; then sudo dnf install -y "$@"
  elif command -v zypper  >/dev/null; then sudo zypper install -y "$@"
  else return 1; fi
}
pkg_present() {  # is this package installed?
  if   command -v apt-get >/dev/null; then dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "ok installed"
  elif command -v pacman  >/dev/null; then pacman -Q "$1" >/dev/null 2>&1
  elif command -v rpm     >/dev/null; then rpm -q "$1" >/dev/null 2>&1
  else return 1; fi
}
RECORD="$DIR/data/setup-installed.txt"   # what setup installed that wasn't here before: clippy uninstall offers to remove it
record() { mkdir -p "$DIR/data" && { grep -qxF "$*" "$RECORD" 2>/dev/null || echo "$*" >> "$RECORD"; }; }
pm_install() {
  local new=() p
  for p in "$@"; do pkg_present "$p" || new+=("$p"); done
  pm_run "$@" || return 1
  for p in ${new[@]+"${new[@]}"}; do pkg_present "$p" && record package "$p"; done
  return 0
}
pkg_name() {  # generic name → this distro's package
  case "$1" in
    emoji) if command -v apt-get >/dev/null; then echo fonts-noto-color-emoji
           elif command -v pacman >/dev/null; then echo noto-fonts-emoji
           elif command -v dnf >/dev/null; then echo google-noto-color-emoji-fonts
           else echo google-noto-coloremoji-fonts; fi ;;
    *) echo "$1" ;;
  esac
}

[ "$(id -u)" = 0 ] && die "Run this as your normal user, not root (it asks for sudo itself when needed)."
[ "$(uname -s)" = Linux ] || die "Clippy runs on Linux. On Windows: open PowerShell, run  wsl --install , restart, then run this inside Ubuntu."
chmod +x clippy.sh setup.sh install.sh tools/ai-server/llama-coder 2>/dev/null   # unzip tools can drop the executable bit

IS_WSL=0
{ [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; } && IS_WSL=1
SMI=$(command -v nvidia-smi || { [ -x /usr/lib/wsl/lib/nvidia-smi ] && echo /usr/lib/wsl/lib/nvidia-smi; } || true)
HAS_NVIDIA=0
[ -n "$SMI" ] && "$SMI" -L >/dev/null 2>&1 && HAS_NVIDIA=1

if [ "$IS_WSL" = 1 ] && [[ "$DIR" == /mnt/* ]]; then
  warn "Clippy is on a Windows drive ($DIR). In WSL that's about 10× slower for video work."
  note "Better: move it into Linux first:  mv \"$DIR\" ~/clippy && cd ~/clippy && bash setup.sh"
  ask "Continue here anyway?" || exit 1
fi

# ── 1. Python ≥ 3.11 ─────────────────────────────────────────────────────────
step "1/6  Python"
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
if [ "$HAS_NVIDIA" = 1 ]; then step "2/6  Python packages (first time: ~3 GB download, takes a few minutes)"
else step "2/6  Python packages (first time: ~1.5 GB download, takes a few minutes)"; fi
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
REQ=requirements.txt
if [ "$HAS_NVIDIA" = 0 ]; then   # the CUDA libraries are only for NVIDIA cards: skip ~1.5 GB
  grep -v '^nvidia-' requirements.txt > .venv/requirements-cpu.txt && REQ=.venv/requirements-cpu.txt
fi
if "${PIP[@]}" install -r "$REQ" -r requirements-dev.txt; then
  ok "Installed the exact versions Clippy was tested with"
else
  warn "Those exact versions aren't available for $("$VPY" -V); installing the newest compatible ones instead."
  sed 's/[=<>~!;].*//' "$REQ" requirements-dev.txt | grep -v '^\s*$' > .venv/requirements-unpinned.txt
  "${PIP[@]}" install -r .venv/requirements-unpinned.txt || die "pip could not install the packages (see the error above)."
fi

# ── 3. ffmpeg, emoji font, yt-dlp, deno ──────────────────────────────────────
step "3/6  ffmpeg, emoji font, yt-dlp"
has_emoji_font() {
  fc-list 2>/dev/null | grep -qi "Noto Color Emoji" && return 0
  for f in /usr/share/fonts/noto/NotoColorEmoji.ttf /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf \
           /usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf; do [ -e "$f" ] && return 0; done
  return 1
}
NEED=()
{ command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; } || NEED+=("$(pkg_name ffmpeg)")
has_emoji_font || NEED+=("$(pkg_name emoji)")
if [ ${#NEED[@]} -gt 0 ]; then
  printf '  Missing: %s\n' "${NEED[*]}"
  if ask "Install them now with sudo?"; then pm_install "${NEED[@]}" || warn "Couldn't install ${NEED[*]} automatically."; fi
fi
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ok "ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3)"
else
  warn "Install ffmpeg with your package manager, then run setup again."
fi
if has_emoji_font; then ok "Emoji font"; else warn "No color emoji font: captions will skip emojis ($(pkg_name emoji) adds them)."; fi

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

# ── 4. Graphics card ─────────────────────────────────────────────────────────
step "4/6  Graphics card"
if [ "$HAS_NVIDIA" = 1 ]; then
  ok "GPU: $("$SMI" --query-gpu=name,memory.total --format=csv,noheader | head -1)"
  if "$VPY" -c 'import ctranslate2, sys; sys.exit(ctranslate2.get_cuda_device_count() < 1)' 2>/dev/null; then
    ok "Whisper can use the GPU"
  else
    warn "Whisper can't see the GPU (check the NVIDIA driver); it'll transcribe on the CPU."
  fi
elif [ "$IS_WSL" = 1 ]; then
  warn "No NVIDIA GPU visible in WSL. Clippy works on the CPU, just slower."
  note "Have an NVIDIA card? Install the latest NVIDIA driver on Windows (not inside Ubuntu),"
  note "then run  wsl --shutdown  in PowerShell, open Ubuntu again and run: bash setup.sh"
else
  warn "No NVIDIA GPU/driver found: Clippy still works, but transcribing and encoding run on the CPU (slower)."
fi

# ── 5. The AI that picks the clips ───────────────────────────────────────────
step "5/6  AI that picks the clips"
ai_json() { "$VPY" -m clippy ai --json 2>/dev/null; }
ai_using() { "$VPY" -c 'import json,sys; u=json.load(sys.stdin).get("using") or {}; print((u.get("model") or "the loaded model") + " on " + u.get("label","?"))'; }
ai_wait() {  # a freshly started server can take a minute to load its model
  local j
  for _ in $(seq 1 60); do j=$(ai_json) && { echo "$j"; return 0; }; sleep 2; done
  return 1
}
setup_ollama() {
  local model
  model=$("$VPY" -m clippy.aisetup ollama-model)
  if ! command -v ollama >/dev/null; then
    if ask "Install Ollama with its official installer from ollama.com? (It asks for your password.)"; then
      command -v zstd >/dev/null || pm_install zstd || true   # the installer needs it to unpack
      curl -fsSL https://ollama.com/install.sh | sh || { warn "The Ollama installer failed (see above)."; return 1; }
      record ollama
    else
      warn "Skipped installing Ollama."; return 1
    fi
  fi
  if ! ollama list >/dev/null 2>&1; then   # not running as a service (WSL without systemd, for example)
    (nohup ollama serve >"$HOME/.ollama-serve.log" 2>&1 &)
    for _ in $(seq 1 20); do ollama list >/dev/null 2>&1 && break; sleep 1; done
  fi
  ollama list >/dev/null 2>&1 || { warn "Ollama isn't answering. Start it with:  ollama serve"; return 1; }
  printf '  Downloading %s, sized for this PC (the big download)…\n' "$model"
  local had=0
  ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -qxF -e "$model" -e "$model:latest" && had=1
  ollama pull "$model" || { warn "Couldn't download $model."; return 1; }
  [ "$had" = 1 ] || record ollama-model "$model"
  ok "Ollama is ready with $model"
}
setup_llamacpp() {
  local had=0 before f ok=0
  { [ -e "$HOME/.local/opt/llama.cpp" ] || [ -e "$HOME/.local/bin/llama-coder" ]; } && had=1
  before=$(ls "$HOME"/models/*.gguf 2>/dev/null || true)
  "$VPY" -m clippy.aisetup llamacpp && ok=1
  # note what this added (also after a half-finished run), so clippy uninstall offers exactly that: never a
  # llama.cpp or model that was here before
  if [ "$had" = 0 ] && { [ -e "$HOME/.local/opt/llama.cpp" ] || [ -e "$HOME/.local/bin/llama-coder" ]; }; then
    record llamacpp
  fi
  for f in "$HOME"/models/*.gguf; do
    [ -e "$f" ] && ! grep -qxF "$f" <<<"$before" && record model "$f"
  done
  [ "$ok" = 1 ] || { warn "llama.cpp setup didn't finish (see above)."; return 1; }
  if ! systemctl --user is-active --quiet llama-coder 2>/dev/null; then   # no systemd: start it for now
    (nohup "$HOME/.local/bin/llama-coder" >"$HOME/.llama-coder.log" 2>&1 &)
  fi
}

if AI_NOW=$(ai_json); then
  ok "Found $(echo "$AI_NOW" | ai_using). Clippy will use it."
  [ -z "$AI" ] && AI=found
fi
if [ -z "$AI" ]; then
  if [ "$YES" = 1 ] || [ ! -t 0 ]; then
    AI=skip
  else
    REC=$("$VPY" -m clippy.aisetup recommend 2>/dev/null)
    OLL=$(echo "$REC" | "$VPY" -c 'import json,sys; print(json.load(sys.stdin)["ollama"])' 2>/dev/null || echo "qwen3.5:9b")
    GGUF=$(echo "$REC" | "$VPY" -c 'import json,sys; g=json.load(sys.stdin)["gguf"] or {}; print(g.get("file", "a model").removesuffix(".gguf") + ", " + str(g.get("gb", "?")) + " GB")' 2>/dev/null)
    echo "  Clippy needs a local AI to pick the best moments, and none is running yet. Pick one:"
    echo "    1) Ollama      easiest: installs Ollama (asks for your password) and downloads $OLL"
    echo "    2) llama.cpp   no password, fastest with big models: downloads into ~/.local and ~/models ($GGUF)"
    echo "    3) Skip        I'll start my own (LM Studio, Jan, KoboldCpp…) or use a cloud API key"
    [ "$IS_WSL" = 1 ] && note "Already running Ollama or LM Studio on Windows? Choose 3 and see README → \"AI on Windows\"."
    read -r -p "  Your choice [1]: " c
    case "${c:-1}" in 1) AI=ollama ;; 2) AI=llamacpp ;; *) AI=skip ;; esac
  fi
fi
case "$AI" in
  ollama|llamacpp)
    if [ "$AI" = ollama ]; then setup_ollama; else setup_llamacpp; fi && {
      if AI_NOW=$(ai_wait); then
        ok "Using $(echo "$AI_NOW" | ai_using)"
        TEST=$("$VPY" -m clippy ai test 2>&1 | tail -1)
        case "$TEST" in "Test answer"*) ok "${TEST%%  (*}" ;; *) warn "The AI answered oddly: $TEST" ;; esac
      else
        warn "The AI server isn't answering yet. Check with:  clippy ai"
      fi
    } ;;
  skip)
    warn "No AI set up yet, so Clippy can't pick clips. Start one (Ollama, LM Studio, llama.cpp…) and Clippy finds it,"
    note "or run:  bash setup.sh --ai ollama   (or --ai llamacpp). Check anytime with:  clippy ai" ;;
esac

# ── 6. Finishing ─────────────────────────────────────────────────────────────
step "6/6  Finishing"
mkdir -p "$HOME/.local/bin"
LINK="$HOME/.local/bin/clippy"
if [ ! -e "$LINK" ] || [ "$(readlink -f "$LINK")" = "$DIR/clippy.sh" ]; then
  ln -sf "$DIR/clippy.sh" "$LINK"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ok "Command: clippy  (for example: clippy web)" ;;
    *) ok "Command: clippy  (open a new terminal first, so it's on your PATH)" ;;
  esac
else
  note "$LINK already exists, so use ./clippy.sh in this folder."
fi
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

printf '\n\033[1mDone%s.\033[0m Start Clippy with:  clippy web   (or ./clippy.sh web).  To remove it again:  clippy uninstall\n' \
  "$([ "$WARN" -gt 0 ] && echo " with $WARN note(s) above")"
if [ "$IS_WSL" = 1 ]; then
  echo "It opens in your Windows browser at http://localhost:7860 (or open that address yourself)."
else
  echo "It opens in your browser at http://localhost:7860."
fi
