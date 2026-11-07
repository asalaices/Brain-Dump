# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Explicit portable installation profiles and one bounded install lock."""
import json
import re
from contextlib import contextmanager
from pathlib import Path
from .discovery import safe


def load_config(path):
    path = Path(path)
    safe(path)
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Select a bounded regular installation profile')
    c = json.loads(path.read_text(encoding='utf-8'))
    required = {'schema_version','host','home','runtime_dir','source_repo',
                'framework_commit','framework_version','python','python_version',
                'setuptools_version','launcher','skill_home','skill'}
    optional = {'legacy_version','legacy_skill_sha256','operation','wheel','wheel_sha256'}
    if not isinstance(c, dict) or set(c)-required-optional or required-set(c) or type(c['schema_version']) is not int or c['schema_version'] != 2:
        raise ValueError('Invalid installation profile schema')
    for key in ('host','framework_commit','framework_version','python_version','setuptools_version','skill'):
        if not isinstance(c[key],str):raise ValueError('Installation profile values must be strings')
    for key in ('home','runtime_dir','source_repo','python','launcher','skill_home'):
        if not isinstance(c[key],str) or any(x in c[key] for x in ('\0','\r','\n')):
            raise ValueError('Invalid installation path')
        safe(c[key],allow_link=(key=='launcher'),allow_external_readonly=(key=='python'))
    if c['skill'] != 'skills/brain-dump' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',c['host']):
        raise ValueError('Invalid host or skill selection')
    if not re.fullmatch('[0-9a-f]{40}',c['framework_commit']):
        raise ValueError('An immutable framework commit is required')
    for key in ('framework_version','python_version','setuptools_version'):
        if not re.fullmatch(r'\d+\.\d+\.\d+',c[key]):
            raise ValueError('Exact dependency versions are required')
    # Every writable resource is confined to the user's explicitly selected home.
    home = Path(c['home'])
    for key in ('runtime_dir','launcher','skill_home'):
        if not Path(c[key]).is_relative_to(home) or Path(c[key]) == home:
            raise ValueError('Managed paths must be below the selected home')
    runtime = Path(c['runtime_dir'])
    if Path(c['source_repo']).is_relative_to(runtime) or runtime.is_relative_to(Path(c['source_repo'])):
        raise ValueError('Keep source and runtime directories separate')
    c.setdefault('operation','brain-bridge-runtime')
    if c['operation'] not in ('brain-bridge-runtime','macbook-brain-bridge'):
        raise ValueError('Unknown installation receipt owner')
    c.setdefault('legacy_version',None)
    c.setdefault('legacy_skill_sha256',{})
    pins = c['legacy_skill_sha256']
    if not isinstance(pins,dict) or any(n not in ('SKILL.md','references/agent-adapters.md') or not re.fullmatch('[0-9a-f]{64}',str(v)) for n,v in pins.items()):
        raise ValueError('Invalid optional legacy migration pins')
    if c['legacy_version'] is not None and (not isinstance(c['legacy_version'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',c['legacy_version']) or not pins):
        raise ValueError('Legacy migration requires reviewed version and exact skill hashes')
    if ('wheel' in c) != ('wheel_sha256' in c):raise ValueError('Offline wheel requires its reviewed SHA256')
    if 'wheel' in c:
        if not isinstance(c['wheel'],str):raise ValueError('Offline wheel path must be a string')
        safe(c['wheel'])
        if not Path(c['wheel']).is_file() or not re.fullmatch('[0-9a-f]{64}',str(c['wheel_sha256'])):raise ValueError('Invalid offline wheel or checksum')
    return c


@contextmanager
def installation_lock(c):
    root = Path(c['runtime_dir'])
    safe(root)
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock = root / '.installation.lock'
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError('Another runtime installation is active; retry') from exc
    try:
        yield
    finally:
        lock.rmdir()
