"""
Client side of the Soul of Waifu server (docs/server-api.md): TTS, STT, embeddings, emotions
and status go to the server stack instead of running in this process, so the app itself
needs no torch or CUDA.

Connection settings: main_settings.server_url and server_cert_sha256, token in api.json as
SOW_SERVER_TOKEN. A pairing string (sow://host:port#token=...&fp=...) fills all three.
"""
import asyncio
import hashlib
import logging
import os
import ssl
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import numpy as np

from app.configuration import configuration

logger = logging.getLogger("SoW Server")

DEFAULT_URL = "http://127.0.0.1:8765"
TOKEN_KEY = "SOW_SERVER_TOKEN"
CAPS_TTL = 30.0


class ServerError(RuntimeError):
    """An error answer from the server; code is one of docs/server-api.md's error codes."""

    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


def parse_pairing(text: str) -> tuple[str, str, str]:
    """sow://host:port#token=T&fp=F -> (base url, token, fingerprint or "")."""
    text = (text or "").strip()
    parts = urlsplit(text)
    if parts.scheme != "sow" or not parts.hostname:
        raise ValueError("Not a pairing string (expected sow://host:port#token=...)")
    params = parse_qs(parts.fragment)
    token = params.get("token", [""])[0]
    fp = params.get("fp", [""])[0].lower()
    if not token:
        raise ValueError("The pairing string has no token")
    scheme = "https" if fp else "http"
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{scheme}://{host}:{parts.port or 8765}", token, fp


def save_pairing(text: str):
    url, token, fp = parse_pairing(text)
    settings = configuration.ConfigurationSettings()
    settings.update_main_setting("server_url", url)
    settings.update_main_setting("server_cert_sha256", fp)
    configuration.ConfigurationAPI().save_api_token(TOKEN_KEY, token)
    # The Local LLM provider talks to the same gateway.
    settings.update_main_setting("local_llm_external", True)
    settings.update_main_setting("local_llm_base_url", f"{url}/v1")
    configuration.ConfigurationAPI().save_api_token("LOCAL_LLM_API_TOKEN", token)
    reset()


def _pinned_context(base_url: str, expected: str) -> ssl.SSLContext:
    """
    TLS context that trusts only the server's own self-signed certificate. The certificate
    is fetched in a separate handshake and checked against the pinned fingerprint before any
    request (and so the token) is sent.
    """
    parts = urlsplit(base_url)
    pem = ssl.get_server_certificate((parts.hostname, parts.port or 443), timeout=5)
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() != expected:
        raise ServerError("unauthorized", "The server's certificate does not match the pairing "
                                          "(pair again if the server was reinstalled)")
    ctx = ssl.create_default_context(cadata=pem)
    ctx.check_hostname = False   # the certificate itself is pinned; the address may be any alias
    return ctx


