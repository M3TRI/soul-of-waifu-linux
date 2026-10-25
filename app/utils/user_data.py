"""
User data outside the program folder, so that updates and reinstalls never touch it.

Everything the app writes lives under DATA_DIR (~/.local/share/soul-of-waifu/data for the
installed copy, "<folder>-data" for other checkouts, SOW_DATA_DIR to override):

  configuration/  settings.json, api.json, characters.json, characters/  (configuration.py
                  reads these through CONFIG_DIR; the copies in app/configuration are the
                  shipped defaults)
  soul/ soul_stage/ cache/ app_data/ rvc_models/ local_llm/ backups/ logs/
                  folders the code addresses by relative path (.soul, app/cache, ...): in the
                  program folder they become symlinks into DATA_DIR
  assets/<backgrounds|ambient|emotions>/
                  files the user added next to the shipped ones; the program folder keeps a
                  symlink per file, so relative paths stored in characters keep working

setup() runs first thing at start-up (main.py). It moves data of an older layout here,
creates missing files from the shipped defaults and adds settings keys a new version
introduced. The upstream file list is the same as profile_backup.BACKUP_GROUPS.
"""
import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("User Data")

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SOW_HOME = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                         "soul-of-waifu")


def _default_data_dir() -> str:
    # The installed copy (install.sh puts it in ~/.local/share/soul-of-waifu/app) keeps its
    # data next to it; any other checkout (development, a manual clone) gets its own
    # "<folder>-data", so two copies never mix their characters.
    if os.path.realpath(APP_DIR) == os.path.realpath(os.path.join(_SOW_HOME, "app")):
        return os.path.join(_SOW_HOME, "data")
    return os.path.realpath(APP_DIR) + "-data"


DATA_DIR = os.environ.get("SOW_DATA_DIR") or _default_data_dir()
CONFIG_DIR = os.path.join(DATA_DIR, "configuration")
DEFAULTS_DIR = os.path.join(APP_DIR, "app", "configuration")

CONFIG_FILES = ["settings.json", "api.json", "characters.json"]
DISCORD_FILES = ["discord_bindings.json", "discord_users.json"]
# path in the program folder -> folder in DATA_DIR
LINKED_DIRS = {
    ".soul": "soul",
    ".soul_stage": "soul_stage",
    "app/cache": "cache",
    "app/data": "app_data",
    "assets/rvc_models": "rvc_models",
    "assets/local_llm": "local_llm",
    "Backups": "backups",
    "logs": "logs",
}
# Folders with shipped files where the user can add more.
MIXED_DIRS = ["assets/backgrounds", "assets/ambient", "assets/emotions"]


def data_path(*parts) -> str:
    return os.path.join(DATA_DIR, *parts)


def resolve(root: str, rel: str) -> str:
    """
    Where a program-relative path (as profile backups name files) lives on disk:
    app/configuration/<user file> is in CONFIG_DIR, anything else under root, where the
    linked folders already lead into DATA_DIR.
    """
    parts = rel.replace("\\", "/").split("/")
    if parts[:2] == ["app", "configuration"] and len(parts) > 2 and (
            parts[2] in CONFIG_FILES or parts[2] in ("characters", *DISCORD_FILES)):
        return os.path.join(CONFIG_DIR, *parts[2:])
    return os.path.join(os.path.abspath(root), *parts)


def _move_contents(src: str, dst: str):
    """Move everything from src into dst; on a name clash the copy already in dst wins."""
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if name == ".gitkeep":
            continue
        if not os.path.lexists(d):
            shutil.move(s, d)
        elif os.path.isdir(s) and os.path.isdir(d) and not os.path.islink(d):
            _move_contents(s, d)


def _link_dir(rel: str, target_name: str):
    link = os.path.join(APP_DIR, rel)
    target = data_path(target_name)
    os.makedirs(target, exist_ok=True)
    if os.path.islink(link):
        if os.path.realpath(link) == os.path.realpath(target):
            return
        os.remove(link)
    elif os.path.isdir(link):
        # Older layout: the data still sits in the program folder.
        _move_contents(link, target)
        shutil.rmtree(link)
        logger.info(f"Moved {rel} to {target}")
    elif os.path.exists(link):
        os.remove(link)
    os.makedirs(os.path.dirname(link), exist_ok=True)
    os.symlink(target, link)


