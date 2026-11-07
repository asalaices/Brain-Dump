#!/usr/bin/env bash
# script_version: 1.0.0
# Purpose: Provide the shared Brain-Dump bootstrap phase interface, progress linkage, and common logging.
# Usage: source bootstrap/includes/bootstrap_general.inc; call bootstrap_phase_exec ASSET "$@"; direct help/version are read-only.
# Output: library
# API: bootstrap_phase_exec ASSET ARGS; imports are silent and all diagnostics use bot_general.inc.
# Prerequisites: Registered Brain-Dump bootstrap controller and Python 3.11+.
# Failure: Returns the delegated phase exit status without changing deployment state.
# Owned wrappers: 000-preflight.sh 100-runtime.sh
# shellcheck source=intelli_bots/bot_general.inc
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)/intelli_bots/bot_general.inc"
bot_interface "${BASH_SOURCE[0]}" "$@"
if [[ -n "${BRAIN_BOOTSTRAP_GENERAL_LOADED:-}" ]]; then return 0; fi
readonly BRAIN_BOOTSTRAP_GENERAL_LOADED=1

bootstrap_phase_exec() {
    local asset="$1"
    shift
    [[ "$asset" =~ ^[A-Za-z0-9_.-]+[.]py$ ]] ||
        die 2 "Invalid registered phase asset" "asset=$asset"
    local root
    root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
    [[ -f "$root/assets/$asset" && ! -L "$root/assets/$asset" ]] ||
        die 2 "Registered phase asset is missing" "asset=$asset"
    local python="${BRAIN_BOOTSTRAP_PYTHON:-python3}"
    exec "$python" -B "$root/assets/$asset" "$@"
}
