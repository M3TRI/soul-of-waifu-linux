import os
import io
import re
import uuid
import queue
import time
import shutil
import asyncio
import logging
import threading
import numpy as np
import soundfile as sf
import sounddevice as sd
from typing import Optional

from pydub import AudioSegment
from elevenlabs.client import AsyncElevenLabs

from PyQt6.QtCore import QThread, pyqtSignal

from app.configuration import configuration
from app.utils import audio_output, sow_server

logger = logging.getLogger("Text-To-Speech Module")


class ElevenLabs:
    def __init__(self):
        self.configuration_settings = configuration.ConfigurationSettings()
        self.configuration_api = configuration.ConfigurationAPI()
        self.configuration_characters = configuration.ConfigurationCharacters()

        self.audio_cache = AudioSegment.empty()
        self.device_index = self.configuration_settings.get_main_setting("output_device_real_index")
        self.output_dir = "app/voices/elevenlabs_audio"
        os.makedirs(self.output_dir, exist_ok=True)

    async def generate_speech_with_elevenlabs(self, text, voice_id):
        try:
            self.eleven_labs_api = self.configuration_api.get_token("ELEVENLABS_API_TOKEN")
            self.eleven = AsyncElevenLabs(api_key=self.eleven_labs_api)

            audio_stream = await self.eleven.generate(
                text=text,
                voice=voice_id,
                model="eleven_multilingual_v2",
                stream=True
            )
            audio_data = b""
            async for chunk in audio_stream:
                audio_data += chunk

            audio_stream_io = io.BytesIO(audio_data)
            new_audio = await asyncio.to_thread(AudioSegment.from_file, audio_stream_io, format="mp3")
            self.audio_cache += new_audio
            await self.play_audio(new_audio)
        except Exception as e:
            logger.error(f"Error: {e}")

    async def generate_speech_with_elevenlabs_sow_system(self, text, voice_id):
        try:
            self.eleven_labs_api = self.configuration_api.get_token("ELEVENLABS_API_TOKEN")
            self.eleven = AsyncElevenLabs(api_key=self.eleven_labs_api)

            audio_stream = await self.eleven.generate(
                text=text,
                voice=voice_id,
                model="eleven_multilingual_v2",
                stream=True
            )
            audio_data = b""
            async for chunk in audio_stream:
                audio_data += chunk

            audio_stream_io = io.BytesIO(audio_data)
            new_audio = await asyncio.to_thread(AudioSegment.from_file, audio_stream_io, format="mp3")

            unique_id = uuid.uuid4().hex
            output_file = os.path.join(self.output_dir, f"output_{unique_id}.wav")
            await asyncio.to_thread(new_audio.export, output_file, format="wav")
            return output_file
        except Exception as e:
            logger.error(f"ElevenLabs Error: {e}")
            return None

    async def play_audio(self, audio):
        try:
            samples = np.array(audio.get_array_of_samples())
            sample_rate = audio.frame_rate
            sd.default.device = self.device_index
            await asyncio.to_thread(audio_output.play, samples, sample_rate)
            await asyncio.to_thread(sd.wait)
        except Exception as e:
            logger.error(f"Error: {e}")

    def clear_audio_cache(self):
        self.audio_cache = AudioSegment.empty()


# Engines whose synthesis of a long sentence takes longer than the listener should wait for the
# first sound (Qwen3-TTS runs at about 0.8x real time on an RTX 5060 Ti).
SLOW_TTS_METHODS = ("Qwen-3 TTS", "XTTSv2")


def split_clauses(text, min_len=30):
    """
    Split a sentence at its clause marks into pieces of at least min_len characters. When
    nothing is playing, a slow engine then synthesises the first clause and each next one while
    the previous plays (each takes less time than the previous one sounds), instead of keeping
    the listener waiting for the whole sentence: on Qwen3-TTS the first sound of a 230-character
    sentence comes after 2.8 s instead of 12.9 s.
    """
    pieces, start = [], 0
    for m in re.finditer(r'[,;:]\s+|\s+[—–-]\s+', text):
        if m.end() - start >= min_len and len(text) - m.end() >= min_len:
            pieces.append(text[start:m.end()].strip())
            start = m.end()
    pieces.append(text[start:].strip())
    return pieces


