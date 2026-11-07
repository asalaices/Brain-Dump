#!/usr/bin/env bash
# script_version: 2.1.0
# Purpose: Reconcile this Git-owned skill through its own public Python package.
# Usage: install.sh {status|install|uninstall} [--skill-home ABSOLUTE] [--execute --yes] [--json|--pretty]
# Output: JSON; framework metadata and guarded discovery receipt.
# Prerequisites: Python3.11+ and Git; no other repository or Bash runtime library.
set -euo pipefail
source_dir="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
root="$(cd -- "$source_dir/../.." && pwd -P)"
if [[ "${1:-}" == '--version' ]]; then printf '%s\n' 'brain-bridge skill installer 2.1.0'; exit 0; fi
if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
    printf '%s\n' 'Usage: install.sh {status|install|uninstall} [--skill-home ABSOLUTE] [--execute --yes] [--json|--pretty]'
    exit 0
fi
operation="${1:-}"; [[ $# -gt 0 ]] && shift
case "$operation" in status|install|uninstall) ;; *) printf '%s\n' 'Select status, install or uninstall' >&2; exit 2 ;; esac
for option in "$@"; do
    case "$option" in --source|--source=*) printf '%s\n' 'This wrapper owns the source; use the native CLI for another package' >&2; exit 2 ;; esac
done
cd -- "$root"
exec "${BRAIN_BRIDGE_PYTHON:-python3}" -m brain_bridge skill-link "$operation" --source "$source_dir" --skill-home "${COPILOT_SKILLS_HOME:-$HOME/.copilot/skills}" "$@"
