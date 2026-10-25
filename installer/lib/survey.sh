# shellcheck shell=bash
# System survey: read-only. Fills the globals below and changes nothing on the system.

survey_os() {
    OS_NAME="unknown" OS_ID="" OS_LIKE="" OS_VERSION="" OS_FAMILY="unknown" PKG=""
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_NAME=${PRETTY_NAME:-${NAME:-unknown}} OS_ID=${ID:-} OS_LIKE=${ID_LIKE:-} OS_VERSION=${VERSION_ID:-}
    fi
    local id
    for id in $OS_ID $OS_LIKE; do
        case "$id" in
            arch|archarm|manjaro|endeavouros|cachyos|garuda) OS_FAMILY=arch PKG=pacman; break ;;
            debian|ubuntu|linuxmint|pop|zorin|elementary|kali|raspbian) OS_FAMILY=debian PKG=apt; break ;;
            fedora|rhel|centos|rocky|almalinux|nobara) OS_FAMILY=fedora PKG=dnf; break ;;
            opensuse*|suse|sles) OS_FAMILY=suse PKG=zypper; break ;;
        esac
    done
    ARCH=$(uname -m)
    KERNEL=$(uname -r)
}

survey_hw() {
    CPU_MODEL=$(awk -F': ' '/^model name/ { print $2; exit }' /proc/cpuinfo 2>/dev/null)
    CPU_MODEL=${CPU_MODEL:-$ARCH}
    CPU_THREADS=$(nproc 2>/dev/null || echo 1)
    CPU_AVX2=no
    grep -qw avx2 /proc/cpuinfo 2>/dev/null && CPU_AVX2=yes
    RAM_MB=$(awk '/^MemTotal/ { print int($2 / 1024) }' /proc/meminfo)
    local probe=$HOME/.local/share
    [ -d "$probe" ] || probe=$HOME
    DISK_FREE_MB=$(df -Pm "$probe" | awk 'NR == 2 { print $4 }')
    # Container images (about 20 GB) go to Docker's data root, often another filesystem.
    DOCKER_ROOT=/var/lib/docker
    DOCKER_FREE_MB=$(df -Pm "$DOCKER_ROOT" 2>/dev/null || df -Pm /var 2>/dev/null)
    DOCKER_FREE_MB=$(printf '%s\n' "$DOCKER_FREE_MB" | awk 'NR == 2 { print $4 }')
}

