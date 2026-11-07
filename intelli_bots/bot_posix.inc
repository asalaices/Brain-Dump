# script_version: 1.0.1
# Purpose: Provide the shared logging and safe interface contract to POSIX-only router and login-shell payloads.
# Usage: source bot_posix.inc; call bot_posix_interface SCRIPT "$@" before operation work.
# Output: library
# API: bot_posix_log LEVEL FUNCTION LINE MESSAGE; bot_posix_interface SCRIPT ARGUMENTS.
# Prerequisites: POSIX sh, date, sed, awk, tr, head and basename; no Bash, Python, secret reads or network.
# Failure: Unsupported direct invocation exits 2; sourcing defines functions silently.

bot_posix_log() {
    _bot_level=$1 _bot_function=$2 _bot_line=$3
    shift 3
    _bot_message=$(printf '%s' "$*" | tr '\r\n\t' '   ' | awk '{ if (tolower($0) ~ /(api[_-]?key|authorization|cookie|credential|password|private[_-]?key|secret|token)[[:space:]]*[:=]/ || tolower($0) ~ /bearer[[:space:]]+[^[:space:]]+/) print "[REDACTED sensitive message]"; else print }')
    printf '%s:%s[%s] [%s] %s run=%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$_bot_function" "$_bot_line" "$_bot_level" "${BOT_POSIX_SCRIPT:-$(basename "$0")}" "${BOT_POSIX_RUN_ID:-$$}" "$_bot_message" >&2
}

bot_posix_interface() {
    _bot_source=$1
    shift
    [ "$_bot_source" = "$0" ] || return 0
    _bot_version=$(sed -n 's/^# script_version: //p' "$_bot_source" | head -n 1)
    for _bot_argument in "$@"; do
        case "$_bot_argument" in
            --) break ;;
            --version) printf '%s %s\n' "$(basename "$_bot_source")" "$_bot_version"; exit 0 ;;
            --help|-h) awk '/^# (Purpose|Usage|Output|API|Prerequisites|Failure|Example): / {sub(/^# /,""); print}' "$_bot_source"; exit 0 ;;
            --json|--pretty)
                _bot_name=$(basename "$_bot_source")
                case "$_bot_name" in *[!A-Za-z0-9_.-]*) _bot_name=script ;; esac
                printf '{"ok":false,"error":"JSON CLI mode is unsupported for this operation","exit_code":2,"info":{"script":"%s","script_version":"%s"}}\n' "$_bot_name" "$_bot_version"
                exit 2 ;;
        esac
    done
    BOT_POSIX_SCRIPT=$(basename "$_bot_source")
    BOT_POSIX_RUN_ID=$$
    export BOT_POSIX_SCRIPT BOT_POSIX_RUN_ID
    bot_posix_log INFO main 0 "$BOT_POSIX_SCRIPT script_version=$_bot_version"
}

case "$0" in
    */bot_posix.inc|bot_posix.inc)
        bot_posix_interface "$0" "$@"
        printf '%s\n' 'Source this shared POSIX logging library; use --help for its API.' >&2
        exit 2 ;;
esac
