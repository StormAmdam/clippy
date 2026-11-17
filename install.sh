#!/usr/bin/env bash
# Install Clippy in one line (Linux, or Ubuntu on Windows via WSL):
#     curl -fsSL https://raw.githubusercontent.com/StormAmdam/clippy/main/install.sh | bash
# Options are passed on to setup.sh, e.g.:   … | bash -s -- --ai ollama
# Installs into ~/clippy (set CLIPPY_DIR to choose another folder). Running it again updates Clippy.
set -euo pipefail
REPO="${CLIPPY_REPO:-https://github.com/StormAmdam/clippy}"
DEST="${CLIPPY_DIR:-$HOME/clippy}"
say() { printf '\033[1m%s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] && { echo "Run this as your normal user, not root (setup asks for sudo itself when it needs it)."; exit 1; }
if [ "$(uname -s)" != Linux ]; then
  echo "Clippy runs on Linux. On Windows: open PowerShell, run  wsl --install , restart your PC,"
  echo "open Ubuntu from the Start menu, then paste this install line in there."
  exit 1
fi
command -v curl >/dev/null || { echo "Needs curl first:  sudo apt install curl   (then run this again)"; exit 1; }

if [ -d "$DEST/.git" ]; then
  say "Updating Clippy in $DEST"
  git -C "$DEST" pull --ff-only
elif [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  echo "$DEST already exists and isn't a Clippy download. Pick another folder:  CLIPPY_DIR=~/somewhere-else"
  exit 1
elif command -v git >/dev/null; then
  say "Downloading Clippy to $DEST"
  git clone --depth 1 "$REPO.git" "$DEST"
else
  say "Downloading Clippy to $DEST"
  mkdir -p "$DEST"
  curl -fsSL "${CLIPPY_TARBALL:-$REPO/archive/refs/heads/main.tar.gz}" | tar xz -C "$DEST" --strip-components=1
fi

cd "$DEST"
# when piped into bash, stdin is this script: give setup the keyboard back so it can ask questions
if [ -t 1 ] && [ -r /dev/tty ] && : < /dev/tty 2>/dev/null; then
  exec bash setup.sh "$@" < /dev/tty
else
  exec bash setup.sh "$@"
fi