class _ServerEngine:
    """
    Base of the TTS engines that run on the Soul of Waifu server (server/speech). Each engine
    reads the character config as the in-process engines did, sends the values with the
    request, and writes the returned wav to the same local folder, so the workers, lip sync
    and replay code are unchanged.
    """
    engine = ""
    output_dir = ""
    prefix = "output"

    def __init__(self):
        self.configuration_settings = configuration.ConfigurationSettings()
        self.configuration_api = configuration.ConfigurationAPI()
        self.configuration_characters = configuration.ConfigurationCharacters()
        self.device_index = self.configuration_settings.get_main_setting("output_device_real_index")
        self.tts_loaded = False
        os.makedirs(self.output_dir, exist_ok=True)

    def _char_config(self, character_name):
        configuration_data = self.configuration_characters.load_configuration()
        return configuration_data["character_list"][character_name]

    async def _rvc_options(self, char_config):
        rvc_file = char_config.get("rvc_file")
        if not (char_config.get("rvc_enabled") and rvc_file):
            return None
        if not os.path.isabs(rvc_file) and not os.path.exists(rvc_file):
            rvc_file = os.path.join("assets", "rvc_models", rvc_file)
        name = await sow_server.ensure_rvc_model(rvc_file)
        return {
            "model": name,
            "f0up_key": char_config.get("rvc_f0up_key", 0),
            "index_rate": char_config.get("rvc_index_rate", 0.75),
            "protect": char_config.get("rvc_protect", 0.5),
        }

    async def _synthesize(self, text, voice, options):
        try:
            wav, _rate = await sow_server.speech(self.engine, text, voice, options)
        except sow_server.ServerError as e:
            if e.code == "out_of_vram":
                raise RuntimeError(f"{self.engine} TTS: not enough video memory on the server ({e})") from e
            raise RuntimeError(f"{self.engine} TTS on the server failed: {e}") from e
        self.tts_loaded = True
        output_file = os.path.join(self.output_dir, f"{self.prefix}_{uuid.uuid4().hex}.wav")
        await asyncio.to_thread(self._write, output_file, wav)
        return output_file

    @staticmethod
    def _write(path, data):
        with open(path, "wb") as f:
            f.write(data)

    async def _preload(self, voice="", options=None):
        try:
            await sow_server.preload_tts(self.engine, voice, options)
            self.tts_loaded = True
        except sow_server.ServerError as e:
            raise RuntimeError(f"Failed to load {self.engine} TTS on the server: {e}") from e

    async def play_audio(self, file_path):
        def _play():
            try:
                data, samplerate = sf.read(file_path, dtype='float32')
                sd.default.device = self.device_index
                audio_output.play(data, samplerate)
                sd.wait()
            except Exception as e:
                logger.error(f"Error: {e}")
        await asyncio.to_thread(_play)

    def stop_audio(self):
        sd.stop()


class XTTSv2_SOW_System(_ServerEngine):
    engine = "xtts"
    output_dir = "app/voices/xttsv2_audio"

    def _load_tts_sync(self):
        if not self.tts_loaded:
            sow_server.run_sync(self._preload("Female"))

    async def generate_speech_with_xttsv2_sow_system(self, text=None, language=None, character_name=None):
        char_config = self._char_config(character_name)
        options = {"language": language or "en", "rvc": await self._rvc_options(char_config)}
        return await self._synthesize(text, char_config["voice_type"], options)


class EdgeTTS(_ServerEngine):
    engine = "edge"
    output_dir = "app/voices/edge_tts_audio"

    async def _generate_base(self, text, character_name):
        char_config = self._char_config(character_name)
        try:
            options = {"rvc": await self._rvc_options(char_config)}
            return await self._synthesize(text, char_config["voice_type"], options)
        except Exception as e:
            logger.error(f"Error when generating EdgeTTS audio: {e}")
            return None

    async def generate_speech_with_edge_tts(self, text, character_name):
        output_file = await self._generate_base(text, character_name)
        if output_file:
            await self.play_audio(file_path=output_file)

    async def generate_speech_with_edge_tts_sow_system(self, text, character_name):
        return await self._generate_base(text, character_name)


class KokoroTTS_SOW_System(_ServerEngine):
    engine = "kokoro"
    output_dir = "app/voices/kokoro_audio"
    prefix = "kokoro_output"

    async def _load_tts(self):
        if not self.tts_loaded:
            await self._preload("af_heart")

    async def generate_speech_with_kokoro(self, text, character_name):
        char_config = self._char_config(character_name)
        options = {"rvc": await self._rvc_options(char_config)}
        return await self._synthesize(text, char_config["voice_type"], options)


class SileroTTS_SOW_System(_ServerEngine):
    engine = "silero"
    output_dir = "app/voices/silero_audio"
    prefix = "silero_output"

    async def _load_tts(self):
        if not self.tts_loaded:
            await self._preload("xenia")

    async def generate_speech_with_silero(self, text, character_name):
        char_config = self._char_config(character_name)
        options = {"rvc": await self._rvc_options(char_config)}
        return await self._synthesize(text, char_config.get("voice_type", "xenia"), options)


class Qwen3TTS_SOW_System(_ServerEngine):
    engine = "qwen3"
    output_dir = "app/voices/qwen_audio"
    prefix = "qwen_output"

    def __init__(self):
        super().__init__()
        self._refs = {}   # (path, mtime) -> id of the clip uploaded to the server

    async def _qwen_options(self, char_config):
        ref_path = char_config.get("qwen_cloning_ref_path", "")
        ref = ""
        if char_config.get("qwen_mode") == "cloning" and ref_path and os.path.exists(ref_path):
            key = (ref_path, os.path.getmtime(ref_path))
            if key not in self._refs:
                self._refs[key] = await sow_server.upload_ref(ref_path)
            ref = self._refs[key]
        return {
            "mode": char_config.get("qwen_mode", "presets"),
            "model_size": char_config.get("qwen_model_size", "1.7B"),
            "device": char_config.get("qwen_device", "cpu"),
            "prompt": char_config.get("qwen_prompt", ""),
            "style_instruct": char_config.get("qwen_style_instruct", ""),
            "ref": ref,
            "ref_text": char_config.get("qwen_cloning_ref_text", ""),
            "language": char_config.get("qwen_language", "English"),
        }

    async def _load_tts(self, character_name: str):
        if not self.tts_loaded:
            char_config = self._char_config(character_name)
            await self._preload(char_config.get("voice_type", "Serena"),
                                {"qwen": await self._qwen_options(char_config)})

    async def generate_speech_with_qwen3(self, text: str, character_name: str):
        char_config = self._char_config(character_name)
        options = {"qwen": await self._qwen_options(char_config), "rvc": await self._rvc_options(char_config)}
        return await self._synthesize(text, char_config.get("voice_type", "Serena"), options)


