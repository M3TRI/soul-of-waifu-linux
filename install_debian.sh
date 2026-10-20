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

LLAMA_TAG=b11565
LLAMA_BASE="https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_TAG"
MODEL_URL="https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"

TORCH="" LLAMA="" GET_MODEL=1
for arg in "$@"; do
    case "$arg" in
        --cpu) TORCH=cpu LLAMA=cpu ;;
        --torch=*) TORCH="${arg#--torch=}" ;;
        --llama=*) LLAMA="${arg#--llama=}" ;;
        --no-model) GET_MODEL=0 ;;
        --model-url=*) MODEL_URL="${arg#--model-url=}" ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "Unknown argument: $arg (see --help)" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" = 0 ]; then
    echo "Run this as your normal user, not root (sudo is used only for apt)." >&2
    exit 1
fi

echo "== [1/5] System packages"
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

echo "== [2/5] Python environment"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# NVIDIA driver major version, 0 without an NVIDIA driver.
driver=0
if command -v nvidia-smi >/dev/null 2>&1; then
    driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 | cut -d. -f1)
fi
case "$driver" in ''|*[!0-9]*) driver=0 ;; esac
if [ -z "$TORCH" ]; then
    if [ "$driver" -ge 570 ]; then TORCH=cu128
    elif [ "$driver" -ge 525 ]; then TORCH=cu126
    else TORCH=cpu; fi
fi
# The CUDA llama.cpp release is built on Ubuntu 24.04 and needs glibc >= 2.38; the Vulkan and
# CPU builds need only 2.34. Ubuntu 22.04 / Zorin 17 / Debian 12 therefore get Vulkan, which
# also runs on NVIDIA GPUs through the proprietary driver.
glibc=$(getconf GNU_LIBC_VERSION | awk '{print $2}')
glibc_ok() { [ "$(printf '%s\n%s\n' "$1" "$glibc" | sort -V | head -n 1)" = "$1" ]; }
if [ -z "$LLAMA" ]; then
    if [ "$driver" -ge 570 ] && glibc_ok 2.38; then LLAMA=cuda; else LLAMA=vulkan; fi
elif [ "$LLAMA" = cuda ] && ! glibc_ok 2.38; then
    echo "--llama=cuda needs glibc >= 2.38 (Ubuntu 24.04+), this system has $glibc; use --llama=vulkan." >&2
    exit 2
fi
echo "NVIDIA driver: ${driver/#0/none}; glibc: $glibc; torch: $TORCH; llama.cpp: $LLAMA"
./install_linux.sh --torch="$TORCH"

echo "== [3/5] llama.cpp $LLAMA_TAG ($LLAMA)"
case "$LLAMA" in
    cuda) archives="llama-$LLAMA_TAG-bin-ubuntu-cuda-12.8-x64.tar.gz cudart-llama-$LLAMA_TAG-bin-ubuntu-cuda-12.8-x64.tar.gz" ;;
    vulkan) archives="llama-$LLAMA_TAG-bin-ubuntu-vulkan-x64.tar.gz" ;;
    cpu) archives="llama-$LLAMA_TAG-bin-ubuntu-x64.tar.gz" ;;
    *) echo "Unsupported --llama=$LLAMA (cuda, vulkan, cpu)" >&2; exit 2 ;;
esac
if [ "$(cat llama/.build 2>/dev/null)" != "$LLAMA_TAG-$LLAMA" ]; then
    rm -rf llama.new && mkdir -p llama.new
    for a in $archives; do
        echo "Downloading $a"
        # Every release archive has a single top directory llama-<tag>/.
        curl -fL --retry 3 "$LLAMA_BASE/$a" | tar -xz -C llama.new --strip-components=1
    done
    # Check that the build actually runs here before it replaces the old one.
    llama.new/llama-server --version >/dev/null 2>&1 || {
        llama.new/llama-server --version 2>&1 | tail -n 3 >&2
        echo "This llama.cpp build does not run on this system, try --llama=vulkan or --llama=cpu." >&2
        exit 1
    }
    echo "$LLAMA_TAG-$LLAMA" > llama.new/.build
    rm -rf llama && mv llama.new llama
