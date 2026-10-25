# shellcheck shell=bash
# Server part: configuration, TLS, images, start-up, model download, pairing string.
# Everything lives under the user's home; Docker volumes are plain bind-mounted folders.

SOW_HOME=${XDG_DATA_HOME:-$HOME/.local/share}/soul-of-waifu
SOW_CONF_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/soul-of-waifu
SERVER_ENV=$SOW_CONF_DIR/server.env
SERVER_DATA=$SOW_HOME/server
SOW_PORT_DEFAULT=8765
SOW_REGISTRY=ghcr.io/m3tri/soul-of-waifu-linux

# compose_cmd ARGS...: docker compose with this install's project, env file and GPU overlay.
compose_cmd() {
    local files=(-f "$APP_DIR/server/compose.yaml") overlay
    overlay=$(env_get SOW_GPU_OVERLAY)
    [ -n "$overlay" ] && files+=(-f "$APP_DIR/server/$overlay")
    SOW_COMMIT=$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo dev)
    # Same server code, same image: the tag is the git tree hash of server/.
    SOW_IMAGE_TAG=$(git -C "$APP_DIR" rev-parse --short=12 HEAD:server 2>/dev/null || echo dev)
    SOW_IMAGE_REPO=$SOW_REGISTRY
    export SOW_COMMIT SOW_IMAGE_TAG SOW_IMAGE_REPO
    dk compose --project-name soul-of-waifu --project-directory "$APP_DIR/server" \
        --env-file "$SERVER_ENV" "${files[@]}" "$@"
}

# env_get NAME: a value from server.env, empty when it or the file is missing (on a first
# install there is none yet: sed's exit code 2 would end the installer through pipefail).
env_get() { [ -f "$SERVER_ENV" ] || return 0; sed -n "s/^$1=//p" "$SERVER_ENV" | tail -n 1; }

# Address of this computer in the local network: a private IPv4 on a physical interface.
# The default route is no guide (with a full-tunnel VPN it points into the tunnel), and
# Docker bridges, libvirt and VPN interfaces are skipped.
lan_ip() {
    ip -4 -o addr show scope global 2>/dev/null \
        | awk '$2 !~ /^(docker|br-|virbr|veth|wg|tun|tap|tailscale|zt|lo)/ { sub(/\/.*/, "", $4); print $4 }' \
        | grep -E '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' | head -n 1
}

# Asks how the server is reached; sets SERVER_BIND, SERVER_HOST, SERVER_TLS.
ask_network() {
    local mode=$1
    SERVER_PORT=$SOW_PORT_DEFAULT
    if [ "$mode" = local ]; then
        SERVER_BIND=127.0.0.1 SERVER_HOST=127.0.0.1 SERVER_TLS=no
        explain "$(t "The server listens only on this computer (127.0.0.1:$SERVER_PORT)." \
                     "Сервер слушает только этот компьютер (127.0.0.1:$SERVER_PORT).")"
    else
        SERVER_BIND=0.0.0.0 SERVER_TLS=yes
        local ip
        ip=$(lan_ip)
        header "$(t "Network" "Сеть")"
        explain "$(t "Other computers connect to this server over the network. The connection is encrypted" \
                     "Другие компьютеры подключаются к этому серверу по сети. Соединение шифруется")" \
                "$(t "(TLS with a certificate made for this server) and protected by a token." \
                     "(TLS с сертификатом, созданным для этого сервера) и защищено токеном.")" \
                "$(t "Do not open this port to the internet directly; use a VPN (WireGuard, Tailscale)." \
                     "Не открывайте этот порт в интернет напрямую; используйте VPN (WireGuard, Tailscale).")"
        ask_text "$(t "Address clients will use to reach this server" "Адрес, по которому клиенты будут подключаться к серверу")" "${ip:-$(hostname)}"
        SERVER_HOST=$ANSWER
    fi
    while port_busy "$SERVER_PORT"; do
        if [ "$(env_get SOW_PORT)" = "$SERVER_PORT" ]; then break; fi   # our own running server
        warn "$(t "Port $SERVER_PORT is already in use." "Порт $SERVER_PORT уже занят.")"
        ask_text "$(t "Port for the server" "Порт для сервера")" "$((SERVER_PORT + 1))"
        SERVER_PORT=$ANSWER
    done
}

