# Speech service: TTS engines, RVC, Whisper STT, embeddings, emotions in one process, so
# there is a single torch install and a single CUDA context. Build context: the repo root.
#   docker build -f server/speech/Dockerfile --build-arg TORCH=cu128 .
FROM python:3.11-slim-bookworm

ARG TORCH=cu128
ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git curl ffmpeg espeak-ng libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

RUN uv venv /opt/venv
COPY server/speech/install_deps.sh /tmp/install_deps.sh
RUN --mount=type=cache,target=/root/.cache/uv /tmp/install_deps.sh "$TORCH"

# Helper models baked into the image, same pinned revisions as install_common.sh.
RUN python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("d0rj/e5-small-en-ru", revision="8d9d26ce7447cedb9dba7c33587dbed883e293bd",
                  local_dir="/opt/sow/e5-small-en-ru")
snapshot_download("joeddav/distilbert-base-uncased-go-emotions-student",
                  revision="82114042047aaa39717090cfb20f3403b73b0215",
                  local_dir="/opt/sow/emotions", allow_patterns=["*.json", "*.txt", "pytorch_model.bin"])
PY
# rvc-python fetches its base models (hubert, rmvpe; pinned revisions in the package) into
# its own folder on first use, which is read-only at run time.
RUN python -c "import os, rvc_python; from rvc_python.download_model import download_rvc_models; \
download_rvc_models(os.path.dirname(rvc_python.__file__))" \
    && test -s /opt/venv/lib/python3.11/site-packages/rvc_python/base_model/rmvpe.pt
COPY app/voices/calm_female.wav app/voices/female.wav app/voices/male.wav /opt/sow/voices/

COPY server/speech/sow_speech /opt/sow/sow_speech
WORKDIR /opt/sow
# Model caches, uploaded voices and RVC models live in the /data volume. XTTSv2 (Coqui CPML
# licence) loads only with COQUI_TOS_AGREED=1, which the installer sets after asking the user.
ENV SOW_DATA=/data HF_HOME=/data/hf_cache TORCH_HOME=/data/torch
EXPOSE 8001
CMD ["python", "-m", "sow_speech"]