fi
llama/llama-server --version 2>&1 | tail -n 2

echo "== [4/5] Models"
# Weights of the app's bundled helper models are too big for git; they are byte-identical
# to these HuggingFace files (pinned revisions, sha256-checked).
fetch_hf() {  # repo revision file destination sha256
    if [ -f "$4" ] && echo "$5  $4" | sha256sum -c --quiet 2>/dev/null; then return 0; fi
    echo "Downloading $1/$3"
    curl -fL --retry 3 -o "$4.part" "https://huggingface.co/$1/resolve/$2/$3"
    echo "$5  $4.part" | sha256sum -c --quiet
    mv "$4.part" "$4"
}
fetch_hf d0rj/e5-small-en-ru 8d9d26ce7447cedb9dba7c33587dbed883e293bd model.safetensors \
    app/utils/e5-small-en-ru/model.safetensors 6079614e8936c70fc6fa65f6692f6983e3d8082cd44d5e37f89464e6f719eb6d
fetch_hf joeddav/distilbert-base-uncased-go-emotions-student 82114042047aaa39717090cfb20f3403b73b0215 pytorch_model.bin \
    app/utils/emotions/detector/pytorch_model.bin 0e97a8d55b9b6c9a57c217d71eb5068469baee9e0f229c8fceddcf33c1480a8b

mkdir -p assets/local_llm
if find assets/local_llm -maxdepth 2 -name '*.gguf' ! -iname '*mmproj*' | grep -q .; then
    echo "A model is already in assets/local_llm, skipping the download."
elif [ "$GET_MODEL" = 1 ]; then
    name=$(basename "${MODEL_URL%%\?*}")
    echo "Downloading $name"
    curl -fL --retry 3 -C - -o "assets/local_llm/$name.part" "$MODEL_URL"
    mv "assets/local_llm/$name.part" "assets/local_llm/$name"
else
    echo "No model downloaded: put a .gguf into assets/local_llm before starting."
fi

echo "== [5/5] Launcher and menu entry"
if [ ! -f llama.conf ]; then
    # Defaults by GPU memory. --fit (on by default in llama-server) offloads as many layers
    # as fit and keeps the rest in RAM; small cards also get a shorter q8_0 KV cache and a
    # larger free-VRAM margin for Whisper/TTS, which run on the same GPU inside the app.
    ngl="" ctx=16384 extra=""
    vram=0
    if command -v nvidia-smi >/dev/null 2>&1; then
        vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1)
    fi
    case "$vram" in ''|*[!0-9]*) vram=0 ;; esac
    if [ "$LLAMA" = cpu ]; then
        ngl=0 ctx=8192
    elif [ "$vram" -gt 0 ] && [ "$vram" -le 6144 ]; then
        ctx=8192 extra="-ctk q8_0 -ctv q8_0 --fit-target 1536"
    fi
    cat > llama.conf <<EOF
# Sourced by launch.sh. The app talks to http://127.0.0.1:\$LLAMA_PORT/v1
# (Options -> LLM Settings -> Advanced -> Hardware & Backend -> External server); keep both in sync.
LLAMA_PORT=8095
LLAMA_MODEL=""      # empty = first *.gguf in assets/local_llm
LLAMA_CTX=$ctx
LLAMA_NGL="$ngl"    # GPU layers; empty = fit into free VRAM automatically, 0 = CPU only
LLAMA_WAIT=300
LLAMA_ARGS="$extra" # extra llama-server flags
EOF
fi
chmod +x launch.sh start.sh install_linux.sh

apps="$HOME/.local/share/applications"
mkdir -p "$apps"
cat > "$apps/soul-of-waifu.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Soul of Waifu
Comment=AI companion with a local LLM
Exec="$PWD/launch.sh"
Path=$PWD
Icon=$PWD/app/gui/icons/logotype.png
Terminal=false
Categories=Game;Chat;
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" || true

echo
echo "Done. Start it from the application menu (Soul of Waifu) or with: $PWD/launch.sh"
echo "llama-server log: $PWD/logs/llama-server.log; settings: $PWD/llama.conf"
