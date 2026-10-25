#!/usr/bin/env bash
# Non-interactive update of an installed Soul of Waifu, started by the app's "Update" button
# (or by hand). Asks nothing: it changes only the app folder, its .venv and, when the server
# runs on this computer, the server containers. System packages and the user data folder
# (~/.local/share/soul-of-waifu/data) are never touched here.
#   1. fast-forward the program folder to the remote branch
#   2. reinstall Python packages if their list changed
#   3. rebuild and restart the local server if this folder runs one
# Exit code 0 means updated (or already up to date); the last line says what to do next.
set -euo pipefail
APP_DIR=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
cd "$APP_DIR"
. installer/lib/ui.sh
. installer/lib/survey.sh
. installer/lib/system.sh
. installer/lib/server.sh
log_start update "$@"

[ -d .git ] || die "$(t "This copy was not installed with git; run the installer again to update." \
                        "Эта копия установлена не через git; для обновления запустите установщик заново.")"

# Phase 2 runs from the freshly merged copy of this script (see the exec below), so the
# new version's own update steps apply right away.
if [ "${1:-}" = --after-merge ]; then
    old=$2 new=$3
else
    upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) \
        || die "$(t "The branch has no upstream to update from." "У ветки нет источника для обновления.")"

    header "$(t "Downloading the update" "Загрузка обновления")"
    git fetch --quiet "${upstream%%/*}"
    # Installs from the docker-split preview follow main once it has been merged there.
    remote=${upstream%%/*}
    if [ "$upstream" = "$remote/docker-split" ] && git rev-parse -q --verify "$remote/main" >/dev/null \
        && git merge-base --is-ancestor "$remote/docker-split" "$remote/main"; then
        git branch --quiet --set-upstream-to="$remote/main"
        upstream=$remote/main
        info "$(t "This install now follows the main branch." "Эта установка теперь следит за веткой main.")"
    fi
    old=$(git rev-parse HEAD)
    new=$(git rev-parse "$upstream")
    if [ "$old" = "$new" ]; then
        ok "$(t "Already up to date." "Обновлений нет.")"
        exit 0
fi
git log --format='   %s' "$old..$new"

# User data lives outside this folder (app/utils/user_data.py), so a clean fast-forward is
# all it takes; local edits to program files stop it instead of being overwritten.
if ! git diff --quiet HEAD; then
    git status --short
    die "$(t "Files of the program were changed in $APP_DIR (listed above); the update would overwrite them. Your data is not in this folder." \
             "В $APP_DIR изменены файлы самой программы (список выше); обновление их перезапишет. Ваших данных в этой папке нет.")"
fi
git merge --ff-only --quiet "$new"
ok "$(t "Program updated." "Программа обновлена.")"
exec bash "$APP_DIR/installer/update.sh" --after-merge "$old" "$new"
fi

if [ ! -x .venv/bin/python ]; then
    :   # server-only install: no app environment here
elif git diff --quiet "$old" "$new" -- installer/client-requirements.txt; then
    info "$(t "Python packages unchanged." "Python-пакеты без изменений.")"
else
    header "$(t "Updating Python packages" "Обновление Python-пакетов")"
    export PATH="$HOME/.local/bin:$PATH" UV_LINK_MODE=copy
    uv pip install --python .venv/bin/python -r installer/client-requirements.txt
fi

# The server of this computer, if it was installed from this folder.
if [ -f "$SERVER_ENV" ] && grep -qF "$APP_DIR/installer/sow-server.sh" "$HOME/.local/bin/sow-server" 2>/dev/null; then
    # Without direct Docker access: sudo asks for the password in a terminal (sow-server
    # update); from the app's Update button there is no terminal, so it must not prompt.
    if ! docker info >/dev/null 2>&1; then
        if [ -t 0 ]; then DOCKER_CMD=(sudo docker); else DOCKER_CMD=(sudo -n docker); fi
    fi
    if ! dk info >/dev/null 2>&1; then
        warn "$(t "The server needs a restart for the new version, but Docker needs sudo here: run 'sow-server update' in a terminal." \
                  "Серверу нужен перезапуск под новую версию, но Docker здесь требует sudo: выполните в терминале 'sow-server update'.")"
    elif git diff --quiet "$old" "$new" -- server; then
        # Only the reported version changes: compose recreates just the gateway.
        compose_cmd up -d
        info "$(t "Server unchanged." "Сервер без изменений.")"
    else
        header "$(t "Updating the server" "Обновление сервера")"
        get_images
        compose_cmd up -d
        ok "$(t "Server restarted." "Сервер перезапущен.")"
    fi
fi

ok "$(t "Update finished. Restart the app." "Обновление завершено. Перезапустите программу.")"
