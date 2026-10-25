"""
TTS engines and RVC, ported from app/utils/text_to_speech.py. The desktop classes read the
character config themselves; here the client sends those values with the request, so the
service keeps no per-character state. Each engine returns (float32 mono samples, rate).
"""
import asyncio
import contextlib
import io
import os
import tempfile
from dataclasses import dataclass, field

import logging

import numpy as np
import soundfile as sf
import torch

from .models import DEVICE, manager

logger = logging.getLogger("sow_speech.tts")

DATA = os.environ.get("SOW_DATA", "/data")
VOICES_DIR = "/opt/sow/voices"
REFS_DIR = os.path.join(DATA, "voice_refs")
RVC_DIR = os.path.join(DATA, "rvc_models")

XTTS_SPEAKERS = {
    "Female Calm": "calm_female.wav",
    "Female": "female.wav",
    "Male": "male.wav",
}
# The voice lists the desktop UI offers (interface_signals.py), reported in capabilities.
KOKORO_VOICES = [
    "af_heart", "af_bella", "af_nicole", "af_aoede", "af_kore", "af_sarah", "af_nova", "am_fenrir",
    "am_michael", "am_puck", "bf_emma", "bf_isabella", "bm_fable", "bm_george", "jf_alpha",
    "jf_gongitsune", "jm_kumo", "zf_xiaobei", "zf_xiaoni", "zm_yunjian", "zm_yunxi",
]
SILERO_SPEAKERS = ["aidar", "baya", "kseniya", "xenia", "eugene"]
QWEN_PRESETS = ["Serena", "Vivian", "Aiden", "Dylan", "Eric", "Ryan", "Uncle_Fu", "Ono_Anna", "Sohee"]


class TtsError(ValueError):
    pass


@dataclass
class RvcOptions:
    model: str
    f0up_key: int = 0
    index_rate: float = 0.75
    protect: float = 0.5


@dataclass
class QwenOptions:
    mode: str = "presets"          # presets | prompt | cloning
    model_size: str = "1.7B"
    device: str = "cuda"
    prompt: str = ""
    style_instruct: str = ""
    ref: str = ""                  # sha256 of an uploaded reference clip
    ref_text: str = ""
    language: str = "English"


@dataclass
class SpeechRequest:
    engine: str
    text: str
    voice: str = ""
    language: str = "en"
    rvc: RvcOptions | None = None
    qwen: QwenOptions = field(default_factory=QwenOptions)
    load_only: bool = False        # preload: load the model, synthesise nothing


def ref_path(sha256: str) -> str:
    return os.path.join(REFS_DIR, sha256)


# --- engines -------------------------------------------------------------------------------

async def _edge(req: SpeechRequest):
    import edge_tts
    from pydub import AudioSegment

    buf = io.BytesIO()
    async for chunk in edge_tts.Communicate(req.text, req.voice).stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    if not buf.tell():
        raise TtsError("Edge TTS returned no audio")
    buf.seek(0)
    seg = AudioSegment.from_file(buf, format="mp3").set_channels(1)
    samples = np.array(seg.get_array_of_samples(), dtype=np.float32) / float(1 << (8 * seg.sample_width - 1))
    return samples, seg.frame_rate


async def _kokoro(req: SpeechRequest):
    def load():
        from kokoro import KPipeline
        return KPipeline(lang_code="a")

    slot = await manager.get("tts:kokoro", load, est_mb=500)
    if req.load_only:
        return None

    def run():
        chunks = [audio for _, _, audio in slot.obj(req.text, voice=req.voice)]
        if not chunks:
            raise TtsError("Kokoro returned no audio")
        return np.concatenate([np.asarray(c, dtype=np.float32) for c in chunks]), 24000

    async with slot.lock:
        return await asyncio.to_thread(run)


async def _silero(req: SpeechRequest):
    def load():
        model, _ = torch.hub.load(repo_or_dir="snakers4/silero-models", model="silero_tts",
                                  language="ru", speaker="v5_3_ru", trust_repo=True)
        model.to(DEVICE)
        return model

    slot = await manager.get("tts:silero", load, est_mb=300)
    if req.load_only:
        return None

    def run():
        try:
            audio = slot.obj.apply_tts(text=req.text, speaker=req.voice or "xenia", sample_rate=48000)
        except ValueError as e:
            # The Russian model reads Cyrillic only and skips Latin words.
            raise TtsError("Silero (Russian voices) cannot read this text: it has no Cyrillic letters") from e
        return audio.cpu().numpy().astype(np.float32), 48000

    async with slot.lock:
        return await asyncio.to_thread(run)


