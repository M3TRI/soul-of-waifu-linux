import logging
from math import gcd

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

logger = logging.getLogger("Audio Output")


def fit_to_device(data, samplerate, device=None):
    """
    Return (data, samplerate) the output device accepts.

    Windows shared-mode audio APIs resample on their own. On Linux, JACK and raw ALSA hw:*
    devices only open at their native rate, so 24 kHz TTS audio fails with
    "Invalid sample rate" unless it is resampled here first.
    """
    channels = 1 if np.ndim(data) == 1 else np.shape(data)[1]
    try:
        sd.check_output_settings(device=device, samplerate=samplerate, channels=channels)
        return data, samplerate
    except Exception:
        pass

    target = int(sd.query_devices(device, "output")["default_samplerate"])
    data = np.asarray(data)
    if np.issubdtype(data.dtype, np.integer):
        data = data.astype(np.float32) / np.iinfo(data.dtype).max
    divisor = gcd(int(samplerate), target)
    resampled = resample_poly(data, target // divisor, int(samplerate) // divisor, axis=0).astype(np.float32)
    logger.info(f"Resampled audio {samplerate} Hz -> {target} Hz for output device {device}")
    return resampled, target


def upmix_mono(data, device=None):
    """
    Duplicate mono audio onto two channels when the output device has them.

    A one-channel stream on a JACK device is connected to its first port only, so mono TTS
    output plays in the left ear; ALSA/PulseAudio devices upmix on their own.
    """
    if np.ndim(data) != 1:
        return data
    try:
        channels = int(sd.query_devices(device, "output")["max_output_channels"])
    except Exception:
        return data
    if channels < 2:
        return data
    return np.column_stack((data, data))


def play(data, samplerate, device=None):
    """sd.play that adapts the sample rate and channel count to the output device."""
    data, samplerate = fit_to_device(data, samplerate, device)
    sd.play(upmix_mono(data, device), samplerate, device=device)
