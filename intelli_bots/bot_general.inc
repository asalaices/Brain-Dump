# script_version: 1.1.1
# Purpose: shared Bash logging, redaction, lifecycle and script-interface adapter.
# Usage: source bot_general.inc; call bot_interface "${BASH_SOURCE[0]}" "$@" early.
# Output: library
# API: bot_log/bot_run_start/bot_run_finish; bot_json SCRIPT [--pretty] reads JSON stdin.
# Imports are silent. bot_interface handles direct --help/--version before effects.

if [[ -n "${BOT_GENERAL_INC_LOADED:-}" ]]; then
    return 0
fi
readonly BOT_GENERAL_INC_LOADED=1

readonly BOT_SCRIPT_NAME="$(basename "$0")"
readonly BOT_RUN_ID="$(printf '%06x' "$(( (RANDOM << 8 ^ RANDOM ^ $$) & 0xFFFFFF ))")"
BOT_DEBUG="${BOT_DEBUG:-false}"
BOT_LOG_FILE=""
BOT_RUN_ACTION=""
BOT_RUN_STARTED_SECONDS=0
BOT_RUN_FINISHED=false

bot_timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

bot_sanitize() {
    local value="$1"
    value="${value//$'\r'/\\r}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\t'/\\t}"
    printf '%s' "$value"
}

bot_redact() {
    local value
    local restore_nocase=false
    value="$(bot_sanitize "$1")"
    if ! shopt -q nocasematch; then
        shopt -s nocasematch
        restore_nocase=true
    fi
    if [[ "$value" =~ ^([^=]*(api[_-]?key|authorization|cookie|credential|password|private[_-]?key|secret|token)[^=]*)= ]]; then
        printf '%s=[REDACTED]' "${BASH_REMATCH[1]}"
    elif [[ "$value" =~ (api[_-]?key|authorization|cookie|credential|password|private[_-]?key|secret|token)[[:space:]]*[:=] || "$value" =~ Bearer[[:space:]]+[^[:space:]]+ ]]; then
        printf '%s' '[REDACTED sensitive message]'
    else
        printf '%s' "$value"
    fi
    if [[ "$restore_nocase" == "true" ]]; then
        shopt -u nocasematch
    fi
}

bot_log() {
    local level="$1"
    local caller_function="$2"
    local caller_line="$3"
    local message="$4"
    shift 4
    local field
    local line

    if [[ "$level" == "DEBUG" && "$BOT_DEBUG" != "true" ]]; then
        return 0
    fi

    printf -v line '%s:%s[%s] [%s] %s run=%s %s' \
        "$(bot_timestamp)" "$caller_function" "$caller_line" "$level" \
        "$BOT_SCRIPT_NAME" "$BOT_RUN_ID" "$(bot_redact "$message")"
    for field in "$@"; do
        line+=" $(bot_redact "$field")"
    done
    if [[ "${BOT_STRUCTURED_OUTPUT:-false}" != true ]]; then printf '%s\n' "$line" >&2; fi
    if [[ -n "$BOT_LOG_FILE" ]]; then
        printf '%s\n' "$line" >>"$BOT_LOG_FILE"
    fi
}

log_debug() {
    bot_log DEBUG "${FUNCNAME[1]:-main}" "${BASH_LINENO[0]:-0}" "$@"
}

log_info() {
    bot_log INFO "${FUNCNAME[1]:-main}" "${BASH_LINENO[0]:-0}" "$@"
}

log_warn() {
    bot_log WARN "${FUNCNAME[1]:-main}" "${BASH_LINENO[0]:-0}" "$@"
}

log_error() {
    bot_log ERROR "${FUNCNAME[1]:-main}" "${BASH_LINENO[0]:-0}" "$@"
}

die() {
    local status=1
    if [[ "${1:-}" =~ ^[1-9][0-9]*$ ]]; then
        status="$1"
        shift
    fi
    bot_log ERROR "${FUNCNAME[1]:-main}" "${BASH_LINENO[0]:-0}" "$@"
    exit "$status"
}

bot_set_debug() {
    BOT_DEBUG=true
}

