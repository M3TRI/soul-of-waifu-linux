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

# On Wayland with the NVIDIA driver, the WebEngine bundled with the PyQt6 wheel cannot use
# GBM and its GPU process ends up on Mesa's EGL, which falls back to llvmpipe, so WebGL is
# blocklisted and the VRM view fails. Pin glvnd to NVIDIA's EGL unless the user chose otherwise.
nvidia_egl=/usr/share/glvnd/egl_vendor.d/10_nvidia.json
if [ -n "$WAYLAND_DISPLAY" ] && [ "${QT_QPA_PLATFORM:-wayland}" != xcb ] \
    && [ -d /proc/driver/nvidia ] && [ -f "$nvidia_egl" ] && [ -z "$__EGL_VENDOR_LIBRARY_FILENAMES" ]; then
    export __EGL_VENDOR_LIBRARY_FILENAMES="$nvidia_egl"
fi

# Wayland is used by default; if Live2D/OpenGL or WebEngine views render black, try:
#   QT_QPA_PLATFORM=xcb ./start.sh
exec .venv/bin/python main.py "$@"
