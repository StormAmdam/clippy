#!/usr/bin/env bash
# Clippy launcher:  ./clippy.sh <youtube-url> [options]   |   ./clippy.sh web
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
if ! "$DIR/.venv/bin/python" -c "" 2>/dev/null; then
  echo "Clippy isn't set up on this PC yet. Run this once:  bash \"$DIR/setup.sh\"" >&2
  exit 1
fi
cd "$DIR" && exec "$DIR/.venv/bin/python" -m clippy "$@"
