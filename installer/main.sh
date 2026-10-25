#!/usr/bin/env bash
# Interactive installer of Soul of Waifu (UI client + server stack). Started by install.sh;
# takes no arguments: everything is asked in the terminal, and nothing on the system is
# changed without a "yes".
set -euo pipefail
APP_DIR=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
. "$APP_DIR/installer/lib/ui.sh"
. "$APP_DIR/installer/lib/survey.sh"
. "$APP_DIR/installer/lib/profile.sh"
. "$APP_DIR/installer/lib/system.sh"
. "$APP_DIR/installer/lib/server.sh"
. "$APP_DIR/installer/lib/packages.sh"
. "$APP_DIR/installer/lib/client.sh"
CATALOG_FILE=$APP_DIR/server/catalog.tsv

choose_language

[ "$(id -u)" != 0 ] || die "$(t "Run the installer as your normal user, not root; it asks for sudo when it needs it." \
                                "Запускайте установщик от обычного пользователя, не root; sudo он попросит сам, когда нужно.")"

printf '\n%s%s%s\n' "$C_BOLD" "Soul of Waifu — $(t "installer" "установщик")" "$C_RESET"
explain "$(t "This installer checks your computer, explains each step and asks before changing anything" \
             "Установщик проверит компьютер, объяснит каждый шаг и спросит разрешения перед любым изменением")" \
        "$(t "outside $HOME/.local/share/soul-of-waifu. You can stop it at any question with Ctrl+C." \
             "за пределами $HOME/.local/share/soul-of-waifu. Прервать можно на любом вопросе через Ctrl+C.")"

info "$(t "Collecting information about the system..." "Сбор сведений о системе...")"
survey_all
print_summary

case "$OS_FAMILY" in
    arch|fedora) ensure_sudo wheel ;;
    *) ensure_sudo sudo ;;
esac
[ "$ARCH" = x86_64 ] || die "$(t "Only x86-64 is supported for now." "Пока поддерживается только x86-64.")"
[ "$OS_FAMILY" != unknown ] || warn "$(t "Unknown distribution: system packages will have to be installed by hand." \
                                       "Неизвестный дистрибутив: системные пакеты придётся ставить вручную.")"

header "$(t "What to install" "Что установить")"
choose "$(t "Choose the installation type" "Выберите вариант установки")" 1 \
    "$(t "Everything on this computer (app + server)" "Всё на этом компьютере (программа + сервер)")" \
    "$(t "Only the server, for other computers on the network" "Только сервер, для других компьютеров в сети")" \
    "$(t "Only the app, connecting to an existing server" "Только программа, подключение к уже работающему серверу")" \
    "$(t "Remove Soul of Waifu" "Удалить Soul of Waifu")"
MODE=$CHOICE
[ "$MODE" = 4 ] && exec bash "$APP_DIR/installer/uninstall.sh"

if [ "$MODE" = 3 ]; then
    header "$(t "Plan" "План")"
    missing=$(missing_packages)
    [ -n "$missing" ] && info "$(t "install system libraries for the app (asks again)" "установить системные библиотеки для программы (спросит отдельно)")"
    info "$(t "Python environment of the app" "Python-окружение программы"): $APP_DIR/.venv"
    info "$(t "connect to your server with a pairing string" "подключиться к вашему серверу по строке подключения")"
    info "$(t "add the menu entry and the command" "добавить пункт меню и команду") soul-of-waifu"
    ask_yn "$(t "Proceed?" "Выполнить?")" y || { say "$(t "Nothing was changed." "Ничего не изменено.")"; exit 0; }
    ensure_tools
    client_packages
    client_python
    ask_pairing || die "$(t "Not connected. Run the installer again when the server is reachable." \
                            "Не подключено. Запустите установщик снова, когда сервер будет доступен.")"
    client_launcher
    ok "$(t "Done. Start the app from the menu or with: soul-of-waifu" "Готово. Запускайте программу из меню или командой: soul-of-waifu")"
    exit 0
fi

# --- server plan ---------------------------------------------------------------------------

if [ "$GPU_VENDOR" = nvidia ] && [ "$NV_DRIVER_MAJOR" = 0 ]; then
    nvidia_driver_help
    GPU_VENDOR=none
fi
choose_backend
case "$BACKEND" in
    cuda) info "$(t "Compute: NVIDIA GPU with CUDA ($GPU_NAME)." "Вычисления: видеокарта NVIDIA с CUDA ($GPU_NAME).")" ;;
    vulkan) info "$(t "Compute: language model on the GPU through Vulkan ($GPU_NAME), voices on the processor." \
                      "Вычисления: языковая модель на видеокарте через Vulkan ($GPU_NAME), голоса на процессоре.")" ;;
    cpu) info "$(t "Compute: processor only." "Вычисления: только процессор.")" ;;
esac

VOICE_PROFILE=light
if [ "$BACKEND" = cuda ]; then
    header "$(t "Voice engines" "Голосовые движки")"
    explain "$(t "Voice engines share video memory with the language model: heavier voices leave less room for it." \
                 "Голосовые движки делят видеопамять с языковой моделью: чем тяжелее голоса, тем меньше места модели.")"
    labels=()
    for p in light cloning rvc; do
        compute_budget "$p"
        case "$p" in
            light) name=$(t "Standard voices (Kokoro, Silero, Edge)" "Обычные голоса (Kokoro, Silero, Edge)") ;;
            cloning) name=$(t "+ voice cloning (Qwen3-TTS, XTTSv2)" "+ клонирование голоса (Qwen3-TTS, XTTSv2)") ;;
            rvc) name=$(t "+ voice cloning and RVC voice conversion" "+ клонирование голоса и преобразование RVC") ;;
        esac
        labels+=("$name — $(t "voices" "голосам") $(gb "$(speech_share_mb "$p")"), $(t "model" "модели") $(gb "$LLM_BUDGET_MB")")
    done
    choose "$(t "Which voice engines will you use?" "Какие голосовые движки вы будете использовать?")" 1 "${labels[@]}"
    VOICE_PROFILE=$(echo light cloning rvc | cut -d' ' -f"$CHOICE")