# GPUs: one line per card in GPU_LIST: "vendor|name|vram_mb|driver|pci".
# The best one for compute is described by GPU_VENDOR/GPU_NAME/GPU_VRAM_MB/GPU_DRIVER.
survey_gpu() {
    GPU_LIST=() GPU_VENDOR=none GPU_NAME="" GPU_VRAM_MB=0 GPU_DRIVER="" NV_DRIVER_VERSION="" NV_DISPLAY=""
    local card dev vendor pci driver name vram seen=" "
    for card in /sys/class/drm/card[0-9]*; do
        dev=$card/device
        [ -e "$dev/vendor" ] || continue
        pci=$(basename "$(readlink -f "$dev")")
        case "$seen" in *" $pci "*) continue ;; esac
        seen="$seen$pci "
        vendor=$(cat "$dev/vendor")
        driver=$(basename "$(readlink -f "$dev/driver" 2>/dev/null)" 2>/dev/null)
        name=""
        command -v lspci >/dev/null 2>&1 && name=$(lspci -s "$pci" 2>/dev/null | sed 's/^[^:]*: //; s/^[^:]*: //')
        vram=0
        case "$vendor" in
            0x10de)
                vendor=nvidia
                if command -v nvidia-smi >/dev/null 2>&1; then
                    local q
                    q=$(nvidia-smi --query-gpu=pci.bus_id,name,memory.total,driver_version,display_active \
                        --format=csv,noheader,nounits 2>/dev/null | grep -i "${pci#0000:}" | head -n 1)
                    if [ -n "$q" ]; then
                        IFS=',' read -r _ name vram NV_DRIVER_VERSION NV_DISPLAY <<<"$q"
                        name=$(echo "$name" | sed 's/^ *//') vram=${vram// /}
                        NV_DRIVER_VERSION=${NV_DRIVER_VERSION// /} NV_DISPLAY=${NV_DISPLAY// /}
                    fi
                fi
                ;;
            0x1002)
                vendor=amd
                [ -r "$dev/mem_info_vram_total" ] && vram=$(( $(cat "$dev/mem_info_vram_total") / 1048576 ))
                ;;
            0x8086) vendor=intel ;;
            *) vendor="other" ;;
        esac
        name=${name:-$vendor GPU}
        GPU_LIST+=("$vendor|$name|$vram|${driver:-none}|$pci")
    done

    # Pick the compute GPU: NVIDIA with a working driver, then AMD with the most VRAM, then Intel.
    local entry v n m d best_rank=0 rank
    for entry in "${GPU_LIST[@]}"; do
        IFS='|' read -r v n m d _ <<<"$entry"
        case "$v" in
            nvidia) if [ "$d" = nvidia ] && [ -n "$NV_DRIVER_VERSION" ]; then rank=4; else rank=1; fi ;;
            amd) if [ "$m" -ge 3000 ]; then rank=3; else rank=2; fi ;;
            intel) rank=1 ;;
            *) rank=0 ;;
        esac
        if [ "$rank" -gt "$best_rank" ] || { [ "$rank" = "$best_rank" ] && [ "$m" -gt "$GPU_VRAM_MB" ]; }; then
            best_rank=$rank GPU_VENDOR=$v GPU_NAME=$n GPU_VRAM_MB=$m GPU_DRIVER=$d
        fi
    done
    NV_DRIVER_MAJOR=${NV_DRIVER_VERSION%%.*}
    case "$NV_DRIVER_MAJOR" in ''|*[!0-9]*) NV_DRIVER_MAJOR=0 ;; esac
}

survey_desktop() {
    SESSION=${XDG_SESSION_TYPE:-unknown}
    DESKTOP=${XDG_CURRENT_DESKTOP:-unknown}
    AUDIO="unknown"
    if command -v pactl >/dev/null 2>&1; then
        AUDIO=$(pactl info 2>/dev/null | sed -n 's/^Server Name: //p')
        AUDIO=${AUDIO:-unknown}
    fi
    SECURE_BOOT=unknown
    if command -v mokutil >/dev/null 2>&1; then
        case "$(mokutil --sb-state 2>/dev/null)" in
            *enabled*) SECURE_BOOT=on ;;
            *disabled*) SECURE_BOOT=off ;;
        esac
    elif [ ! -d /sys/firmware/efi ]; then
        SECURE_BOOT=off   # legacy BIOS boot has no Secure Boot
    else
        # efivarfs: 4 bytes of attributes, then the value byte.
        local var
        var=$(ls /sys/firmware/efi/efivars/SecureBoot-* 2>/dev/null | head -n 1)
        if [ -n "$var" ] && [ -r "$var" ]; then
            case "$(od -An -tu1 -j4 -N1 "$var" 2>/dev/null | tr -d ' ')" in
                1) SECURE_BOOT=on ;;
                0) SECURE_BOOT=off ;;
            esac
        fi
    fi
}

survey_containers() {
    DOCKER=no DOCKER_VERSION="" DOCKER_ACCESS=no COMPOSE_VERSION="" DOCKER_CDI_NVIDIA=no
    if command -v docker >/dev/null 2>&1; then
        DOCKER=yes
        if docker info >/dev/null 2>&1; then
            DOCKER_ACCESS=yes
            DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null)
            docker info 2>/dev/null | grep -q 'nvidia.com/gpu=all' && DOCKER_CDI_NVIDIA=yes
        else
            DOCKER_VERSION=$(docker --version 2>/dev/null | sed -n 's/.*version \([0-9.]*\).*/\1/p')
        fi
        COMPOSE_VERSION=$(docker compose version --short 2>/dev/null)
    fi
    PODMAN_VERSION=$(podman --version 2>/dev/null | awk '{ print $3 }' || true)
    NVIDIA_CTK_VERSION=$(nvidia-ctk --version 2>/dev/null | sed -n 's/.*version \([0-9.]*\).*/\1/p' | head -n 1 || true)
    NVIDIA_CDI_SPEC=no
    { [ -f /etc/cdi/nvidia.yaml ] || [ -f /var/run/cdi/nvidia.yaml ]; } && NVIDIA_CDI_SPEC=yes
}