bot_set_log_file() {
    local path="$1"
    local parent

    [[ -n "$path" ]] || die 2 "--log-file requires a path"
    parent="$(dirname "$path")"
    [[ -d "$parent" ]] ||
        die 2 "Log file parent directory does not exist" "path=$parent"
    [[ ! -L "$path" ]] ||
        die 2 "Refusing symbolic-link log file" "path=$path"
    [[ ! -e "$path" || -f "$path" ]] ||
        die 2 "Log path is not a regular file" "path=$path"
    (umask 077 && : >>"$path") ||
        die 2 "Could not open log file" "path=$path"
    chmod 0600 "$path" ||
        die 2 "Could not secure log file" "path=$path"
    BOT_LOG_FILE="$path"
    log_debug "File logging enabled" "path=$path"
}

bot_run_start() {
    BOT_RUN_ACTION="$1"
    BOT_RUN_STARTED_SECONDS="$SECONDS"
    BOT_RUN_FINISHED=false
    bot_log INFO "${FUNCNAME[1]:-main}" "${BASH_LINENO[0]:-0}" \
        "Started" "action=$BOT_RUN_ACTION"
}

bot_run_finish() {
    local status="${1:-0}"
    local elapsed_seconds=$((SECONDS - BOT_RUN_STARTED_SECONDS))
    BOT_RUN_FINISHED=true
    bot_log INFO "${FUNCNAME[1]:-main}" "${BASH_LINENO[0]:-0}" "Completed" \
        "action=$BOT_RUN_ACTION" \
        "exit=$status" \
        "elapsed_seconds=$elapsed_seconds"
}

