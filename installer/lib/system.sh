# shellcheck shell=bash
# Changes to the system itself. Every function explains what it is about to do and asks
# before doing it; nothing here runs without a "yes".

# pkg_install PKG...: installs distro packages with the distro's package manager.
# apt, dnf and zypper run non-interactively with no stdin: they must not swallow what the
# user types ahead for the installer's next question (debconf reads the terminal otherwise).
# pacman stays interactive: it asks before replacing conflicting packages.
pkg_install() {
    case "$PKG" in
        pacman) as_root pacman -S --needed "$@" ;;
        apt) as_root env DEBIAN_FRONTEND=noninteractive apt-get update </dev/null \
                && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" </dev/null ;;
        dnf) as_root dnf install -y "$@" </dev/null ;;
        zypper) as_root zypper --non-interactive install "$@" </dev/null ;;
        *) return 1 ;;
    esac
}

# Tools the installer itself needs. Package names are the same on all four families.
ensure_tools() {
    local missing=() tool
    for tool in curl tar openssl awk; do
        # awk comes as gawk on every family
        command -v "$tool" >/dev/null 2>&1 || missing+=("${tool/#awk/gawk}")
    done
    [ "${#missing[@]}" = 0 ] && return 0
    header "$(t "Required tools" "Необходимые утилиты")"
    explain "$(t "The installer needs: ${missing[*]}." "Установщику нужны: ${missing[*]}.")"
    [ -n "$PKG" ] || die "$(t "Install them with your package manager and run the installer again." \
                              "Установите их пакетным менеджером и запустите установщик снова.")"
    ask_yn "$(t "Install them with $PKG?" "Установить их через $PKG?")" y || die "$(t "Cancelled." "Отменено.")"
    pkg_install "${missing[@]}"
}

# --- container runtime ---------------------------------------------------------------------

# DOCKER_CMD is how the installer and sow-server call Docker: plain "docker" when the user
# already has access, otherwise through sudo. The installer never adds the user to the
# docker group (that group is equivalent to root); the app itself never talks to Docker.
DOCKER_CMD=(docker)
dk() { "${DOCKER_CMD[@]}" "$@"; }

install_docker() {
    header "$(t "Container runtime" "Среда контейнеров")"
    explain "$(t "The server part (language model, voices, speech recognition) runs in Docker containers:" \
                 "Серверная часть (языковая модель, голоса, распознавание речи) работает в контейнерах Docker:")" \
            "$(t "it stays isolated from the system and is removed completely with the containers." \
                 "она изолирована от системы и удаляется вместе с контейнерами без следов.")" \
            "$(t "Docker is not installed. It will be installed from your distribution's repositories" \
                 "Docker не установлен. Он будет установлен из репозиториев вашего дистрибутива")" \
            "$(t "and its service enabled (systemctl enable --now docker)." \
                 "и будет включена его служба (systemctl enable --now docker).")"
    case "$OS_FAMILY" in
        debian) explain "$(t "On Debian/Ubuntu the distribution's Docker is too old for GPU access (CDI)," \
                             "В Debian/Ubuntu Docker из репозиториев слишком старый для доступа к GPU (CDI),")" \
                        "$(t "so Docker's official repository download.docker.com is added." \
                             "поэтому добавляется официальный репозиторий Docker download.docker.com.")" ;;
    esac
    ask_yn "$(t "Install Docker?" "Установить Docker?")" y || die "$(t "Docker is required for the server part." "Для серверной части нужен Docker.")"
    case "$OS_FAMILY" in
        arch) pkg_install docker docker-compose ;;
        fedora) pkg_install moby-engine docker-compose ;;
        suse) pkg_install docker docker-compose ;;
        debian) install_docker_debian ;;
        *) die "$(t "Unsupported distribution: install Docker by hand (docs.docker.com) and run the installer again." \
                    "Дистрибутив не поддерживается: установите Docker вручную (docs.docker.com) и запустите установщик снова.")" ;;
    esac
    as_root systemctl enable --now docker.service
}

