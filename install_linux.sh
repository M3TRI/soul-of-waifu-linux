#!/usr/bin/env bash
# Linux counterpart of installer.bat: same packages and pins, installed into ./.venv with uv.
# System packages (build tools, portaudio, ffmpeg, Qt libraries) come from install_arch.sh or
# install_debian.sh, which install them and then run this script.
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
# uv-managed Python only: a distro python3.11 (Debian 12) lacks the headers live2d-py builds against.
[ -x "$PY" ] || uv venv --python-preference only-managed --python 3.11 .venv
pipi() { uv pip install --python "$PY" "$@"; }

# PyTorch wheel flavour: cu128 (default, NVIDIA driver >= 570, required for RTX 50xx),
# cu126 (driver >= 525) or cpu. "--cpu" is kept as a shorthand for "--torch=cpu".
TORCH=cu128
for arg in "$@"; do
    case "$arg" in
        --cpu) TORCH=cpu ;;
        --torch=*) TORCH="${arg#--torch=}" ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done
case "$TORCH" in cu128|cu126|cpu) ;; *) echo "Unsupported --torch=$TORCH (cu128, cu126, cpu)" >&2; exit 2 ;; esac

echo "[1/4] PyTorch ($TORCH wheels)"
pipi torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url "https://download.pytorch.org/whl/$TORCH"

echo "[2/4] Core dependencies (installer.bat step 4, same order)"
pipi numpy==1.26.4
pipi PyQt6==6.9.0 PyQt6-WebEngine==6.9.0 qasync==0.27.1
pipi beautifulsoup4 mss
pipi ddgs pypdf python-docx
pipi discord.py PyNaCl davey
pipi pypresence
pipi pyautogui playwright
pipi sentence-transformers==5.1.0
pipi openai==1.70.0 mistralai==1.5.0
pipi edge-tts==7.2.7 elevenlabs==1.52.0 kokoro==0.9.4
pipi qwen-tts
pipi faster-whisper
pipi curl_cffi
pipi translators==6.0.1 psutil==7.0.0 GPUtil==1.4.0
pipi sounddevice==0.5.1 soundfile==0.13.1 pydub==0.25.1
# live2d-py 0.5.4 is sdist-only on Linux and needs CMake >= 3.26 (Debian 12 ships 3.25,
# Ubuntu 22.04 3.22): take CMake from PyPI; uv build envs inherit PATH.
pipi "cmake>=3.26,<4"
PATH="$PWD/.venv/bin:$PATH" pipi PyOpenGL==3.1.9 live2d-py==0.5.4
pipi scikit-learn==1.4.2 aiohttp==3.11.13 requests==2.32.3
pipi tiktoken==0.11.0 PyYAML==6.0.2 pillow==11.3.0 ipython==9.4.0
pipi huggingface-hub==0.36.0 hf_transfer==0.1.9
pipi transformers==4.57.3
pipi av praat-parselmouth scipy==1.13.1
pipi python-multipart PyAudio tensorboardX
pipi antlr4-python3-runtime==4.9.3 portalocker==3.2.0
# On Windows these arrive with the bundled conda env (rvc-python deps); installer.bat never lists them.
pipi fastapi==0.139.0 uvicorn==0.51.0

echo "[3/4] Coqui TTS + RVC support"
pipi "coqui-tts[codec]"
pipi pyworld torchcrepe omegaconf==2.3.0
pipi torchcodec==0.10.0
# rvc_python is imported at startup (text_to_speech.py). Windows gets it pre-bundled with a
# hand-built fairseq 0.12.3 wheel; on Linux build the py3.11-compatible Tps-F fairseq fork
# against the installed torch, then rvc-python without its numpy<=1.23.5 pin.
pipi cython wheel "setuptools<81" ffmpeg-python faiss-cpu==1.7.3 loguru
pipi --no-build-isolation "fairseq @ git+https://github.com/Tps-F/fairseq@ff08af27e302625a27d3502b0791a9367c8af0c7"
pipi --no-deps "rvc-python @ git+https://github.com/JarodMica/rvc-python@9a67ac77743d749e9f2cbbb02798957d5343fd19"
# setuptools>=81 dropped pkg_resources, which fairseq/pyworld still import
pipi "setuptools<81"
pipi numpy==1.26.4

echo "[4/4] Smoke test"
"$PY" -c "import torch, numpy, transformers, PyQt6; print('Core imports OK, CUDA:', torch.cuda.is_available())"
"$PY" -c "from TTS.api import TTS; print('Coqui TTS import OK')" || echo "WARNING: Coqui TTS import failed"
"$PY" -c "import rvc_python.infer, live2d.v3; print('RVC + Live2D import OK')"
echo "Optional: '$PY -m playwright install chromium' for the web tools."
