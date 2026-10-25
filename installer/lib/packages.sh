# shellcheck shell=bash
# System packages the UI client needs, per distribution family. A subset of what
# install_arch.sh / install_debian.sh install for the all-in-one desktop build: no TTS or
# llama.cpp runtime here (sox, espeak-ng, Vulkan drivers live in the server containers).
#   build tools  - live2d-py is built from source (CMake itself comes from PyPI) and
#                  needs the OpenGL headers (libgl-dev, mesa-libGL-devel)
#   portaudio    - PyAudio (microphone) and sounddevice
#   ffmpeg       - pydub decodes ElevenLabs mp3; start.sh checks for it
#   glib         - QtWebEngine (libgthread), present on desktops but not on minimal systems
#   the rest     - what the PyQt6 / PyQt6-WebEngine wheels load at run time

ui_packages() {
    case "$1" in
        arch) echo base-devel git curl ffmpeg portaudio glib2 \
            libglvnd mesa glu libxkbcommon libxkbcommon-x11 xcb-util-cursor xcb-util-wm \
            xcb-util-image xcb-util-keysyms xcb-util-renderutil libxcomposite libxdamage libxrandr \
            libxtst libxkbfile libxshmfence nss alsa-lib dbus fontconfig \
            libnotify desktop-file-utils xdg-utils ;;
        debian) echo ca-certificates curl git build-essential pkg-config \
            ffmpeg libportaudio2 portaudio19-dev libglib2.0-0 \
            libgl1 libegl1 libopengl0 libglu1-mesa libgl-dev \
            libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
            libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
            libxcb-xkb1 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxkbfile1 libxshmfence1 \
            libnss3 libasound2 libdbus-1-3 libfontconfig1 \
            libnotify-bin desktop-file-utils xdg-utils ;;
        fedora) echo gcc gcc-c++ make git curl ffmpeg-free portaudio portaudio-devel glib2 \
            mesa-libGL mesa-libGL-devel mesa-libEGL mesa-libGLU libxkbcommon libxkbcommon-x11 xcb-util-cursor \
            xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil libXcomposite \
            libXdamage libXrandr libXtst libxkbfile libxshmfence nss alsa-lib dbus-libs fontconfig \
            libnotify desktop-file-utils xdg-utils ;;
        suse) echo gcc gcc-c++ make git curl ffmpeg portaudio-devel libgthread-2_0-0 \
            Mesa-libGL1 Mesa-libGL-devel Mesa-libEGL1 libGLU1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 \
            libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libXcomposite1 \
            libXdamage1 libXrandr2 libXtst6 libxkbfile1 libxshmfence1 mozilla-nss libasound2 \
            libdbus-1-3 fontconfig libnotify-tools desktop-file-utils xdg-utils ;;
    esac
}

# Debian 13 / Ubuntu 24.04 renamed some libraries for the 64-bit time_t transition
# (libasound2 -> libasound2t64): use whichever name the system can install.
# "apt-cache show" prints the providers of a virtual package, so ask for an install
# candidate instead.
# No pipe into grep -q: under pipefail apt-cache dies of SIGPIPE when grep stops early,
# and the match would count as a failure.
apt_installable() {
    local policy
    policy=$(apt-cache policy "$1" 2>/dev/null) || return 1
    [[ "$policy" == *"Candidate: "[!\(]* ]]
}
apt_name() {
    if apt_installable "$1"; then echo "$1"
    elif apt_installable "${1}t64"; then echo "${1}t64"
    else echo "$1"; fi
}

# Packages from that list that are not installed yet.
missing_packages() {
    local p missing=()
    for p in $(ui_packages "$OS_FAMILY"); do
        [ "$PKG" = apt ] && p=$(apt_name "$p")
        case "$PKG" in
            pacman) pacman -Qq "$p" >/dev/null 2>&1 || pacman -Qqg "$p" >/dev/null 2>&1 || missing+=("$p") ;;
            apt) [[ "$(dpkg-query -W -f='${Status}' "$p" 2>/dev/null)" == *"ok installed"* ]] || missing+=("$p") ;;
            dnf|zypper) rpm -q "$p" >/dev/null 2>&1 || missing+=("$p") ;;
        esac
    done
    echo "${missing[@]}"
}
