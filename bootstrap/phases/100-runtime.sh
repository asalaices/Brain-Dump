#!/usr/bin/env bash
# script_version: 1.0.0
# Purpose: Reconcile the existing pinned Brain runtime through the registered numbered bootstrap owner.
# Usage: bash bootstrap/phases/100-runtime.sh --host local --config PROFILE [--plan|--verify|--install --execute] [--json|--pretty]
# Output: wrapper
# Logging-Owner: bootstrap/includes/bootstrap_general.inc
# Prerequisites: Phase 000 and an existing reviewed schema-2 installation profile.
# Failure: Nonzero exit; existing consultation, cache, grants, routes, and services remain untouched.
# shellcheck source=bootstrap/includes/bootstrap_general.inc
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)/includes/bootstrap_general.inc"
case "${1:-}" in
    --help) printf '%s\n' 'Usage: bash bootstrap/phases/100-runtime.sh --host local --config PROFILE [--plan|--verify|--install --execute] [--json|--pretty]'; exit 0 ;;
    --version) printf '%s\n' '100-runtime.sh 1.0.0'; exit 0 ;;
esac
bootstrap_phase_exec runtime_phase.py "$@"
