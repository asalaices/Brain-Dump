# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Git-owned skill discovery; never replace another owner's files."""
import os
import subprocess
from pathlib import Path


def safe(path, allow_link=False, allow_system_owned=False):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Installation paths must be absolute')
    for item in (path, *path.parents):
        if item.is_symlink() and not (item == path and allow_link):
            raise ValueError('Symlinked installation path refused: ' + str(item))
        if item.exists() and hasattr(os, 'getuid') and item.stat().st_uid != os.getuid():
            # System-owned ancestors are normal; only the selected object is owned.
            if item == path:
                mode=item.stat().st_mode
                if allow_system_owned and item.stat().st_uid == 0 and not mode & 0o022:
                    continue
                raise ValueError('Installation path belongs to another user')


def validate_source(source):
    source = Path(source)
    safe(source)
    if source.name != 'brain-dump' or not source.is_dir():
        raise ValueError('Select a Git-owned brain-dump skill directory')
    def git(*args):
        p = subprocess.run(['git', '-C', str(source), *args], capture_output=True,
                           text=True, timeout=30)
        if p.returncode:
            raise ValueError('Skill source must be tracked in its Git checkout')
        return p.stdout.strip()
    root = Path(git('rev-parse', '--show-toplevel')).resolve()
    relative = source.relative_to(root).as_posix()
    names = ('SKILL.md', 'README.md', 'install.sh',
             'references/submission.md', 'references/agent-adapters.md')
    for name in names:
        path = source / name
        safe(path)
        if not path.is_file():
            raise ValueError('Incomplete Git-owned skill package')
        tracked = relative + '/' + name
        git('ls-files', '--error-unmatch', '--', ':(top)'+tracked)
        # Discovery is executable agent policy: reject loose/unreviewed edits.
        if git('hash-object', '--', str(path)) != git('rev-parse', 'HEAD:' + tracked):
            raise ValueError('Skill source differs from its committed Git version')
    text = (source / 'SKILL.md').read_text(encoding='utf-8')
    if not text.startswith('---\n') or '\nname: brain-dump\n' not in text:
        raise ValueError('Skill frontmatter does not name brain-dump')
    return source


def reconcile_skill(source, skill_home, operation, execute=False, yes=False):
    if operation not in ('status', 'install', 'uninstall'):
        raise ValueError('Unknown discovery operation')
    if (yes and not execute) or (operation == 'status' and (yes or execute)):
        raise ValueError('Execution flags are invalid for this operation')
    source = validate_source(source)
    home = Path(skill_home)
    safe(home)
    target = home / 'brain-dump'
    safe(target, allow_link=True)
    def state():
        if target.is_symlink():
            return 'linked' if os.readlink(target) == str(source) else 'conflict'
        return 'conflict' if target.exists() else 'missing'
    before = state()
    if operation != 'status' and before == 'conflict':
        raise ValueError('Refusing non-owned skill discovery path')
    if execute:
        if not yes:
            raise ValueError('Skill changes require --execute --yes')
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        safe(home)
        lock = home / '.brain-bridge-discovery.lock'
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise ValueError('Another discovery operation is active; retry') from exc
        try:
            if state() != before:
                raise ValueError('Skill ownership changed before execution')
            if operation == 'install' and before == 'missing':
                target.symlink_to(source, target_is_directory=True)
            elif operation == 'uninstall' and before == 'linked':
                target.unlink()
        finally:
            lock.rmdir()
    return {'ok': True, 'operation': operation, 'source': str(source),
            'target': str(target), 'before': before, 'state': state(),
            'executed': execute, 'changed': state() != before,
            'activates_sources': False}


def migrate_skill(source, skill_home, previous_source, execute=False, yes=False):
    """Replace one explicitly identified obsolete link; no foreign replacement."""
    source = validate_source(source)
    home = Path(skill_home); safe(home)
    previous_source = Path(previous_source); safe(previous_source)
    if previous_source.name != 'brain-bridge':
        raise ValueError('Select the exact prior brain-bridge source')
    if yes and not execute:
        raise ValueError('--yes requires --execute')
    old = home / 'brain-bridge'; target = home / 'brain-dump'
    safe(old, allow_link=True); safe(target, allow_link=True)
    def state(path, expected):
        if path.is_symlink():
            return 'owned' if os.readlink(path) == str(expected) else 'conflict'
        return 'conflict' if path.exists() else 'missing'
    before = (state(old,previous_source),state(target,source))
    if 'conflict' in before:
        raise ValueError('Discovery migration refuses foreign links, files or directories')
    created = removed = False
    if execute:
        if not yes:raise ValueError('Migration requires --execute --yes')
        home.mkdir(mode=0o700,parents=True,exist_ok=True)
        lock=home/'.brain-bridge-discovery.lock'
        try:lock.mkdir(mode=0o700)
        except FileExistsError as exc:raise ValueError('Another discovery operation is active; retry') from exc
        try:
            if (state(old,previous_source),state(target,source)) != before:
                raise ValueError('Discovery ownership changed before migration')
            if before[1]=='missing':
                target.symlink_to(source,target_is_directory=True);created=True
            if before[0]=='owned':old.unlink();removed=True
            if state(target,source)!='owned' or state(old,previous_source)!='missing':
                raise ValueError('Discovery migration verification failed')
        except Exception:
            if removed and not old.exists() and not old.is_symlink():old.symlink_to(previous_source,target_is_directory=True)
            if created and state(target,source)=='owned':target.unlink()
            raise
        finally:lock.rmdir()
    return {'ok':True,'operation':'migrate','source':str(source),'target':str(target),
            'previous_source':str(previous_source),'previous_target':str(old),
            'executed':execute,'changed':created or removed,
            'state':state(target,source),'previous_state':state(old,previous_source),
            'activates_sources':False}