class AudioPlaybackWorker(QThread):
    queue_empty_signal = pyqtSignal()
    lipsync_signal = pyqtSignal(float)

    def __init__(self, device_index):
        super().__init__()
        self.queue = queue.Queue()
        self.is_running = True
        self.device_index = device_index
        self.interrupt_flag = False
        self.playing = False

    def add_audio_file(self, file_path, persist=False):
        self.interrupt_flag = False
        self.queue.put((file_path, persist))

    def clear_queue(self):
        self.interrupt_flag = True
        with self.queue.mutex:
            for item in list(self.queue.queue):
                file_path, persist = item if isinstance(item, tuple) else (item, False)
                if persist:
                    continue
                try:
                    if file_path and os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    pass
            self.queue.queue.clear()

    def run(self):
        logger.info("Audio Playback Worker Started")
        while self.is_running:
            try:
                item = self.queue.get(timeout=0.1)

                if item is None:
                    self.queue.task_done()
                    continue

                file_path, persist = item if isinstance(item, tuple) else (item, False)

                if self.interrupt_flag:
                    if not persist:
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except Exception:
                            pass
                    self.queue.task_done()
                    continue

                self.playing = True
                try:
                    data, samplerate = sf.read(file_path, dtype='float32')
                    sd.default.device = self.device_index
                    audio_output.play(data, samplerate)

                    duration = len(data) / samplerate
                    chunk_size = int(samplerate * 0.05)
                    slept = 0

                    while slept < duration:
                        if self.interrupt_flag:
                            sd.stop()
                            self.lipsync_signal.emit(0.0)
                            break

                        start_idx = int(slept * samplerate)
                        end_idx = min(start_idx + chunk_size, len(data))
                        current_chunk = data[start_idx:end_idx]

                        if len(current_chunk) > 0:
                            rms = np.sqrt(np.mean(current_chunk ** 2))
                            mouth_open = min(rms * 5.0, 1.0)
                            self.lipsync_signal.emit(float(mouth_open))

                        time.sleep(0.05)
                        slept += 0.05

                    self.lipsync_signal.emit(0.0)

                except Exception as e:
                    logger.error(f"Playback error: {e}")

                finally:
                    self.playing = False
                    if not persist:
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except Exception:
                            pass

                self.queue.task_done()

                if self.queue.empty() and not self.interrupt_flag:
                    self.queue_empty_signal.emit()

            except queue.Empty:
                continue

    def stop(self):
        self.is_running = False
        self.interrupt_flag = True
        try:
            sd.stop()
        except Exception:
            pass
        self.queue.put(None)
        self.quit()
        self.wait()


# Workers stopped with retire() stay referenced here until their thread has finished.
_RETIRED_WORKERS = set()


