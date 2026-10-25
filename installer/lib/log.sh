# shellcheck shell=bash
# Installer log: everything the scripts print (colours stripped) plus timestamped "##" records
# of the environment, every answer the user typed and every command run with its exit code.
# One file per run in ~/.local/state/soul-of-waifu/logs (kept after an uninstall). The
# pairing token is masked wherever it appears.
LOG_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/soul-of-waifu/logs
LOG_KEEP=30
_LOG_FILTER='s/\x1b\[[0-9;?]*[A-Za-z]//g; s/\x1b[()][0-9A-Za-z]//g; s/.*\r//; s/(token=)[^&[:space:]]+/\1***/g'

# log_event TEXT...: a timestamped record that goes to the log file only.
log_event() {
    [ -n "${SOW_LOG:-}" ] || return 0
    printf '%s ## %s\n' "$(date '+%F %T')" "$*" | sed -E "$_LOG_FILTER" >>"$SOW_LOG"
}

# log_start KIND: from here on the output also goes to the log. A script started by one that
# already logs into a pipe it inherited (main.sh after install.sh, update.sh after its own
# exec, uninstall.sh from the menu) keeps writing to the same file.
log_start() {
    local kind=$1 fd1
    fd1=$(readlink /proc/$$/fd/1 2>/dev/null || true)
    if [ -n "${SOW_LOG:-}" ] && [ -f "$SOW_LOG" ] && [ -n "$fd1" ] && [ "$fd1" = "${SOW_LOG_FD1:-}" ]; then
        log_event "---- $kind: $0 ${*:2}"
    else
        mkdir -p "$LOG_DIR"
        # Old logs beyond the last LOG_KEEP go.
        # (ls fails when there is no log yet: under pipefail that would end the script.)
        { ls -1t "$LOG_DIR"/*.log 2>/dev/null || true; } | tail -n +"$LOG_KEEP" | xargs -r rm -f
        SOW_LOG=$LOG_DIR/$kind-$(date +%Y%m%d-%H%M%S).log
        : >"$SOW_LOG"
        unset SOW_LOG_HEADER
        # The colours were chosen for a terminal; keep them although stdout becomes a pipe.
        [ -t 1 ] && export SOW_TTY=1
        exec > >(tee >(sed -u -E "$_LOG_FILTER" >>"$SOW_LOG")) 2>&1
        SOW_LOG_FD1=$(readlink /proc/$$/fd/1 2>/dev/null || true)
        export SOW_LOG SOW_LOG_FD1
        log_event "Soul of Waifu $kind: $0 ${*:2}"
    fi
    # The environment once per file (install.sh starts the log before the program exists).
    if [ -z "${SOW_LOG_HEADER:-}" ]; then
        export SOW_LOG_HEADER=1
        log_event "version: $(git -C "${APP_DIR:-.}" rev-parse --short HEAD 2>/dev/null || echo unknown)" \
                  "branch: $(git -C "${APP_DIR:-.}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo -)"
        log_event "user: $(id -un) uid=$(id -u) groups=$(id -Gn | tr ' ' ,)"
        log_event "system: $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}") kernel $(uname -r) $(uname -m)"
        log_event "locale: LANG=${LANG:-} SOW_LANG=${SOW_LANG:-} terminal=${SOW_TTY:-no} session=${XDG_SESSION_TYPE:-} desktop=${XDG_CURRENT_DESKTOP:-}"
    fi
    # The failing command and its place: set -e otherwise ends the script without a word when
    # the command itself printed nothing (a sed on a missing file did exactly that).
    set -o errtrace
    trap '_log_error $? "$BASH_COMMAND" "${BASH_SOURCE[0]:-$0}" "$LINENO"' ERR
    trap '_log_finish $?' EXIT
}

_log_error() {
    # Inside $(...) a failure may be expected and handled by the caller; the caller's own
    # line is reported if it is not.
    [ "$BASH_SUBSHELL" = 0 ] || return 0
    SOW_LOG_FAILED="$2 ($(basename "$3"):$4, exit $1)"
    log_event "error: exit $1 at $3:$4: $2"
}

_log_finish() {
    local code=$1
    if [ "$code" != 0 ] && [ -n "${SOW_LOG_FAILED:-}" ]; then
        printf '%s  %s %s\n' "${C_RED:-}✗${C_RESET:-}" "$(t "Stopped at:" "Прервалось на:")" "$SOW_LOG_FAILED" >&2
    fi
    log_event "finished with exit code $code"
    printf '\n%s  %s %s\n' "${C_DIM:-}•" "$(t "Log:" "Лог:")" "$SOW_LOG${C_RESET:-}"
    # Let tee and sed write the last lines before the terminal gets its prompt back.
    exec 1>&- 2>&-
    sleep 0.3
}

# log_vars NAME...: one record with the values of the given variables (unset ones skipped).
log_vars() {
    local v out=""
    for v in "$@"; do
        [ -n "${!v+x}" ] && out+="$v=${!v} "
    done
    log_event "$out"
}
