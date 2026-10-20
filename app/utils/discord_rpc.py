import os
import time
import queue
import random
import logging
import threading
import asyncio
from typing import Optional

logger = logging.getLogger("Discord RPC")

try:
    from pypresence import Presence
    PYPRESENCE_AVAILABLE = True
except ImportError:
    PYPRESENCE_AVAILABLE = False
    logger.warning("pypresence is not installed. Discord RPC disabled.")

DISCORD_CLIENT_ID = "1540392006956621876"


class DiscordRPCManager:
    _instance: Optional["DiscordRPCManager"] = None
    _lock = threading.Lock()

    MENU_STATUSES = [
        ("Main Hub", "Looking around"),
        ("Main Hub", "Picking something to try"),
        ("Main Hub", "Deciding what to do next"),
        ("Main Hub", "Preparing Next Adventure"),
        ("Main Hub", "Browsing chats")
    ]

    CHAT_STATUSES = [
        ("Chat", "Chatting with Character"),
        ("Chat", "Writing Infinite Stories"),
        ("Chat", "Sharing Memories"),
        ("Chat", "Just talking"),
        ("Chat", "Lost in chat"),
        ("Chat", "Talking privately"),
        ("Chat", "Exploring Personal Lore")
    ]

    CALL_STATUSES = [
        ("Soul of Waifu System", "Voice call"),
        ("Soul of Waifu System", "Talking via Voice"),
        ("Soul of Waifu System", "Speaking with Character")
    ]

    STAGE_STATUSES = [
        ("Soul Stage", "In Campaign Adventure"),
        ("Soul Stage", "Rolling the Dice"),
        ("Soul Stage", "Exploring Narrative Arcs"),
        ("Soul Stage", "Party on a Journey")
    ]

    COMPANION_STATUSES = [
        ("Soul Companion", "Living on Desktop"),
        ("Soul Companion", "Watching Over the Screen"),
        ("Soul Companion", "Assistant Online"),
        ("Soul Companion", "Just chilling"),
        ("Soul Companion", "Sitting on the Desktop"),
    ]

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DiscordRPCManager, cls).__new__(cls)
            return cls._instance

    def __init__(self, client_id: str = DISCORD_CLIENT_ID):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        
        self.client_id = client_id
        self.start_timestamp = int(time.time())
        self._queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.is_connected = False

    def connect(self):
        if not PYPRESENCE_AVAILABLE:
            return

        if not self.client_id:
            return

        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        rpc = None
        logger.info(f"[Discord RPC] Connecting to Discord IPC with Client ID: {self.client_id}...")

        try:
            rpc = Presence(self.client_id, loop=loop)
            rpc.connect()
            self.is_connected = True
            logger.info("[Discord RPC] Discord Rich Presence successfully connected and active!")
            
            details, state = random.choice(self.MENU_STATUSES)
            rpc.update(
                details=details,
                state=state,
                start=self.start_timestamp,
                large_image="logotype",
                large_text="Soul of Waifu",
                buttons=[
                    {"label": "Get Soul of Waifu", "url": "https://github.com/jofizcd/Soul-of-Waifu"}
                ]
            )
        except Exception as e:
            self.is_connected = False
            rpc = None
            logger.info(f"[Discord RPC] Could not connect to Discord (is Discord desktop app open?): {e}")

        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=1.0)
                if item == "STOP":
                    break

                if rpc and isinstance(item, dict):
                    try:
                        rpc.update(**item)
                    except Exception as e:
                        logger.debug(f"[Discord RPC] Update failed: {e}")
            except queue.Empty:
                continue
            except Exception as e:
                logger.debug(f"[Discord RPC] Worker error: {e}")

        if rpc:
            try:
                rpc.close()
                logger.info("[Discord RPC] Closed connection.")
            except Exception:
                pass

        try:
            loop.close()
        except Exception:
            pass

    def update_presence(self, details: str, state: str, large_text: str = "Soul of Waifu"):
        if not PYPRESENCE_AVAILABLE:
            return

        payload = {
            "details": details,
            "state": state,
            "start": self.start_timestamp,
            "large_image": "logotype",
            "large_text": large_text,
            "buttons": [
                {"label": "Get Soul of Waifu", "url": "https://github.com/jofizcd/Soul-of-Waifu"},
            ]
        }
        self._queue.put(payload)

    def set_menu_presence(self):
        details, state = random.choice(self.MENU_STATUSES)
        self.update_presence(details=details, state=state, large_text="Soul of Waifu")

    def set_chat_presence(self):
        details, state = random.choice(self.CHAT_STATUSES)
        self.update_presence(details=details, state=state, large_text="Single Chat")

    def set_call_presence(self):
        details, state = random.choice(self.CALL_STATUSES)
        self.update_presence(details=details, state=state, large_text="Soul of Waifu System")

    def set_stage_presence(self):
        details, state = random.choice(self.STAGE_STATUSES)
        self.update_presence(details=details, state=state, large_text="Soul Stage")

    def set_companion_presence(self):
        details, state = random.choice(self.COMPANION_STATUSES)
        self.update_presence(details=details, state=state, large_text="Soul Companion")

    def close(self):
        self._stop_event.set()
        self._queue.put("STOP")
        self.is_connected = False