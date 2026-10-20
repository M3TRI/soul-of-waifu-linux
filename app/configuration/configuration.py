import os
import shutil
import re
import uuid as uuid_lib
import uuid
import json
import logging
import datetime
import hashlib
import threading
import traceback
from typing import Optional
import copy

logger = logging.getLogger("Configuration")

class ConfigurationSettings():
    """
    A class that manages a JSON configuration file containing application settings and user data.
    """
    def __init__(self):
        self.settings_path = "app/configuration/settings.json"

    def load_configuration(self):
        """
        Loads and returns the configuration data from the JSON file.
        """
        if not os.path.exists(self.settings_path):
            
            return {
                "main_settings": {
                    "conversation_method": "0",
                    "stt_method": "0",
                    "sow_system_status": "",
                    "emotions_method": "",
                    "program_language": "0",
                    "input_device": "0",
                    "output_device": "0",
                    "translator": "0",
                    "target_language": "0",
                    "context_size": 8192,
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "frequency_penalty": 0.0,
                    "presence_penalty": 0.0,
                    "stop_strings": "",
                    "reasoning_mode": True,
                    "reasoning_effort": "medium",
                    "soul_memory_reasoning_effort": "none",
                    "soul_stage_reasoning_effort": "none"
                },
                "user_data": {
                    "default_persona": "None",
                    "personas": {},
                    "presets": {},
                    "current_character_image": "None"
                }
            }
        with open(self.settings_path, 'r', encoding='utf-8') as file:
            return json.load(file)

    def save_configuration_edit(self, data):
        """
        Saves provided configuration data to the JSON file.
        """
        with open(self.settings_path, 'w', encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)

    def update_main_setting(self, setting, value):
        """
        Updates a specific main setting in the configuration.

        Args:
            setting (str): The key of the main setting to update.
            value (any): The new value to assign to the specified key.
        """
        configuration_data = self.load_configuration()
        
        if "main_settings" not in configuration_data:
            configuration_data["main_settings"] = {}
        
        configuration_data["main_settings"][setting] = value
        self.save_configuration_edit(configuration_data)

    def get_main_setting(self, setting):
        """
        Retrieves the value of a main setting from the configuration.

        Args:
            setting (str): The key of the main setting to retrieve.

        Returns:
            value (any): The value associated with the specified key, or None if the key is not found.
        """
        configuration_data = self.load_configuration()
        return configuration_data["main_settings"].get(setting, None)

    def update_user_data(self, key, value):
        """
        Updates a user data field in the configuration.

        Args:
            key (str): The key of the user data field to update.
            value (any): The new value to assign to the specified key.
        """
        configuration_data = self.load_configuration()
        
        if "user_data" not in configuration_data:
            configuration_data["user_data"] = {}
        
        configuration_data["user_data"][key] = value
        self.save_configuration_edit(configuration_data)

    def get_user_data(self, key):
        """
        Retrieves a user data field from the configuration.

        Args:
            key (str): The key of the user data field to retrieve.

        Returns:
            value (any): The value associated with the specified key, or None if the key is not found.
        """
        configuration_data = self.load_configuration()
        return configuration_data["user_data"].get(key, None)
    
    def update_preset(self, preset_name, preset_data):
        config = self.load_configuration()
        if "user_data" not in config:
            config["user_data"] = {}
        if "presets" not in config["user_data"]:
            config["user_data"]["presets"] = {}

        config["user_data"]["presets"][preset_name] = preset_data
        self.save_configuration_edit(config)

    def get_all_presets(self):
        return self.load_configuration().get("user_data", {}).get("presets", {})
    
    def delete_preset(self, name):
        presets = self.load_configuration().get("user_data", {}).get("presets", {})

        if name in presets:
            del presets[name]

            self.update_user_data("presets", presets)

    def update_lorebook(self, name, lorebook_data):
        """
        Adds or updates a single lorebook entry in the configuration.
        """
        config = self.load_configuration()
        if "user_data" not in config:
            config["user_data"] = {}
        if "lorebooks" not in config["user_data"]:
            config["user_data"]["lorebooks"] = {}

        config["user_data"]["lorebooks"][name] = lorebook_data
        self.save_configuration_edit(config)
    
    def delete_lorebook(self, name):
        """
        Deletes a lorebook by name from the configuration.
        """
        config = self.load_configuration()
        lorebooks = config.get("user_data", {}).get("lorebooks", {})

        if name in lorebooks:
            del lorebooks[name]
            config["user_data"]["lorebooks"] = lorebooks
            self.save_configuration_edit(config)

    def save_lorebooks(self, lorebooks):
        """
        Replaces all existing lorebooks with the provided dictionary of lorebooks.
        """
        config = self.load_configuration()
        if "user_data" not in config:
            config["user_data"] = {}

        config["user_data"]["lorebooks"] = lorebooks
        self.save_configuration_edit(config)
    
