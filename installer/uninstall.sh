#!/usr/bin/env bash
# Interactive removal of Soul of Waifu, started from the installer menu. Each part is asked
# about separately; the user's data (characters, chats, settings) defaults to "keep".
# System packages, Docker and the NVIDIA Container Toolkit stay: other programs may use them.
set -euo pipefail
APP_DIR=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
. "$APP_DIR/installer/lib/ui.sh"
. "$APP_DIR/installer/lib/survey.sh"
. "$APP_DIR/installer/lib/system.sh"
. "$APP_DIR/installer/lib/server.sh"
log_start uninstall "$@"

DATA_DIR=$SOW_HOME/data
size_of() { du -sh "$1" 2>/dev/null | cut -f1; }

header "$(t "Remove Soul of Waifu" "Удаление Soul of Waifu")"
explain "$(t "Each part is asked about separately; nothing is removed without a yes." \
             "Про каждую часть будет отдельный вопрос; без «да» ничего не удаляется.")"

# --- server -------------------------------------------------------------------------------
if [ -f "$SERVER_ENV" ]; then
    docker info >/dev/null 2>&1 || DOCKER_CMD=(sudo docker)
    header "$(t "Server" "Сервер")"
    explain "$(t "Containers and images of the server (llama.cpp, voices, gateway), the sow-server command" \
                 "Контейнеры и образы сервера (llama.cpp, голоса, gateway), команда sow-server")" \
            "$(t "and the automatic update timer, if any." "и таймер автообновления, если он есть.")"
    if ask_yn "$(t "Remove the server?" "Удалить сервер?")" y; then
        compose_cmd down --rmi all --remove-orphans || warn "$(t "Some containers or images could not be removed." "Часть контейнеров или образов удалить не удалось.")"
        if systemctl --user list-unit-files sow-server-update.timer >/dev/null 2>&1; then
            systemctl --user disable --now sow-server-update.timer 2>/dev/null || true
        fi
        rm -f "$HOME/.config/systemd/user/sow-server-update.service" "$HOME/.config/systemd/user/sow-server-update.timer"
        rm -f "$HOME/.local/bin/sow-server"
        ok "$(t "Server removed." "Сервер удалён.")"
        explain "$(t "Downloaded models and server settings: $SERVER_DATA ($(size_of "$SERVER_DATA")), $SERVER_ENV" \
                     "Скачанные модели и настройки сервера: $SERVER_DATA ($(size_of "$SERVER_DATA")), $SERVER_ENV")"
        if ask_yn "$(t "Remove them too?" "Удалить и их?")" y; then
            # Files the containers wrote may belong to root when Docker ran rootful.
            rm -rf "$SERVER_DATA" 2>/dev/null || as_root rm -rf "$SERVER_DATA"
            rm -f "$SERVER_ENV"
            ok "$(t "Models and server settings removed." "Модели и настройки сервера удалены.")"
        fi
    fi
fi

# --- app ----------------------------------------------------------------------------------
header "$(t "App" "Программа")"
explain "$(t "Program folder $APP_DIR ($(size_of "$APP_DIR")) with its Python environment," \
             "Папка программы $APP_DIR ($(size_of "$APP_DIR")) вместе с Python-окружением,")" \
        "$(t "the soul-of-waifu command and the menu entry." "команда soul-of-waifu и пункт меню.")"
REMOVE_APP=no
ask_yn "$(t "Remove the app?" "Удалить программу?")" y && REMOVE_APP=yes

# --- user data ----------------------------------------------------------------------------
REMOVE_DATA=no
if [ -d "$DATA_DIR" ]; then
    header "$(t "Your data" "Ваши данные")"
    explain "$(t "Characters, chats, memory, settings and API keys: $DATA_DIR ($(size_of "$DATA_DIR"))." \
                 "Персонажи, чаты, память, настройки и API-ключи: $DATA_DIR ($(size_of "$DATA_DIR")).")" \
            "$(t "Kept by default: a new install picks them up again." \
                 "По умолчанию остаются: новая установка подхватит их снова.")"
    if ask_yn "$(t "Delete your data for good?" "Удалить ваши данные навсегда?")" n; then
        warn "$(t "This cannot be undone." "Это нельзя отменить.")"
        ask_yn "$(t "Really delete $DATA_DIR?" "Точно удалить $DATA_DIR?")" n && REMOVE_DATA=yes
    fi
fi

# The program folder last: this script lives in it.
if [ "$REMOVE_DATA" = yes ]; then
    rm -rf "$DATA_DIR"
    ok "$(t "Your data removed." "Ваши данные удалены.")"
fi
if [ "$REMOVE_APP" = yes ]; then
    rm -f "$HOME/.local/bin/soul-of-waifu" "$HOME/.local/share/applications/soul-of-waifu.desktop"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    rm -rf "$APP_DIR"
    rmdir "$SOW_HOME" "$SOW_CONF_DIR" 2>/dev/null || true
    ok "$(t "App removed." "Программа удалена.")"
fi

header "$(t "Left in the system" "Осталось в системе")"
explain "$(t "Docker, the NVIDIA Container Toolkit and the system libraries stay installed: other programs" \
             "Docker, NVIDIA Container Toolkit и системные библиотеки остались установлены: ими могут")" \
        "$(t "may use them. Remove them with your package manager if you do not need them." \
             "пользоваться другие программы. Если не нужны, удалите их пакетным менеджером.")"