class TTSWorker(QThread):
    audio_ready_signal = pyqtSignal(str)
    segment_saved_signal = pyqtSignal(str, str)

    def __init__(self, tts_method, character_name, voice_id=None, language="en"):
        super().__init__()
        self.queue = queue.Queue()
        self.is_running = True
        self.discard_current = False

        self.tts_method = tts_method
        self.character_name = character_name
        self.voice_id = voice_id
        self.language = language

        self.configuration_settings = configuration.ConfigurationSettings()
        self.configuration_api = configuration.ConfigurationAPI()
        self.configuration_characters = configuration.ConfigurationCharacters()

        self.device_index = self.configuration_settings.get_main_setting("output_device_real_index")

        self.tts_mode = self.configuration_settings.get_main_setting("tts_voicing_mode") or 0
        self.tts_custom_regex = self.configuration_settings.get_main_setting("tts_custom_regex") or ""

        self._in_tts_quote = False
        self._in_asterisk = False

        self.xtts = XTTSv2_SOW_System()
        self.edge = EdgeTTS()
        self.kokoro = KokoroTTS_SOW_System()
        self.silero = SileroTTS_SOW_System()
        self.qwen = Qwen3TTS_SOW_System()
        self.eleven = ElevenLabs()

        self._generating = False

        self.playback_worker = AudioPlaybackWorker(self.device_index)
        self.playback_worker.start()

    def _idle(self):
        """Nothing queued, being synthesised or playing: the next sentence is heard only when done."""
        return (not self._generating and self.queue.empty()
                and self.playback_worker.queue.empty() and not self.playback_worker.playing)

    def add_text(self, text, message_id=None):
        if not text:
            return
            
        text = self.clean_text_for_speech(text)
        if not text:
            return

        raw_sentences = re.split(r'(?<=[.!?])\s+', text)
        current_chunk = ""
        max_chunk_len = 450 
        split_lead = self.tts_method in SLOW_TTS_METHODS and self._idle()
        
        def _enqueue(chunk_text):
            nonlocal split_lead
            if chunk_text:
                pieces = split_clauses(chunk_text) if split_lead else [chunk_text]
                split_lead = False
                for piece in pieces:
                    self.queue.put((piece, message_id))

        for sentence in raw_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            if len(sentence) > max_chunk_len:
                if current_chunk:
                    _enqueue(current_chunk)
                    current_chunk = ""
                
                sub_chunks = re.split(r'(?<=[,;])\s', sentence)
                for sub in sub_chunks:
                    sub = sub.strip()
                    if len(sub) > max_chunk_len:
                        for i in range(0, len(sub), max_chunk_len):
                            _enqueue(sub[i:i+max_chunk_len])
                    else:
                        _enqueue(sub)
            else:
                if len(current_chunk) + len(sentence) + 1 > max_chunk_len:
                    _enqueue(current_chunk)
                    current_chunk = sentence
                else:
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence
        
        if current_chunk:
            _enqueue(current_chunk)

    def _persist_segment_for_replay(self, source_file, message_id):
        if not source_file or not os.path.exists(source_file):
            return None

        segment_dir = os.path.join(
            os.getcwd(), "app", "data", ".soul", self.character_name, "tts_audio", message_id
        )
        os.makedirs(segment_dir, exist_ok=True)

        existing = [f for f in os.listdir(segment_dir) if f.lower().endswith((".wav", ".mp3"))]
        next_index = len(existing) + 1
        ext = os.path.splitext(source_file)[1] or ".wav"
        segment_filename = f"seg_{next_index:04d}{ext}"
        destination = os.path.join(segment_dir, segment_filename)

        shutil.copyfile(source_file, destination)

        return f"tts_audio/{message_id}/{segment_filename}"

    def clean_text_for_speech(self, text: str) -> str:
        if not text:
            return ""

        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"https?://\S+|www\.\S+", "", text)

        mode = self.tts_mode
        regex = self.tts_custom_regex

        # --- Mode 0: Voice Everything ---
        if mode == 0:
            return re.sub(r"[*_~`#]", "", text).strip()

        # --- Mode 1: Voice Only Quotes ---
        elif mode == 1:
            result = []
            parts = re.split(r'(["“”«»])', text)
            for part in parts:
                if part in ('"', "“", "”", "«", "»"):
                    self._in_tts_quote = not self._in_tts_quote
                    if not self._in_tts_quote:
                        result.append(" ")
                    continue
                if self._in_tts_quote:
                    result.append(part)
            return re.sub(r"[*_~`#]", "", "".join(result)).strip()

        # --- Mode 2: Ignore Asterisks ---
        elif mode == 2:
            result = []
            parts = re.split(r"(\*|_)", text)
            for part in parts:
                if part in ("*", "_"):
                    self._in_asterisk = not self._in_asterisk
                    if not self._in_asterisk:
                        result.append(" ")
                    continue
                if not self._in_asterisk:
                    result.append(part)
            return re.sub(r"[*_~`#]", "", "".join(result)).strip()

        # --- Mode 3: Voice Outside Quotes ---
        elif mode == 3:
            result = []
            parts = re.split(r'(["“”«»])', text)
            for part in parts:
                if part in ('"', "“", "”", "«", "»"):
                    if part in ("“", "«"):
                        self._in_tts_quote = True
                    elif part in ("”", "»"):
                        self._in_tts_quote = False
                    else:
                        self._in_tts_quote = not self._in_tts_quote

                    if not self._in_tts_quote:
                        result.append(" ")
                    continue

                if not self._in_tts_quote:
                    result.append(part)

            return re.sub(r"[*_~`#]", "", "".join(result)).strip()

        # --- Mode 4: Custom Regex ---
        elif mode == 4:
            if not regex:
                return re.sub(r"[*_~`#]", "", text).strip()
            try:
                matches = re.findall(regex, text)
                if matches:
                    extracted = []
                    for m in matches:
                        if isinstance(m, tuple):
                            val = next((g for g in m if g), "")
                            extracted.append(val)
                        else:
                            extracted.append(m)
                    return " ".join(extracted).strip()
                return ""
            except re.error:
                return re.sub(r"[*_~`#]", "", text).strip()

        return text.strip()
    
    def clear_queue(self):
        with self.queue.mutex:
            self.queue.queue.clear()
        self.discard_current = True
        self._in_tts_quote = False
        self._in_asterisk = False
        if hasattr(self, 'playback_worker'):
            self.playback_worker.clear_queue()

    def run(self):
        logger.info(f"TTS Worker Started ({self.tts_method})")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while self.is_running:
            try:
                item = self.queue.get(timeout=0.5)

                if item is None:
                    self.queue.task_done()
                    continue

                text, message_id = item if isinstance(item, tuple) else (item, None)

                if text:
                    self.discard_current = False
                    self._generating = True
                    logger.info(f"Generating Audio for: {text[:30]}...")
                    output_file = None

                    if self.tts_method == "XTTSv2":
                        output_file = loop.run_until_complete(
                            self.xtts.generate_speech_with_xttsv2_sow_system(text, self.language, self.character_name)
                        )
                    elif self.tts_method == "Edge TTS":
                        output_file = loop.run_until_complete(
                            self.edge.generate_speech_with_edge_tts_sow_system(text, self.character_name)
                        )
                    elif self.tts_method == "Kokoro":
                        output_file = loop.run_until_complete(
                            self.kokoro.generate_speech_with_kokoro(text, self.character_name)
                        )
                    elif self.tts_method == "Silero":
                        output_file = loop.run_until_complete(
                            self.silero.generate_speech_with_silero(text, self.character_name)
                        )
                    elif self.tts_method == "Qwen-3 TTS":
                        output_file = loop.run_until_complete(
                            self.qwen.generate_speech_with_qwen3(text, self.character_name)
                        )
                    elif self.tts_method == "ElevenLabs":
                        output_file = loop.run_until_complete(
                            self.eleven.generate_speech_with_elevenlabs_sow_system(text, self.voice_id)
                        )

                    self._generating = False
                    if self.discard_current:
                        logger.info("TTS finished, but was interrupted. Discarding audio.")
                        if output_file and os.path.exists(output_file):
                            try:
                                os.remove(output_file)
                            except Exception:
                                pass
                        self.queue.task_done()
                        continue

                    if output_file:
                        try:
                            import base64
                            with open(output_file, "rb") as f:
                                b64_audio = base64.b64encode(f.read()).decode("utf-8")
                            self.audio_ready_signal.emit(b64_audio)
                        except Exception as e:
                            logger.error(f"Error encoding audio for web client: {e}")
                        
                        if message_id:
                            try:
                                relative_path = self._persist_segment_for_replay(output_file, message_id)
                                if relative_path:
                                    self.segment_saved_signal.emit(message_id, relative_path)
                            except Exception as e:
                                logger.error(f"Failed to persist TTS segment for replay: {e}")

                        self.playback_worker.add_audio_file(output_file)

                    self.queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                self._generating = False
                logger.error(f"TTS Error: {e}")

    def stop(self):
        self.is_running = False
        self.discard_current = True
        self.queue.put(None)
        if hasattr(self, 'playback_worker'):
            self.playback_worker.stop()
        self.quit()
        self.wait()

    def retire(self):
        """
        Stop without blocking the caller: the thread drops the sentence it is synthesising and
        then deletes itself. stop() holds the GUI until that sentence is done, which takes
        minutes while the server is still loading the voice model.
        """
        self.is_running = False
        self.discard_current = True
        self.queue.put(None)
        self.playback_worker.stop()
        _RETIRED_WORKERS.add(self)
        self.finished.connect(self._on_retired)
        if not self.isRunning():
            self._on_retired()

    def _on_retired(self):
        if self in _RETIRED_WORKERS:
            _RETIRED_WORKERS.discard(self)
            self.deleteLater()