make_tls() {
    local dir=$SERVER_DATA/tls san
    mkdir -p "$dir"
    if [[ "$SERVER_HOST" =~ ^[0-9.]+$ ]]; then san="IP:$SERVER_HOST,IP:127.0.0.1"; else san="DNS:$SERVER_HOST,IP:127.0.0.1"; fi
    if [ -f "$dir/cert.pem" ] && [[ "$(openssl x509 -in "$dir/cert.pem" -noout -ext subjectAltName 2>/dev/null)" == *"$SERVER_HOST"* ]]; then
        return 0
    fi
    info "$(t "Creating a TLS certificate for $SERVER_HOST" "Создаётся TLS-сертификат для $SERVER_HOST")"
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
        -subj "/CN=Soul of Waifu server" -addext "subjectAltName=$san" \
        -keyout "$dir/key.pem" -out "$dir/cert.pem" >/dev/null 2>&1
    chmod 600 "$dir/key.pem"
}

cert_fingerprint() {
    openssl x509 -in "$SERVER_DATA/tls/cert.pem" -noout -fingerprint -sha256 | sed 's/.*=//; s/://g' | tr '[:upper:]' '[:lower:]'
}

write_server_env() {
    local token overlay=""
    token=$(env_get SOW_TOKEN)
    [ -n "$token" ] || token=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')
    case "$BACKEND" in
        # With a driver older than 570 llama.cpp uses its Vulkan image on the same NVIDIA GPU.
        cuda) if [ "$NVIDIA_MODE" = runtime ]; then overlay=compose.nvidia-runtime.yaml; else overlay=compose.nvidia.yaml; fi ;;
        vulkan) overlay=compose.vulkan.yaml ;;
    esac
    local llama_args="-c 16384 -ctk q8_0 -ctv q8_0"
    [ "$BACKEND" = cpu ] && llama_args="-c 8192 -ngl 0"
    local render_gid
    render_gid=$(stat -c %g /dev/dri/renderD128 2>/dev/null || echo video)
    mkdir -p "$SOW_CONF_DIR" "$SERVER_DATA/models" "$SERVER_DATA/speech"
    umask 077
    cat > "$SERVER_ENV" <<EOF
# Soul of Waifu server settings, written by the installer. Re-run the installer to change
# them; sow-server reads this file.
SOW_TOKEN=$token
SOW_UID=$(id -u)
SOW_GID=$(id -g)
SOW_BIND=$SERVER_BIND
SOW_PORT=$SERVER_PORT
SOW_HOST=$SERVER_HOST
SOW_TLS=$SERVER_TLS
SOW_TLS_DIR=$SERVER_DATA/tls
SOW_TLS_CERT=$([ "$SERVER_TLS" = yes ] && echo /tls/cert.pem)
SOW_TLS_KEY=$([ "$SERVER_TLS" = yes ] && echo /tls/key.pem)
SOW_MODELS_DIR=$SERVER_DATA/models
SOW_SPEECH_DATA_DIR=$SERVER_DATA/speech
SOW_TORCH=$TORCH
SOW_SPEECH_VRAM_MB=$SPEECH_VRAM_MB
SOW_RENDER_GID=$render_gid
SOW_GPU_OVERLAY=$overlay
LLAMA_IMAGE_TAG=$LLAMA_IMAGE_TAG
LLAMA_ARGS=$llama_args
COQUI_TOS_AGREED=$COQUI_TOS_AGREED
EOF
    umask 022
    mkdir -p "$SERVER_DATA/tls"
}

