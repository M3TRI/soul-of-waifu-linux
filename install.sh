#!/usr/bin/env bash
# Soul of Waifu one-command installer:
#   curl -fsSL https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux/-/raw/main/install.sh | bash
# Downloads the project into ~/.local/share/soul-of-waifu/app (or uses this checkout) and
# starts the interactive installer, which asks before every change to the system.
set -euo pipefail

REPO=https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux
# Branch this installer belongs to; the one-command install clones it.
BRANCH=${SOW_BRANCH:-main}

# Run from a checkout: use it as is.
src=${BASH_SOURCE[0]:-}
if [ -n "$src" ] && [ -f "$(dirname "$(readlink -f "$src")")/installer/main.sh" ]; then
    exec bash "$(dirname "$(readlink -f "$src")")/installer/main.sh" </dev/tty
fi

APP_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/soul-of-waifu/app

# The log of this run starts here and installer/lib/log.sh continues it: everything printed
# (colours stripped, the pairing token masked) plus "##" records of the answers.
SOW_LOG=${XDG_STATE_HOME:-$HOME/.local/state}/soul-of-waifu/logs/install-$(date +%Y%m%d-%H%M%S).log
mkdir -p "$(dirname "$SOW_LOG")"
[ -t 1 ] && export SOW_TTY=1
exec > >(tee >(sed -u -E 's/\x1b\[[0-9;?]*[A-Za-z]//g; s/.*\r//; s/(token=)[^&[:space:]]+/\1***/g' >>"$SOW_LOG")) 2>&1
SOW_LOG_FD1=$(readlink /proc/$$/fd/1 2>/dev/null || true)
export SOW_LOG SOW_LOG_FD1
note() { printf '%s ## %s\n' "$(date '+%F %T')" "$*" >>"$SOW_LOG"; }
note "Soul of Waifu install.sh (branch $BRANCH), app folder $APP_DIR"

# Ask the language once here; installer/main.sh reads it from SOW_LANG.
case "${LC_ALL:-${LANG:-}}" in ru*) default=2 ;; *) default=1 ;; esac
printf 'Language / Язык:\n   1) English\n   2) Русский\n   [%s]: ' "$default"
read -r answer </dev/tty || answer=""
case "${answer:-$default}" in 2) SOW_LANG=ru ;; *) SOW_LANG=en ;; esac
export SOW_LANG
note "language: '$answer' -> $SOW_LANG"
msg() { if [ "$SOW_LANG" = ru ]; then echo "$2"; else echo "$1"; fi; }

if [ -d "$APP_DIR/.git" ]; then
    msg "Updating $APP_DIR" "Обновление $APP_DIR"
    # Copies installed before the user data folder kept settings and characters inside the
    # program folder: move them to ~/.local/share/soul-of-waifu/data first (as the app's
    # user_data.py would), so that git can update the folder.
    conf=$(dirname "$APP_DIR")/data/configuration
    if [ ! -d "$conf" ] && ! git -C "$APP_DIR" diff --quiet -- app/configuration 2>/dev/null; then
        mkdir -p "$conf/characters"
        for f in settings.json api.json characters.json discord_bindings.json discord_users.json; do
            [ -f "$APP_DIR/app/configuration/$f" ] && cp -a "$APP_DIR/app/configuration/$f" "$conf/"
        done
        cp -a "$APP_DIR"/app/configuration/characters/*.json "$conf/characters/" 2>/dev/null || true
        git -C "$APP_DIR" checkout -- app/configuration
        git -C "$APP_DIR" clean -fq -- app/configuration/characters
        msg "Your settings and characters were moved to $conf" "Ваши настройки и персонажи перенесены в $conf"
    fi
    git -C "$APP_DIR" pull --ff-only
elif [ -f "$APP_DIR/installer/main.sh" ]; then
    :
else
    msg "Soul of Waifu will be downloaded into $APP_DIR (about 450 MB)." \
        "Soul of Waifu будет скачан в $APP_DIR (около 450 МБ)."
    mkdir -p "$APP_DIR"
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 --branch "$BRANCH" "$REPO.git" "$APP_DIR"
    else
        curl -fL "$REPO/-/archive/$BRANCH/soul-of-waifu-linux-$BRANCH.tar.gz" | tar -xz -C "$APP_DIR" --strip-components=1
    fi
fi
exec bash "$APP_DIR/installer/main.sh" </dev/tty