def _shipped_files(rel: str):
    """Files of rel that belong to the program (tracked by git), or None without git."""
    try:
        out = subprocess.run(["git", "-C", APP_DIR, "ls-files", "-z", "--", rel],
                             capture_output=True, check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return {os.path.normpath(p) for p in out.decode("utf-8", "replace").split("\0") if p}


def _sync_mixed_dir(rel: str):
    folder = os.path.join(APP_DIR, rel)
    store = data_path(rel)
    os.makedirs(folder, exist_ok=True)
    os.makedirs(store, exist_ok=True)
    shipped = _shipped_files(rel)
    if shipped is not None:
        # Files the user added into the program folder: move them to the data folder.
        for root, _dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(root, name)
                relpath = os.path.normpath(os.path.relpath(path, APP_DIR))
                if os.path.islink(path) or relpath in shipped:
                    continue
                dest = os.path.join(store, os.path.relpath(path, folder))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if not os.path.exists(dest):
                    shutil.move(path, dest)
                else:
                    os.remove(path)
                os.symlink(dest, path)
    # Every stored file is visible at its old place in the program folder.
    links = []
    for root, _dirs, files in os.walk(store):
        for name in files:
            dest = os.path.join(root, name)
            path = os.path.join(folder, os.path.relpath(dest, store))
            if not os.path.lexists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.symlink(dest, path)
            links.append(os.path.relpath(path, APP_DIR))
    _git_exclude(links)


def _git_exclude(paths):
    """Hide links to user files from git status (local to this checkout, never committed)."""
    exclude = os.path.join(APP_DIR, ".git", "info", "exclude")
    if not paths or not os.path.isdir(os.path.dirname(exclude)):
        return
    try:
        with open(exclude, encoding="utf-8") as f:
            known = set(f.read().splitlines())
    except OSError:
        known = set()
    new = ["/" + p.replace(os.sep, "/") for p in paths if "/" + p.replace(os.sep, "/") not in known]
    if new:
        with open(exclude, "a", encoding="utf-8") as f:
            f.write("\n".join(new) + "\n")


def _git(*args) -> bool:
    try:
        subprocess.run(["git", "-C", APP_DIR, *args], capture_output=True, check=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _reset_program_copies():
    """
    After the user's files were copied out of app/configuration, put the program folder
    back to the shipped state, so that git can update it: tracked defaults restored,
    characters the user created there removed (their copies are in CONFIG_DIR now).
    """
    if not os.path.isdir(os.path.join(APP_DIR, ".git")):
        return
    rel = os.path.join("app", "configuration")
    # One path per call: a pathspec without tracked files would fail the whole command.
    for name in CONFIG_FILES + ["characters"]:
        _git("checkout", "--", os.path.join(rel, name))
    _git("clean", "-fq", "--", os.path.join(rel, "characters"))
    logger.info(f"User configuration moved to {CONFIG_DIR}")


def _add_missing_keys(dst: dict, src: dict) -> int:
    added = 0
    for key, value in src.items():
        if key not in dst:
            dst[key] = value
            added += 1
        elif isinstance(dst[key], dict) and isinstance(value, dict):
            added += _add_missing_keys(dst[key], value)
    return added


def _setup_configuration():
    first_run = not os.path.isdir(CONFIG_DIR)
    os.makedirs(os.path.join(CONFIG_DIR, "characters"), exist_ok=True)
    legacy_from_app = False
    for name in CONFIG_FILES:
        dest = os.path.join(CONFIG_DIR, name)
        if os.path.exists(dest):
            continue
        # A real (non-default) file from the older layout, or the shipped default.
        src = os.path.join(DEFAULTS_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, dest)
            legacy_from_app = True
    shards_src = os.path.join(DEFAULTS_DIR, "characters")
    if (first_run or legacy_from_app) and os.path.isdir(shards_src):
        for name in os.listdir(shards_src):
            dest = os.path.join(CONFIG_DIR, "characters", name)
            if name.endswith(".json") and not os.path.exists(dest):
                shutil.copy2(os.path.join(shards_src, name), dest)
    for name in DISCORD_FILES:
        src, dest = os.path.join(DEFAULTS_DIR, name), os.path.join(CONFIG_DIR, name)
        if os.path.exists(src) and not os.path.exists(dest):
            shutil.move(src, dest)
    if legacy_from_app:
        _reset_program_copies()
    # Settings keys added by a newer version; the user's values stay.
    for name in ("settings.json", "api.json"):
        default, user = os.path.join(DEFAULTS_DIR, name), os.path.join(CONFIG_DIR, name)
        try:
            with open(default, encoding="utf-8") as f:
                defaults = json.load(f)
            with open(user, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if _add_missing_keys(data, defaults):
            tmp = user + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, user)


def setup():
    """Prepare DATA_DIR and the links into it. Safe to run on every start."""
    os.makedirs(DATA_DIR, exist_ok=True)
    _setup_configuration()
    for rel, name in LINKED_DIRS.items():
        _link_dir(rel, name)
    for rel in MIXED_DIRS:
        try:
            _sync_mixed_dir(rel)
        except OSError as e:
            logger.warning(f"Could not sync {rel}: {e}")
