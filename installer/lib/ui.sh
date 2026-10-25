# shellcheck shell=bash
# Terminal UI helpers for the installer: messages in the user's language, questions read
# from the terminal (the installer may itself be piped from curl), and a wrapper that shows
# every privileged command before it runs.

# SOW_TTY: stdout was a terminal before log.sh turned it into a pipe to the log.
if { [ -t 1 ] || [ "${SOW_TTY:-}" = 1 ]; } && [ -z "${NO_COLOR:-}" ]; then
    C_RESET=$'\e[0m' C_BOLD=$'\e[1m' C_DIM=$'\e[2m' C_RED=$'\e[31m' C_GREEN=$'\e[32m'
    C_YELLOW=$'\e[33m' C_BLUE=$'\e[34m' C_CYAN=$'\e[36m'
else
    C_RESET="" C_BOLD="" C_DIM="" C_RED="" C_GREEN="" C_YELLOW="" C_BLUE="" C_CYAN=""
fi

. "$(dirname "${BASH_SOURCE[0]}")/log.sh"

# UI_LANG: SOW_LANG when install.sh already asked, else the locale until choose_language.
case "${SOW_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in
    ru*) UI_LANG=ru ;;
    *) UI_LANG=en ;;
esac

# t "English text" "Русский текст" -> the one in the chosen language.
t() { if [ "$UI_LANG" = ru ] && [ -n "${2:-}" ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

say()   { printf '%s\n' "$*"; }
info()  { printf '%s  %s\n' "${C_BLUE}•${C_RESET}" "$*"; }
ok()    { printf '%s  %s\n' "${C_GREEN}✓${C_RESET}" "$*"; }
warn()  { printf '%s  %s\n' "${C_YELLOW}!${C_RESET}" "$*" >&2; }
fail()  { printf '%s  %s\n' "${C_RED}✗${C_RESET}" "$*" >&2; }
die()   { fail "$*"; exit 1; }

header() {
    printf '\n%s%s%s\n' "$C_BOLD$C_CYAN" "== $* " "$C_RESET"
}

# Prints a block that explains what is about to happen.
explain() {
    local line
    for line in "$@"; do printf '   %s%s%s\n' "$C_DIM" "$line" "$C_RESET"; done
}

TTY=/dev/tty
read_tty() {
    # read_tty VAR: one line from the terminal; aborts cleanly when there is none.
    local __var=$1 __line
    if ! IFS= read -r __line <"$TTY"; then
        echo
        die "$(t "No terminal to read the answer from. Run the installer in a terminal." \
                 "Нет терминала для ответа. Запустите установщик в терминале.")"
    fi
    printf -v "$__var" '%s' "$__line"
}

# ask_yn "Question" y|n -> 0 for yes, 1 for no. The default is taken on an empty answer.
ask_yn() {
    local question=$1 default=${2:-y} hint answer
    if [ "$default" = y ]; then hint="[$(t Y/n Д/н)]"; else hint="[$(t y/N д/Н)]"; fi
    while true; do
        printf '%s?%s %s %s ' "$C_BOLD$C_YELLOW" "$C_RESET" "$question" "$hint"
        read_tty answer
        answer=${answer//[[:space:]]/}
        # Listed explicitly: tr and ${,,} do not lowercase Cyrillic in every locale.
        case "${answer:-$default}" in
            y|Y|yes|Yes|YES|д|Д|да|Да|ДА) log_event "answer: $question -> '$answer' = yes"; return 0 ;;
            n|N|no|No|NO|н|Н|нет|Нет|НЕТ) log_event "answer: $question -> '$answer' = no"; return 1 ;;
        esac
        log_event "answer: $question -> '$answer' not understood, asked again"
    done
}

# choose "Question" default_index "option 1" "option 2" ... -> sets CHOICE (1-based).
choose() {
    local question=$1 default=$2 i answer
    shift 2
    printf '%s?%s %s\n' "$C_BOLD$C_YELLOW" "$C_RESET" "$question"
    i=1
    for opt in "$@"; do
        if [ "$i" = "$default" ]; then
            printf '   %s%2d)%s %s %s\n' "$C_BOLD" "$i" "$C_RESET" "$opt" "$C_DIM$(t "(default)" "(по умолчанию)")$C_RESET"
        else
            printf '   %2d) %s\n' "$i" "$opt"
        fi
        i=$((i + 1))
    done
    while true; do
        printf '   %s [%s]: ' "$(t "Number" "Номер")" "$default"
        read_tty answer
        answer=${answer:-$default}
        if [[ "$answer" =~ ^[0-9]+$ ]] && [ "$answer" -ge 1 ] && [ "$answer" -le $# ]; then
            CHOICE=$answer
            log_event "choice: $question -> $answer (${!answer})"
            return 0
        fi
        log_event "choice: $question -> '$answer' out of range, asked again"
    done
}

# ask_text "Question" "default" -> sets ANSWER.
ask_text() {
    printf '%s?%s %s [%s]: ' "$C_BOLD$C_YELLOW" "$C_RESET" "$1" "$2"
    read_tty ANSWER
    ANSWER=${ANSWER:-$2}
    log_event "text: $1 -> '$ANSWER'"
}

pause_enter() {
    local _
    printf '%s' "$C_DIM$(t "Press Enter to continue..." "Нажмите Enter, чтобы продолжить...")$C_RESET"
    read_tty _
    log_event "Enter pressed"
}

# as_root CMD...: runs a command as root after showing it. sudo asks for the password
# itself; without sudo (minimal Debian with a root password) su asks for root's password.
as_root() {
    local rc=0
    log_event "run as root: $*"
    if [ "$(id -u)" = 0 ]; then
        printf '   %s# %s%s\n' "$C_DIM" "$*" "$C_RESET"
        "$@" || rc=$?
    elif command -v sudo >/dev/null 2>&1; then
        printf '   %s$ %s%s\n' "$C_DIM" "sudo $*" "$C_RESET"
        sudo "$@" || rc=$?
    else
        printf '   %s$ %s%s\n' "$C_DIM" "su -c '$*'" "$C_RESET"
        su root -c "$(printf '%q ' "$@")" <"$TTY" || rc=$?
    fi
    log_event "exit $rc: $1"
    return $rc
}

# run CMD...: shows and runs an unprivileged command.
run() {
    local rc=0
    printf '   %s$ %s%s\n' "$C_DIM" "$*" "$C_RESET"
    log_event "run: $*"
    "$@" || rc=$?
    log_event "exit $rc: $1"
    return $rc
}

mb_to_gb() { awk -v m="$1" 'BEGIN { printf "%.1f", m / 1024 }'; }
# gb MB -> "12.3 GB" in the user's language.
gb() { printf '%s %s' "$(mb_to_gb "$1")" "$(t GB ГБ)"; }

# The very first question; the only one shown in both languages. Skipped when install.sh
# already asked (SOW_LANG). The locale only picks the default.
choose_language() {
    if [ -n "${SOW_LANG:-}" ]; then
        export SOW_LANG=$UI_LANG
        return 0
    fi
    local default=1 answer
    [ "$UI_LANG" = ru ] && default=2
    printf '\n%s?%s Language / Язык:\n   1) English\n   2) Русский\n   [%s]: ' "$C_BOLD$C_YELLOW" "$C_RESET" "$default"
    while true; do
        read_tty answer
        case "${answer:-$default}" in
            1) UI_LANG=en; break ;;
            2) UI_LANG=ru; break ;;
        esac
        log_event "language: '$answer' not understood, asked again"
        printf '   [%s]: ' "$default"
    done
    export SOW_LANG=$UI_LANG
    log_event "language: '${answer:-}' -> $UI_LANG"
}
