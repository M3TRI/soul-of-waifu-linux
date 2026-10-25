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

[ -d .git ] || die "$(t "This copy was not installed with git; run the installer again to update." \
                        "Эта копия установлена не через git; для обновления запустите установщик заново.")"
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) \
    || die "$(t "The branch has no upstream to update from." "У ветки нет источника для обновления.")"

header "$(t "Downloading the update" "Загрузка обновления")"
git fetch --quiet "${upstream%%/*}"
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

if git diff --quiet "$old" "$new" -- installer/client-requirements.txt; then
    info "$(t "Python packages unchanged." "Python-пакеты без изменений.")"
else
    header "$(t "Updating Python packages" "Обновление Python-пакетов")"
    export PATH="$HOME/.local/bin:$PATH" UV_LINK_MODE=copy
    uv pip install --python .venv/bin/python -r installer/client-requirements.txt
fi

# The server of this computer, if it was installed from this folder.
if [ -f "$SERVER_ENV" ] && grep -qF "$APP_DIR/installer/sow-server.sh" "$HOME/.local/bin/sow-server" 2>/dev/null; then
    if git diff --quiet "$old" "$new" -- server; then
        info "$(t "Server unchanged." "Сервер без изменений.")"
    elif docker info >/dev/null 2>&1; then
        header "$(t "Updating the server" "Обновление сервера")"
        compose_cmd build
        compose_cmd up -d
        ok "$(t "Server restarted." "Сервер перезапущен.")"
    else
        warn "$(t "The server needs an update, but Docker needs sudo here: run 'sow-server update' in a terminal." \
                  "Серверу нужно обновление, но Docker здесь требует sudo: выполните в терминале 'sow-server update'.")"
    fi
fi

ok "$(t "Update finished. Restart the app." "Обновление завершено. Перезапустите программу.")"
