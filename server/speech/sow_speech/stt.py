"""Whisper STT (faster-whisper), ported from app/utils/speech_to_text.STTWorker."""
import asyncio
import io


from .models import DEVICE, manager

MODELS = ["small", "medium", "large-v3-turbo"]
EST_MB = {"small": 700, "medium": 1800, "large-v3-turbo": 1800}


async def transcribe(audio: bytes, model: str = "small", language: str | None = None) -> str:
    if model not in MODELS:
        raise ValueError(f"Unknown Whisper model: {model}")

    def load():
        from faster_whisper import WhisperModel
        if DEVICE == "cuda":
            return WhisperModel(model, device="cuda", compute_type="float16")
        return WhisperModel(model, device="cpu", compute_type="int8")

    # STT is used for every utterance; keep it loaded rather than reloading after TTS.
    slot = await manager.get(f"stt:{model}", load, est_mb=EST_MB[model] if DEVICE == "cuda" else 0,
                             pinned=True)

    def run():
        from faster_whisper.audio import decode_audio
        # PyAV decodes any container: wav from the desktop client, webm/ogg from the browser.
        samples = decode_audio(io.BytesIO(audio), sampling_rate=16000)
        segments, _info = slot.obj.transcribe(samples, beam_size=5, language=language)
        return "".join(s.text for s in segments).strip()

    async with slot.lock:
        return await asyncio.to_thread(run)