# Asks about the Coqui CPML licence of XTTSv2; sets COQUI_TOS_AGREED.
ask_xtts_licence() {
    COQUI_TOS_AGREED=$(env_get COQUI_TOS_AGREED)
    [ "$COQUI_TOS_AGREED" = 1 ] && return 0
    explain "$(t "XTTSv2 voice cloning is licensed under the Coqui Public Model License (non-commercial use" \
                 "Клонирование голоса XTTSv2 распространяется по лицензии Coqui Public Model License (только")" \
            "$(t "only): https://coqui.ai/cpml. Other voice engines do not need this." \
                 "некоммерческое использование): https://coqui.ai/cpml. Другим голосовым движкам это не нужно.")"
    if ask_yn "$(t "Accept it and enable XTTSv2?" "Принять её и включить XTTSv2?")" n; then COQUI_TOS_AGREED=1; else COQUI_TOS_AGREED=0; fi
}

deploy_server() {
    header "$(t "Starting the server" "Запуск сервера")"
    explain "$(t "Downloading the server images (about 8 GB; they take about 20 GB in /var/lib/docker)." \
                 "Скачиваются образы сервера (около 8 ГБ; в /var/lib/docker займут около 20 ГБ).")" \
            "$(t "Without prebuilt images for this version they are built here instead: 15-30 minutes." \
                 "Если готовых образов для этой версии нет, они собираются здесь: 15-30 минут.")"
    get_images
    compose_cmd up -d
    info "$(t "Waiting for the server to answer..." "Ожидание ответа сервера...")"
    local scheme=http i
    [ "$SERVER_TLS" = yes ] && scheme=https
    for i in $(seq 120); do
        if curl -sfk --max-time 3 "$scheme://127.0.0.1:$SERVER_PORT/sow/health" >/dev/null; then
            ok "$(t "Server is running on port $SERVER_PORT." "Сервер работает на порту $SERVER_PORT.")"
            return 0
        fi
        sleep 2
    done
    compose_cmd ps
    die "$(t "The server did not start; see: sow-server logs" "Сервер не запустился; смотрите: sow-server logs")"
}

download_model() {
    [ -n "$MODEL_ID" ] || return 0
    local dest=$SERVER_DATA/models/$MODEL_FILE
    if [ -f "$dest" ]; then
        ok "$(t "$MODEL_FILE is already downloaded." "$MODEL_FILE уже скачана.")"
        return 0
    fi
    header "$(t "Downloading $MODEL_FILE ($(gb "$MODEL_SIZE_MB"))" "Скачивание $MODEL_FILE ($(gb "$MODEL_SIZE_MB"))")"
    curl -fL --retry 5 --retry-all-errors --retry-delay 3 --progress-bar -C - -o "$dest.part" "$MODEL_URL"
    if [ -n "$MODEL_SHA" ]; then
        info "$(t "Checking the file (sha256)..." "Проверка файла (sha256)...")"
        echo "$MODEL_SHA  $dest.part" | sha256sum -c --quiet || die "$(t "Checksum mismatch, the file is damaged." "Контрольная сумма не совпала, файл повреждён.")"
    fi
    mv "$dest.part" "$dest"
    ok "$MODEL_FILE"
}

# Server images: pull the prebuilt ones, build locally when that fails (offline registry,
# an unpublished version, a modified server/ folder).
# Images of this server version already on this computer (built here before, or loaded).
images_present() {
    local image
    for image in $(compose_cmd config --images gateway speech 2>/dev/null); do
        dk image inspect "$image" >/dev/null 2>&1 || return 1
    done
    [ -n "${image:-}" ]
}

get_images() {
    compose_cmd pull llama
    if [ -z "$(git -C "$APP_DIR" status --porcelain -- server 2>/dev/null)" ] && images_present; then
        return 0
    fi
    if [ -n "$(git -C "$APP_DIR" status --porcelain -- server 2>/dev/null)" ] || ! compose_cmd pull gateway speech; then
        info "$(t "No prebuilt images for this version: building them here (15-30 minutes)." \
                  "Готовых образов для этой версии нет: они собираются здесь (15-30 минут).")"
        compose_cmd build
    fi
}