class _Connection:
    def __init__(self):
        settings = configuration.ConfigurationSettings()
        self.base_url = (settings.get_main_setting("server_url") or DEFAULT_URL).rstrip("/")
        self.fingerprint = (settings.get_main_setting("server_cert_sha256") or "").lower()
        self.token = (configuration.ConfigurationAPI().get_token(TOKEN_KEY) or "").strip()
        self._caps = None
        self._caps_at = 0.0
        self._ssl = None

    def _kwargs(self, timeout: float) -> dict:
        kw = {"base_url": self.base_url, "timeout": httpx.Timeout(timeout, connect=5.0),
              "headers": {"Authorization": f"Bearer {self.token}"}}
        if self.base_url.startswith("https://") and self.fingerprint:
            if self._ssl is None:
                self._ssl = _pinned_context(self.base_url, self.fingerprint)
            kw["verify"] = self._ssl
        return kw

    def client(self, timeout: float = 120.0) -> httpx.Client:
        return httpx.Client(**self._kwargs(timeout))

    def async_client(self, timeout: float = 120.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(**self._kwargs(timeout))


_conn = None
_conn_lock = threading.Lock()


def connection() -> _Connection:
    global _conn
    with _conn_lock:
        if _conn is None:
            _conn = _Connection()
        return _conn


def reset():
    """Forget cached settings and capabilities (after the connection settings change)."""
    global _conn
    with _conn_lock:
        _conn = None


def _raise_for(r: httpx.Response):
    if r.status_code < 400:
        return
    try:
        err = r.json()["error"]
        code = err.get("code", "internal")
        raise ServerError(code, err.get("message") or f"{code} (HTTP {r.status_code})", r.status_code)
    except (ValueError, KeyError, TypeError):
        raise ServerError("internal", f"HTTP {r.status_code}: {r.text[:200]}", r.status_code)


# --- service -------------------------------------------------------------------------------

def capabilities(force: bool = False) -> dict | None:
    """Server capabilities, cached for CAPS_TTL seconds; None when the server is offline."""
    conn = connection()
    if not force and conn._caps is not None and time.monotonic() - conn._caps_at < CAPS_TTL:
        return conn._caps
    try:
        with conn.client(timeout=5.0) as c:
            r = c.get("/sow/capabilities")
            _raise_for(r)
            conn._caps = r.json()
    except (httpx.HTTPError, ServerError) as e:
        logger.warning(f"Server not available at {conn.base_url}: {e}")
        conn._caps = None
    conn._caps_at = time.monotonic()
    return conn._caps


def status() -> dict | None:
    try:
        with connection().client(timeout=5.0) as c:
            r = c.get("/sow/status")
            _raise_for(r)
            return r.json()
    except (httpx.HTTPError, ServerError):
        return None


def gpu_info() -> dict | None:
    """{"name", "vram_total_mb", ...} of the server's GPU, None without one or offline."""
    st = status()
    gpu = (st or {}).get("gpu") or {}
    return gpu if gpu.get("backend") == "cuda" else None


# --- TTS -----------------------------------------------------------------------------------

async def upload_ref(path: str) -> str:
    """Make a reference clip available on the server; returns its id (sha256)."""
    with open(path, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    async with connection().async_client() as c:
        r = await c.head(f"/sow/voices/refs/{sha}")
        if r.status_code == 404:
            r = await c.put(f"/sow/voices/refs/{sha}", content=data)
        _raise_for(r)
    return sha


async def ensure_rvc_model(rvc_file: str) -> str:
    """Upload a local RVC model (.pth plus the .index next to it) unless the server has it."""
    name = os.path.splitext(os.path.basename(rvc_file))[0]
    async with connection().async_client(timeout=600.0) as c:
        r = await c.get("/sow/rvc/models")
        _raise_for(r)
        if name in r.json().get("models", []):
            return name
        folder = os.path.dirname(rvc_file)
        index = next((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".index")), None)
        files = {"pth": open(rvc_file, "rb")}
        if index:
            files["index"] = open(index, "rb")
        try:
            r = await c.put(f"/sow/rvc/models/{name}", files=files)
        finally:
            for f in files.values():
                f.close()
        _raise_for(r)
    return name


async def speech(engine: str, text: str, voice: str = "", options: dict | None = None) -> tuple[bytes, int]:
    """POST /v1/audio/speech; returns (wav bytes, sample rate)."""
    body = {"model": engine, "input": text, "voice": voice or "", "response_format": "wav",
            "sow": options or {}}
    async with connection().async_client(timeout=300.0) as c:
        r = await c.post("/v1/audio/speech", json=body)
        _raise_for(r)
        return r.content, int(r.headers.get("x-sow-sample-rate", "0") or 0)


async def preload_tts(engine: str, voice: str = "", options: dict | None = None):
    body = {"model": engine, "input": "", "voice": voice or "", "sow": options or {}}
    async with connection().async_client(timeout=900.0) as c:
        _raise_for(await c.post("/sow/tts/preload", json=body))


# --- STT, embeddings, emotions -------------------------------------------------------------

def transcribe(wav: bytes, model: str = "small", language: str | None = None) -> str:
    data = {"model": model}
    if language:
        data["language"] = language
    with connection().client(timeout=120.0) as c:
        r = c.post("/v1/audio/transcriptions", files={"file": ("speech.wav", wav, "audio/wav")}, data=data)
        _raise_for(r)
        return r.json().get("text", "")


def embed(texts: list[str]) -> np.ndarray:
    with connection().client(timeout=60.0) as c:
        r = c.post("/v1/embeddings", json={"input": texts})
        _raise_for(r)
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return np.asarray([d["embedding"] for d in data], dtype=np.float32)


async def emotions(texts: list[str]) -> list[dict]:
    async with connection().async_client(timeout=30.0) as c:
        r = await c.post("/sow/emotions", json={"input": texts})
        _raise_for(r)
        return r.json()["data"]


def run_sync(coro):
    """Run a coroutine of this module from a worker thread that has no event loop."""
    return asyncio.run(coro)
