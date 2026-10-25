# shellcheck shell=bash
# Hardware profile: which images to run and which LLM fits next to the voice engines.
# Numbers follow docs/server-api.md (VRAM budget); catalog VRAM figures come from
# server/catalog.tsv (weights + q8_0 KV cache at 16k context + buffers).

# Speech share in MB on a CUDA GPU, by voice profile:
#   light   - Kokoro, Silero, Edge + Whisper small
#   cloning - + Qwen3-TTS 1.7B or XTTSv2 (one heavy engine at a time)
#   rvc     - cloning + RVC voice conversion
SPEECH_CTX_MB=500
SPEECH_STT_MB=700
speech_share_mb() {
    case "$1" in
        light) echo $((SPEECH_CTX_MB + SPEECH_STT_MB + 500)) ;;
        cloning) echo $((SPEECH_CTX_MB + SPEECH_STT_MB + 4500)) ;;
        rvc) echo $((SPEECH_CTX_MB + SPEECH_STT_MB + 4500 + 1200)) ;;
    esac
}

# Decide the compute backend from the survey: sets BACKEND (cuda|vulkan|cpu), TORCH
# (cu128|cu126|cpu) and LLAMA_IMAGE_TAG.
choose_backend() {
    BACKEND=cpu TORCH=cpu LLAMA_IMAGE_TAG=server
    if [ "$GPU_VENDOR" = nvidia ] && [ "$NV_DRIVER_MAJOR" -ge 525 ]; then
        BACKEND=cuda
        # llama.cpp's server-cuda image is CUDA 12.8 (driver >= 570); older drivers run the
        # Vulkan image on the same GPU instead. torch wheels: cu128 >= 570, cu126 >= 525.
        if [ "$NV_DRIVER_MAJOR" -ge 570 ]; then TORCH=cu128 LLAMA_IMAGE_TAG=server-cuda
        else TORCH=cu126 LLAMA_IMAGE_TAG=server-vulkan; fi
    elif [ "$GPU_VENDOR" = amd ] && [ "$GPU_VRAM_MB" -ge 3000 ]; then
        BACKEND=vulkan LLAMA_IMAGE_TAG=server-vulkan
    elif [ "$GPU_VENDOR" = nvidia ] && [ -n "$NV_DRIVER_VERSION" ]; then
        BACKEND=vulkan LLAMA_IMAGE_TAG=server-vulkan
    fi
}

# VRAM kept free for the desktop and other programs.
display_reserve_mb() {
    if [ "$GPU_VENDOR" = nvidia ] && [ "$NV_DISPLAY" != Enabled ]; then echo 300; else echo 1024; fi
}

# Memory available to the LLM: sets LLM_BUDGET_MB and SPEECH_VRAM_MB for a voice profile.
compute_budget() {
    local profile=$1 reserve share
    reserve=$(display_reserve_mb)
    case "$BACKEND" in
        cuda)
            share=$(speech_share_mb "$profile")
            SPEECH_VRAM_MB=$((share - SPEECH_CTX_MB))
            LLM_BUDGET_MB=$((GPU_VRAM_MB - reserve - share))
            ;;
        vulkan)
            # Voice engines run on the CPU; the GPU is for the LLM only.
            SPEECH_VRAM_MB=0
            LLM_BUDGET_MB=$((GPU_VRAM_MB - reserve))
            ;;
        cpu)
            # Model and KV cache in RAM; leave room for the OS, the UI and the voice engines.
            SPEECH_VRAM_MB=0
            LLM_BUDGET_MB=$(( (RAM_MB - 6144) / 2 ))
            ;;
    esac
    [ "$LLM_BUDGET_MB" -lt 0 ] && LLM_BUDGET_MB=0
    return 0
}

CATALOG_FILE=""
# catalog_rows -> "id<TAB>name<TAB>size<TAB>vram<TAB>url<TAB>sha<TAB>note<TAB>note_ru" lines.
catalog_rows() { grep -v '^#' "$CATALOG_FILE" | grep -v '^[[:space:]]*$'; }

# Lets the user pick an LLM that fits LLM_BUDGET_MB. Sets MODEL_ID/MODEL_URL/MODEL_SHA/
# MODEL_FILE/MODEL_SIZE_MB, or MODEL_ID="" for "download later".
pick_model() {
    local ids=() labels=() urls=() shas=() sizes=() id name size vram url sha note note_ru
    while IFS=$'\t' read -r id name size vram url sha note note_ru; do
        [ "$vram" -le "$LLM_BUDGET_MB" ] || continue
        ids+=("$id") urls+=("$url") shas+=("$sha") sizes+=("$size")
        labels+=("$(printf '%-30s %s %5s %s, %s %5s %s  %s' "$name" "$(t file файл)" "$(mb_to_gb "$size")" "$(t GB ГБ)" \
            "$([ "$BACKEND" = cpu ] && t RAM ОЗУ || echo VRAM)" "$(mb_to_gb "$vram")" "$(t GB ГБ)" "$C_DIM$(t "$note" "$note_ru")$C_RESET")")
    done < <(catalog_rows)

    header "$(t "Language model" "Языковая модель")"
    if [ "$BACKEND" = cpu ]; then
        explain "$(t "No suitable GPU: the model runs on the processor. Only small models are listed;" \
                     "Подходящей видеокарты нет: модель будет работать на процессоре. Показаны только")" \
                "$(t "answers will be slower than on a GPU." "небольшие модели, ответы будут медленнее, чем на видеокарте.")"
    else
        explain "$(t "Models below fit into the $(gb "$LLM_BUDGET_MB") of video memory left after the voice engines" \
                     "Модели ниже помещаются в $(gb "$LLM_BUDGET_MB") видеопамяти, которые остаются после голосовых движков")" \
                "$(t "and the desktop, with a 16k-token context." "и рабочего стола, с контекстом 16k токенов.")"
    fi
    if [ "${#ids[@]}" = 0 ]; then
        warn "$(t "No model from the catalog fits. You can add a .gguf model later." \
                  "Ни одна модель из каталога не помещается. Модель .gguf можно добавить позже.")"
        MODEL_ID=""
        return 0
    fi
    # Default: the largest model that fits (the catalog is ordered by size).
    local default=${#ids[@]}
    labels+=("$(t "Do not download a model now" "Не скачивать модель сейчас")")
    choose "$(t "Which model should be downloaded?" "Какую модель скачать?")" "$default" "${labels[@]}"
    if [ "$CHOICE" -gt "${#ids[@]}" ]; then
        MODEL_ID=""
        return 0
    fi
    local i=$((CHOICE - 1))
    MODEL_ID=${ids[$i]} MODEL_URL=${urls[$i]} MODEL_SHA=${shas[$i]} MODEL_SIZE_MB=${sizes[$i]}
    MODEL_FILE=${MODEL_URL##*/}
}
