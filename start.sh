#!/usr/bin/env bash
# Linux counterpart of start.bat. All app paths are relative, so run from the project root.
cd "$(dirname "$0")" || exit 1

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ERROR: ffmpeg not found in PATH (Arch: pacman -S ffmpeg)." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "ERROR: .venv not found, run ./install_linux.sh first." >&2
    exit 1
fi

# Wayland is used by default; if Live2D/OpenGL or WebEngine views render black, try:
#   QT_QPA_PLATFORM=xcb ./start.sh
exec .venv/bin/python main.py "$@"
