#!/usr/bin/env bash
# Soul of Waifu one-command installer:
#   curl -fsSL https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux/-/raw/docker-split/install.sh | bash
# Downloads the project into ~/.local/share/soul-of-waifu/app (or uses this checkout) and
# starts the interactive installer, which asks before every change to the system.
set -euo pipefail

REPO=https://gitlab.projectmiku.cc/opensrc/soul-of-waifu-linux
# Branch this installer belongs to; the one-command install clones it.
BRANCH=${SOW_BRANCH:-docker-split}

# Run from a checkout: use it as is.
src=${BASH_SOURCE[0]:-}
if [ -n "$src" ] && [ -f "$(dirname "$(readlink -f "$src")")/installer/main.sh" ]; then
    exec bash "$(dirname "$(readlink -f "$src")")/installer/main.sh" </dev/tty
fi

APP_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/soul-of-waifu/app

# Ask the language once here; installer/main.sh reads it from SOW_LANG.
case "${LC_ALL:-${LANG:-}}" in ru*) default=2 ;; *) default=1 ;; esac
printf 'Language / Язык:\n   1) English\n   2) Русский\n   [%s]: ' "$default"
read -r answer </dev/tty || answer=""
case "${answer:-$default}" in 2) SOW_LANG=ru ;; *) SOW_LANG=en ;; esac
export SOW_LANG
msg() { if [ "$SOW_LANG" = ru ]; then echo "$2"; else echo "$1"; fi; }

if [ -d "$APP_DIR/.git" ]; then
    msg "Updating $APP_DIR" "Обновление $APP_DIR"
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
