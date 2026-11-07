#!/usr/bin/env bash
# script_version: 1.0.0
# Purpose: Plan Brain-Dump bootstrap telemetry publication; public-repository publication remains disabled.
# Usage: bash bootstrap/telemetry/publish.sh [--json|--pretty]
# Output: json
# Prerequisites: A separately reviewed private telemetry destination; none is configured in public source.
# Failure: Returns nonzero for execution because publication is intentionally unavailable.
# shellcheck source=intelli_bots/bot_general.inc
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)/intelli_bots/bot_general.inc"
bot_interface "${BASH_SOURCE[0]}" "$@"
pretty=()
for arg in "$@"; do
  case "$arg" in
    --json) ;;
    --pretty) pretty=(--pretty) ;;
    *) die 2 "Usage: publish.sh [--json|--pretty]" ;;
  esac
done
printf '%s\n' '{"ok":true,"action":"plan","executed":false,"effects":[],"status":"private_destination_not_configured"}' |
  bot_json "${BASH_SOURCE[0]}" ${pretty[@]+"${pretty[@]}"}