fi
COQUI_TOS_AGREED=0
[ "$VOICE_PROFILE" != light ] && ask_xtts_licence
compute_budget "$VOICE_PROFILE"
pick_model

SHARE_LAN=no
if [ "$MODE" = 1 ]; then
    header "$(t "Other devices" "Другие устройства")"
    explain "$(t "The app on this computer always uses this server. Other computers in your network (a laptop," \
                 "Программа на этом компьютере всегда пользуется этим сервером. Другие компьютеры в вашей сети (ноутбук,")" \
            "$(t "for example) can use it too: they then need only the app, not their own GPU." \
                 "например) тоже могут к нему подключаться: им нужна только программа, без своей видеокарты.")"
    if ask_yn "$(t "Allow other devices in the local network to connect?" "Разрешить подключение с других устройств в локальной сети?")" n; then
        SHARE_LAN=yes
    fi
fi
if [ "$MODE" = 1 ] && [ "$SHARE_LAN" = no ]; then ask_network local; else ask_network lan; fi
AUTO_UPDATE=no
[ "$MODE" = 2 ] && ask_auto_update

# Disk space: images + model.
need_mb=$((20 * 1024 + ${MODEL_SIZE_MB:-0}))
if [ "${DOCKER_FREE_MB:-0}" -lt "$need_mb" ]; then
    warn "$(t "Docker's disk (/var/lib/docker) has $(gb "$DOCKER_FREE_MB") free; about $(gb "$need_mb") are needed." \
              "На диске Docker (/var/lib/docker) свободно $(gb "$DOCKER_FREE_MB"); нужно около $(gb "$need_mb").")"
    ask_yn "$(t "Continue anyway?" "Всё равно продолжить?")" n || exit 1
fi

header "$(t "Plan" "План")"
plan=()
[ "$DOCKER" = no ] && plan+=("$(t "install Docker and enable its service (asks again)" "установить Docker и включить его службу (спросит отдельно)")")
[ "$BACKEND" = cuda ] && [ -z "$NVIDIA_CTK_VERSION" ] && plan+=("$(t "install NVIDIA Container Toolkit (asks again)" "установить NVIDIA Container Toolkit (спросит отдельно)")")
plan+=("$(t "download/build server images (~20 GB in /var/lib/docker)" "скачать/собрать образы сервера (~20 ГБ в /var/lib/docker)")")
if [ -n "${MODEL_ID:-}" ]; then
    if [ -f "$SERVER_DATA/models/$MODEL_FILE" ]; then
        plan+=("$(t "use the already downloaded model" "использовать уже скачанную модель") $MODEL_FILE")
    else
        plan+=("$(t "download the model" "скачать модель") $MODEL_FILE ($(gb "$MODEL_SIZE_MB"))")
    fi
fi
plan+=("$(t "server data and settings" "данные и настройки сервера"): $SERVER_DATA, $SERVER_ENV")
plan+=("$(t "start the server on" "запустить сервер на") $SERVER_BIND:$SERVER_PORT$([ "$SERVER_TLS" = yes ] && echo " (TLS)")")
plan+=("$(t "add the command" "добавить команду") ~/.local/bin/sow-server")
if [ "$MODE" = 1 ]; then
    [ -n "$(missing_packages)" ] && plan+=("$(t "install system libraries for the app (asks again)" "установить системные библиотеки для программы (спросит отдельно)")")
    plan+=("$(t "Python environment of the app" "Python-окружение программы"): $APP_DIR/.venv")
    plan+=("$(t "add the menu entry and the command" "добавить пункт меню и команду") soul-of-waifu")
fi
for line in "${plan[@]}"; do info "$line"; done
ask_yn "$(t "Proceed?" "Выполнить?")" y || { say "$(t "Nothing was changed." "Ничего не изменено.")"; exit 0; }

# --- do it ---------------------------------------------------------------------------------

ensure_tools
ensure_docker
NVIDIA_MODE=cdi
if [ "$BACKEND" = cuda ]; then
    info "$(t "Downloading the llama.cpp image..." "Скачивание образа llama.cpp...")"
    dk pull "ghcr.io/ggml-org/llama.cpp:$LLAMA_IMAGE_TAG"
    if ! ensure_nvidia_containers; then
        warn "$(t "Containers cannot use the GPU." "Контейнеры не могут использовать видеокарту.")"
        ask_yn "$(t "Continue on the processor only?" "Продолжить только на процессоре?")" n || exit 1
        GPU_VENDOR=none
        choose_backend
        compute_budget light
    fi
fi
[ "$SERVER_TLS" = yes ] && make_tls
write_server_env
install_server_cli
deploy_server
download_model

if [ "$MODE" = 2 ]; then
    [ "$AUTO_UPDATE" = yes ] && install_auto_update
    print_pairing
    ok "$(t "Done." "Готово.")"
else
    client_packages
    client_python
    client_pair "$(pairing_string)" || die "$(t "The app could not reach the server just installed; see: sow-server logs" \
                                              "Программа не смогла подключиться к только что установленному серверу; смотрите: sow-server logs")"
    client_launcher
    [ "$SHARE_LAN" = yes ] && print_pairing
    ok "$(t "Done. Start the app from the menu or with: soul-of-waifu" "Готово. Запускайте программу из меню или командой: soul-of-waifu")"
fi
