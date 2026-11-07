#!/usr/bin/env bash
# script_version: 1.0.0
# Purpose: Plan or verify Brain-Dump bootstrap platform, interpreter, Git, and profile prerequisites.
# Usage: bash bootstrap/phases/000-preflight.sh --host local [--plan|--verify|--install --execute] [--config PROFILE] [--json|--pretty]
# Output: wrapper
# Logging-Owner: bootstrap/includes/bootstrap_general.inc
# Prerequisites: Registered Brain-Dump bootstrap checkout; help/version are read-only.
# Failure: Nonzero exit when platform, Python, Git, or selected profile prerequisites are invalid.
# shellcheck source=bootstrap/includes/bootstrap_general.inc
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)/includes/bootstrap_general.inc"
case "${1:-}" in
    --help) printf '%s\n' 'Usage: bash bootstrap/phases/000-preflight.sh --host local [--plan|--verify|--install --execute] [--config PROFILE] [--json|--pretty]'; exit 0 ;;
    --version) printf '%s\n' '000-preflight.sh 1.0.0'; exit 0 ;;
esac
bootstrap_phase_exec preflight_phase.py "$@"
