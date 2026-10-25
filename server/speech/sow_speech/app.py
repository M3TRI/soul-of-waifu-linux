"""
HTTP API of the speech service (docs/server-api.md). It listens on the compose network
only; the gateway in front of it does auth and TLS.
"""
import hashlib
import logging
import os
import re
import shutil
import tempfile

import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import nlp, stt, tts
from .models import BUDGET_MB, DEVICE, OutOfVram, is_oom, manager

logger = logging.getLogger("sow_speech")
app = FastAPI(docs_url=None, redoc_url=None)

MAX_REF_BYTES = 20 * 2**20
MAX_RVC_BYTES = 600 * 2**20
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[\w .-]{1,80}$")


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(tts.TtsError)
async def _tts_error(_req, exc):
    return error(422, "engine_unavailable", _describe(exc))


@app.exception_handler(OutOfVram)
async def _oom(_req, exc):
    return error(507, "out_of_vram", str(exc))


def _describe(exc: BaseException) -> str:
    """Exception text for the client; some libraries raise with an empty message."""
    return str(exc) or type(exc).__name__


@app.exception_handler(ValueError)
async def _bad(_req, exc):
    logger.warning("Bad request: %s", _describe(exc))
    return error(400, "bad_request", _describe(exc))


@app.exception_handler(HTTPException)
async def _http(_req, exc):
    code = {401: "unauthorized", 404: "not_found", 413: "bad_request"}.get(exc.status_code, "bad_request")
    return error(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def _internal(_req, exc):
    if is_oom(exc):
        logger.warning("Out of VRAM during inference: %s", exc)
        return error(507, "out_of_vram", f"not enough free video memory: {exc}")
    logger.exception("Unhandled error")
    return error(500, "internal", f"{type(exc).__name__}: {exc}")


# --- service -------------------------------------------------------------------------------

def _gpu() -> dict:
    if DEVICE != "cuda":
        return {"backend": "cpu"}
    free, total = torch.cuda.mem_get_info()
    return {"backend": "cuda", "name": torch.cuda.get_device_name(0),
            "vram_total_mb": total // 2**20, "vram_used_mb": (total - free) // 2**20,
            "speech_budget_mb": BUDGET_MB}


@app.get("/sow/health")
async def health():
    return {"status": "ok", "api_version": 1}


# Smallest VRAM each optional engine needs on CUDA (measured, docs/server-api.md); with
# Whisper resident next to it. Engines that cannot fit the installer's voice profile are
# reported unavailable instead of failing on the first sentence.
MIN_ENGINE_MB = {"qwen3": 2000, "xtts": 2000, "rvc": 1200, "kokoro": 400}
RESIDENT_MB = stt.EST_MB["small"]


def _fit(engine: str) -> dict:
    need = MIN_ENGINE_MB.get(engine, 0)
    if DEVICE != "cuda" or BUDGET_MB is None or need + RESIDENT_MB <= BUDGET_MB:
        return {"available": True}
    return {"available": False, "reason_code": "vram", "need_mb": need + RESIDENT_MB, "budget_mb": BUDGET_MB,
            "reason": f"needs about {(need + RESIDENT_MB) / 1024:.1f} GB of video memory, the voice profile "
                      f"chosen at install time allows {BUDGET_MB / 1024:.1f} GB (re-run the installer to change it)"}


@app.get("/sow/speech/capabilities")
async def capabilities():
    gpu_or_cpu = "cuda" if DEVICE == "cuda" else "cpu"
    xtts = _fit("xtts")
    if os.environ.get("COQUI_TOS_AGREED") != "1":
        xtts = {"available": False, "reason_code": "licence", "reason": "Coqui CPML licence not accepted"}
    return {
        "gpu": _gpu(),
        "tts": [
            {"engine": "kokoro", **_fit("kokoro"), "device": gpu_or_cpu, "voices": tts.KOKORO_VOICES},
            {"engine": "xtts", **xtts, "device": gpu_or_cpu, "voices": list(tts.XTTS_SPEAKERS)},
            {"engine": "qwen3", **_fit("qwen3"), "device": gpu_or_cpu, "voices": tts.QWEN_PRESETS},
            {"engine": "silero", "available": True, "device": gpu_or_cpu, "voices": tts.SILERO_SPEAKERS},
            {"engine": "edge", "available": True, "device": "cloud"},
        ],
        "rvc": {**_fit("rvc"), "models": tts.rvc_models()},
        "stt": {"available": True, "models": stt.MODELS, "device": gpu_or_cpu},
        "embeddings": {"available": True, "model": nlp.EMBEDDING_MODEL},
        "emotions": {"available": True, "labels": nlp.EMOTIONS},
    }


@app.get("/sow/speech/status")
async def status():
    return {"gpu": _gpu(), "loaded": manager.status()}


# --- TTS -----------------------------------------------------------------------------------

class RvcIn(BaseModel):
    model: str
    f0up_key: int = 0
    index_rate: float = 0.75
    protect: float = 0.5


class QwenIn(BaseModel):
    mode: str = "presets"
    model_size: str = "1.7B"
    device: str = "cuda"
    prompt: str = ""
    style_instruct: str = ""
    ref: str = ""
    ref_text: str = ""
    language: str = "English"


class SowOptions(BaseModel):
    language: str = "en"
    rvc: RvcIn | None = None
    qwen: QwenIn = Field(default_factory=QwenIn)


class SpeechIn(BaseModel):
    model: str
    input: str
    voice: str = ""
    response_format: str = "wav"
    sow: SowOptions = Field(default_factory=SowOptions)


def _speech_request(body: SpeechIn) -> tts.SpeechRequest:
    if body.response_format != "wav":
        raise ValueError("Only response_format=wav is supported")
    return tts.SpeechRequest(
        engine=body.model, text=body.input, voice=body.voice, language=body.sow.language,
        rvc=tts.RvcOptions(**body.sow.rvc.model_dump()) if body.sow.rvc else None,
        qwen=tts.QwenOptions(**body.sow.qwen.model_dump()),
    )


@app.post("/v1/audio/speech")
async def speech(body: SpeechIn):
    wav, sr, duration = await tts.synthesize(_speech_request(body))
    return Response(wav, media_type="audio/wav",
                    headers={"X-Sow-Sample-Rate": str(sr), "X-Sow-Duration": f"{duration:.3f}"})


@app.post("/sow/tts/preload")
async def tts_preload(body: SpeechIn):
    await tts.preload(_speech_request(body))
    return {"status": "ok"}


async def _save_upload(request: Request, dest: str, limit: int, expect_sha256: str | None = None):
    """Stream the request body to dest (atomically), enforcing a size limit and a hash."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    digest, size = hashlib.sha256(), 0
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest))
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Upload larger than {limit // 2**20} MB")
                digest.update(chunk)
                f.write(chunk)
        if expect_sha256 and digest.hexdigest() != expect_sha256:
            raise HTTPException(400, "Body does not match its sha256")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@app.head("/sow/voices/refs/{sha256}")
async def ref_exists(sha256: str):
    if not SHA256_RE.match(sha256) or not os.path.exists(tts.ref_path(sha256)):
        raise HTTPException(404, "No such reference clip")
    return Response()


@app.put("/sow/voices/refs/{sha256}")
async def ref_upload(sha256: str, request: Request):
    if not SHA256_RE.match(sha256):
        raise HTTPException(400, "Reference id must be a lowercase sha256 hex digest")
    await _save_upload(request, tts.ref_path(sha256), MAX_REF_BYTES, sha256)
    return {"status": "ok"}


@app.get("/sow/rvc/models")
async def rvc_list():
    return {"models": tts.rvc_models()}


@app.put("/sow/rvc/models/{name}")
async def rvc_upload(name: str, pth: UploadFile = File(...), index: UploadFile | None = File(None)):
    if not NAME_RE.match(name) or name.startswith("."):
        raise HTTPException(400, "Bad model name")
    folder = os.path.join(tts.RVC_DIR, name)
    tmp = folder + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        for upload, ext in ((pth, ".pth"), (index, ".index")):
            if upload is None:
                continue
            size = 0
            with open(os.path.join(tmp, name + ext), "wb") as f:
                while chunk := await upload.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_RVC_BYTES:
                        raise HTTPException(413, "RVC file too large")
                    f.write(chunk)
        shutil.rmtree(folder, ignore_errors=True)
        os.replace(tmp, folder)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    manager.unload("rvc")  # drop a cached copy of a replaced model
    return {"status": "ok"}


@app.delete("/sow/rvc/models/{name}")
async def rvc_delete(name: str):
    if name not in tts.rvc_models():
        raise HTTPException(404, "No such RVC model")
    shutil.rmtree(os.path.join(tts.RVC_DIR, name))
    manager.unload("rvc")
    return {"status": "ok"}


# --- STT, embeddings, emotions -------------------------------------------------------------

@app.post("/v1/audio/transcriptions")
async def transcriptions(file: UploadFile = File(...), model: str = Form("small"),
                         language: str | None = Form(None)):
    audio = await file.read()
    if len(audio) > 50 * 2**20:
        raise HTTPException(413, "Audio larger than 50 MB")
    return {"text": await stt.transcribe(audio, model, language or None)}


class EmbeddingsIn(BaseModel):
    model: str = nlp.EMBEDDING_MODEL
    input: str | list[str]


@app.post("/v1/embeddings")
async def embeddings(body: EmbeddingsIn):
    texts = [body.input] if isinstance(body.input, str) else body.input
    if not texts or len(texts) > 512:
        raise ValueError("input must have 1-512 items")
    vecs = await nlp.embed(texts)
    return {"object": "list", "model": nlp.EMBEDDING_MODEL,
            "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]}


class EmotionsIn(BaseModel):
    input: list[str]


@app.post("/sow/emotions")
async def emotions(body: EmotionsIn):
    if not body.input or len(body.input) > 64:
        raise ValueError("input must have 1-64 items")
    return {"data": await nlp.emotions(body.input)}
