#!/usr/bin/env bash
# script_version: 1.0.0
# Purpose: Run registered Brain-Dump offline tests through the common suite runner and local telemetry capture.
# Usage: bash bootstrap/telemetry/run-tests.sh [-- TEST_PATH...]
# Output: wrapper
# Prerequisites: Python 3.11+ and registered tests; live/manual checks are never selected.
# Failure: Preserves the suite runner status and retains private local telemetry.
# shellcheck source=intelli_bots/bot_general.inc
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)/intelli_bots/bot_general.inc"
bot_interface "${BASH_SOURCE[0]}" "$@"
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
args=(--component bootstrap --all --offline)
if [[ "${1:-}" == -- ]]; then
    shift
    args=(--component bootstrap --offline)
    for test in "$@"; do args+=(--test "$test"); done
fi
exec /bin/bash "$root/bootstrap/telemetry/mac-run.sh" -- "${BRAIN_BOOTSTRAP_PYTHON:-python3}" "$root/tests/suite_runner.py" "${args[@]}"
