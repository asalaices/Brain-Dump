#!/usr/bin/env bash
# script_version: 1.0.0
# Purpose: Select registered Brain-Dump phases and stacks and explicitly plan, verify, or install owned resources.
# Usage: bash bootstrap/bootstrap.sh --host local [--phase ID|--stack NAME] [--plan|--verify|--install --execute] --config PROFILE [--json|--pretty]
# Output: wrapper
# Prerequisites: Bash 3.2+, Python 3.11+, Git, and a reviewed Brain-Dump checkout; help/version are read-only.
# Failure: Nonzero exit; plans never mutate, and install requires --execute.
# shellcheck source=intelli_bots/bot_general.inc
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)/intelli_bots/bot_general.inc"
bot_interface "${BASH_SOURCE[0]}" "$@"
export PYTHONDONTWRITEBYTECODE=1
bootstrap_python="${BRAIN_BOOTSTRAP_PYTHON:-python3}"
exec "$bootstrap_python" -B "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/assets/controller.py" "$@"
