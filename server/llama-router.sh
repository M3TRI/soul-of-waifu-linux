#!/bin/sh
# Entrypoint of the llama service: llama-server in router mode, restarted when the set of
# GGUF files in /models changes. The router scans the folder only at start-up, and models
# downloaded later (installer, gateway /sow/llm/download) must show up without a restart of
# the stack. Arguments are passed to llama-server.
list() { ls -1 /models/*.gguf 2>/dev/null | grep -vi mmproj; }

trap 'kill "$pid" 2>/dev/null; wait "$pid"; exit 0' TERM INT
while true; do
    current=$(list)
    /app/llama-server "$@" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 5
        if [ "$(list)" != "$current" ]; then
            echo "llama-router: model files changed, restarting llama-server"
            kill "$pid"
            wait "$pid"
            break
        fi
    done
    wait "$pid" 2>/dev/null
    sleep 1
done
