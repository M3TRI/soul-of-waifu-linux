#!/usr/bin/env bash
# One-shot installer for Arch Linux and derivatives (EndeavourOS, Manjaro, CachyOS, ...).
# Installs in place:
#   1. system packages (pacman, needs sudo; also brings the system up to date)
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
    # base-devel: live2d-py and fairseq are built from source (CMake comes from PyPI, see
    # install_linux.sh: the system CMake 4.x is too new for live2d-py);
    # portaudio: PyAudio; the lib* and xcb-util* list is what the PyQt6/WebEngine wheels expect.
    local pkgs=(
        base-devel git curl xz uv
        ffmpeg sox portaudio espeak-ng
        libglvnd mesa glu
        libxkbcommon libxkbcommon-x11 xcb-util-cursor xcb-util-wm xcb-util-image
        xcb-util-keysyms xcb-util-renderutil libxcomposite libxdamage libxrandr libxtst
        libxkbfile libxshmfence nss alsa-lib dbus fontconfig vulkan-icd-loader
        libnotify desktop-file-utils xdg-utils
    )
    # Vulkan drivers for the Vulkan llama.cpp build. NVIDIA's comes with its driver
    # (nvidia-utils), which is left to the user like on any Arch system.
    local vendor
    for vendor in /sys/class/drm/card*/device/vendor; do
        case "$(cat "$vendor" 2>/dev/null)" in
            0x1002) pkgs+=(vulkan-radeon) ;;
            0x8086) pkgs+=(vulkan-intel) ;;
        esac
    done
    # -Syu, not -Sy: installing on top of a partial upgrade is unsupported on Arch.
    sudo pacman -Syu --needed "${pkgs[@]}"
}

. tools/install_common.sh "$@"
