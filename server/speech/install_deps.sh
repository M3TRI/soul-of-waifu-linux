#!/usr/bin/env bash
# Python deps of the speech service: the ML part of install_linux.sh with the same pins and
# order, without the GUI packages. Runs inside the image build (venv at $VIRTUAL_ENV).
set -euo pipefail
TORCH=${1:?usage: install_deps.sh cu128|cu126|cpu}
pipi() { uv pip install "$@"; }

pipi torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url "https://download.pytorch.org/whl/$TORCH"
pipi numpy==1.26.4
pipi sentence-transformers==5.1.0
pipi edge-tts==7.3.1 kokoro==0.9.4
# misaki (Kokoro's G2P) downloads this spaCy model with pip on first use, which cannot work in
# a read-only image running as an unprivileged user.
# The newest preshed/cymem/murmurhash break loading that model (OverflowError in
# Tokenizer._flush_specials); these are the versions of the working desktop venv.
pipi preshed==3.0.13 cymem==2.0.13 murmurhash==1.0.15
pipi "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
pipi qwen-tts
pipi faster-whisper
pipi soundfile==0.13.1 pydub==0.25.1 omegaconf==2.3.0
pipi huggingface-hub==0.36.0 hf_transfer==0.1.9
pipi transformers==4.57.3
pipi av praat-parselmouth scipy==1.13.1
pipi antlr4-python3-runtime==4.9.3 portalocker==3.2.0
pipi fastapi==0.139.0 uvicorn==0.51.0 python-multipart nvidia-ml-py
pipi "coqui-tts[codec]"
pipi pyworld torchcrepe
pipi torchcodec==0.10.0
# RVC: same fairseq fork and rvc-python commit as install_linux.sh.
pipi cython wheel "setuptools<81" ffmpeg-python faiss-cpu==1.7.3 loguru
pipi --no-build-isolation "fairseq @ git+https://github.com/Tps-F/fairseq@ff08af27e302625a27d3502b0791a9367c8af0c7"
pipi --no-deps "rvc-python @ git+https://github.com/JarodMica/rvc-python@9a67ac77743d749e9f2cbbb02798957d5343fd19"
pipi "setuptools<81"
pipi numpy==1.26.4