survey_net() {
    NET_OK=no
    curl -fsI --max-time 8 https://huggingface.co >/dev/null 2>&1 && NET_OK=yes
}

port_busy() {
    # port_busy PORT -> 0 if something listens on it.
    if command -v ss >/dev/null 2>&1; then
        ss -ltnH "sport = :$1" 2>/dev/null | grep -q .
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
    fi
}

survey_all() {
    # Best effort: a missing tool (podman, lspci, pactl...) must not abort the installer.
    local saved
    saved=$(set +o)
    set +e +o pipefail
    survey_os
    survey_hw
    survey_gpu
    survey_desktop
    survey_containers
    survey_net
    eval "$saved"
}

# version_ge A B -> 0 when A >= B (dotted versions).
version_ge() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n 1)" = "$2" ]; }

print_summary() {
    header "$(t "Your system" "Ваша система")"
    local row
    # printf pads by bytes; pad by characters so Cyrillic labels line up.
    row() { printf '   %s%*s %s\n' "$1" $((24 - ${#1})) "" "$2"; }
    row "$(t "System" "Система")" "$OS_NAME ($ARCH, $(t kernel ядро) $KERNEL)"
    row "$(t "Processor" "Процессор")" "$CPU_MODEL, $CPU_THREADS $(t threads потоков)$([ "$CPU_AVX2" = yes ] && echo ", AVX2")"
    row "$(t "Memory" "Память")" "$(gb "$RAM_MB")"
    row "$(t "Free disk space" "Свободно на диске")" "$(gb "$DISK_FREE_MB") ($HOME/.local/share), $(gb "${DOCKER_FREE_MB:-0}") (/var/lib/docker)"
    if [ "${#GPU_LIST[@]}" = 0 ]; then
        row "$(t "Graphics" "Видеокарта")" "$(t "not found" "не найдена")"
    fi
    local entry v n m d
    for entry in "${GPU_LIST[@]}"; do
        IFS='|' read -r v n m d _ <<<"$entry"
        local extra=""
        [ "$m" -gt 0 ] && extra=", $(gb "$m") VRAM"
        [ "$v" = nvidia ] && [ -n "$NV_DRIVER_VERSION" ] && extra="$extra, $(t driver драйвер) $NV_DRIVER_VERSION"
        [ "$v" = nvidia ] && [ -z "$NV_DRIVER_VERSION" ] && extra="$extra, ${C_YELLOW}$(t "NVIDIA driver not working" "драйвер NVIDIA не работает")${C_RESET}"
        row "$(t "Graphics" "Видеокарта")" "$n$extra"
    done
    row "$(t "Session" "Сеанс")" "$SESSION, $DESKTOP; $(t audio звук): $AUDIO"
    row "Secure Boot" "$SECURE_BOOT"
    local docker_state
    if [ "$DOCKER" = no ]; then docker_state=$(t "not installed" "не установлен")
    elif [ "$DOCKER_ACCESS" = no ]; then docker_state="$DOCKER_VERSION, $(t "no access for this user" "нет доступа у этого пользователя")"
    else docker_state="$DOCKER_VERSION, compose ${COMPOSE_VERSION:-$(t missing нет)}"; fi
    row "Docker" "$docker_state"
    [ -n "$PODMAN_VERSION" ] && row "Podman" "$PODMAN_VERSION"
    if [ "$GPU_VENDOR" = nvidia ]; then
        row "NVIDIA Container Toolkit" "${NVIDIA_CTK_VERSION:-$(t "not installed" "не установлен")}$([ "$NVIDIA_CDI_SPEC" = yes ] && echo ", CDI")"
    fi
    row "$(t "Internet" "Интернет")" "$([ "$NET_OK" = yes ] && t "OK" "есть" || t "huggingface.co not reachable" "huggingface.co недоступен")"
}
