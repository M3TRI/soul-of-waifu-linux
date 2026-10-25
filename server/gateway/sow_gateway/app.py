"""
Gateway: the only published port of the server stack (docs/server-api.md). Checks the
Bearer token, proxies OpenAI-style and /sow/* requests to the llama and speech services,
merges their capabilities and manages GGUF models in the shared models volume.
"""
import asyncio
import logging
import os
import re
import secrets
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

logger = logging.getLogger("sow_gateway")

TOKEN = os.environ["SOW_TOKEN"]
LLAMA_URL = os.environ.get("SOW_LLAMA_URL", "http://llama:8080")
SPEECH_URL = os.environ.get("SOW_SPEECH_URL", "http://speech:8001")
MODELS_DIR = os.environ.get("SOW_MODELS_DIR", "/models")
CATALOG = os.environ.get("SOW_CATALOG", "/opt/sow/catalog.tsv")
SERVER_VERSION = os.environ.get("SOW_SERVER_VERSION", "dev")

app = FastAPI(docs_url=None, redoc_url=None)
client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0))

HOP_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "authorization",
               "keep-alive", "upgrade", "te", "trailer", "proxy-authorization"}
GGUF_NAME_RE = re.compile(r"^[\w.+-]{1,200}\.gguf$")
HF_URL_RE = re.compile(r"^https://huggingface\.co/[\w.-]+/[\w.-]+/resolve/[\w.-]+/[\w./+-]+\.gguf$")


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.middleware("http")
async def auth(request: Request, call_next):
    if request.url.path == "/sow/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    given = header[7:] if header.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(given.encode(), TOKEN.encode()):
        return error(401, "unauthorized", "Missing or wrong token")
    return await call_next(request)


async def proxy(request: Request, base: str, path: str | None = None) -> Response:
    """Stream the request to base+path and the answer back (SSE and uploads included)."""
    url = base + (path or request.url.path)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    upstream = client.build_request(request.method, url, params=request.query_params,
                                    headers=headers, content=request.stream())
    try:
        resp = await client.send(upstream, stream=True)
    except httpx.TransportError as e:
        service = "llama" if base == LLAMA_URL else "speech"
        return error(503, "engine_unavailable", f"{service} service is not reachable: {e}")
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_HEADERS}
    return StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, headers=out_headers,
                             background=BackgroundTask(resp.aclose))


# --- service -------------------------------------------------------------------------------

@app.get("/sow/health")
async def health():
    return {"status": "ok", "api_version": 1}


async def _get_json(url: str):
    try:
        r = await client.get(url, timeout=5.0)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


async def _llm_state() -> dict:
    data = await _get_json(f"{LLAMA_URL}/models")
    if data is None:
        return {"available": False, "reason": "llama service is not reachable", "models": []}
    models = [m["id"] for m in data.get("data", [])]
    loaded = next((m["id"] for m in data.get("data", []) if m.get("status", {}).get("value") == "loaded"), None)
    return {"available": bool(models), "models": models, "loaded": loaded,
            **({} if models else {"reason": "no GGUF model on the server"})}


@app.get("/sow/capabilities")
async def capabilities():
    speech, llm = await asyncio.gather(_get_json(f"{SPEECH_URL}/sow/speech/capabilities"), _llm_state())
    caps = {"api_version": 1, "server_version": SERVER_VERSION, "llm": llm}
    if speech is None:
        off = {"available": False, "reason": "speech service is not reachable"}
        caps.update({"gpu": {"backend": "unknown"}, "tts": [], "rvc": off, "stt": off,
                     "embeddings": off, "emotions": off})
    else:
        caps.update(speech)
    return caps


@app.get("/sow/status")
async def status():
    speech, llm = await asyncio.gather(_get_json(f"{SPEECH_URL}/sow/speech/status"), _llm_state())
    return {"gpu": (speech or {}).get("gpu"), "loaded": (speech or {}).get("loaded", []),
            "llm": {"loaded": llm.get("loaded")}}


# --- LLM -----------------------------------------------------------------------------------

@app.api_route("/v1/chat/completions", methods=["POST"])
@app.api_route("/v1/completions", methods=["POST"])
@app.api_route("/v1/models", methods=["GET"])
async def llm_proxy(request: Request):
    return await proxy(request, LLAMA_URL)


