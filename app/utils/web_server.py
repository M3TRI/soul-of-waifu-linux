import os
import json
import secrets
import asyncio
import logging
import ipaddress
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, Security, Depends
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader, APIKeyQuery
from faster_whisper import WhisperModel
import uvicorn

logger = logging.getLogger("WebBridge")

STANDARD_EMOTIONS = [
    "admiration", "amusement", "anger", "annoyance", "approval", "caring",
    "confusion", "curiosity", "desire", "disappointment", "disapproval",
    "disgust", "embarrassment", "excitement", "fear", "gratitude", "grief",
    "love", "nervousness", "neutral", "optimism", "pride", "realization",
    "relief", "remorse", "surprise", "joy", "sadness"
]

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict, exclude: WebSocket = None):
        disconnected = []
        for connection in self.active_connections:
            if connection == exclude:
                continue
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket Broadcast Error: {e}")
                disconnected.append(connection)
                
        for connection in disconnected:
            self.disconnect(connection)

class WebBridge:
    def __init__(self, interface_signals, auth_token: str = None):
        self.app = FastAPI(docs_url=None, redoc_url=None)
        self.signals = interface_signals
        self.manager = ConnectionManager()
        
        self.auth_token = auth_token or secrets.token_urlsafe(16)
        logger.info(f"WebBridge Auth Token initialized: {self.auth_token}")
        
        self.app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_dir = os.path.dirname(self.app_dir)
        
        self.setup_middleware()
        self.setup_routes()
        self.hook_interface_signals()

    def hook_interface_signals(self):
        self.signals.web_bridge = self

    def setup_middleware(self):
        @self.app.middleware("http")
        async def no_cache_static(request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/static") or request.url.path == "/":
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
            return response

        @self.app.middleware("http")
        async def validate_host_header(request: Request, call_next):
            host_header = (request.headers.get("host") or "").split(":")[0]
            if host_header in ("localhost", "127.0.0.1", ""):
                return await call_next(request)
            try:
                ipaddress.ip_address(host_header)
            except ValueError:
                return PlainTextResponse("Forbidden: Invalid Host Header", status_code=400)
            return await call_next(request)

        @self.app.middleware("http")
        async def check_auth_token(request: Request, call_next):
            path = request.url.path
            if path in ["/", "/favicon.ico"] or path.startswith("/static") or \
               path.startswith("/vrm") or path.startswith("/assets") or \
               path.startswith("/app/utils/emotions"):
                return await call_next(request)

            token_header = request.headers.get("X-SOW-Token")
            token_query = request.query_params.get("token")
            
            if (token_header and secrets.compare_digest(token_header, self.auth_token)) or \
               (token_query and secrets.compare_digest(token_query, self.auth_token)):
                return await call_next(request)

            return PlainTextResponse("Unauthorized: Invalid Token", status_code=401)

    def _resolve_user_name(self, char_name: str) -> str:
        try:
            config = self.signals.configuration_characters.load_configuration()
            char_info = config.get("character_list", {}).get(char_name, {})
            persona_key = char_info.get("selected_persona")
            personas = self.signals.configuration_settings.get_user_data("personas") or {}
            if persona_key and persona_key != "None" and persona_key in personas:
                return personas[persona_key].get("user_name", "User") or "User"
        except Exception:
            pass
        return "User"

    # ── Live2D helpers ────────────────────────────────────────────
    def _find_model_json(self, folder: str) -> str | None:
        """Deterministically pick the model json inside a Live2D folder."""
        if not folder or not os.path.isdir(folder):
            return None
        candidates = []
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if f.endswith(".model3.json"):
                    candidates.append(os.path.join(root, f))
        if not candidates:
            for root, _dirs, files in os.walk(folder):
                for f in files:
                    if f.endswith(".model.json"):
                        candidates.append(os.path.join(root, f))
        if not candidates:
            return None
        candidates.sort()
        folder_base = os.path.basename(os.path.normpath(folder)).lower()
        for c in candidates:
            if os.path.basename(c).lower().startswith(folder_base):
                return c
        return candidates[0]

    def _web_path(self, disk_path: str) -> str | None:
        try:
            rel = os.path.relpath(disk_path, self.project_dir).replace("\\", "/")
        except ValueError:
            return None
        if rel.startswith(".."):
            return None
        if not os.path.exists(disk_path):
            return None
        return "/" + rel

    def _build_l2d_model_payload(self, model_json_path: str) -> dict:
        with open(model_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        model_dir = os.path.dirname(os.path.abspath(model_json_path))
        refs = data.get("FileReferences", {})

        def to_url(rel_file: str) -> str:
            abs_path = os.path.normpath(os.path.join(model_dir, rel_file))
            web = self._web_path(abs_path)
            return web if web else rel_file

        if refs.get("Moc"):
            refs["Moc"] = to_url(refs["Moc"])
        if refs.get("Physics"):
            refs["Physics"] = to_url(refs["Physics"])
        if refs.get("Pose"):
            refs["Pose"] = to_url(refs["Pose"])
        if refs.get("UserData"):
            refs["UserData"] = to_url(refs["UserData"])
        refs["Textures"] = [to_url(t) for t in refs.get("Textures", [])]

        # ── Expressions ──
        expressions = refs.get("Expressions") or []
        existing = {e.get("Name"): e for e in expressions if isinstance(e, dict)}

        std_expr_url = "/app/utils/emotions/live2d/expressions/{name}_animation.exp3.json"
        for emotion in STANDARD_EMOTIONS:
            existing.setdefault(emotion, {"Name": emotion, "File": std_expr_url.format(name=emotion)})

        fixed = []
        for e in existing.values():
            f_path = e.get("File") or ""
            if f_path and not f_path.startswith("/"):
                e["File"] = to_url(f_path)
            fixed.append(e)
        refs["Expressions"] = fixed

        # ── Motions ──
        motions = refs.get("Motions") or {}
        motions = {g: lst for g, lst in motions.items() if isinstance(lst, list) and lst}
        if not motions:
            loose = []
            seen = set()

            def _scan_loose(scan_dir: str):
                try:
                    for entry in sorted(os.listdir(scan_dir)):
                        if entry.lower().endswith(".motion3.json") and entry not in seen:
                            seen.add(entry)
                            loose.append({"Name": entry, "File": to_url(os.path.join(scan_dir, entry))})
                except OSError:
                    pass

            _scan_loose(model_dir)
            motions_sub = os.path.join(model_dir, "motions")
            if os.path.isdir(motions_sub):
                _scan_loose(motions_sub)

            if loose:
                motions["Emotions"] = loose
                logger.info(f"[WebBridge] Registered {len(loose)} loose motion files for the web client.")
        else:
            for group, entries in motions.items():
                for m in entries:
                    m_path = m.get("File") or ""
                    if m_path and not m_path.startswith("/"):
                        m["File"] = to_url(m_path)
        if motions:
            refs["Motions"] = motions

        data["FileReferences"] = refs
        return data

    def setup_routes(self):
        web_client_dir = os.path.join(self.app_dir, "web_client")
        vrm_dir = os.path.join(self.app_dir, "utils", "emotions", "vrm")
        live2d_res_dir = os.path.join(self.app_dir, "utils", "emotions", "live2d")
        
        if not os.path.exists(web_client_dir):
            os.makedirs(web_client_dir, exist_ok=True)
            
        self.app.mount("/static", StaticFiles(directory=web_client_dir), name="static")
        self.app.mount("/assets", StaticFiles(directory=os.path.join(self.project_dir, "assets")), name="assets")
        
        if os.path.exists(vrm_dir):
            self.app.mount("/vrm", StaticFiles(directory=vrm_dir), name="vrm")

        if os.path.exists(live2d_res_dir):
            self.app.mount(
                "/app/utils/emotions/live2d",
                StaticFiles(directory=live2d_res_dir),
                name="l2d_resources",
            )

        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            index_path = os.path.join(web_client_dir, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return HTMLResponse("<h1>Web Client Not Found</h1>")

        @self.app.get("/api/config")
        async def get_config():
            char_name = self.signals.current_active_character or "None"
            chat_id = "default"
            try:
                config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
                chat_id = config.get("character_list", {}).get(char_name, {}).get("current_chat", "default")
            except Exception:
                pass
            return {
                "active_character": char_name,
                "chat_id": chat_id,
                "user_name": self._resolve_user_name(char_name) if char_name != "None" else "User"
            }

        @self.app.get("/api/chats/{char_name}")
        async def get_chats(char_name: str):
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config.get("character_list", {}).get(char_name, {})
            current_chat = char_info.get("current_chat", "default")
            chats = char_info.get("chats", {})

            result = []
            user_name = self._resolve_user_name(char_name)
            for chat_id, chat in chats.items():
                content = chat.get("chat_content", {})
                last_text = ""
                if content:
                    last_msg = max(content.values(), key=lambda m: m.get("sequence_number", 0))
                    cur_v = last_msg.get("current_variant_id", "default")
                    last_text = next(
                        (v.get("text", "") for v in last_msg.get("variants", []) if v.get("variant_id") == cur_v),
                        ""
                    )
                last_text = (last_text
                             .replace("{{user}}", user_name)
                             .replace("{{char}}", char_name)
                             .replace("{{User}}", user_name)
                             .replace("{{Char}}", char_name))
                result.append({
                    "id": chat_id,
                    "name": chat.get("name", chat_id),
                    "is_branch": bool(chat.get("is_branch")),
                    "is_current": chat_id == current_chat,
                    "message_count": len(content),
                    "last_message": (last_text[:90] + "…") if len(last_text) > 90 else last_text,
                })

            result.sort(key=lambda c: c["name"].lower())
            return {"chats": result}

        @self.app.post("/api/chat/switch")
        async def switch_chat(request: Request):
            data = await request.json()
            char_name = data.get("character")
            chat_id = data.get("chat_id")
            if not char_name or not chat_id:
                return {"status": "error", "message": "Missing character or chat_id"}

            def _switch():
                config = self.signals.configuration_characters.load_configuration()
                char_data = config.get("character_list", {}).get(char_name)
                if not char_data or chat_id not in char_data.get("chats", {}):
                    return False
                char_data["current_chat"] = chat_id
                self.signals.configuration_characters.save_configuration_edit(config)
                return True

            ok = await asyncio.to_thread(_switch)
            if not ok:
                return {"status": "error", "message": "Chat not found"}

            await self.manager.broadcast({
                "type": "chat_switched",
                "character": char_name,
                "chat_id": chat_id
            })
            return {"status": "ok"}

        @self.app.get("/api/variables/{char_name}")
        async def get_variables(char_name: str):
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config.get("character_list", {}).get(char_name, {})
            current_chat = char_info.get("current_chat", "default")
            chat = char_info.get("chats", {}).get(current_chat, {})
            state = chat.get("variables_state", {}) or {}
            schema = char_info.get("sow_variables", []) or []

            variables = []
            for var in schema:
                vid = var.get("id")
                if vid not in state:
                    continue
                variables.append({
                    "id": vid,
                    "name": var.get("name", vid),
                    "icon": var.get("icon", ""),
                    "type": var.get("type", "int"),
                    "value": state.get(vid),
                    "max": var.get("max") if var.get("type") == "int" else None,
                })
            return {"variables": variables}

        @self.app.get("/api/avatar_config/{char_name}")
        async def get_avatar_config(char_name: str):
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config["character_list"].get(char_name, {})
            
            mode = char_info.get("current_sow_system_mode", "Nothing")
            img_folder = char_info.get("expression_images_folder", "")
            l2d_folder = char_info.get("live2d_model_folder", "")
            vrm_file = char_info.get("vrm_model_file", "")
            
            if img_folder:
                img_web = self._web_path(img_folder)
                img_folder = img_web if img_web else ""
            model_json_path = await asyncio.to_thread(self._find_model_json, l2d_folder)
            l2d_url = f"/api/l2d_model/{char_name}" if model_json_path else ""

            if vrm_file:
                vrm_web = self._web_path(vrm_file)
                vrm_file = vrm_web if vrm_web else ""

            return {
                "mode": mode,
                "expression_images_folder": img_folder,
                "live2d_model_file": l2d_url,
                "vrm_model_file": vrm_file,
                "emotion_motions": char_info.get("emotion_motions", {}) or {},
                "emotion_expressions": char_info.get("emotion_expressions", {}) or {},
            }

        @self.app.get("/api/l2d_model/{char_name}")
        async def get_l2d_model(char_name: str):
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config["character_list"].get(char_name, {})
            l2d_folder = char_info.get("live2d_model_folder", "")

            model_json_path = await asyncio.to_thread(self._find_model_json, l2d_folder)
            if not model_json_path:
                return JSONResponse({"error": "Live2D model not found"}, status_code=404)

            try:
                payload = await asyncio.to_thread(self._build_l2d_model_payload, model_json_path)
            except Exception as e:
                logger.error(f"[WebBridge] Failed to build L2D payload: {e}")
                return JSONResponse({"error": str(e)}, status_code=500)

            return JSONResponse(
                payload,
                headers={"Cache-Control": "no-store"},
            )

        @self.app.get("/api/characters")
        async def get_characters():
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            chars = []
            for name, info in config.get("character_list", {}).items():
                chars.append({
                    "name": name,
                    "title": info.get("character_title", "") or "",
                    "chat_count": len(info.get("chats", {}) or {}),
                    "is_active": name == self.signals.current_active_character,
                })
            return {"characters": chars}

        @self.app.post("/api/character/switch")
        async def switch_character(request: Request):
            data = await request.json()
            char_name = data.get("character")
            if char_name:
                asyncio.create_task(self.signals.open_chat(char_name))
                await self.manager.broadcast({
                    "type": "character_changed",
                    "character": char_name
                })
                return {"status": "ok"}
            return {"status": "error"}

        @self.app.get("/api/background")
        async def get_background():
            bg_path = await asyncio.to_thread(self.signals.configuration_settings.get_main_setting, "chat_background_image")
            if bg_path and bg_path != "None" and os.path.exists(bg_path):
                return FileResponse(bg_path)
            return HTMLResponse("No background", status_code=404)

        @self.app.get("/api/history/{char_name}")
        async def get_history(char_name: str, offset: int = 0, limit: int = 50):
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config["character_list"].get(char_name, {})
            current_chat = char_info.get("current_chat", "default")
            chat_content = char_info.get("chats", {}).get(current_chat, {}).get("chat_content", {})

            user_name = self._resolve_user_name(char_name)

            messages = []
            for msg_id, msg_data in sorted(chat_content.items(), key=lambda x: x[1].get("sequence_number", 0)):
                current_variant_id = msg_data.get("current_variant_id", "default")
                variant = next(
                    (v for v in msg_data.get("variants", []) if v["variant_id"] == current_variant_id),
                    {}
                )
                text = variant.get("text", "")
                created_at = variant.get("created_at", "") or ""

                processed_text = (text.replace("{{user}}", user_name)
                                      .replace("{{char}}", char_name)
                                      .replace("{{User}}", user_name)
                                      .replace("{{Char}}", char_name)
                                      .replace("<USER>", user_name)
                                      .replace("<CHAR>", char_name))

                variants = msg_data.get("variants", [])
                variant_count = len(variants) if isinstance(variants, list) else 1
                current_idx = next((i for i, v in enumerate(variants) if v.get("variant_id") == current_variant_id), 0) if variant_count else 0

                messages.append({
                    "id": msg_id,
                    "is_user": msg_data.get("is_user", True),
                    "text": processed_text,
                    "created_at": created_at,
                    "author": user_name if msg_data.get("is_user", True) else (msg_data.get("author_name") or char_name),
                    "variant_count": variant_count,
                    "variant_index": current_idx,
                })
            
            if messages:
                total = len(messages)
                start_idx = max(0, total - offset - limit)
                end_idx = total - offset
                history_slice = messages[start_idx:end_idx]
            else:
                history_slice = []
                
            return {"history": history_slice}

        @self.app.delete("/api/messages/{message_id}")
        async def delete_message_api(message_id: str, request: Request):
            data = await request.json()
            char_name = data.get("character")
            
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config["character_list"].get(char_name, {})
            conv_method = char_info.get("conversation_method", "Local LLM")
            
            asyncio.create_task(self.signals.delete_message(char_name, conv_method, message_id))
            
            await self.manager.broadcast({"type": "message_deleted", "id": message_id})
            return {"status": "ok"}

        @self.app.patch("/api/messages/{message_id}")
        async def edit_message_api(message_id: str, request: Request):
            data = await request.json()
            char_name = data.get("character")
            new_text = data.get("text")
            
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config.get("character_list", {}).get(char_name, {})
            current_chat = char_info.get("current_chat", "default")
            chats = char_info.get("chats", {})
            
            updated_on_disk = False
            if current_chat in chats:
                chat_content = chats[current_chat].get("chat_content", {})
                if message_id in chat_content:
                    msg_data = chat_content[message_id]
                    current_variant_id = msg_data.get("current_variant_id", "default")
                    
                    for variant in msg_data.get("variants", []):
                        if variant["variant_id"] == current_variant_id:
                            variant["text"] = new_text
                            updated_on_disk = True
                            break
            
            if updated_on_disk:
                await asyncio.to_thread(self.signals.configuration_characters.save_configuration_edit, config)
                
                if message_id in self.signals.messages:
                    processed_text = self.signals.markdown_to_html(new_text)
                    user_name = self.signals.configuration_settings.get_user_data("user_name") or "User"
                    processed_text = (processed_text.replace("{{user}}", user_name)
                                .replace("{{char}}", char_name)
                                .replace("{{User}}", user_name)
                                .replace("{{Char}}", char_name))
                    
                    self.signals.messages[message_id]["label"].setText(processed_text)
                    self.signals.messages[message_id]["text"] = new_text
                
                await self.manager.broadcast({"type": "message_edited", "id": message_id, "text": new_text})
                return {"status": "ok"}
                
            return {"status": "error", "message": "Message not found in database"}

        @self.app.post("/api/messages/{message_id}/regenerate")
        async def regenerate_message_api(message_id: str, request: Request):
            data = await request.json()
            char_name = data.get("character")
            
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config["character_list"].get(char_name, {})
            conv_method = char_info.get("conversation_method", "Local LLM")
            
            asyncio.create_task(self.signals.regenerate_message(conv_method, char_name, message_id))
            return {"status": "ok"}

        @self.app.post("/api/messages/{message_id}/variant")
        async def switch_variant_api(message_id: str, request: Request):
            data = await request.json()
            char_name = data.get("character")
            direction = data.get("direction", 1)
            try:
                direction = int(direction)
            except Exception:
                direction = 1
            if direction not in (-1, 1):
                direction = 1 if direction > 0 else -1
            result = self.signals.switch_message_variant(char_name, message_id, direction)
            if not result:
                return JSONResponse({"status": "error", "message": "No variants"}, status_code=400)
            await self.manager.broadcast({
                "type": "message_variant_changed",
                "id": message_id,
                "text": result["text"],
                "current": result["current"] + 1,
                "total": result["total"]
            })
            return {"status": "ok", "current": result["current"] + 1, "total": result["total"], "text": result["text"]}

        @self.app.post("/api/generation/stop")
        async def stop_generation_api():
            self.signals.stop_generation()
            return {"status": "ok"}

        @self.app.post("/api/voice/stt")
        async def stt_api(request: Request):
            form = await request.form()
            audio_file = form.get("audio")
            char_name = form.get("character")
            
            if not audio_file or not char_name:
                return {"status": "error", "message": "Missing audio or character"}

            audio_bytes = await audio_file.read()
            temp_path = os.path.join(self.app_dir, "cache", f"web_stt_{os.getpid()}.webm")
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            
            with open(temp_path, "wb") as f:
                f.write(audio_bytes)
                
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config["character_list"].get(char_name, {})
            conv_method = char_info.get("conversation_method", "Local LLM")

            def _transcribe():
                if not hasattr(self, "_whisper_model"):
                    self._whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
                
                segments, info = self._whisper_model.transcribe(temp_path, beam_size=5)
                full_text = "".join([segment.text for segment in segments])
                return full_text.strip()

            try:
                text = await asyncio.to_thread(_transcribe)
                os.remove(temp_path)
            except Exception as e:
                logger.error(f"Web STT Error: {e}")
                return {"status": "error", "message": str(e)}

            if text and len(text) > 2:
                self.signals.textEdit_write_user_message.setPlainText(text)
                
                await self.manager.broadcast({
                    "type": "user_message",
                    "text": text
                })
                
                asyncio.create_task(
                    self.signals.handle_user_message(char_name, conv_method)
                )
                
            return {"status": "ok", "text": text}

        @self.app.get("/api/avatar/{char_name}")
        async def get_avatar(char_name: str):
            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
            char_info = config["character_list"].get(char_name, {})
            path = char_info.get("character_avatar")
            if path and os.path.exists(path):
                return FileResponse(path)
            
            fallback_path = os.path.join(self.app_dir, "gui", "icons", "logotype.png")
            if os.path.exists(fallback_path):
                return FileResponse(fallback_path)
            return HTMLResponse("Avatar not found", status_code=404)

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            token = websocket.query_params.get("token")
            if not token or not secrets.compare_digest(token, self.auth_token):
                await websocket.close(code=1008)
                return

            await self.manager.connect(websocket)
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "user_input":
                        char_name = data.get("character")
                        text = data.get("text")
                        
                        if text and char_name:
                            self.signals.textEdit_write_user_message.setPlainText(text)
                            
                            config = await asyncio.to_thread(self.signals.configuration_characters.load_configuration)
                            char_info = config["character_list"].get(char_name, {})
                            conv_method = char_info.get("conversation_method", "Local LLM")
                            
                            await self.manager.broadcast({
                                "type": "user_message",
                                "text": text
                            }, exclude=websocket)
                            
                            asyncio.create_task(
                                self.signals.handle_user_message(char_name, conv_method)
                            )

            except WebSocketDisconnect:
                self.manager.disconnect(websocket)
            except Exception as e:
                logger.error(f"WebSocket Error: {e}")
                self.manager.disconnect(websocket)

    async def broadcast_chunk(self, chunk: str):
        await self.manager.broadcast({"type": "chunk", "text": chunk})
        
    async def broadcast_message_start(self):
        await self.manager.broadcast({"type": "message_start"})
        
    async def broadcast_message_end(self):
        await self.manager.broadcast({"type": "message_end"})

    async def broadcast_character_change(self, new_char: str):
        await self.manager.broadcast({"type": "character_changed", "character": new_char})

    async def broadcast_audio(self, b64_audio: str):
        await self.manager.broadcast({"type": "audio", "data": b64_audio})

async def run_web_server(interface_signals, host="127.0.0.1", port=8000, auth_token=None):
    bridge = WebBridge(interface_signals, auth_token=auth_token)
    config = uvicorn.Config(bridge.app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()