class _AudioChunk:
    __slots__ = ("file_path", "text", "message_id", "persist", "is_poison")

    def __init__(self, file_path: Optional[str] = None, text: str = "",
                 message_id: Optional[str] = None, persist: bool = False,
                 is_poison: bool = False):
        self.file_path = file_path
        self.text = text
        self.message_id = message_id
        self.persist = persist
        self.is_poison = is_poison

class PipelinedTTSWorker(QThread):
    audio_ready_signal = pyqtSignal(str)
    segment_saved_signal = pyqtSignal(str, str)
    lipsync_signal = pyqtSignal(float)
    queue_empty_signal = pyqtSignal()

    AUDIO_BUFFER_SIZE = 2
    LIPSYNC_POLL_SEC = 0.05
    TTS_TIMEOUT_SEC = 30

    def __init__(self, tts_method, character_name, voice_id=None, language="en"):
        super().__init__()

        self.text_queue = queue.Queue()

        self.is_running = True
        self.discard_current = False
        self._interrupt_flag = threading.Event()

        self.tts_method = tts_method
        self.character_name = character_name
        self.voice_id = voice_id
        self.language = language

        self.configuration_settings = configuration.ConfigurationSettings()
        self.configuration_api = configuration.ConfigurationAPI()
        self.configuration_characters = configuration.ConfigurationCharacters()

        self.device_index = self.configuration_settings.get_main_setting("output_device_real_index")

        self.tts_mode = self.configuration_settings.get_main_setting("tts_voicing_mode") or 0
        self.tts_custom_regex = self.configuration_settings.get_main_setting("tts_custom_regex") or ""

        self._in_tts_quote = False
        self._in_asterisk = False

        self._tts_engines_initialized = False
        self.xtts = None
        self.edge = None
        self.kokoro = None
        self.silero = None
        self.qwen = None
        self.eleven = None

        self._generating = False
        self._playing = False

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._audio_buffer: Optional[asyncio.Queue] = None
        self._producer_task: Optional[asyncio.Task] = None
        self._player_task: Optional[asyncio.Task] = None

    def _idle(self):
        """Nothing queued, being synthesised or playing: the next sentence is heard only when done."""
        return (not self._generating and not self._playing and self.text_queue.empty()
                and (self._audio_buffer is None or self._audio_buffer.empty()))

    def _ensure_tts_engines(self):
        if self._tts_engines_initialized:
            return
        from app.utils.text_to_speech import (
            XTTSv2_SOW_System, EdgeTTS, KokoroTTS_SOW_System,
            SileroTTS_SOW_System, Qwen3TTS_SOW_System, ElevenLabs
        )
        self.xtts = XTTSv2_SOW_System()
        self.edge = EdgeTTS()
        self.kokoro = KokoroTTS_SOW_System()
        self.silero = SileroTTS_SOW_System()
        self.qwen = Qwen3TTS_SOW_System()
        self.eleven = ElevenLabs()
        self._tts_engines_initialized = True
        logger.info(f"[PipelinedTTS] engines initialized for method='{self.tts_method}'")

    def add_text(self, text, message_id=None):
        if not text:
            return

        self.discard_current = False
        self._interrupt_flag.clear()

        text = self.clean_text_for_speech(text)
        if not text:
            return

        raw_sentences = re.split(r'(?<=[.!?])\s+', text)
        current_chunk = ""
        max_chunk_len = 450
        split_lead = self.tts_method in SLOW_TTS_METHODS and self._idle()

        def _enqueue(chunk_text):
            nonlocal split_lead
            if chunk_text:
                pieces = split_clauses(chunk_text) if split_lead else [chunk_text]
                split_lead = False
                for piece in pieces:
                    self.text_queue.put((piece, message_id))

        for sentence in raw_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > max_chunk_len:
                if current_chunk:
                    _enqueue(current_chunk)
                    current_chunk = ""
                sub_chunks = re.split(r'(?<=[,;])\s', sentence)
                for sub in sub_chunks:
                    sub = sub.strip()
                    if len(sub) > max_chunk_len:
                        for i in range(0, len(sub), max_chunk_len):
                            _enqueue(sub[i:i+max_chunk_len])
                    else:
                        _enqueue(sub)
            else:
                if len(current_chunk) + len(sentence) + 1 > max_chunk_len:
                    _enqueue(current_chunk)
                    current_chunk = sentence
                else:
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence

        if current_chunk:
            _enqueue(current_chunk)

    def clean_text_for_speech(self, text: str) -> str:
        if not text:
            return ""

        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"https?://\S+|www\.\S+", "", text)

        mode = self.tts_mode
        regex = self.tts_custom_regex

        # --- Mode 0: Voice Everything ---
        if mode == 0:
            return re.sub(r"[*_~`#]", "", text).strip()

        # --- Mode 1: Voice Only Quotes ---
        elif mode == 1:
            result = []
            parts = re.split(r'(["“”«»])', text)
            for part in parts:
                if part in ('"', "“", "”", "«", "»"):
                    self._in_tts_quote = not self._in_tts_quote
                    if not self._in_tts_quote:
                        result.append(" ")
                    continue
                if self._in_tts_quote:
                    result.append(part)
            
            cleaned = re.sub(r"[*_~`#]", "", "".join(result)).strip()

            if not cleaned and not any(q in text for q in ('"', "“", "”", "«", "»")):
                no_actions = re.sub(r"\*[^*]+\*", "", text)
                no_actions = re.sub(r"_[^_]+_", "", no_actions)
                cleaned = re.sub(r"[*_~`#]", "", no_actions).strip()

            return cleaned

        # --- Mode 2: Ignore Asterisks ---
        elif mode == 2:
            result = []
            parts = re.split(r"(\*|_)", text)
            for part in parts:
                if part in ("*", "_"):
                    self._in_asterisk = not self._in_asterisk
                    if not self._in_asterisk:
                        result.append(" ")
                    continue
                if not self._in_asterisk:
                    result.append(part)
            return re.sub(r"[*_~`#]", "", "".join(result)).strip()

        # --- Mode 3: Voice Outside Quotes ---
        elif mode == 3:
            result = []
            parts = re.split(r'(["“”«»])', text)
            for part in parts:
                if part in ('"', "“", "”", "«", "»"):
                    if part in ("“", "«"):
                        self._in_tts_quote = True
                    elif part in ("”", "»"):
                        self._in_tts_quote = False
                    else:
                        self._in_tts_quote = not self._in_tts_quote

                    if not self._in_tts_quote:
                        result.append(" ")
                    continue

                if not self._in_tts_quote:
                    result.append(part)

            return re.sub(r"[*_~`#]", "", "".join(result)).strip()

        # --- Mode 4: Custom Regex ---
        elif mode == 4:
            if not regex:
                return re.sub(r"[*_~`#]", "", text).strip()
            try:
                matches = re.findall(regex, text)
                if matches:
                    extracted = []
                    for m in matches:
                        if isinstance(m, tuple):
                            val = next((g for g in m if g), "")
                            extracted.append(val)
                        else:
                            extracted.append(m)
                    return " ".join(extracted).strip()
                return ""
            except re.error:
                return re.sub(r"[*_~`#]", "", text).strip()

        return text.strip()

    def clear_queue(self):
        with self.text_queue.mutex:
            self.text_queue.queue.clear()
        self.discard_current = True
        self._interrupt_flag.set()
        self._in_tts_quote = False
        self._in_asterisk = False
        if self._loop and self._audio_buffer and self._loop.is_running():
            def _drain():
                while not self._audio_buffer.empty():
                    try:
                        self._audio_buffer.get_nowait()
                    except asyncio.QueueEmpty:
                        break
            self._loop.call_soon_threadsafe(_drain)
        try:
            self.lipsync_signal.emit(0.0)
        except Exception:
            pass
        logger.info("[PipelinedTTS] queue cleared, playback interrupted")

    def stop(self):
        self.is_running = False
        self.discard_current = True
        self._interrupt_flag.set()
        self.text_queue.put(None)

        if self._loop and self._loop.is_running():
            for task in (self._producer_task, self._player_task):
                if task and not task.done():
                    self._loop.call_soon_threadsafe(task.cancel)

        try:
            sd.stop()
        except Exception:
            pass

        self.quit()
        self.wait()
        logger.info("[PipelinedTTS] worker stopped")

    def run(self):
        logger.info(f"PipelinedTTSWorker started (method={self.tts_method}, "
                    f"buffer={self.AUDIO_BUFFER_SIZE})")

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._audio_buffer = asyncio.Queue(maxsize=self.AUDIO_BUFFER_SIZE)

        self.discard_current = False
        self._interrupt_flag.clear()

        self._producer_task = self._loop.create_task(self._producer_loop())
        self._player_task = self._loop.create_task(self._player_loop())

        try:
            self._loop.run_until_complete(
                asyncio.gather(self._producer_task, self._player_task,
                               return_exceptions=True)
            )
        except Exception as e:
            logger.error(f"[PipelinedTTS] run() error: {e}", exc_info=True)
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
            logger.info("[PipelinedTTS] run() exited")

    async def _producer_loop(self):
        logger.info("[PipelinedTTS] producer loop started")

        while self.is_running:
            try:
                item = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.text_queue.get(timeout=0.5)
                )
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[PipelinedTTS] producer get error: {e}")
                continue

            if item is None:

                logger.info("[PipelinedTTS] producer received poison pill")
                await self._audio_buffer.put(_AudioChunk(is_poison=True))
                break

            text, message_id = item
            if not text:
                continue

            self.discard_current = False
            self._interrupt_flag.clear()

            logger.info(f"[PipelinedTTS] producer: generating '{text[:40]}...'")

            try:
                self._ensure_tts_engines()
            except Exception as e:
                logger.error(f"[PipelinedTTS] engine init failed: {e}")
                continue

            try:
                await self._load_engine_model()
            except asyncio.CancelledError:
                logger.info("[PipelinedTTS] producer cancelled")
                break
            except Exception as e:
                logger.error(f"[PipelinedTTS] TTS model load failed: {e}")
                continue

            output_file = None
            self._generating = True
            try:
                output_file = await asyncio.wait_for(
                    self._generate_wav(text),
                    timeout=self.TTS_TIMEOUT_SEC
                )
            except asyncio.TimeoutError:
                logger.error(f"[PipelinedTTS] TTS timed out for: '{text[:40]}...'")
                continue
            except asyncio.CancelledError:
                logger.info("[PipelinedTTS] producer cancelled")
                break
            except Exception as e:
                logger.error(f"[PipelinedTTS] TTS generation error: {e}", exc_info=True)
                continue
            finally:
                self._generating = False

            if self.discard_current:
                logger.info(f"[PipelinedTTS] producer: discarding '{text[:40]}...' (interrupted)")
                if output_file and os.path.exists(output_file):
                    try:
                        os.remove(output_file)
                    except Exception:
                        pass
                continue

            if not output_file or not os.path.exists(output_file):
                logger.warning(f"[PipelinedTTS] producer: no output file for '{text[:40]}...'")
                continue

            try:
                import base64
                b64_audio = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: base64.b64encode(open(output_file, "rb").read()).decode("utf-8")
                )
                self.audio_ready_signal.emit(b64_audio)
            except Exception as e:
                logger.error(f"[PipelinedTTS] base64 encoding error: {e}")

            if message_id:
                try:
                    relative_path = await asyncio.get_event_loop().run_in_executor(
                        None, self._persist_segment_for_replay, output_file, message_id
                    )
                    if relative_path:
                        self.segment_saved_signal.emit(message_id, relative_path)
                except Exception as e:
                    logger.error(f"[PipelinedTTS] persist error: {e}")

            chunk = _AudioChunk(
                file_path=output_file,
                text=text,
                message_id=message_id,
                persist=False,
            )
            try:
                await self._audio_buffer.put(chunk)
                logger.info(f"[PipelinedTTS] producer: enqueued '{text[:40]}...' "
                            f"(buffer now has {self._audio_buffer.qsize() + 1} items)")
            except asyncio.CancelledError:
                try:
                    if output_file and os.path.exists(output_file):
                        os.remove(output_file)
                except Exception:
                    pass
                break

        logger.info("[PipelinedTTS] producer loop ended")

    async def _player_loop(self):
        logger.info("[PipelinedTTS] player loop started")

        while self.is_running:
            try:
                chunk = await self._audio_buffer.get()
            except asyncio.CancelledError:
                logger.info("[PipelinedTTS] player cancelled")
                break
            except Exception as e:
                logger.error(f"[PipelinedTTS] player get error: {e}")
                continue

            if chunk is None or chunk.is_poison:
                logger.info("[PipelinedTTS] player received poison pill")
                break

            if not chunk.file_path or not os.path.exists(chunk.file_path):
                logger.warning(f"[PipelinedTTS] player: missing file '{chunk.file_path}'")
                continue

            if self._interrupt_flag.is_set():
                logger.info(f"[PipelinedTTS] player: skipping '{chunk.text[:40]}...' (interrupted)")
                try:
                    if not chunk.persist and os.path.exists(chunk.file_path):
                        os.remove(chunk.file_path)
                except Exception:
                    pass
                continue

            logger.info(f"[PipelinedTTS] player: playing '{chunk.text[:40]}...'")
            self._playing = True
            try:
                await self._play_audio_with_lipsync(chunk.file_path, chunk.persist)
            finally:
                self._playing = False

            if self._audio_buffer.empty() and self.text_queue.empty() and not self._interrupt_flag.is_set():
                try:
                    self.queue_empty_signal.emit()
                except Exception:
                    pass

        try:
            self.lipsync_signal.emit(0.0)
        except Exception:
            pass

        logger.info("[PipelinedTTS] player loop ended")

    async def _play_audio_with_lipsync(self, file_path: str, persist: bool):
        try:
            data, samplerate = await asyncio.get_event_loop().run_in_executor(
                None, lambda: sf.read(file_path, dtype='float32')
            )
        except Exception as e:
            logger.error(f"[PipelinedTTS] read error: {e}")
            try:
                if not persist and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            return

        if data is None or len(data) == 0:
            logger.warning(f"[PipelinedTTS] empty audio data for '{file_path}'")
            try:
                if not persist and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            return

        try:
            audio_output.play(data, samplerate, device=self.device_index)
        except Exception as e:
            logger.error(f"[PipelinedTTS] sd.play error: {e}")
            try:
                if not persist and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            return

        duration = len(data) / samplerate
        chunk_size = max(1, int(samplerate * self.LIPSYNC_POLL_SEC))
        total_samples = len(data)

        is_stereo = data.ndim > 1
        if is_stereo:
            data_mono = data.mean(axis=1)
        else:
            data_mono = data

        slept = 0.0
        sample_idx = 0
        try:
            while slept < duration:
                if self._interrupt_flag.is_set():
                    sd.stop()
                    self.lipsync_signal.emit(0.0)
                    logger.info(f"[PipelinedTTS] player: interrupted at {slept:.2f}/{duration:.2f}s")
                    break

                end_idx = min(sample_idx + chunk_size, total_samples)
                current_chunk = data_mono[sample_idx:end_idx]
                if len(current_chunk) > 0:
                    rms = float(np.sqrt(np.mean(current_chunk ** 2)))
                    mouth_open = min(rms * 5.0, 1.0)
                    try:
                        self.lipsync_signal.emit(mouth_open)
                    except Exception:
                        pass

                await asyncio.sleep(self.LIPSYNC_POLL_SEC)
                slept += self.LIPSYNC_POLL_SEC
                sample_idx += chunk_size

        except asyncio.CancelledError:
            sd.stop()
            try:
                self.lipsync_signal.emit(0.0)
            except Exception:
                pass
            raise
        except Exception as e:
            logger.error(f"[PipelinedTTS] lipsync loop error: {e}")
        finally:

            try:
                self.lipsync_signal.emit(0.0)
            except Exception:
                pass

            if not self._interrupt_flag.is_set():
                try:
                    await asyncio.get_event_loop().run_in_executor(None, sd.wait)
                except Exception:
                    pass

            try:
                if not persist and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    async def _load_engine_model(self):
        """
        Load the local TTS model outside the per-sentence timeout. A cold load (download or
        first GPU init) outlasts TTS_TIMEOUT_SEC; wait_for then cancels it before tts_loaded
        is set and every following sentence starts loading the model again.
        """
        method = self.tts_method
        if method == "XTTSv2":
            await asyncio.to_thread(self.xtts._load_tts_sync)
        elif method == "Kokoro":
            await self.kokoro._load_tts()
        elif method == "Silero":
            await self.silero._load_tts()
        elif method == "Qwen-3 TTS":
            await self.qwen._load_tts(self.character_name)

    async def _generate_wav(self, text: str) -> Optional[str]:
        method = self.tts_method
        if method == "XTTSv2":
            return await self.xtts.generate_speech_with_xttsv2_sow_system(
                text, self.language, self.character_name)
        elif method == "Edge TTS":
            return await self.edge.generate_speech_with_edge_tts_sow_system(
                text, self.character_name)
        elif method == "Kokoro":
            return await self.kokoro.generate_speech_with_kokoro(
                text, self.character_name)
        elif method == "Silero":
            return await self.silero.generate_speech_with_silero(
                text, self.character_name)
        elif method == "Qwen-3 TTS":
            return await self.qwen.generate_speech_with_qwen3(
                text, self.character_name)
        elif method == "ElevenLabs":
            return await self.eleven.generate_speech_with_elevenlabs_sow_system(
                text, self.voice_id)
        else:
            logger.error(f"[PipelinedTTS] unknown TTS method: {method}")
            return None

    def _persist_segment_for_replay(self, source_file, message_id):
        if not source_file or not os.path.exists(source_file):
            return None

        segment_dir = os.path.join(
            os.getcwd(), "app", "data", ".soul",
            self.character_name, "tts_audio", message_id
        )
        os.makedirs(segment_dir, exist_ok=True)

        existing = [f for f in os.listdir(segment_dir)
                    if f.lower().endswith((".wav", ".mp3"))]
        next_index = len(existing) + 1
        ext = os.path.splitext(source_file)[1] or ".wav"
        segment_filename = f"seg_{next_index:04d}{ext}"
        destination = os.path.join(segment_dir, segment_filename)

        shutil.copyfile(source_file, destination)
        return f"tts_audio/{message_id}/{segment_filename}"