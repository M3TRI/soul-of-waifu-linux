"""
Loaded-model registry with a VRAM budget.

Every engine model goes through ModelManager.get(): it loads on first use, keeps the model
until it has to make room, and serialises inference per model (none of the engines are safe
to call from two threads at once). On CUDA the service may use SOW_SPEECH_VRAM_MB; models are
unloaded least recently used first to stay inside it, and only one heavy TTS model (XTTS,
Qwen3) is kept at a time.
"""
import asyncio
import gc
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import torch

logger = logging.getLogger("sow_speech.models")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BUDGET_MB = int(os.environ.get("SOW_SPEECH_VRAM_MB", "0")) or None


class OutOfVram(RuntimeError):
    pass


@dataclass
class Slot:
    key: str
    obj: Any
    heavy: bool
    pinned: bool
    vram_mb: int
    last_used: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def is_oom(e: BaseException) -> bool:
    """torch raises OutOfMemoryError; CTranslate2 (Whisper) a RuntimeError with this text."""
    return isinstance(e, torch.OutOfMemoryError) or "out of memory" in str(e).lower()


def _free_mb() -> int:
    free, _total = torch.cuda.mem_get_info()
    return free // 2**20


def _usage() -> tuple[int, int]:
    return torch.cuda.memory_reserved() // 2**20, _free_mb()


def _grown_mb(before: tuple[int, int]) -> int:
    """
    VRAM a load took. torch's own counter is exact and unaffected by other processes or by
    memory a just-unloaded model frees meanwhile; CTranslate2 (Whisper) allocates outside
    torch, so for it fall back to the drop in free device memory.
    """
    reserved, free = _usage()
    grown = reserved - before[0]
    return grown if grown > 0 else max(0, before[1] - free)


class ModelManager:
    def __init__(self):
        self.slots: dict[str, Slot] = {}
        self._load_lock = asyncio.Lock()

    def used_mb(self) -> int:
        return sum(s.vram_mb for s in self.slots.values())

    async def get(self, key: str, loader: Callable[[], Any], *, est_mb: int = 0,
                  heavy: bool = False, pinned: bool = False) -> Slot:
        """Return the slot for key, loading it with loader() (run in a thread) if needed."""
        slot = self.slots.get(key)
        if slot:
            slot.last_used = time.monotonic()
            return slot
        async with self._load_lock:
            slot = self.slots.get(key)
            if slot:
                return slot
            if DEVICE == "cuda":
                self._make_room(est_mb, heavy)
                before = _usage()
            logger.info("Loading %s", key)
            started = time.monotonic()
            try:
                obj = await asyncio.to_thread(loader)
            except Exception as e:
                if DEVICE != "cuda" or not is_oom(e):
                    raise
                # Other programs (or llama.cpp) may hold the GPU: free what this service can
                # and try once more before giving up.
                self._evict_all()
                logger.warning("Out of VRAM loading %s, retrying after unloading idle models", key)
                before = _usage()
                try:
                    obj = await asyncio.to_thread(loader)
                except Exception as e2:
                    if is_oom(e2):
                        raise OutOfVram(f"not enough free video memory for {key} "
                                        f"({_free_mb()} MB free on the GPU)") from e2
                    raise
            # Some engines load their weights lazily on the first request (RVC's hubert);
            # count the estimate until a real figure exists.
            vram = (_grown_mb(before) or est_mb) if DEVICE == "cuda" else 0
            slot = Slot(key, obj, heavy, pinned, vram)
            self.slots[key] = slot
            logger.info("Loaded %s in %.1fs, %d MB VRAM", key, time.monotonic() - started, vram)
            return slot

    def _make_room(self, est_mb: int, heavy: bool):
        # Iterate over keys: a lingering reference to a slot would keep its model alive, and
        # its memory would stay in torch's cache instead of going back to the GPU.
        if heavy:
            for key in [k for k, s in self.slots.items() if s.heavy]:
                self.unload(key)
        if BUDGET_MB is None:
            return
        while self.used_mb() + est_mb > BUDGET_MB:
            victims = sorted((k for k, s in self.slots.items() if not s.pinned and not s.lock.locked()),
                             key=lambda k: self.slots[k].last_used)
            if not victims:
                raise OutOfVram(f"needs ~{est_mb} MB, {self.used_mb()} of {BUDGET_MB} MB in use")
            self.unload(victims[0])

    def _evict_all(self):
        for key in [k for k, s in self.slots.items() if not s.pinned and not s.lock.locked()]:
            self.unload(key)

    def unload(self, key: str):
        slot = self.slots.pop(key, None)
        if slot is None:
            return
        logger.info("Unloading %s (%d MB)", key, slot.vram_mb)
        del slot
        gc.collect()
        if DEVICE == "cuda":
            torch.cuda.empty_cache()

    def status(self) -> list[dict]:
        return [{"component": s.key, "vram_mb": s.vram_mb, "busy": s.lock.locked()}
                for s in sorted(self.slots.values(), key=lambda s: s.key)]


manager = ModelManager()