install_docker_debian() {
    local distro=$OS_ID codename=${VERSION_CODENAME:-}
    # Derivatives (Mint, Pop!_OS, Zorin...) use the repository of the release they are based on.
    if [ "$OS_ID" != debian ] && [ "$OS_ID" != ubuntu ]; then
        if [ -n "${UBUNTU_CODENAME:-}" ]; then distro=ubuntu codename=$UBUNTU_CODENAME; else distro=debian; fi
    fi
    [ -n "$codename" ] || die "$(t "Cannot tell the release codename." "Не удалось определить кодовое имя выпуска.")"
    as_root apt-get update
    as_root apt-get install -y ca-certificates curl
    as_root install -m 0755 -d /etc/apt/keyrings
    as_root curl -fsSL "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc
    as_root chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$distro $codename stable" \
        | as_root tee /etc/apt/sources.list.d/docker.list >/dev/null
    as_root apt-get update
    as_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

ensure_docker() {
    if [ "$DOCKER" = no ]; then
        install_docker
        survey_containers
    fi
    if [ "$DOCKER_ACCESS" = yes ]; then
        DOCKER_CMD=(docker)
    else
        explain "$(t "Your user has no direct access to Docker; Docker commands will run through sudo." \
                     "У вашего пользователя нет прямого доступа к Docker; команды Docker будут выполняться через sudo.")" \
                "$(t "(Adding you to the docker group would give root-equivalent rights, so the installer does not do it.)" \
                     "(Добавление в группу docker дало бы права, равные root, поэтому установщик этого не делает.)")"
        DOCKER_CMD=(sudo docker)
        if ! sudo docker info >/dev/null 2>&1; then
            ask_yn "$(t "The Docker service is not running. Start and enable it?" "Служба Docker не запущена. Запустить и включить её?")" y \
                || die "$(t "Docker is required for the server part." "Для серверной части нужен Docker.")"
            as_root systemctl enable --now docker.service
        fi
        DOCKER_VERSION=$(sudo docker version --format '{{.Server.Version}}' 2>/dev/null)
        COMPOSE_VERSION=$(sudo docker compose version --short 2>/dev/null)
    fi
    if [ -z "$COMPOSE_VERSION" ]; then
        explain "$(t "Docker Compose v2 is missing." "Нет Docker Compose v2.")"
        ask_yn "$(t "Install it?" "Установить его?")" y || die "$(t "Docker Compose is required." "Нужен Docker Compose.")"
        case "$OS_FAMILY" in
            arch|fedora|suse) pkg_install docker-compose ;;
            debian) pkg_install docker-compose-plugin || pkg_install docker-compose-v2 ;;
        esac
        COMPOSE_VERSION=$(dk compose version --short 2>/dev/null)
        [ -n "$COMPOSE_VERSION" ] || die "$(t "Docker Compose is still not available." "Docker Compose по-прежнему недоступен.")"
    fi
    ok "Docker $DOCKER_VERSION, Compose $COMPOSE_VERSION"
}

# --- NVIDIA --------------------------------------------------------------------------------