async def _xtts(req: SpeechRequest):
    speaker = XTTS_SPEAKERS.get(req.voice)
    if speaker:
        speaker = os.path.join(VOICES_DIR, speaker)
    elif req.voice and os.path.exists(ref_path(req.voice)):
        speaker = ref_path(req.voice)
    else:
        raise TtsError(f"Unknown XTTS voice: {req.voice}")
    if os.environ.get("COQUI_TOS_AGREED") != "1":
        raise TtsError("XTTSv2 is disabled: its licence (Coqui CPML) was not accepted during install")

    def load():
        from TTS.api import TTS
        return TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False).to(DEVICE)

    slot = await manager.get("tts:xtts", load, est_mb=2000, heavy=True)
    if req.load_only:
        return None

    def run():
        wav = slot.obj.tts(text=req.text, speaker_wav=speaker, language=req.language)
        return np.asarray(wav, dtype=np.float32), slot.obj.synthesizer.output_sample_rate

    async with slot.lock:
        return await asyncio.to_thread(run)


def _qwen_loader(model_name: str, device: str):
    def load():
        from qwen_tts import Qwen3TTSModel
        if device == "cuda":
            # Whole model on the GPU: device_map="auto" lets accelerate offload part of it to
            # the CPU when VRAM looks tight, and generation then fails on meta tensors.
            return Qwen3TTSModel.from_pretrained(model_name, dtype=torch.bfloat16, device_map="cuda",
                                                 attn_implementation="sdpa")
        model = Qwen3TTSModel.from_pretrained(model_name, dtype=torch.float32, device_map=None,
                                              attn_implementation="sdpa")
        _cast_float32(model)
        return model
    return load


def _cast_float32(obj, visited=None):
    """CPU fallback from the desktop code: drop accelerate hooks and cast everything to fp32."""
    visited = visited if visited is not None else set()
    if id(obj) in visited:
        return
    visited.add(id(obj))
    if isinstance(obj, torch.nn.Module):
        if hasattr(obj, "_hf_hook"):
            with contextlib.suppress(Exception):
                delattr(obj, "_hf_hook")
        with contextlib.suppress(Exception):
            obj.to(torch.float32)
        for child in obj.children():
            _cast_float32(child, visited)
    elif hasattr(obj, "__dict__"):
        for name, value in list(obj.__dict__.items()):
            if not name.startswith("__"):
                _cast_float32(value, visited)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _cast_float32(item, visited)
    elif isinstance(obj, dict):
        for value in obj.values():
            _cast_float32(value, visited)


async def _qwen3(req: SpeechRequest):
    q = req.qwen
    variant = {"prompt": "VoiceDesign", "cloning": "Base"}.get(q.mode, "CustomVoice")
    size = "1.7B" if variant == "VoiceDesign" else q.model_size
    device = "cuda" if q.device == "cuda" and DEVICE == "cuda" else "cpu"
    model_name = f"Qwen/Qwen3-TTS-12Hz-{size}-{variant}"
    if q.mode == "cloning" and not (q.ref and os.path.exists(ref_path(q.ref))):
        raise TtsError("Qwen3-TTS cloning: reference clip not uploaded")

    est = {"0.6B": 2000, "1.7B": 4500}.get(size, 4500) if device == "cuda" else 0
    slot = await manager.get(f"tts:qwen3:{size}-{variant}:{device}", _qwen_loader(model_name, device),
                             est_mb=est, heavy=True)
    if req.load_only:
        return None

    def run():
        params = {"text": req.text, "language": q.language, "max_new_tokens": 1500,
                  "temperature": 0.7, "top_p": 0.9}
        autocast = (torch.amp.autocast(device_type="cpu", enabled=False) if device == "cpu"
                    else contextlib.nullcontext())
        with torch.no_grad(), autocast:
            if q.mode == "cloning":
                if q.ref_text:
                    wavs, sr = slot.obj.generate_voice_clone(ref_audio=ref_path(q.ref), ref_text=q.ref_text, **params)
                else:
                    wavs, sr = slot.obj.generate_voice_clone(ref_audio=ref_path(q.ref), x_vector_only_mode=True, **params)
            elif q.mode == "prompt" and q.prompt:
                wavs, sr = slot.obj.generate_voice_design(instruct=q.prompt, **params)
            else:
                wavs, sr = slot.obj.generate_custom_voice(speaker=req.voice or "Serena",
                                                          instruct=q.style_instruct, **params)
        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().to(torch.float32).numpy()
        return np.asarray(audio, dtype=np.float32), sr

    async with slot.lock:
        return await asyncio.to_thread(run)


