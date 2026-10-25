# shellcheck shell=bash
# Server part: configuration, TLS, images, start-up, model download, pairing string.
# Everything lives under the user's home; Docker volumes are plain bind-mounted folders.

SOW_HOME=${XDG_DATA_HOME:-$HOME/.local/share}/soul-of-waifu
SOW_CONF_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/soul-of-waifu
SERVER_ENV=$SOW_CONF_DIR/server.env
SERVER_DATA=$SOW_HOME/server
SOW_PORT_DEFAULT=8765

# compose_cmd ARGS...: docker compose with this install's project, env file and GPU overlay.
compose_cmd() {
    local files=(-f "$APP_DIR/server/compose.yaml") overlay
    overlay=$(sed -n 's/^SOW_GPU_OVERLAY=//p' "$SERVER_ENV" 2>/dev/null)
    [ -n "$overlay" ] && files+=(-f "$APP_DIR/server/$overlay")
    dk compose --project-name soul-of-waifu --project-directory "$APP_DIR/server" \
        --env-file "$SERVER_ENV" "${files[@]}" "$@"
}

env_get() { sed -n "s/^$1=//p" "$SERVER_ENV" 2>/dev/null | tail -n 1; }

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
    if [ -f "$dir/cert.pem" ] && openssl x509 -in "$dir/cert.pem" -noout -ext subjectAltName 2>/dev/null | grep -q "${SERVER_HOST}"; then
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
    explain "$(t "Downloading the llama.cpp image and building the voice image. The first time this takes" \
                 "Скачивается образ llama.cpp и собирается образ голосовых движков. В первый раз это занимает")" \
            "$(t "15-30 minutes and about 20 GB of disk space (/var/lib/docker)." \
                 "15-30 минут и около 20 ГБ места на диске (/var/lib/docker).")"
    compose_cmd pull llama
    compose_cmd build
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
    curl -fL --retry 3 --progress-bar -C - -o "$dest.part" "$MODEL_URL"
    if [ -n "$MODEL_SHA" ]; then
        info "$(t "Checking the file (sha256)..." "Проверка файла (sha256)...")"
        echo "$MODEL_SHA  $dest.part" | sha256sum -c --quiet || die "$(t "Checksum mismatch, the file is damaged." "Контрольная сумма не совпала, файл повреждён.")"
    fi
    mv "$dest.part" "$dest"
    ok "$MODEL_FILE"
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
}