nvidia_driver_help() {
    header "$(t "NVIDIA driver" "Драйвер NVIDIA")"
    explain "$(t "An NVIDIA GPU was found, but its driver is not working (nvidia-smi fails)." \
                 "Найдена видеокарта NVIDIA, но её драйвер не работает (nvidia-smi не отвечает).")" \
            "$(t "The installer never installs or replaces GPU drivers: that needs a reboot and, with" \
                 "Установщик никогда не ставит и не меняет драйверы видеокарты: для этого нужна перезагрузка,")" \
            "$(t "Secure Boot on, signing the kernel module. Install it the way your distribution recommends:" \
                 "а при включённом Secure Boot ещё и подпись модуля ядра. Поставьте его так, как рекомендует дистрибутив:")"
    case "$OS_FAMILY" in
        arch) explain "  sudo pacman -S nvidia-open nvidia-utils   (wiki.archlinux.org/title/NVIDIA)" ;;
        debian) explain "  Ubuntu: sudo ubuntu-drivers install;  Debian: wiki.debian.org/NvidiaGraphicsDrivers" ;;
        fedora) explain "  rpmfusion.org/Howto/NVIDIA" ;;
        suse) explain "  en.opensuse.org/SDB:NVIDIA_drivers" ;;
    esac
    [ "$SECURE_BOOT" = on ] && explain "$(t "Secure Boot is on: you will be asked to enroll a key (MOK) on the next boot." \
                                           "Secure Boot включён: при следующей загрузке нужно будет подтвердить ключ (MOK).")"
    ask_yn "$(t "Continue without the GPU (everything on the processor)?" \
                "Продолжить без видеокарты (всё на процессоре)?")" n \
        || die "$(t "Install the driver, reboot and run the installer again." "Поставьте драйвер, перезагрузитесь и запустите установщик снова.")"
}

install_nvidia_toolkit() {
    case "$OS_FAMILY" in
        arch) pkg_install nvidia-container-toolkit ;;
        debian)
            as_root install -m 0755 -d /usr/share/keyrings
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
                | as_root gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
            curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
                | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' \
                | as_root tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
            pkg_install nvidia-container-toolkit ;;
        fedora)
            curl -fsSL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
                | as_root tee /etc/yum.repos.d/nvidia-container-toolkit.repo >/dev/null
            pkg_install nvidia-container-toolkit ;;
        suse)
            as_root zypper --non-interactive ar https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo
            # The user agreed to NVIDIA's repository; accept its signing key as NVIDIA's
            # instructions do (non-interactive zypper rejects unknown keys).
            as_root zypper --non-interactive --gpg-auto-import-keys refresh nvidia-container-toolkit
            pkg_install nvidia-container-toolkit ;;
    esac
}