ENGINES = {"edge": _edge, "kokoro": _kokoro, "silero": _silero, "xtts": _xtts, "qwen3": _qwen3}


# --- RVC -----------------------------------------------------------------------------------

def rvc_models() -> list[str]:
    if not os.path.isdir(RVC_DIR):
        return []
    return sorted(d for d in os.listdir(RVC_DIR)
                  if any(f.endswith(".pth") for f in os.listdir(os.path.join(RVC_DIR, d))))


async def _apply_rvc(samples: np.ndarray, sr: int, opts: RvcOptions):
    if opts.model not in rvc_models():
        raise TtsError(f"RVC model not found on the server: {opts.model}")

    def load():
        from fairseq.data.dictionary import Dictionary
        from rvc_python.infer import RVCInference
        # torch >= 2.6 loads checkpoints weights-only; the hubert checkpoint pickles a fairseq
        # Dictionary (same allowance as in text_to_speech.py).
        torch.serialization.add_safe_globals([Dictionary])
        return RVCInference(models_dir=RVC_DIR, device="cuda:0" if DEVICE == "cuda" else "cpu:0")

    slot = await manager.get("rvc", load, est_mb=1200)

    def run():
        rvc = slot.obj
        if getattr(rvc, "_sow_model", None) != opts.model:
            rvc.load_model(opts.model)
            rvc._sow_model = opts.model
        # The desktop code passes these only when RVC is first created; set them every time.
        rvc.set_params(f0up_key=opts.f0up_key, index_rate=opts.index_rate, protect=opts.protect)
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.wav")
            sf.write(src, samples, sr)
            # RVCInference.infer_file, minus the file write: on failure vc_single returns
            # (traceback text, (None, None)) instead of raising.
            out = rvc.vc.vc_single(
                sid=0, input_audio_path=src, f0_up_key=rvc.f0up_key, f0_method=rvc.f0method,
                file_index=rvc.models[rvc.current_model].get("index", ""), index_rate=rvc.index_rate,
                filter_radius=rvc.filter_radius, resample_sr=rvc.resample_sr,
                rms_mix_rate=rvc.rms_mix_rate, protect=rvc.protect, f0_file="", file_index2="")
            if isinstance(out, tuple):
                logger.error("RVC failed:\n%s", out[0])
                raise TtsError(f"RVC failed: {str(out[0]).strip().splitlines()[-1]}")
            out = np.asarray(out, dtype=np.float32)
            if np.abs(out).max(initial=0) > 1.5:   # int16 range
                out /= 32768.0
            out_sr = rvc.vc.tgt_sr
        if out.ndim > 1:
            out = out.mean(axis=1)
        return out.astype(np.float32), out_sr

    async with slot.lock:
        return await asyncio.to_thread(run)


# Rates Opus accepts; anything else (RVC models output 32 or 40 kHz) is resampled up.
OPUS_RATES = (8000, 12000, 16000, 24000, 48000)


def encode(samples: np.ndarray, sr: int, fmt: str) -> tuple[bytes, int]:
    """16-bit wav, or Ogg/Opus (about a tenth of the size, for clients on a slow link)."""
    buf = io.BytesIO()
    if fmt == "opus":
        if sr not in OPUS_RATES:
            import torchaudio.functional as AF
            target = next(r for r in OPUS_RATES if r >= sr) if sr < 48000 else 48000
            samples = AF.resample(torch.from_numpy(samples), sr, target).numpy()
            sr = target
        sf.write(buf, samples, sr, format="OGG", subtype="OPUS")
    else:
        sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue(), sr


async def synthesize(req: SpeechRequest, fmt: str = "wav") -> tuple[bytes, int, float]:
    """Run the engine (and RVC if asked); return the encoded audio, its rate and duration."""
    engine = ENGINES.get(req.engine)
    if engine is None:
        raise TtsError(f"Unknown TTS engine: {req.engine}")
    if not req.text.strip():
        raise TtsError("Empty text")
    samples, sr = await engine(req)
    if req.rvc:
        samples, sr = await _apply_rvc(samples, sr, req.rvc)
    duration = len(samples) / sr
    data, sr = await asyncio.to_thread(encode, samples, sr, fmt)
    return data, sr, duration


async def preload(req: SpeechRequest):
    """Load the engine without generating, so the first sentence does not pay for it."""
    engine = ENGINES.get(req.engine)
    if engine is None:
        raise TtsError(f"Unknown TTS engine: {req.engine}")
    if req.engine != "edge":
        # No test phrase: a short word in the wrong script is rejected by Silero's Russian
        # model, for example.
        await engine(SpeechRequest(**{**req.__dict__, "rvc": None, "load_only": True}))
