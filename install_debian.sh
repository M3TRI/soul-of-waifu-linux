#!/usr/bin/env bash
# One-shot installer for Debian 12+/Ubuntu 22.04+ and derivatives. Installs in place:
#   1. system packages (apt, needs sudo)
#   2. uv + Python 3.11 + all Python deps into ./.venv (install_linux.sh)
#   3. official llama.cpp build into ./llama (CUDA for NVIDIA driver >= 570, else Vulkan)
#   4. a default GGUF model into ./assets/local_llm (skipped if one is already there)
#   5. ./llama.conf and a desktop menu entry that runs ./launch.sh
# Re-running is safe: finished steps are skipped or redone idempotently.
#
# Options:
#   --cpu               CPU only (torch cpu wheels, CPU llama.cpp build, no GPU offload)
#   --torch=cu128|cu126|cpu
#   --llama=cuda|vulkan|cpu
#   --no-model          do not download the default model
#   --model-url=URL     download this GGUF instead of the default one
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

install_system_packages() {
    # build-essential/pkg-config: live2d-py and fairseq are built from source (CMake comes
    # from PyPI, see install_linux.sh);
    # portaudio19-dev: PyAudio; the lib* list is what the PyQt6/WebEngine wheels expect.
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends \
        ca-certificates curl git xz-utils build-essential pkg-config \
        ffmpeg sox libportaudio2 portaudio19-dev espeak-ng \
        libgl1 libegl1 libopengl0 libglu1-mesa libgl-dev \
        libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
        libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
        libxcb-xkb1 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxkbfile1 libxshmfence1 \
        libnss3 libasound2 libdbus-1-3 libfontconfig1 libvulkan1 mesa-vulkan-drivers \
        libnotify-bin desktop-file-utils xdg-utils
}

. tools/install_common.sh "$@"
