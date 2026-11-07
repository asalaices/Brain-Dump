#!/usr/bin/env bash
# script_version: 1.0.0
# Purpose: Capture a Brain-Dump bootstrap/test command into private raw and sanitized local telemetry without publishing.
# Usage: bash bootstrap/telemetry/mac-run.sh -- COMMAND [ARG...]
# Output: wrapper
# Prerequisites: Existing command and private writable local state; help/version are read-only.
# Failure: Returns the child status; telemetry failure never converts child success into deployment success or vice versa.
# shellcheck source=intelli_bots/bot_general.inc
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)/intelli_bots/bot_general.inc"
bot_interface "${BASH_SOURCE[0]}" "$@"
set -Eeuo pipefail
[[ "${1:-}" == -- ]] || die 2 "Usage: mac-run.sh -- COMMAND [ARG...]"
shift
(($#)) || die 2 "A command is required"
state="${XDG_STATE_HOME:-$HOME/.local/state}/brain-bridge/bootstrap-telemetry"
run="$(date -u '+%Y%m%dT%H%M%SZ')-$BOT_RUN_ID"
directory="$state/$run"
umask 077
mkdir -p "$directory"
raw="$directory/execution.raw.log"
sanitized="$directory/execution.log"
manifest="$directory/manifest.json"
started="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
set +e
"$@" >"$raw" 2>&1
status=$?
set -e
sed -E \
  -e 's/([Aa]uthorization|[Cc]ookie|[Cc]redential|[Pp]assword|[Pp]rivate[_ -]?[Kk]ey|[Ss]ecret|[Tt]oken)([=:][[:space:]]*|[[:space:]]+).*/\1=[REDACTED]/g' \
  -e 's/B[e]arer[[:space:]]+[^[:space:]]+/AUTH_SCHEME=[REDACTED]/g' \
  -e 's/gh[pousr]_[A-Za-z0-9_]+/GITHUB_TOKEN=[REDACTED]/g' \
  "$raw" >"$sanitized"
"${BRAIN_BOOTSTRAP_PYTHON:-python3}" - "$manifest" "$run" "$started" "$status" "$(basename "$1")" <<'PY'
import json,pathlib,sys
path=pathlib.Path(sys.argv[1])
path.write_text(json.dumps({'schema_version':1,'run_id':sys.argv[2],
    'started_utc':sys.argv[3],'exit_code':int(sys.argv[4]),
    'command_basename':sys.argv[5],'published':False},indent=2)+'\n')
path.chmod(0o600)
PY
chmod 0600 "$raw" "$sanitized"
exit "$status"