# Makes the NVIDIA GPU visible to containers through CDI. Sets NVIDIA_MODE to cdi (compose
# devices: nvidia.com/gpu=all) or runtime (the older nvidia runtime, as a fallback).
ensure_nvidia_containers() {
    NVIDIA_MODE=cdi
    header "$(t "GPU access for containers" "Доступ контейнеров к видеокарте")"
    if [ -z "$NVIDIA_CTK_VERSION" ]; then
        explain "$(t "Containers reach the NVIDIA GPU through the NVIDIA Container Toolkit." \
                     "Контейнеры получают доступ к видеокарте NVIDIA через NVIDIA Container Toolkit.")" \
                "$(t "It does not touch the driver; it only describes the GPU for containers." \
                     "Он не трогает драйвер, а только описывает видеокарту для контейнеров.")"
        [ "$OS_FAMILY" = debian ] || [ "$OS_FAMILY" = fedora ] || [ "$OS_FAMILY" = suse ] && \
            explain "$(t "NVIDIA's package repository (nvidia.github.io/libnvidia-container) will be added." \
                         "Будет добавлен репозиторий пакетов NVIDIA (nvidia.github.io/libnvidia-container).")"
        ask_yn "$(t "Install the NVIDIA Container Toolkit?" "Установить NVIDIA Container Toolkit?")" y || return 1
        install_nvidia_toolkit
        survey_containers
    fi
    if [ "$NVIDIA_CDI_SPEC" = no ]; then
        explain "$(t "Generating the GPU description for containers: /etc/cdi/nvidia.yaml." \
                     "Создаётся описание видеокарты для контейнеров: /etc/cdi/nvidia.yaml.")"
        ask_yn "$(t "Generate it?" "Создать его?")" y || return 1
        as_root nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
    fi
    # Newer toolkits regenerate the spec after driver updates by themselves.
    if systemctl list-unit-files nvidia-cdi-refresh.path >/dev/null 2>&1 \
        && ! systemctl is-enabled --quiet nvidia-cdi-refresh.path 2>/dev/null; then
        explain "$(t "Enabling automatic refresh of that file after NVIDIA driver updates." \
                     "Включается автоматическое обновление этого файла после обновлений драйвера NVIDIA.")"
        ask_yn "$(t "Enable it?" "Включить?")" y && as_root systemctl enable --now nvidia-cdi-refresh.path
    fi

    info "$(t "Checking that a container can see the GPU..." "Проверка: видит ли контейнер видеокарту...")"
    if dk run --rm --device nvidia.com/gpu=all --entrypoint nvidia-smi \
        "ghcr.io/ggml-org/llama.cpp:$LLAMA_IMAGE_TAG" -L >/dev/null 2>&1; then
        ok "$(t "GPU is available in containers (CDI)." "Видеокарта доступна в контейнерах (CDI).")"
        return 0
    fi
    warn "$(t "Docker $DOCKER_VERSION did not accept the CDI device (CDI is on by default since Docker 28.2)." \
              "Docker $DOCKER_VERSION не принял CDI-устройство (CDI включён по умолчанию с Docker 28.2).")"
    explain "$(t "Fallback: register the NVIDIA runtime in /etc/docker/daemon.json (nvidia-ctk runtime" \
                 "Запасной путь: зарегистрировать среду NVIDIA в /etc/docker/daemon.json (nvidia-ctk runtime")" \
            "$(t "configure; a backup of the file is kept) and restart Docker, which restarts running containers." \
                 "configure; копия файла сохраняется) и перезапустить Docker, что перезапустит работающие контейнеры.")"
    ask_yn "$(t "Do that?" "Сделать это?")" n || return 1
    [ -f /etc/docker/daemon.json ] && as_root cp -a /etc/docker/daemon.json "/etc/docker/daemon.json.sow-backup"
    as_root nvidia-ctk runtime configure --runtime=docker
    as_root systemctl restart docker.service
    if dk run --rm --gpus all --entrypoint nvidia-smi "ghcr.io/ggml-org/llama.cpp:$LLAMA_IMAGE_TAG" -L >/dev/null 2>&1; then
        NVIDIA_MODE=runtime
        ok "$(t "GPU is available in containers (NVIDIA runtime)." "Видеокарта доступна в контейнерах (среда NVIDIA).")"
        return 0
    fi
    return 1
}

# Minimal Debian installs with a root password have no sudo; the installer needs it for
# system steps and Docker. Offer the usual setup (sudo + the sudo group) with root's
# password, then a re-login.
ensure_sudo() {
    [ "$(id -u)" = 0 ] || command -v sudo >/dev/null 2>&1 && return 0
    header "sudo"
    explain "$(t "This system has no sudo; the installer needs it to install packages and run Docker." \
                 "В системе нет sudo; установщику он нужен, чтобы ставить пакеты и запускать Docker.")" \
            "$(t "It can install sudo and add $USER to the '$1' group (root's password is asked once)." \
                 "Он может поставить sudo и добавить $USER в группу '$1' (пароль root спросят один раз).")" \
            "$(t "After that log out and in again, and run the installer once more." \
                 "После этого выйдите из системы, войдите снова и запустите установщик ещё раз.")"
    ask_yn "$(t "Install sudo and add $USER to '$1'?" "Поставить sudo и добавить $USER в '$1'?")" n \
        || die "$(t "Install sudo and run the installer again." "Поставьте sudo и запустите установщик снова.")"
    local install
    case "$PKG" in
        apt) install="apt-get update && apt-get install -y sudo" ;;
        dnf) install="dnf install -y sudo" ;;
        zypper) install="zypper --non-interactive install sudo" ;;
        pacman) install="pacman -S --needed --noconfirm sudo" ;;
        *) die "$(t "Install sudo by hand." "Поставьте sudo вручную.")" ;;
    esac
    as_root bash -c "$install && usermod -aG $1 $USER"
    ok "$(t "Done. Log out and in again, then run the installer once more." \
            "Готово. Выйдите из системы, войдите снова и запустите установщик ещё раз.")"
    exit 0
}
