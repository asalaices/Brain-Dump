# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Committed integration routing; configuration hints never grant source access."""
import json
import subprocess
from pathlib import Path

CONTROL_PATH = '.brain-bridge/publisher-route.json'

def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError('Required operator Git/GitHub operation failed')
    return result.stdout.strip()

def git(root, *args):
    return run('git', '-C', str(root), *args)

def project_root(value):
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir() or Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('Operator project must be an existing Git checkout root')
    return root

def control_json(root, ref, path):
    """Read only a regular small JSON blob from an existing committed ref."""
    commit = git(root, 'rev-parse', '--verify', ref + '^{commit}')
    parent = git(root, 'ls-tree', commit, '--', '.brain-bridge')
    if parent and parent.split()[0] != '040000':
        raise ValueError('Brain configuration namespace must be a committed directory')
    row = git(root, 'ls-tree', commit, '--', path)
    if not row:
        return None, commit
    mode, kind, oid = row.split('\t', 1)[0].split()
    if mode not in ('100644', '100755') or kind != 'blob':
        raise ValueError('Brain configuration must be a regular Git blob')
    if int(git(root, 'cat-file', '-s', oid)) > 65536:
        raise ValueError('Oversized Brain configuration')
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj: raise ValueError('Duplicate Brain configuration key')
            obj[key] = value
        return obj
    raw = subprocess.check_output(['git', '-C', str(root), 'show', commit + ':' + path])
    return json.loads(raw, object_pairs_hook=unique), commit

def publisher_route(root, ref='origin/main'):
    state, commit = control_json(root, ref, CONTROL_PATH)
    if state is None: raise ValueError('Operator requires an explicitly committed publisher route')
    if not isinstance(state,dict) or type(state.get('generation')) is not int or state['generation']<0 or type(state.get('schema_version')) is not int:
        raise ValueError('Invalid publisher route policy')
    if state['schema_version']==1:
        if set(state)!={'schema_version','mode','generation'} or state['mode'] not in ('legacy','paused'):raise ValueError('Invalid publisher route policy')
    elif state['schema_version']==2:
        if set(state)!={'schema_version','mode','reader','generation'} or state['mode'] not in ('legacy','paused','managed') or state['reader'] not in ('legacy','managed') or (state['mode']=='managed' and state['reader']!='managed'):raise ValueError('Invalid publisher route policy')
    else:raise ValueError('Unsupported publisher route schema')
    return {**state, 'policy_commit':commit}

def refresh_publisher_route(root):
    # Refresh only metadata/objects, never the active branch, index or files.
    remote=subprocess.run(['git','-C',str(root),'remote','get-url','origin'],capture_output=True,text=True)
    if remote.returncode==0:git(root,'fetch','origin','main')
    state=publisher_route(root)
    if remote.returncode and (state['mode']=='managed' or reader_route(state)=='managed'):
        raise ValueError('Managed routing requires a refreshable canonical origin')
    return state

def reader_route(state):
    return state.get('reader','legacy')

def require_managed_promotion_route(root,initial):
    git(root,'fetch','origin','main')
    current=publisher_route(root)
    if current['mode']!='managed' or current['generation']!=initial['generation'] or reader_route(current)!=reader_route(initial):
        raise ValueError('Managed promotion route changed or paused; retain the exact original draft/PR')
    before,_=control_json(root,initial['policy_commit'],'.brain-bridge/managed-runtime.json')
    after,_=control_json(root,current['policy_commit'],'.brain-bridge/managed-runtime.json')
    if before!=after:raise ValueError('Managed runtime profile changed; review and retry original draft')
    return current
