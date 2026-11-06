#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
# script_version: 1.0.0
# Purpose: Delegate discovery of this Git-owned consult skill to the explicitly selected guarded master installer.
# Usage: install.sh --installer-root ROOT {status|install|uninstall} [--execute --yes] [--debug] [--log-file PATH]; --help | --version.
# Output: wrapper; preserves the selected link owner's output, logging and exit status.
# Prerequisites: Git-owned source package and an explicit existing master installer checkout; no network or source grants are configured.
# Failure: Missing or conflicting ownership fails closed; this wrapper never copies source or replaces discovery paths itself.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: skills/brain-bridge/install.sh --installer-root ROOT COMMAND [OPTIONS]

Commands and options belong to the existing guarded skill-link owner:
  status
  install|uninstall [--execute --yes] [--debug] [--log-file PATH]

ROOT must be the explicitly selected master installer Git checkout. This wrapper
supplies its own Git-owned source directory. COPILOT_SKILLS_HOME overrides the
discovery directory (for example, a chosen Codex skills directory). Plans do not
create links; conflicting files, directories and foreign links remain refused.
No credentials, source registration, access grants or publishing route changes.
EOF
}

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 2; }

# Informational flags perform no Git, filesystem-owner or link operation.
for argument in "$@"; do
    case "$argument" in
        --help|-h) usage; exit 0 ;;
        --version) printf '%s\n' 'brain-bridge skill installer 1.0.0'; exit 0 ;;
    esac
done

installer_root=''
forward=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --installer-root)
            [[ -z "$installer_root" && $# -ge 2 && -n "$2" ]] || fail 'Provide exactly one --installer-root ROOT'
            installer_root="$2"; shift 2 ;;
        --source|--source=*) fail 'The package owns --source; select only --installer-root' ;;
        *) forward+=("$1"); shift ;;
    esac
done
[[ -n "$installer_root" && ${#forward[@]} -gt 0 ]] || { usage >&2; fail 'An explicit installer root and command are required'; }
case "${forward[0]}" in status|install|uninstall) ;; *) fail 'Command must be status, install or uninstall' ;; esac
[[ -d "$installer_root" && ! -L "$installer_root" ]] || fail 'Installer root must be an existing Git checkout directory'
installer_root="$(cd -P -- "$installer_root" && pwd -P)"
installer_git_root="$(git -C "$installer_root" rev-parse --show-toplevel 2>/dev/null)" || fail 'Installer root must be the Git checkout root'
installer_git_root="$(cd -P -- "$installer_git_root" && pwd -P)"
[[ "$installer_git_root" == "$installer_root" ]] || fail 'Installer root must be the Git checkout root'
for relative in intelli_bots/bot_local_skill_link.sh intelli_bots/bot_general.inc intelli_bots/bot_general.py; do
    [[ -f "$installer_root/$relative" && ! -L "$installer_root/$relative" ]] || fail 'Selected installer is missing its regular shared owner files'
    git -C "$installer_root" ls-files --error-unmatch -- "$relative" >/dev/null 2>&1 || fail 'Selected installer owner files must be tracked in Git'
done
source_dir="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source_root="$(git -C "$source_dir" rev-parse --show-toplevel 2>/dev/null)" || fail 'Skill source must belong to a Git checkout'
source_root="$(cd -P -- "$source_root" && pwd -P)"
source_relative="${source_dir#"$source_root"/}"
[[ "$source_relative" != "$source_dir" ]] || fail 'Skill source must be inside its Git checkout'
for name in SKILL.md README.md install.sh; do
    [[ -f "$source_dir/$name" && ! -L "$source_dir/$name" ]] || fail 'Skill source requires regular package files'
    git -C "$source_root" ls-files --error-unmatch -- "$source_relative/$name" >/dev/null 2>&1 || fail 'Skill package files must be tracked in Git'
done
exec "$BASH" "$installer_root/intelli_bots/bot_local_skill_link.sh" "${forward[@]}" --source "$source_dir"