bot_stack_trace() {
    local index
    for ((index = 1; index < ${#FUNCNAME[@]}; index++)); do
        log_debug "Stack frame" \
            "function=${FUNCNAME[$index]:-main}" \
            "source=$(basename "${BASH_SOURCE[$index]:-$BOT_SCRIPT_NAME}")" \
            "line=${BASH_LINENO[$((index - 1))]:-0}"
    done
}

bot_unexpected_error() {
    local status="$1"
    local line="$2"
    trap - ERR
    bot_log ERROR "${FUNCNAME[1]:-main}" "$line" \
        "Unexpected command failure" \
        "action=${BOT_RUN_ACTION:-unknown}" \
        "exit=$status"
    bot_stack_trace
    exit "$status"
}

bot_exit_report() {
    local status="$1"
    if [[ -n "$BOT_RUN_ACTION" && "$BOT_RUN_FINISHED" != "true" ]]; then
        local elapsed_seconds=$((SECONDS - BOT_RUN_STARTED_SECONDS))
        bot_log ERROR main 0 "Failed" \
            "action=$BOT_RUN_ACTION" \
            "exit=$status" \
            "elapsed_seconds=$elapsed_seconds"
    fi
}

bot_install_traps() {
    trap 'bot_unexpected_error "$?" "$LINENO"' ERR
    trap 'bot_exit_report "$?"' EXIT
}

bot_require_execution() {
    local action="$1"
    local execute="$2"
    local assume_yes="$3"

    if [[ "$execute" != "true" ]]; then
        [[ "$assume_yes" != "true" ]] ||
            die 2 "--yes requires --execute" "action=$action"
        log_info "Plan only; no state changes performed" \
            "action=$action" \
            "execute=false"
        return 1
    fi

    if [[ "$assume_yes" == "true" ]]; then
        log_debug "Confirmation accepted noninteractively" \
            "action=$action" \
            "execute=true" \
            "yes=true"
        return 0
    fi

    [[ -t 0 && -t 2 ]] ||
        die 2 "Interactive confirmation unavailable; rerun with --execute --yes" \
            "action=$action"
    printf 'Execute %s? [y/N] ' "$action" >&2
    local response
    IFS= read -r response
    [[ "$response" == "y" || "$response" == "Y" ||
        "$response" == "yes" || "$response" == "YES" ]] ||
        die 3 "Execution cancelled" "action=$action"
    log_debug "Interactive confirmation accepted" "action=$action"
}

# Public bootstrap output is a log stream. Internal data pipes remain untouched.
bot_log_stream() {
    local function_name="${1:-external_output}" line_number="${2:-0}" line
    local pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[^[:space:]]+:[^[:space:]]+\[[0-9]+\][[:space:]]+\['
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ $pattern ]]; then
            printf '%s\n' "$line"
        else
            bot_log INFO "$function_name" "$line_number" "$line" 2>&1
        fi
    done
}

bot_enable_stream_logging() {
    if [[ "${BOT_STREAM_LOGGED:-}" != 1 ]]; then
        export BOT_STREAM_LOGGED=1
        exec > >(bot_log_stream external_output "${BASH_LINENO[0]:-0}") 2> >(bot_log_stream external_output "${BASH_LINENO[0]:-0}" >&2)
    fi
}

bot_script_banner() {
    local file="${1:-$0}" line version='' number=0
    [[ "$file" == "$0" && -r "$file" ]] || return 0
    while IFS= read -r line && ((number < 20)); do
        number=$((number + 1))
        if [[ "$line" =~ ^#[[:space:]]script_version:[[:space:]]([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
            version="${BASH_REMATCH[1]}"
            break
        fi
    done < "$file"
    [[ -n "$version" ]] || return 0
    bot_log INFO main "$number" "$(basename "$file") script_version=$version"
}

bot_json_string() {
    # Encode one metadata string without requiring Python on text-only hosts.
    local value="$1" char code index
    printf '"'
    for ((index=0; index<${#value}; index++)); do
        char="${value:index:1}"
        case "$char" in
            '\') printf '\\\\' ;;
            '"') printf '\\"' ;;
            *) printf -v code '%d' "'$char"
               if ((code < 32)); then printf '\\u%04x' "$code"; else printf '%s' "$char"; fi ;;
        esac
    done
    printf '"'
}

bot_interface() {
    local caller="$1"; shift
    # Sourced libraries and scripts must not consume their caller's arguments.
    [[ "$caller" == "$0" ]] || return 0
    local argument version='' purpose='' output='' line number=0
    while IFS= read -r line && ((number < 70)); do
        number=$((number + 1))
        case "$line" in
            '# script_version: '*) version="${line#\# script_version: }" ;;
            '# Purpose: '*) purpose="${line#\# Purpose: }" ;;
            '# Output: '*) output="${line#\# Output: }" ;;
        esac
    done < "$caller"
    for argument in "$@"; do
        [[ "$argument" != -- ]] || break
        case "$argument" in
            --version) printf '%s %s\n' "$(basename "$caller")" "$version"; exit 0 ;;
            --help|-h)
                while IFS= read -r line; do
                    case "$line" in
                        '# Purpose: '*|'# Usage: '*|'# Output: '*|'# Prerequisites: '*|'# Failure: '*|'# Example: '*|'# API: '*) printf '%s\n' "${line#\# }" ;;
                    esac
                done < "$caller"
                printf '%s\n' 'Common options: --help, --version. See Usage for command-specific options.'
                exit 0 ;;
        esac
    done
    case "$output" in
        test|library|text|artifact|protocol|service)
            for argument in "$@"; do
                [[ "$argument" != -- ]] || break
                case "$argument" in --json|--pretty) export BOT_STRUCTURED_OUTPUT=true; printf '{"ok":false,"error":"JSON CLI output is unsupported for this interface","exit_code":2,"info":{"script":%s,"script_version":%s}}\n' "$(bot_json_string "$(basename "$caller")")" "$(bot_json_string "$version")"; exit 2 ;; esac
            done ;;
    esac
    if [[ "$output" == library ]]; then printf '%s\n' 'Source this library; use --help for its API.' >&2; exit 2; fi
    # JSON identity belongs in info, never in a separate startup line.
    for argument in "$@"; do
        [[ "$argument" != -- ]] || break
        case "$argument" in --json|--pretty) export BOT_STRUCTURED_OUTPUT=true; return 0 ;; esac
    done
    bot_script_banner "$caller"
}

bot_json() {
    local caller="$1"; shift
    local runtime="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/bot_general.py"
    python3 "$runtime" --emit-json --script "$caller" "$@"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    bot_interface "${BASH_SOURCE[0]}" "$@"
fi
