import io
import os
import sys
import time
import pyaudio
import logging
import numpy as np
import soundfile as sf

from PyQt6.QtCore import QThread, pyqtSignal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils import sow_server

logger = logging.getLogger("Speech-To-Text Module")

SILERO_VAD_ONNX = os.path.join("app", "utils", "speech-to-text", "silero-vad", "src", "silero_vad",
                               "data", "silero_vad.onnx")


class SileroVad:
    """
    Silero VAD through onnxruntime, without torch: the ONNX model shipped in the silero-vad
    folder, driven like its OnnxWrapper (state carried between calls, 64-sample context).
    Takes 512-sample float32 chunks at 16 kHz and returns the speech probability.
    """

    CONTEXT = 64

    def __init__(self, path=SILERO_VAD_ONNX):
        import onnxruntime
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset_states()

    def reset_states(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def __call__(self, chunk: np.ndarray, sr: int = 16000) -> float:
        x = np.concatenate([self._context, chunk.reshape(1, -1).astype(np.float32)], axis=1)
        out, self._state = self.session.run(None, {"input": x, "state": self._state,
                                                   "sr": np.array(sr, dtype=np.int64)})
        self._context = x[:, -self.CONTEXT:]
        return float(out[0][0])


class AudioInputWorker(QThread):
    voice_detected_signal = pyqtSignal()
    volume_signal = pyqtSignal(float)
    silence_detected_signal = pyqtSignal()
    audio_packet_ready = pyqtSignal(bytes)

    def __init__(self, input_device_index=None, vad_device="cpu"):
        super().__init__()
        self.input_device_index = input_device_index
        self.is_running = True

        self.SAMPLE_RATE = 16000
        self.CHUNK_SIZE = 512

        # VAD runs here on the CPU (ONNX, ~1 ms per chunk): only speech segments go to the server.
        logger.info("Loading Silero VAD model (ONNX)...")
        try:
            self.model = SileroVad()
            logger.info("Silero VAD loaded successfully!")
        except Exception as e:
            logger.error(f"Error loading Silero VAD: {e}")
            self.model = None

        self.frames = []
        self.silence_threshold = 45
        self.voice_threshold = 0.5

    def run(self):
        logger.info("Audio Worker Thread Started")
        p = pyaudio.PyAudio()

        numdevices = p.get_device_count()
        logger.info(f"Found {numdevices} audio devices total:")
        found_device = False

        for i in range(0, numdevices):
            try:
                device_info = p.get_device_info_by_index(i)
                if device_info.get('maxInputChannels') > 0:
                    name = device_info.get('name')
                    logger.info(f"   Device ID {i}: {name}")
                    if self.input_device_index == i:
                        found_device = True
            except Exception:
                continue

        if self.input_device_index is not None and not found_device:
            logger.warning(f"Device ID {self.input_device_index} not found. Using Default.")
            self.input_device_index = None

        stream = None
        try:
            stream = p.open(format=pyaudio.paInt16,
                            channels=1,
                            rate=self.SAMPLE_RATE,
                            input=True,
                            input_device_index=self.input_device_index,
                            frames_per_buffer=self.CHUNK_SIZE)
            logger.info(f"Microphone stream opened successfully! (Device ID: {self.input_device_index if self.input_device_index is not None else 'Default'})")
        except Exception as e:
            logger.error(f"Failed to open microphone: {e}")
            p.terminate()
            return

        speaking = False
        silence_chunks = 0

        while self.is_running:
            try:
                if not self.model:
                    time.sleep(1)
                    continue

                data = stream.read(self.CHUNK_SIZE, exception_on_overflow=False)

                audio_int16 = np.frombuffer(data, np.int16)
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                speech_prob = self.model(audio_float32, self.SAMPLE_RATE)

                rms = float(np.sqrt(np.mean(audio_float32 ** 2)))
                volume = min(1.0, rms * 22.0)
                self.volume_signal.emit(volume)

                if speech_prob > self.voice_threshold:
                    if not speaking:
                        speaking = True
                        self.voice_detected_signal.emit()
                        logger.info("User started speaking")

                    silence_chunks = 0
                    self.frames.append(data)

                else:
                    if speaking:
                        self.frames.append(data)
                        silence_chunks += 1

                        if silence_chunks > self.silence_threshold:
                            speaking = False
                            self.silence_detected_signal.emit()
                            logger.info(f"User stopped. Sending {len(self.frames)} frames.")

                            full_audio = b''.join(self.frames)
                            self.audio_packet_ready.emit(full_audio)

                            self.frames = []
                            silence_chunks = 0

            except Exception as e:
                logger.error(f"Error in audio loop: {e}")
                break

        logger.info("Stopping Audio Stream...")
        if stream:
            stream.stop_stream()
            stream.close()
        p.terminate()
        logger.info("Audio Worker Stopped cleanly")

    def stop(self):
        self.is_running = False
        self.wait()


class STTWorker(QThread):
    text_ready_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    HALLUCINATIONS = [
        "субтитры создавал", "редактор субтитров", "спасибо за просмотр",
        "подписывайтесь на канал", "продолжение следует",
        "субтитры", "а. семенов", "перевод", "озвучка", "Thank you.",

        "ВЕСЕЛАЯ МУЗЫКА", "СПОКОЙНАЯ МУЗЫКА", "ГРУСТНАЯ МЕЛОДИЯ",
        "ЛИРИЧЕСКАЯ МУЗЫКА", "ДИНАМИЧНАЯ МУЗЫКА", "ТАИНСТВЕННАЯ МУЗЫКА",
        "ТОРЖЕСТВЕННАЯ МУЗЫКА", "ИНТРИГУЮЩАЯ МУЗЫКА", "НАПРЯЖЕННАЯ МУЗЫКА",
        "ПЕЧАЛЬНАЯ МУЗЫКА", "ТРЕВОЖНАЯ МУЗЫКА", "МУЗЫКАЛЬНАЯ ЗАСТАВКА",

        "ПЕРЕСТРЕЛКА", "ГУДОК ПОЕЗДА", "РЁВ МОТОРА", "ШУМ ДВИГАТЕЛЯ",
        "СИГНАЛ АВТОМОБИЛЯ", "ЛАЙ СОБАК", "ПЕС ЛАЕТ", "КАШЕЛЬ", "ВЫСТРЕЛЫ",
        "ШУМ ДОЖДЯ", "ПЕСНЯ", "ПО ГРОМКОГОВОРИЧЕСКОМУ ЯЗЫКЕ", "ПО ГРОМКОГОВОРИТЕЛЮ",
        "ВЗРЫВ", "ШУМ МОТОРА", "ПЛЕСК ВОДЫ", "ГУДОК АВТОМОБИЛЯ", "ЛАЙ СОБАКИ",
        "ПО ТВ.", "АПЛОДИСМЕНТЫ", "ГОРОДСКОЙ ШУМ", "ПОЛИЦИЯ", "ГОРОДСКОЙ ГУДОК",
        "СИГНАЛ МАШИНЫ", "СМЕХ", "СТУК В ДВЕРЬ", "ААААААААААААААААААА",
        "ПОЛИЦЕЙСКАЯ СИРЕНА", "ЗВОНОК В ДВЕРЬ",

        "Спасибо за субтитры!", "Субтитры добавил DimaTorzok",
        "Субтитры подогнал «Симон»!",
        "Редактор субтитров М.Лосева Корректор А.Егорова",
        "Редактор субтитров А.Синецкая Корректор А.Егорова",
        "Редактор субтитров Т.Горелова Корректор А.Егорова",
        "Редактор субтитров Е.Жукова Корректор А.Егорова",
        "Редактор субтитров А.Семкин Корректор А.Егорова",
        "Редактор субтитров А.Захарова Корректор А.Егорова",

        "Смотрите продолжение во второй части видео.",
        "Смотрите продолжение в следующей части.",
        "Смотрите продолжение в следующей части видео.",
        "Смотрите продолжение в 4 части видео.",
        "Смотрите продолжение в следующей серии...",
        "Смотрите продолжение во второй части.",
        "Продолжение следует...",

        "ПОДПИШИСЬ НА КАНАЛ", "ПОДПИШИСЬ!", "ПОДПИШИСЬ",

        "🦜", "💥", "😎", "🤨", "🤔", "Поехали!", "Поехали.",
        "Девушки отдыхают..."
    ]

    def __init__(self, model_size="small", device="auto", compute_type="auto"):
        super().__init__()
        self.queue = []
        self.is_running = True

        # Whisper runs on the Soul of Waifu server; device and compute type are its business.
        self.model_size = model_size

    def load_model(self):
        """Wait until the server answers; Whisper itself is loaded there on first use."""
        caps = sow_server.capabilities(force=True)
        if not caps or not caps.get("stt", {}).get("available"):
            raise RuntimeError("speech recognition is not available on the server")
        self.status_signal.emit(f"Model ready (server, {caps['stt'].get('device', '?')})")

    def add_audio(self, audio_bytes):
        self.queue.append(audio_bytes)

    def run(self):
        try:
            self.load_model()
        except Exception as e:
            logger.error(f"Failed to load STT model, worker stopped: {e}")
            self.status_signal.emit("Model load failed")
            return

        logger.info("STT Loop Started")

        while self.is_running:
            if len(self.queue) > 0:
                audio_bytes = self.queue.pop(0)

                try:
                    buf = io.BytesIO()
                    sf.write(buf, np.frombuffer(audio_bytes, np.int16), 16000, format="WAV", subtype="PCM_16")
                    full_text = sow_server.transcribe(buf.getvalue(), self.model_size).strip()
                    text_lower = full_text.lower()
                    is_hallucination = any(h.lower() in text_lower for h in self.HALLUCINATIONS)

                    if full_text and not is_hallucination and len(full_text) > 2:
                        logger.info(f"Text Recognized: {full_text}")
                        self.text_ready_signal.emit(full_text)
                    else:
                        logger.info("Empty audio fragment or hallucination ignored.")

                except Exception as e:
                    logger.error(f"STT Error: {e}")

            else:
                self.msleep(50)

        logger.info("STT Worker Stopped")

    def stop(self):
        logger.info("Signaling Audio Worker to stop...")
        self.is_running = False
        self.queue.append(b'')
        self.quit()
        self.wait()