class ConfigurationAPI():
    """
    A class for managing API tokens stored in a JSON configuration file.
    """
    def __init__(self):
        self.api_tokens_path = "app/configuration/api.json"

    def load_configuration(self):
        """
        Loads the current API token configuration from the JSON file.
        """
        if not os.path.exists(self.api_tokens_path):
            return {}
        with open(self.api_tokens_path, 'r', encoding='utf-8') as file:
            return json.load(file)

    def save_configuration_edit(self, data):
        """
        Saves provided configuration data directly to the JSON file.
        """
        with open(self.api_tokens_path, 'w', encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
    
    def save_api_token(self, variable, variable_value):
        """
        Saves or updates an API token in the configuration file.
        
        Args:
            variable (str): Variable name.
            value (any): Variable value.
        """
        configuration_data = self.load_configuration()
        
        configuration_data[variable] = variable_value
        self.save_configuration_edit(configuration_data)

    def get_token(self, api):
        """
        Retrieves the value of an API token from the configuration file.
        """
        configuration_data = self.load_configuration()
        
        return configuration_data.get(api)

class ConfigurationCharacters():
    """
    Manages character data with SHARDED storage.
    """
    INDEX_VERSION = 2

    _cache: Optional[dict] = None
    _serialized: dict = {}
    _shard_rels: dict = {}
    _loaded_index_mtime: Optional[float] = None
    _lock = threading.RLock()

    def __init__(self):
        self.characters_path = "app/configuration/characters.json"
        self.shards_dir = os.path.join("app", "configuration", "characters")
        self.configuration_data = self.load_configuration()

    def _shard_abs(self, rel: str) -> str:
        return os.path.join("app", "configuration", *rel.split("/"))

    def _new_shard_rel(self, name: str) -> str:
        safe = re.sub(r'[^A-Za-z0-9_-]', '_', name).strip('_') or "character"
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
        return f"characters/{safe}_{digest}.json"

    @staticmethod
    def _atomic_write_text(path: str, text: str):
        tmp = f"{path}.tmp{os.getpid()}"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)

    def load_configuration(self):
        cls = ConfigurationCharacters
        with cls._lock:
            try:
                idx_mtime = os.path.getmtime(self.characters_path)
            except OSError:
                idx_mtime = None

            if cls._cache is not None and cls._loaded_index_mtime == idx_mtime:
                return cls._cache

            return self._reload_from_disk(idx_mtime)

    def _reload_from_disk(self, idx_mtime):
        cls = ConfigurationCharacters

        if not os.path.exists(self.characters_path):
            cls._cache = {}
            cls._serialized = {}
            cls._shard_rels = {}
            cls._loaded_index_mtime = idx_mtime
            return {}

        try:
            with open(self.characters_path, 'r', encoding='utf-8') as file:
                index = json.load(file)
        except Exception as e:
            logger.error(f"[Characters] Failed to read index: {e}")
            cls._cache = {}
            cls._serialized = {}
            cls._shard_rels = {}
            cls._loaded_index_mtime = idx_mtime
            return {}

        if not isinstance(index, dict):
            index = {}
        char_index = index.get("character_list", {})
        if not isinstance(char_index, dict):
            char_index = {}

        if index.get("version") != self.INDEX_VERSION or any(
            not (isinstance(v, dict) and v.get("__shard__")) for v in char_index.values()
        ):
            return self._migrate_legacy(char_index)

        merged = {"character_list": {}}
        serialized = {}
        shard_rels = {}
        for name, meta in char_index.items():
            rel = meta.get("__shard__")
            if not rel:
                continue
            shard_path = self._shard_abs(rel)
            try:
                with open(shard_path, 'r', encoding='utf-8') as f:
                    cdata = json.load(f)
            except FileNotFoundError:
                logger.warning(f"[Characters] Shard missing for '{name}' ({rel}) — skipped.")
                continue
            except Exception as e:
                logger.error(f"[Characters] Failed to read shard for '{name}': {e}")
                continue
            if not isinstance(cdata, dict):
                continue
            merged["character_list"][name] = cdata
            shard_rels[name] = rel
            try:
                serialized[name] = json.dumps(cdata, ensure_ascii=False, indent=2)
            except Exception:
                pass

        cls._cache = merged
        cls._serialized = serialized
        cls._shard_rels = shard_rels
        cls._loaded_index_mtime = idx_mtime
        return merged

    def _migrate_legacy(self, char_index: dict) -> dict:
        cls = ConfigurationCharacters
        logger.info(f"[Characters] Migrating {len(char_index)} character(s) to sharded storage...")

        try:
            backup_path = self.characters_path + ".legacy_backup"
            if os.path.exists(self.characters_path) and not os.path.exists(backup_path):
                shutil.copy2(self.characters_path, backup_path)
        except Exception as e:
            logger.warning(f"[Characters] Could not keep a legacy backup copy: {e}")

        os.makedirs(self.shards_dir, exist_ok=True)

        merged = {"character_list": {}}
        serialized = {}
        shard_rels = {}
        new_index = {"version": self.INDEX_VERSION, "character_list": {}}

        for name, cdata in char_index.items():
            if not isinstance(cdata, dict):
                continue
            rel = self._new_shard_rel(name)
            try:
                text = json.dumps(cdata, ensure_ascii=False, indent=2)
                self._atomic_write_text(self._shard_abs(rel), text)
            except Exception as e:
                logger.error(f"[Characters] Migration write failed for '{name}': {e}")
                continue
            new_index["character_list"][name] = {"__shard__": rel}
            merged["character_list"][name] = cdata
            serialized[name] = text
            shard_rels[name] = rel

        try:
            self._atomic_write_text(
                self.characters_path,
                json.dumps(new_index, ensure_ascii=False, indent=2),
            )
        except Exception as e:
            logger.error(f"[Characters] Failed to write sharded index: {e}")

        cls._cache = merged
        cls._serialized = serialized
        cls._shard_rels = shard_rels
        try:
            cls._loaded_index_mtime = os.path.getmtime(self.characters_path)
        except OSError:
            cls._loaded_index_mtime = None

        logger.info(f"[Characters] Migration complete ({len(merged['character_list'])} shard(s) written).")
        return merged

    def save_configuration_edit(self, data):
        cls = ConfigurationCharacters
        with cls._lock:
            if not isinstance(data, dict):
                logger.error("[Characters] save_configuration_edit expects a dict — skipped.")
                return

            if cls._cache is None:
                self.load_configuration()

            new_list = data.get("character_list", {}) or {}
            if not isinstance(new_list, dict):
                new_list = {}

            new_serialized = {}
            new_rels = {}

            for name, cdata in new_list.items():
                rel = cls._shard_rels.get(name) or self._new_shard_rel(name)
                try:
                    text = json.dumps(cdata, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.error(f"[Characters] Serialization failed for '{name}': {e}")
                    continue
                if text != cls._serialized.get(name):
                    try:
                        self._atomic_write_text(self._shard_abs(rel), text)
                    except Exception as e:
                        logger.error(f"[Characters] Shard write failed for '{name}': {e}")
                        continue
                new_serialized[name] = text
                new_rels[name] = rel

            for name in list(cls._shard_rels.keys()):
                if name not in new_list:
                    rel = cls._shard_rels.pop(name)
                    try:
                        os.remove(self._shard_abs(rel))
                    except OSError:
                        pass
                    cls._serialized.pop(name, None)

            index = {
                "version": self.INDEX_VERSION,
                "character_list": {n: {"__shard__": r} for n, r in new_rels.items()},
            }
            try:
                self._atomic_write_text(
                    self.characters_path,
                    json.dumps(index, ensure_ascii=False, indent=2),
                )
            except Exception as e:
                logger.error(f"[Characters] Failed to write index: {e}")
                return

            cls._serialized = new_serialized
            cls._shard_rels = new_rels
            cls._cache = data
            try:
                cls._loaded_index_mtime = os.path.getmtime(self.characters_path)
            except OSError:
                cls._loaded_index_mtime = None

    def save_character_card(self, character_name, character_title, character_avatar, 
                            character_description, character_personality, first_message, 
                            scenario, example_messages, alternate_greetings, selected_persona, 
                            selected_system_prompt_preset, selected_lorebook, elevenlabs_voice_id, 
                            voice_type, rvc_enabled, rvc_file, expression_images_folder, 
                            live2d_model_folder, vrm_model_file, conversation_method, 
                            selected_lorebooks=None, sow_variables=None):
        """
        Saves or updates a character's card information in the configuration.
        """
        cached_avatar_path = character_avatar
        
        if character_avatar and os.path.exists(character_avatar):
            try:
                cache_dir = os.path.join("app", "cache", "avatars")
                os.makedirs(cache_dir, exist_ok=True)
                
                sanitized_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', character_name)
                
                _, ext = os.path.splitext(character_avatar)
                if not ext:
                    ext = ".png"
                
                dest_filename = f"{sanitized_name}_avatar{ext.lower()}"
                dest_path = os.path.join(cache_dir, dest_filename)
                
                abs_src = os.path.abspath(character_avatar)
                abs_dest = os.path.abspath(dest_path)
                
                if abs_src != abs_dest:
                    shutil.copy2(abs_src, abs_dest)
                
                cached_avatar_path = f"app/cache/avatars/{dest_filename}"
                
            except Exception as e:
                print(f"[Error] Failed to cache avatar for {character_name}: {e}")
                cached_avatar_path = character_avatar

        if selected_lorebooks is None:
            selected_lorebooks = []
            if selected_lorebook and selected_lorebook != "None":
                selected_lorebooks = [selected_lorebook]

        configuration_data = self.load_configuration()
        if 'character_list' not in configuration_data:
            configuration_data['character_list'] = {}

        message_id = str(uuid.uuid4())

        variants = [
            {"variant_id": "default", "text": first_message}
        ]

        for i, greeting in enumerate(alternate_greetings):
            variants.append({
                "variant_id": f"v{i+1}",
                "text": greeting.strip()
            })

        main_message = {
            "message_id": message_id,
            "sequence_number": 1,
            "author_name": character_name,
            "is_user": False,
            "current_variant_id": "default",
            "variants": variants
        }

        chat_content = {message_id: main_message}

        chat_history = []
        chat_history.append({
            "user": "",
            "character": first_message
        })
        
        character_information_parts = []

        if character_description.strip():
            character_information_parts.append(character_description.strip())

        if character_personality.strip():
            character_information_parts.append(f"{character_personality.strip()}.")

        if scenario.strip():
            character_information_parts.append(f"Here is the dialogue script: {scenario.strip()}.\n\n")

        if example_messages.strip():
            character_information_parts.append(
                f"[Example Chat]:\n{example_messages.strip()}\n\n"
                "Your response should follow the same pattern and style as above."
            )

        if character_information_parts:
            character_information_parts.append("Respond as the character, do not break role or add extra explanations.")

        character_information = " ".join(character_information_parts)

        initial_state = {}
        if sow_variables:
            for var in sow_variables:
                initial_state[var["id"]] = var["default"]

        configuration_data['character_list'][character_name] = {
            "character_avatar": cached_avatar_path,
            "character_title": character_title,
            "character_description": character_description,
            "character_personality": character_personality,
            "first_message": first_message,
            "scenario": scenario,
            "example_messages": example_messages,
            "alternate_greetings": alternate_greetings,
            "selected_persona": selected_persona,
            "selected_system_prompt_preset": selected_system_prompt_preset,
            "selected_lorebook": selected_lorebook,
            "selected_lorebooks": selected_lorebooks,
            "current_text_to_speech": "Nothing",
            "elevenlabs_voice_id": elevenlabs_voice_id,
            "voice_type": voice_type,
            "rvc_enabled": rvc_enabled,
            "rvc_file": rvc_file,
            "current_sow_system_mode": "Nothing",
            "expression_images_folder": expression_images_folder,
            "live2d_model_folder": live2d_model_folder,
            "vrm_model_file": vrm_model_file,
            "conversation_method": conversation_method,
            "character_information": character_information,
            "sow_variables": sow_variables if sow_variables else [],
            "current_chat": "default",
            "chats": {
                "default": {
                    "name": "default",
                    "created_at": datetime.datetime.now().isoformat(),
                    "current_emotion": "neutral",
                    "summary_text": "",
                    "last_summarized_sequence": 0,
                    "chat_history": chat_history,
                    "chat_content": chat_content,
                    "variables_state": initial_state
                }
            }
        }

        self.save_configuration_edit(configuration_data)
    
    def update_chat_history(self, character_name):
        """
        Updates the chat history for a specific character based on their chat content.
        """
        configuration_data = self.load_configuration()
        character_data = configuration_data['character_list'].get(character_name)

        if not character_data or "chats" not in character_data:
            return

        current_chat_id = character_data.get("current_chat", None)
        if not current_chat_id or current_chat_id not in character_data["chats"]:
            return
        
        chat_data = character_data["chats"][current_chat_id]
        chat_content = chat_data.get("chat_content", {})
        
        chat_history = []
        user_turn = {"user": "", "character": ""}

        for msg_id, msg_data in sorted(chat_content.items(), key=lambda x: x[1].get("sequence_number", 0)):
            current_variant_id = msg_data.get("current_variant_id", "default")
            current_text = next(
                (variant["text"] for variant in msg_data.get("variants", []) if variant["variant_id"] == current_variant_id),
                ""
            )

            if msg_data["is_user"]:
                if user_turn["user"] or user_turn["character"]:
                    chat_history.append(user_turn)
                    user_turn = {"user": current_text, "character": ""}
                else:
                    user_turn["user"] = current_text
            else:
                if user_turn["user"] or not user_turn["character"]:
                    user_turn["character"] = current_text
                else:
                    user_turn["character"] += "\n" + current_text

        if user_turn["user"] or user_turn["character"]:
            chat_history.append(user_turn)

        chat_data["chat_history"] = chat_history
        character_data["chats"][current_chat_id] = chat_data
        configuration_data['character_list'][character_name] = character_data
        
        self.save_configuration_edit(configuration_data)

    def add_message_to_config(self, character_name, author_name, is_user, text, message_id,
                              variables_state_before=None):
        """
        Adds a new message to the chat content of a specific character in the configuration.
        """
        configuration_data = self.load_configuration()
        character_data = configuration_data['character_list'].get(character_name)

        if not character_data or "chats" not in character_data:
            return

        current_chat_id = character_data.get("current_chat", None)
        if not current_chat_id or current_chat_id not in character_data["chats"]:
            return

        chat_data = character_data["chats"][current_chat_id]

        chat_content = chat_data.get("chat_content", {})

        sequence_number = len(chat_content) + 1

        existing_entry = chat_content.get(message_id, {})

        new_message = {
            "message_id": message_id,
            "sequence_number": sequence_number,
            "author_name": author_name,
            "is_user": is_user,
            "current_variant_id": "default",
            "variants": [
                {
                    "variant_id": "default",
                    "text": text,
                    "created_at": datetime.datetime.now().isoformat()
                }
            ]
        }

        for extra_key in ("image", "image_status", "image_prompt", "tts_audio", "attachments"):
            if extra_key in existing_entry:
                new_message[extra_key] = existing_entry[extra_key]

        if variables_state_before is None and "variables_state_before" in existing_entry:
            variables_state_before = existing_entry.get("variables_state_before")
        if isinstance(variables_state_before, dict) and variables_state_before:
            new_message["variables_state_before"] = dict(variables_state_before)

        chat_content[message_id] = new_message
        chat_data["chat_content"] = chat_content

        character_data["chats"][current_chat_id] = chat_data
        configuration_data['character_list'][character_name] = character_data

        self.save_configuration_edit(configuration_data)

        self.renumber_sequence_numbers(character_name)
        self.update_chat_history(character_name)

    def regenerate_message_in_config(self, character_name, message_id, text,
                                     variables_state_before=None):
        """
        Regenerates a message by adding a new variant to the same message_id.
        """
        configuration_data = self.load_configuration()
        character_data = configuration_data['character_list'].get(character_name)

        if not character_data or "chats" not in character_data:
            logger.error(f"Character '{character_name}' not found or has no chats.")
            return

        current_chat_id = character_data.get("current_chat")
        if not current_chat_id or current_chat_id not in character_data["chats"]:
            logger.error(f"Current chat for '{character_name}' is invalid or missing.")
            return

        chat_data = character_data["chats"][current_chat_id]
        chat_content = chat_data.get("chat_content", {})

        msg = chat_content.get(message_id)
        if not msg:
            logger.error(f"Message with ID {message_id} not found.")
            return

        variant_ids = [v["variant_id"] for v in msg.get("variants", [])]
        regen_count = sum(1 for vid in variant_ids if vid.startswith("regen_"))
        new_variant_id = f"regen_{regen_count}"

        msg["variants"].append({
            "variant_id": new_variant_id,
            "text": text
        })

        msg["current_variant_id"] = new_variant_id

        if isinstance(variables_state_before, dict) and variables_state_before:
            msg["variables_state_before"] = dict(variables_state_before)

        chat_content[message_id] = msg
        chat_data["chat_content"] = chat_content
        character_data["chats"][current_chat_id] = chat_data
        configuration_data['character_list'][character_name] = character_data

        self.save_configuration_edit(configuration_data)

        self.renumber_sequence_numbers(character_name)
        self.update_chat_history(character_name)

    def edit_chat_message(self, message_id, character_name, edited_text):
        """
        Edits the text of an existing chat message inside the currently selected chat of a character.
        """
        try:
            configuration_data = self.load_configuration()
            character_list = configuration_data.get("character_list", {})

            if character_name not in character_list:
                logger.error(f"Character {character_name} not found")
                return False

            char_data = character_list[character_name]

            current_chat_id = char_data.get("current_chat")
            if not current_chat_id or current_chat_id not in char_data["chats"]:
                logger.error(f"Current chat for {character_name} is invalid or missing.")
                return False

            chat_data = char_data["chats"][current_chat_id]
            chat_content = chat_data.get("chat_content", {})

            if message_id not in chat_content:
                logger.error(f"Message {message_id} not found")
                return False

            target = chat_content[message_id]
            current_variant_id = target.get("current_variant_id", "default")
            variants = target.get("variants", [])

            updated = False

            for variant in variants:
                if variant["variant_id"] == current_variant_id:
                    variant["text"] = edited_text
                    updated = True
                    break

            if not updated and variants:
                logger.warning(f"Current variant {current_variant_id} not found in variants. Creating new default variant.")
                variants.append({
                    "variant_id": "default",
                    "text": edited_text
                })
                target["variants"] = variants
                target["current_variant_id"] = "default"
                updated = True

            if not variants:
                target["variants"] = [{
                    "variant_id": "default",
                    "text": edited_text
                }]
                target["current_variant_id"] = "default"
                updated = True

            if not updated:
                logger.warning(f"Failed to update message {message_id}")
                return False

            chat_content[message_id] = target
            chat_data["chat_content"] = chat_content
            char_data["chats"][current_chat_id] = chat_data
            configuration_data["character_list"][character_name] = char_data

            self.save_configuration_edit(configuration_data)

            self.renumber_sequence_numbers(character_name)
            self.update_chat_history(character_name)

            return True

        except Exception as e:
            logger.error(f"Edit message error: {e}")
            traceback.print_exc()
            return False
    
    def delete_chat_message(self, message_id, character_name):
        """
        Deletes a message from the currently selected chat of a character.
        """
        try:
            configuration_data = self.load_configuration()
            character_list = configuration_data.get("character_list", {})

            if character_name not in character_list:
                logger.error(f"Character {character_name} not found")
                return False

            char_data = character_list[character_name]

            current_chat_id = char_data.get("current_chat")
            if not current_chat_id or current_chat_id not in char_data["chats"]:
                logger.error(f"Current chat for {character_name} is invalid or missing.")
                return False

            chat_data = char_data["chats"][current_chat_id]
            chat_content = chat_data.get("chat_content", {})
            
            if message_id in chat_content:
                removed = chat_content.pop(message_id)
                snap = removed.get("variables_state_before")
                if isinstance(snap, dict) and snap:
                    chat_data["variables_state"] = dict(snap)
                    logger.info(f"[State] Rolled back variables_state after deleting message {message_id}.")
                
            chat_data["chat_content"] = chat_content
            char_data["chats"][current_chat_id] = chat_data
            configuration_data["character_list"][character_name] = char_data
            
            self.save_configuration_edit(configuration_data)
            
            self.renumber_sequence_numbers(character_name)
            self.update_chat_history(character_name)
            
            return True
        
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
            traceback.print_exc()
            return False
    
    def delete_chat_messages(self, character_name, message_ids):
        """
        Deletes multiple messages from the currently selected chat of a character.
        """
        try:
            configuration_data = self.load_configuration()
            character_list = configuration_data.get("character_list", {})

            if character_name not in character_list:
                logger.error(f"Character {character_name} not found")
                return False

            char_data = character_list[character_name]

            current_chat_id = char_data.get("current_chat")
            if not current_chat_id or current_chat_id not in char_data["chats"]:
                logger.error(f"Current chat for {character_name} is invalid or missing.")
                return False

            chat_data = char_data["chats"][current_chat_id]
            chat_content = chat_data.get("chat_content", {})

            ids_set = set(message_ids or [])
            candidates = [
                chat_content[mid] for mid in ids_set
                if mid in chat_content and isinstance(chat_content[mid].get("variables_state_before"), dict)
                and chat_content[mid].get("variables_state_before")
            ]
            if candidates:
                earliest = min(candidates, key=lambda m: m.get("sequence_number", 0))
                chat_data["variables_state"] = dict(earliest["variables_state_before"])
                logger.info(f"[State] Rolled back variables_state after deleting {len(candidates)} message(s).")

            for message_id in message_ids:
                if message_id in chat_content:
                    del chat_content[message_id]

            chat_data["chat_content"] = chat_content
            char_data["chats"][current_chat_id] = chat_data
            configuration_data["character_list"][character_name] = char_data

            self.save_configuration_edit(configuration_data)
            
            self.renumber_sequence_numbers(character_name)
            self.update_chat_history(character_name)
            
            return True
        
        except Exception as e:
            logger.error(f"Error deleting messages: {e}")
            traceback.print_exc()
            return False
    
    def create_new_chat(self, character_name, conversation_method, new_name, new_description, new_personality, new_scenario, new_first_message, new_example_messages, new_alternate_greetings, new_creator_notes, chat_name):
        """
        Creates a new chat session for the specified character with updated information, including support for variants.

        Args:
            character_name (str): Name of the existing character to start a new chat with.
            conversation_method (str): Method used for conversation.
            new_name (str): New name for the character (optional).
            new_description (str): Character description.
            new_personality (str): Personality traits.
            new_scenario (str): Scenario or background context.
            new_first_message (str): First message from the character.
            new_example_messages (list): Example messages for training.
            new_alternate_greetings (list): Alternative greetings as message variants.
            new_creator_notes (str): Creator notes or title.
            chat_name (str): The custom name for this chat (used as chat_id).
        """
        configuration_data = self.load_configuration()
        character_list = configuration_data.get("character_list", {})

        if character_name not in character_list:
            logger.error(f"Character '{character_name}' not found in configuration.")
            return

        character_data = character_list[character_name]

        new_chat_id = str(uuid.uuid4())

        current_chat_id = character_data.get("current_chat", None)
        if not current_chat_id or current_chat_id not in character_data["chats"]:
            return

        message_id = str(uuid.uuid4())

        variants = [
            {"variant_id": "default", "text": new_first_message}
        ]

        for i, greeting in enumerate(new_alternate_greetings):
            variants.append({
                "variant_id": f"v{i+1}",
                "text": greeting.strip()
            })

        main_message = {
            "message_id": message_id,
            "sequence_number": 1,
            "author_name": new_name or character_name,
            "is_user": False,
            "current_variant_id": "default",
            "variants": variants
        }

        chat_content = {message_id: main_message}

        chat_history = []
        chat_history.append({
            "user": "",
            "character": new_first_message
        })

        system_prompt_parts = []

        if new_description.strip():
            system_prompt_parts.append(new_description.strip())

        if new_personality.strip():
            system_prompt_parts.append(f"{new_personality.strip()}.")

        if new_scenario.strip():
            system_prompt_parts.append(f"Here is the dialogue script: {new_scenario.strip()}.\n\n")

        if new_example_messages.strip():
            system_prompt_parts.append(
                f"[Example Chat]:\n{new_example_messages.strip()}\n\n"
                "Your response should follow the same pattern and style as above.[End Example Chat]"
            )

        system_prompt_parts.append("Respond as the character, do not break role or add extra explanations.")
        system_prompt = " ".join(system_prompt_parts)

        sow_variables = character_data.get("sow_variables", [])
        initial_state = {}
        for var in sow_variables:
            initial_state[var["id"]] = var["default"]

        character_data.update({
            "character_title": new_creator_notes,
            "character_description": new_description,
            "character_personality": new_personality,
            "first_message": new_first_message,
            "scenario": new_scenario,
            "example_messages": new_example_messages,
            "alternate_greetings": new_alternate_greetings,
            "conversation_method": conversation_method,
            "character_information": system_prompt,
            "system_prompt": system_prompt
        })

        new_chat = {
            "name": chat_name,
            "created_at": datetime.datetime.now().isoformat(),
            "current_emotion": "neutral",
            "chat_history": chat_history,
            "chat_content": chat_content,
            "variables_state": initial_state
        }
        
        if "chats" not in character_data:
            character_data["chats"] = {}

        character_data["chats"][new_chat_id] = new_chat
        character_data["current_chat"] = new_chat_id

        if new_name and new_name != character_name:
            del character_list[character_name]
            character_list[new_name] = character_data
        else:
            character_list[character_name] = character_data

        configuration_data['character_list'] = character_list
        self.save_configuration_edit(configuration_data)
        logger.info(f"Created new chat '{chat_name}' for character '{character_name}'")
    
    def branch_chat(self, character_name: str, source_chat_id: str,
                    fork_message_id: Optional[str] = None, new_name: Optional[str] = None) -> Optional[str]:
        """
        Creates a branch: a full copy of `source_chat_id` truncated UP TO AND
        INCLUDING `fork_message_id` (or the whole chat when fork_message_id is
        None). The original chat is never modified.

        Returns the new chat_id, or None on any problem.
        """
        try:
            configuration_data = self.load_configuration()
            char_data = configuration_data.get('character_list', {}).get(character_name)
            if not char_data:
                logger.error(f"[Branch] Character '{character_name}' not found.")
                return None

            chats = char_data.get("chats", {})
            source = chats.get(source_chat_id)
            if not source:
                logger.error(f"[Branch] Source chat '{source_chat_id}' not found for '{character_name}'.")
                return None

            content = source.get("chat_content", {})

            if fork_message_id is not None:
                fork_entry = content.get(fork_message_id)
                if not fork_entry:
                    logger.error(f"[Branch] fork_message_id '{fork_message_id}' not in source chat.")
                    return None
                fork_seq = fork_entry.get("sequence_number", 0)
                kept = {
                    mid: copy.deepcopy(msg)
                    for mid, msg in content.items()
                    if msg.get("sequence_number", 0) <= fork_seq
                }
            else:
                kept = copy.deepcopy(content)

            if not kept:
                logger.error("[Branch] Fork point produced an empty chat — refusing.")
                return None

            new_chat_id = str(uuid.uuid4())

            new_chat = copy.deepcopy(source)
            new_chat["name"] = (new_name or f"{source.get('name', 'Chat')} (branch)").strip()
            new_chat["chat_content"] = kept
            new_chat["is_branch"] = True
            new_chat["parent_chat_id"] = source_chat_id
            new_chat["fork_message_id"] = fork_message_id
            new_chat["created_at"] = datetime.datetime.now().isoformat()

            history = []
            user_turn = {"user": "", "character": ""}
            for mid, msg in sorted(kept.items(), key=lambda x: x[1].get("sequence_number", 0)):
                current_variant_id = msg.get("current_variant_id", "default")
                current_text = next(
                    (v["text"] for v in msg.get("variants", [])
                     if v["variant_id"] == current_variant_id),
                    ""
                )
                if msg.get("is_user"):
                    if user_turn["user"] or user_turn["character"]:
                        history.append(user_turn)
                        user_turn = {"user": current_text, "character": ""}
                    else:
                        user_turn["user"] = current_text
                else:
                    if user_turn["user"] or not user_turn["character"]:
                        user_turn["character"] = current_text
                    else:
                        user_turn["character"] += "\n" + current_text
            if user_turn["user"] or user_turn["character"]:
                history.append(user_turn)
            new_chat["chat_history"] = history

            chats[new_chat_id] = new_chat
            char_data["chats"] = chats

            char_data["current_chat"] = new_chat_id
            configuration_data['character_list'][character_name] = char_data

            self.save_configuration_edit(configuration_data)
            logger.info(
                f"[Branch] Created branch '{new_chat['name']}' ({new_chat_id}) "
                f"from '{source_chat_id}' at message '{fork_message_id or 'END'}' "
                f"({len(kept)} messages kept)."
            )
            return new_chat_id

        except Exception as e:
            logger.error(f"[Branch] branch_chat failed: {e}", exc_info=True)
            return None

    def cleanup_branch_links(self, character_name: str, deleted_chat_id: str) -> int:
        """
        After deleting `deleted_chat_id`, clears parent links of its branches.
        Returns the number of affected branches.
        """
        try:
            configuration_data = self.load_configuration()
            char_data = configuration_data.get('character_list', {}).get(character_name)
            if not char_data:
                return 0
            affected = 0
            for chat in char_data.get("chats", {}).values():
                if chat.get("parent_chat_id") == deleted_chat_id:
                    chat["parent_chat_id"] = None
                    affected += 1
            if affected:
                self.save_configuration_edit(configuration_data)
            return affected
        except Exception as e:
            logger.error(f"[Branch] cleanup_branch_links failed: {e}", exc_info=True)
            return 0

    def get_character_data(self, name, key):
        """
        Retrieves a specific value from a character's configuration data.
        """
        configuration_data = self.load_configuration()
        return configuration_data["character_list"][name].get(key, None)

    def delete_character(self, character_name):
        """
        Deletes a character from the configuration file.
        """
        configuration_data = self.load_configuration()
        if "character_list" in configuration_data and character_name in configuration_data["character_list"]:
            del configuration_data["character_list"][character_name]
            self.save_configuration_edit(configuration_data)
            logger.info(f"Character '{character_name}' has been deleted successfully.")
        else:
            logger.error(f"Character '{character_name}' not found in the configuration.")

    @staticmethod
    def _apply_single_state_update(var_schema: dict, current_val, delta_or_val,
                                   operation: str = "add"):
        var_type = var_schema.get("type", "int")
        if isinstance(delta_or_val, list):
            val = current_val
            for item in delta_or_val:
                val = ConfigurationCharacters._apply_single_state_update(
                    var_schema, val, item, operation
                )
            return val

        if var_type == "int":
            min_val = var_schema.get("min", 0)
            max_val = var_schema.get("max", 100)
            try:
                if operation == "add":
                    new_val = int(float(current_val)) + int(float(delta_or_val))
                else:
                    new_val = int(float(delta_or_val))
            except (ValueError, TypeError):
                logging.getLogger("Configuration").warning(
                    f"[State] Unparseable int delta {delta_or_val!r} for "
                    f"'{var_schema.get('id')}' — keeping {current_val!r}"
                )
                return current_val
            return max(min_val, min(max_val, new_val))

        if var_type == "bool":
            if isinstance(delta_or_val, str):
                return delta_or_val.strip().lower() in ("true", "1", "yes", "да", "on")
            return bool(delta_or_val)

        if var_type == "list":
            if not isinstance(current_val, list):
                current_val = []
            val_str = str(delta_or_val).strip()
            if val_str.startswith("+"):
                item_name = val_str[1:].strip()
                if item_name and item_name not in current_val:
                    current_val = current_val + [item_name]
            elif val_str.startswith("-"):
                item_name = val_str[1:].strip()
                if item_name in current_val:
                    current_val = [x for x in current_val if x != item_name]
            elif val_str:
                if val_str not in current_val:
                    current_val = current_val + [val_str]
            return current_val

        return str(delta_or_val)

    def apply_state_updates(self, character_name: str, updates: dict,
                            operation: str = "add") -> dict:
        cls = ConfigurationCharacters
        applied = {}
        if not isinstance(updates, dict) or not updates:
            return applied

        with cls._lock:
            config = self.load_configuration()
            char_data = config.get("character_list", {}).get(character_name)
            if not char_data:
                return applied

            current_chat_id = char_data.get("current_chat", "default")
            chat_obj = char_data.get("chats", {}).get(current_chat_id)
            if not isinstance(chat_obj, dict):
                return applied

            variables_state = chat_obj.setdefault("variables_state", {})
            sow_variables = char_data.get("sow_variables", [])

            for var_id, delta_or_val in updates.items():
                var_schema = next((v for v in sow_variables if v.get("id") == var_id), None)
                if not var_schema:
                    logger.warning(f"[State] No schema for variable '{var_id}' — skipped.")
                    continue
                current_val = variables_state.get(var_id, var_schema.get("default"))
                new_val = self._apply_single_state_update(
                    var_schema, current_val, delta_or_val, operation
                )
                variables_state[var_id] = new_val
                applied[var_id] = new_val

            if applied:
                self.save_configuration_edit(config)
        return applied

    def set_variables_state(self, character_name: str, state: dict) -> bool:
        cls = ConfigurationCharacters
        with cls._lock:
            config = self.load_configuration()
            char_data = config.get("character_list", {}).get(character_name)
            if not char_data:
                return False
            current_chat_id = char_data.get("current_chat", "default")
            chat_obj = char_data.get("chats", {}).get(current_chat_id)
            if not isinstance(chat_obj, dict):
                return False
            chat_obj["variables_state"] = dict(state or {})
            self.save_configuration_edit(config)
            return True

    def get_variables_state(self, character_name: str) -> dict:
        config = self.load_configuration()
        char_data = config.get("character_list", {}).get(character_name, {})
        current_chat_id = char_data.get("current_chat", "default")
        chat_obj = char_data.get("chats", {}).get(current_chat_id, {})
        state = chat_obj.get("variables_state", {})
        return dict(state) if isinstance(state, dict) else {}

    def renumber_sequence_numbers(self, character_name, conversation_method=None):
        config = self.load_configuration()
        char_data = config["character_list"].get(character_name)
        if not char_data:
            return
        
        if conversation_method is None:
            conversation_method = char_data.get("conversation_method")

        chat_id = char_data.get("current_chat")
        if not chat_id or "chats" not in char_data:
            return
        
        chat_data = char_data["chats"][chat_id]
        if not chat_data:
            return
        
        chat_content = chat_data.get("chat_content", {})
        sorted_messages = sorted(chat_content.items(), key=lambda x: x[1].get("sequence_number", float('inf')))

        for idx, (msg_id, msg) in enumerate(sorted_messages):
            msg["sequence_number"] = idx + 1

        chat_data["chat_content"] = chat_content
        char_data["chats"][chat_id] = chat_data
        config["character_list"][character_name] = char_data

        self.save_configuration_edit(config)