pairing_string() {
    local s
    s="sow://$SERVER_HOST:$SERVER_PORT#token=$(env_get SOW_TOKEN)"
    [ "$SERVER_TLS" = yes ] && s="$s&fp=$(cert_fingerprint)"
    printf '%s' "$s"
}

print_pairing() {
    header "$(t "Connecting clients" "Подключение клиентов")"
    explain "$(t "Paste this line into the app (Settings -> Server) or into the installer on another computer:" \
                 "Вставьте эту строку в программу (Настройки -> Сервер) или в установщик на другом компьютере:")"
    printf '\n   %s%s%s\n\n' "$C_BOLD" "$(pairing_string)" "$C_RESET"
    if command -v qrencode >/dev/null 2>&1; then qrencode -t ansiutf8 "$(pairing_string)"; fi
    explain "$(t "It contains the access token: share it only with your own devices." \
                 "В ней есть токен доступа: передавайте её только на свои устройства.")" \
            "$(t "Show it again later with: sow-server pair" "Показать её снова: sow-server pair")"
}

install_server_cli() {
    mkdir -p "$HOME/.local/bin"
    cat > "$HOME/.local/bin/sow-server" <<EOF
#!/usr/bin/env bash
# Soul of Waifu server control, written by the installer.
exec bash "$APP_DIR/installer/sow-server.sh" "\$@"
EOF
    chmod +x "$HOME/.local/bin/sow-server"
    ensure_local_bin_on_path
}

# Daily automatic update of a server-only install (opt-in): a systemd user timer running
# installer/update.sh, the same updater as 'sow-server update'.
ask_auto_update() {
    AUTO_UPDATE=no
    header "$(t "Automatic updates" "Автоматические обновления")"
    if [ "$DOCKER_ACCESS" != yes ]; then
        explain "$(t "Automatic updates need Docker access without sudo; update with 'sow-server update' instead." \
                     "Для автообновления нужен доступ к Docker без sudo; обновляйте командой 'sow-server update'.")"
        return 0
    fi
    explain "$(t "Once a day the server can check this branch for a new version and update itself" \
                 "Раз в сутки сервер может проверять новую версию и обновляться сам")" \
            "$(t "(git fast-forward, rebuild, restart: a few seconds without the server)." \
                 "(git fast-forward, пересборка, перезапуск: несколько секунд без сервера).")"
    ask_yn "$(t "Update the server automatically?" "Обновлять сервер автоматически?")" n && AUTO_UPDATE=yes
    return 0
}

install_auto_update() {
    local units=$HOME/.config/systemd/user
    mkdir -p "$units"
    cat > "$units/sow-server-update.service" <<UNIT
[Unit]
Description=Soul of Waifu server update

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash $APP_DIR/installer/update.sh
UNIT
    cat > "$units/sow-server-update.timer" <<UNIT
[Unit]
Description=Daily Soul of Waifu server update

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    run systemctl --user daemon-reload
    run systemctl --user enable --now sow-server-update.timer
    # User timers run only while the user is logged in, unless lingering is on.
    if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]; then
        explain "$(t "This user is not set to 'linger', so the timer runs only while you are logged in." \
                     "Для этого пользователя не включён режим 'linger', поэтому таймер работает, только пока вы вошли в систему.")"
        if ask_yn "$(t "Enable lingering for $USER (loginctl enable-linger)?" "Включить linger для $USER (loginctl enable-linger)?")" y; then
            as_root loginctl enable-linger "$USER"
        fi
    fi
    ok "$(t "Daily server updates are on (systemctl --user list-timers)." "Ежедневное обновление сервера включено (systemctl --user list-timers).")"
}
