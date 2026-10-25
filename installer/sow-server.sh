#!/usr/bin/env bash
# sow-server: control the Soul of Waifu server installed by install.sh.
#   sow-server status | start | stop | restart | logs [service] | pair | update
set -euo pipefail
APP_DIR=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
. "$APP_DIR/installer/lib/ui.sh"
. "$APP_DIR/installer/lib/survey.sh"
. "$APP_DIR/installer/lib/system.sh"
. "$APP_DIR/installer/lib/server.sh"

[ -f "$SERVER_ENV" ] || die "$(t "No server is installed (missing $SERVER_ENV)." "Сервер не установлен (нет $SERVER_ENV).")"
docker info >/dev/null 2>&1 || DOCKER_CMD=(sudo docker)
SERVER_HOST=$(env_get SOW_HOST) SERVER_PORT=$(env_get SOW_PORT) SERVER_TLS=$(env_get SOW_TLS)

case "${1:-status}" in
    status) compose_cmd ps ;;
    start) compose_cmd up -d ;;
    stop) compose_cmd stop ;;
    restart) compose_cmd restart ;;
    logs) shift; compose_cmd logs --tail 200 -f "$@" ;;
    pair) print_pairing ;;
    update) compose_cmd pull llama && compose_cmd build && compose_cmd up -d ;;
    *) sed -n '2,3p' "$0" | sed 's/^# //'; exit 2 ;;
esac
