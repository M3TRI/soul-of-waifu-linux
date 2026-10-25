# shellcheck shell=bash
# UI client: system libraries, Python environment, connection to the server, launcher.
# The app runs from the downloaded folder ($APP_DIR) with its own .venv there.

client_packages() {
    local missing
    missing=$(missing_packages)
    [ -n "$missing" ] || return 0
    header "$(t "Libraries for the app" "Библиотеки для программы")"
    explain "$(t "The app's window, sound and microphone need these system packages:" \
                 "Окну программы, звуку и микрофону нужны эти системные пакеты:")" \
            "  $missing"
    [ -n "$PKG" ] || die "$(t "Install them with your package manager and run the installer again." \
                              "Установите их пакетным менеджером и запустите установщик снова.")"
    if [ "$PKG" = pacman ]; then
        explain "$(t "pacman -Syu also brings the system up to date (partial upgrades are unsupported on Arch)." \
                     "pacman -Syu заодно обновит систему (частичные обновления на Arch не поддерживаются).")"
    fi
    ask_yn "$(t "Install them with $PKG?" "Установить их через $PKG?")" y \
        || die "$(t "The app cannot run without them." "Без них программа не запустится.")"
    if [ "$PKG" = apt ]; then
        # Package names (t64 renames) are resolved against fresh package lists.
        as_root env DEBIAN_FRONTEND=noninteractive apt-get update </dev/null
        missing=$(missing_packages)
    fi
    # shellcheck disable=SC2086  # the list is meant to be split into package names
    if [ "$PKG" = pacman ]; then as_root pacman -Syu --needed $missing; else pkg_install $missing; fi
}

ensure_uv() {
    export PATH="$HOME/.local/bin:$PATH"
    # The uv cache is often on another filesystem than the app; copying is expected there.
    export UV_LINK_MODE=copy
    command -v uv >/dev/null 2>&1 && return 0
    explain "$(t "Python packages are installed with uv (astral.sh), into ~/.local/bin; the system Python is not touched." \
                 "Python-пакеты ставятся через uv (astral.sh) в ~/.local/bin; системный Python не затрагивается.")"
    ask_yn "$(t "Download and install uv?" "Скачать и установить uv?")" y || die "$(t "uv is required." "Нужен uv.")"
    curl -LsSf https://astral.sh/uv/install.sh | sh
}

client_python() {
    header "$(t "App environment" "Окружение программы")"
    explain "$(t "Python 3.11 and the app's packages go into $APP_DIR/.venv (about 1.5 GB)." \
                 "Python 3.11 и пакеты программы ставятся в $APP_DIR/.venv (около 1,5 ГБ).")"
    ensure_uv
    local py=$APP_DIR/.venv/bin/python
    # uv-managed Python only: distro Pythons may lack the headers PyAudio builds against.
    [ -x "$py" ] || run uv venv --python-preference only-managed --python 3.11 "$APP_DIR/.venv"
    run uv pip install --python "$py" -r "$APP_DIR/installer/client-requirements.txt"
    "$py" -c "import PyQt6.QtWebEngineWidgets, live2d.v3, onnxruntime" \
        || die "$(t "The app environment is incomplete." "Окружение программы собралось не полностью.")"
    ok "$(t "App environment ready." "Окружение программы готово.")"
}

# Saves the server connection into the app's settings (and points Local LLM at it).
client_pair() {
    local pairing=$1
    (cd "$APP_DIR" && .venv/bin/python -c "
import sys
from app.utils import user_data
user_data.setup()   # the data folder the settings are written to may not exist yet
from app.utils import sow_server
sow_server.save_pairing(sys.argv[1])
caps = sow_server.capabilities(force=True)
sys.exit(0 if caps else 3)" "$pairing")
}

ask_pairing() {
    header "$(t "Server connection" "Подключение к серверу")"
    explain "$(t "On the server computer run 'sow-server pair' (or look at the end of its installer output)" \
                 "На компьютере с сервером выполните 'sow-server pair' (или посмотрите конец вывода его установщика)")" \
            "$(t "and paste the line that starts with sow://" "и вставьте строку, которая начинается с sow://")"
    while true; do
        ask_text "$(t "Pairing string" "Строка подключения")" ""
        case "$ANSWER" in
            sow://*) ;;
            *) warn "$(t "It must start with sow://" "Она должна начинаться с sow://")"; continue ;;
        esac
        if client_pair "$ANSWER"; then
            ok "$(t "Connected to the server." "Подключено к серверу.")"
            return 0
        fi
        warn "$(t "Could not reach the server with this string (address, VPN, token or certificate)." \
                  "Не удалось подключиться к серверу по этой строке (адрес, VPN, токен или сертификат).")"
        ask_yn "$(t "Try another string?" "Попробовать другую строку?")" y || return 1
    done
}

client_launcher() {
    mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
    local entry=$HOME/.local/share/applications/soul-of-waifu.desktop
    if [ -f "$entry" ] && ! grep -q "^Exec=\"$HOME/.local/bin/soul-of-waifu\"" "$entry"; then
        explain "$(t "A 'Soul of Waifu' menu entry from another installation exists:" \
                     "Уже есть пункт меню 'Soul of Waifu' от другой установки:")" \
                "  $(grep -m1 '^Exec=' "$entry")"
        ask_yn "$(t "Replace it with this installation?" "Заменить его этой установкой?")" n || return 0
    fi
    cat > "$HOME/.local/bin/soul-of-waifu" <<EOF
#!/usr/bin/env bash
# Soul of Waifu app, written by the installer.
exec "$APP_DIR/start.sh" "\$@"
EOF
    chmod +x "$HOME/.local/bin/soul-of-waifu" "$APP_DIR/start.sh"
    cat > "$HOME/.local/share/applications/soul-of-waifu.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Soul of Waifu
Comment=AI companion
Exec="$HOME/.local/bin/soul-of-waifu"
Path=$APP_DIR
Icon=$APP_DIR/app/gui/icons/logotype.png
Terminal=false
Categories=Game;Chat;
EOF
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    # KDE Plasma shows a new entry only after its menu cache is rebuilt.
    local k
    for k in kbuildsycoca6 kbuildsycoca5; do
        if command -v "$k" >/dev/null 2>&1; then "$k" >/dev/null 2>&1 || true; break; fi
    done
    log_event "launcher: $HOME/.local/bin/soul-of-waifu, $HOME/.local/share/applications/soul-of-waifu.desktop"
    ok "$(t "Menu entry 'Soul of Waifu' and command 'soul-of-waifu' added." \
            "Добавлены пункт меню 'Soul of Waifu' и команда 'soul-of-waifu'.")"
    ensure_local_bin_on_path
}
