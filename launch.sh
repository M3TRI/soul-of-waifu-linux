#!/usr/bin/env bash
# Starts the bundled llama-server (unless an OpenAI-compatible server already answers on
# LLAMA_PORT), waits until the model is loaded, runs the app, and stops the server again
# when the app exits. Settings live in ./llama.conf (written by install_arch.sh/install_debian.sh).
# The app reaches the server through main_settings.local_llm_base_url, which must point
# at the same port (http://127.0.0.1:8095/v1 by default).
cd "$(dirname "$(readlink -f "$0")")" || exit 1

LLAMA_PORT=8095
LLAMA_MODEL=""      # empty = first *.gguf in assets/local_llm (mmproj files skipped)
LLAMA_CTX=16384
LLAMA_NGL=""        # GPU layers; empty = llama-server --fit uses what fits in free VRAM, 0 = CPU only
LLAMA_WAIT=300      # seconds to wait for the model to load
LLAMA_ARGS=""       # extra llama-server flags, e.g. "--n-cpu-moe 20"
[ -f llama.conf ] && . ./llama.conf

URL="http://127.0.0.1:$LLAMA_PORT"
LOG=logs/llama-server.log
mkdir -p logs

say() {
    echo "$*" >&2
    command -v notify-send >/dev/null 2>&1 && notify-send -a "Soul of Waifu" "Soul of Waifu" "$*"
}

server_pid=""
stop_server() {
    [ -n "$server_pid" ] || return 0
    kill "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
    server_pid=""
}
trap stop_server EXIT
trap 'exit 130' INT TERM

if curl -sf -o /dev/null "$URL/v1/models"; then
    echo "LLM server already running on $URL, using it."
else
    model="$LLAMA_MODEL"
    if [ -z "$model" ]; then
        model=$(find assets/local_llm -maxdepth 2 -name '*.gguf' ! -iname '*mmproj*' 2>/dev/null | sort | head -n 1)
    fi
    if [ -z "$model" ] || [ ! -f "$model" ]; then
        say "No GGUF model found. Put a .gguf file into $(pwd)/assets/local_llm or set LLAMA_MODEL in llama.conf."
        exit 1
    fi
    if [ ! -x llama/llama-server ]; then
        say "llama/llama-server is missing, run ./install_arch.sh or ./install_debian.sh first."
        exit 1
    fi

    alias_name=$(basename "$model" .gguf)
    gpu_args=()
    [ -n "$LLAMA_NGL" ] && gpu_args=(-ngl "$LLAMA_NGL")
    echo "Starting llama-server: $model (log: $LOG)"
    # shellcheck disable=SC2086  # LLAMA_ARGS is intentionally word-split
    llama/llama-server -m "$model" --alias "$alias_name" \
        --host 127.0.0.1 --port "$LLAMA_PORT" -c "$LLAMA_CTX" "${gpu_args[@]}" \
        --parallel 1 --jinja $LLAMA_ARGS >"$LOG" 2>&1 &
    server_pid=$!

    say "Loading model $alias_name..."
    deadline=$((SECONDS + LLAMA_WAIT))
    until curl -sf -o /dev/null "$URL/health"; do
        if ! kill -0 "$server_pid" 2>/dev/null; then
            server_pid=""
            say "llama-server exited while loading the model, see $(pwd)/$LOG"
            tail -n 20 "$LOG" >&2
            exit 1
        fi
        if [ "$SECONDS" -ge "$deadline" ]; then
            say "llama-server did not get ready in ${LLAMA_WAIT}s, see $(pwd)/$LOG"
            exit 1
        fi
        sleep 1
    done
    echo "llama-server ready on $URL"
fi

./start.sh "$@"