def _local_models() -> list[dict]:
    if not os.path.isdir(MODELS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(MODELS_DIR)):
        if name.endswith(".gguf") and "mmproj" not in name.lower():
            out.append({"file": name, "id": name[:-5],
                        "size_mb": os.path.getsize(os.path.join(MODELS_DIR, name)) // 2**20})
    return out


@app.get("/sow/llm/models")
async def llm_models():
    state = await _llm_state()
    return {"models": [{**m, "loaded": m["id"] == state.get("loaded")} for m in _local_models()]}


@app.post("/sow/llm/load")
async def llm_load(request: Request):
    body = await request.json()
    model = str(body.get("model", ""))
    if model not in {m["id"] for m in _local_models()}:
        return error(404, "model_missing", f"No such model on the server: {model}")
    # Router mode keeps one model at a time (--models-max 1) and swaps on load.
    r = await client.post(f"{LLAMA_URL}/models/load", json={"model": model})
    return Response(r.content, status_code=r.status_code, media_type="application/json")


def read_catalog() -> list[dict]:
    """Model catalog shared with the installer: tab-separated, '#' comments."""
    rows = []
    try:
        with open(CATALOG, encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.startswith("#"):
                    continue
                cid, name, size_mb, vram_mb, url, sha256, note, note_ru = line.rstrip("\n").split("\t")
                rows.append({"id": cid, "name": name, "size_mb": int(size_mb), "vram_mb": int(vram_mb),
                             "url": url, "sha256": sha256, "note": note, "note_ru": note_ru})
    except FileNotFoundError:
        pass
    return rows


@app.get("/sow/llm/catalog")
async def llm_catalog():
    return {"models": read_catalog()}


JOBS: dict[str, dict] = {}


async def _download(job: dict, url: str, dest: str, sha256: str | None):
    import hashlib
    part = dest + ".part"
    try:
        digest = hashlib.sha256()
        async with client.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(60.0)) as r:
            r.raise_for_status()
            job["total"] = int(r.headers.get("content-length", 0))
            with open(part, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    f.write(chunk)
                    digest.update(chunk)
                    job["done"] += len(chunk)
        if sha256 and digest.hexdigest() != sha256:
            raise ValueError("sha256 mismatch")
        os.replace(part, dest)
        job["status"] = "done"
    except asyncio.CancelledError:
        job["status"] = "cancelled"
        if os.path.exists(part):
            os.remove(part)
    except Exception as e:
        job.update(status="failed", error=f"{type(e).__name__}: {e}")
        if os.path.exists(part):
            os.remove(part)


@app.post("/sow/llm/download")
async def llm_download(request: Request):
    body = await request.json()
    sha256 = None
    if body.get("catalog_id"):
        entry = next((m for m in read_catalog() if m["id"] == body["catalog_id"]), None)
        if entry is None:
            return error(404, "model_missing", "No such catalog entry")
        url, sha256 = entry["url"], entry["sha256"] or None
    else:
        url = str(body.get("url", ""))
        if not HF_URL_RE.match(url):
            return error(400, "bad_request", "Only huggingface.co .../resolve/... .gguf URLs are allowed")
    name = url.rsplit("/", 1)[-1]
    if not GGUF_NAME_RE.match(name):
        return error(400, "bad_request", f"Bad file name: {name}")
    dest = os.path.join(MODELS_DIR, name)
    if os.path.exists(dest):
        return error(409, "bad_request", f"{name} is already on the server")
    if any(j["file"] == name and j["status"] == "running" for j in JOBS.values()):
        return error(409, "busy", f"{name} is already downloading")
    job_id = uuid.uuid4().hex
    job = JOBS[job_id] = {"id": job_id, "file": name, "status": "running", "done": 0, "total": 0,
                          "started": time.time()}
    job["task"] = asyncio.create_task(_download(job, url, dest, sha256))
    return {"job": job_id}


@app.delete("/sow/jobs/{job_id}")
async def job_cancel(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        return error(404, "not_found", "No such job")
    if job["status"] == "running":
        job["task"].cancel()
    return {"status": "ok"}


@app.get("/sow/jobs/{job_id}")
async def job_status(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        return error(404, "not_found", "No such job")
    return {k: v for k, v in job.items() if k != "task"}


# --- speech --------------------------------------------------------------------------------

@app.api_route("/v1/audio/{rest:path}", methods=["POST"])
@app.api_route("/v1/embeddings", methods=["POST"])
@app.api_route("/sow/emotions", methods=["POST"])
@app.api_route("/sow/tts/{rest:path}", methods=["POST"])
@app.api_route("/sow/voices/{rest:path}", methods=["HEAD", "PUT"])
@app.api_route("/sow/rvc/{rest:path}", methods=["GET", "PUT", "DELETE"])
async def speech_proxy(request: Request, rest: str = ""):
    return await proxy(request, SPEECH_URL)
