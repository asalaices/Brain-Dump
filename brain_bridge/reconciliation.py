# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Bounded historical reconciliation; observe and checkpoint, never transplant.

Pending observation is not a published watermark. Only exact canonical bytes,
paths, IDs and provenance can acknowledge a captured source snapshot. No record
content, authorization, PR, installation or scheduler is written by this module.
"""
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from .authority import GitHubAuthority, Grant, git, github_slug
from .contract import record_entries
from .historical_import import plan_import, _facts
from .managed import immutable_snapshot, object_bytes
from .migration import plan_migration, repo_facts, repo_metadata, audience, audience_expansion, digest
from .policy import AccessDenied
from .store import unique_object, reject_constant
from .sync import sync, preflight

STATE_LIMIT = 8388608
STATE_KEYS = {'schema_version', 'binding', 'observed_source', 'observed_destination', 'inventory',
              'destination_inventory', 'captures', 'watermark', 'pending', 'token'}
HEX = re.compile(r'[0-9a-f]{64}')


def _inventory(repo, facts, namespace):
    snapshot = immutable_snapshot(repo, Grant('reconciliation-observer', facts['repository_id'],
                                  facts['repository'], facts['commit'], facts['ref']), namespace)
    listing = object_bytes(repo, 'ls-tree', '-rz', facts['commit'], '--', namespace + '/',
                           'metadata/' if namespace == 'records' else 'Brain-Bridge/metadata/')
    modes = {}
    for row in listing.split(b'\0'):
        if row:
            metadata, name = row.split(b'\t', 1)
            modes[name.decode()] = metadata.decode().split()[0]
    result = {}
    for name, sha, envelope in snapshot['records']:
        result['records/' + name] = {'kind': 'record', 'sha256': sha,
            'mode': modes[namespace + '/' + name], 'entry_ids': [entry['id'] for entry in record_entries(envelope)]}
    for name, sha, overlay in snapshot['overlays']:
        source_path = ('Brain-Bridge/' if namespace == 'Brain-Bridge' else '') + name
        result[name] = {'kind': 'provenance', 'sha256': sha, 'mode': modes[source_path], 'entry_ids': [overlay['entry_id']]}
    return result


def _plain(inventory):
    return {path: {key: value for key, value in item.items() if key != 'seen_at'}
            for path, item in inventory.items()}


def _counts(inventory):
    return {'files': len(inventory), 'records': sum(item['kind'] == 'record' for item in inventory.values()),
            'entries': sum(len(item['entry_ids']) for item in inventory.values() if item['kind'] == 'record'),
            'overlays': sum(item['kind'] == 'provenance' for item in inventory.values())}


def _append_only(previous, current):
    for path, old in previous.items():
        if current.get(path) != old:
            raise ValueError('Observed immutable ledger path/bytes/mode/IDs changed or disappeared')


def _audit_history(repo, old, new, namespace):
    if old == new: return
    git(repo, 'merge-base', '--is-ancestor', old, new)
    commits = git(repo, 'rev-list', '--first-parent', '--reverse', old + '..' + new).splitlines()
    previous = old
    for commit in commits:
        if git(repo, 'rev-parse', commit + '^1') != previous:
            raise ValueError('Observed canonical first-parent ancestry changed; review required')
        roots = [namespace + '/']
        if namespace == 'records': roots.append('metadata/')
        changed = object_bytes(repo, 'diff', '--name-status', '--no-renames', '-z', previous, commit, '--', *roots).split(b'\0')
        for index in range(0, len(changed) - 1, 2):
            action, path = changed[index:index + 2]
            if path.endswith(b'.json') and action != b'A':
                raise ValueError('Canonical ledger history was modified or deleted between observations')
        previous = commit
    if previous != new:
        raise ValueError('Canonical source ancestry could not be verified')


def _state_path(value, roots):
    path = Path(os.path.abspath(Path(value).expanduser()))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Reconciliation state must not contain symlinks')
    if any(path.is_relative_to(Path(root).resolve(strict=True)) for root in roots):
        raise ValueError('Reconciliation state must be outside Git checkouts')
    existing = path
    while not existing.exists(): existing = existing.parent
    if not existing.is_dir(): raise ValueError('Reconciliation state requires a directory')
    # Excludes every Git checkout, including a separately configured identity
    # repository, without discovering or reading another Brain source.
    check = subprocess.run(['git', '-C', str(existing), 'rev-parse', '--absolute-git-dir'],
                           capture_output=True, timeout=30)
    if check.returncode == 0:
        raise ValueError('Reconciliation state must be outside Git checkouts')
    return path


def _private(path, directory=False):
    if path.is_symlink(): raise ValueError('Reconciliation state symlink refused')
    info = path.stat()
    if (directory and not stat.S_ISDIR(info.st_mode)) or (not directory and not stat.S_ISREG(info.st_mode)):
        raise ValueError('Reconciliation state requires regular owner files')
    if os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)):
        raise ValueError('Reconciliation state must have owner-only permissions')


def _inventory_shape(inventory, observed=False):
    if not isinstance(inventory, dict) or len(inventory) > 20000: raise ValueError('Invalid reconciliation inventory')
    seen = set()
    for path, item in inventory.items():
        fields = {'kind', 'sha256', 'mode', 'entry_ids'} | ({'seen_at'} if observed else set())
        if not isinstance(path, str) or not path.endswith('.json') or not path.startswith(('records/', 'metadata/')) or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or PurePosixPath(path).as_posix() != path or '\\' in path or not isinstance(item, dict) or set(item) != fields:
            raise ValueError('Invalid reconciliation inventory file')
        if item['kind'] not in ('record', 'provenance') or path.startswith('records/') != (item['kind'] == 'record') or item['mode'] not in ('100644', '100755') or not isinstance(item['sha256'], str) or not HEX.fullmatch(item['sha256']):
            raise ValueError('Invalid reconciliation inventory identity')
        ids = item['entry_ids']
        if not isinstance(ids, list) or not ids or any(not isinstance(uid, str) or not uid for uid in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid reconciliation entry IDs')
        if item['kind'] == 'record':
            if seen.intersection(ids): raise ValueError('Duplicate reconciliation entry ID')
            seen.update(ids)
        elif len(ids) != 1: raise ValueError('Invalid provenance target')
        if observed and (type(item['seen_at']) is not int or item['seen_at'] < 0):
            raise ValueError('Invalid reconciliation observation sequence')


def _load(directory, binding):
    path = directory / 'state.json'
    if path.is_symlink(): raise ValueError('Reconciliation checkpoint symlink refused')
    if not path.exists(): return None
    _private(path)
    if path.stat().st_size > STATE_LIMIT: raise ValueError('Oversized reconciliation state')
    with path.open('rb') as stream: raw = stream.read(STATE_LIMIT + 1)
    if len(raw) > STATE_LIMIT: raise ValueError('Oversized reconciliation state')
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(value, dict) or set(value) != STATE_KEYS or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Invalid reconciliation checkpoint')
    body = dict(value); token = body.pop('token')
    if not isinstance(token, str) or not HEX.fullmatch(token) or digest(body) != token or value['binding'] != binding:
        raise ValueError('Reconciliation checkpoint token/source binding mismatch')
    for key in ('observed_source', 'observed_destination'): _facts(value[key])
    _inventory_shape(value['inventory'], True); _inventory_shape(value['destination_inventory'])
    captures = value['captures']; last = -1
    if not isinstance(captures, list) or not 1 <= len(captures) <= 1024:
        raise ValueError('Invalid reconciliation capture history')
    for capture in captures:
        if not isinstance(capture, dict) or set(capture) != {'sequence', 'source_commit', 'captured_at', 'inventory_sha256', 'counts'} or type(capture['sequence']) is not int or capture['sequence'] <= last:
            raise ValueError('Invalid reconciliation capture')
        last = capture['sequence']
        if not isinstance(capture['source_commit'], str) or not re.fullmatch(r'[0-9a-f]{40}', capture['source_commit']) or not isinstance(capture['captured_at'], str) or datetime.fromisoformat(capture['captured_at']).utcoffset() is None:
            raise ValueError('Invalid reconciliation captured snapshot')
        subset = {path: item for path, item in value['inventory'].items() if item['seen_at'] <= last}
        if digest(_plain(subset)) != capture['inventory_sha256'] or _counts(subset) != capture['counts']:
            raise ValueError('Reconciliation captured inventory differs from checkpoint')
    if captures[-1]['source_commit'] != value['observed_source']['commit'] or any(item['seen_at'] > last for item in value['inventory'].values()):
        raise ValueError('Reconciliation latest observation mismatch')
    if not isinstance(value['pending'], list) or any(not isinstance(path, str) for path in value['pending']) or value['pending'] != sorted(set(value['pending'])) or any(path not in value['inventory'] for path in value['pending']):
        raise ValueError('Invalid reconciliation pending outbox')
    watermark = value['watermark']
    if watermark is not None:
        fields = {'sequence', 'source_commit', 'captured_at', 'inventory_sha256', 'counts', 'verified_at', 'destination_commit'}
        if not isinstance(watermark, dict) or set(watermark) != fields or not any(all(watermark.get(key) == item for key, item in capture.items()) for capture in captures):
            raise ValueError('Invalid reconciliation verified watermark')
        if not isinstance(watermark['verified_at'], str) or datetime.fromisoformat(watermark['verified_at']).utcoffset() is None or not isinstance(watermark['destination_commit'], str) or not re.fullmatch(r'[0-9a-f]{40}', watermark['destination_commit']):
            raise ValueError('Invalid reconciliation watermark verification')
    return value


@contextmanager
def _lock(directory, create):
    path = directory / 'state.lock'
    flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    if create: flags |= os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
    try:
        _private(path)
        if os.name == 'nt':
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                if not create: raise ValueError('Checkpoint lock is uninitialized; explicit execution required')
                os.write(descriptor, b'\0'); os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try: msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc: raise RuntimeError('Reconciliation checkpoint is locked by another worker') from exc
        else:
            import fcntl
            try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc: raise RuntimeError('Reconciliation checkpoint is locked by another worker') from exc
        yield
    finally:
        os.close(descriptor)


def _save(directory, state):
    raw = (json.dumps(state, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
    if len(raw) > STATE_LIMIT: raise ValueError('Reconciliation checkpoint exceeds bounded private storage')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.state-', delete=False) as stream:
            temporary = Path(stream.name); os.chmod(temporary, 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, directory / 'state.json')
        if os.name == 'posix':
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def _refresh_targets(source_repo, destination_repo, source_id, destination_id, api):
    targets = {}
    for role, repo, expected, write in (('source', source_repo, source_id, False), ('destination', destination_repo, destination_id, True)):
        remote = git(repo, 'remote', 'get-url', 'origin')
        facts, info = repo_metadata(repo, expected, 'main', api, write=write)
        if github_slug(remote) != facts['repository'] or git(repo, 'remote', 'get-url', 'origin') != remote:
            raise AccessDenied('Reader origin changed during refresh authorization')
        targets[role] = {'repo': repo, 'remote': remote, 'facts': facts, 'info': info,
                         'audience': audience(api, facts['repository'], info)}
    if audience_expansion(targets['source']['info'], targets['source']['audience'], targets['destination']['audience']):
        raise AccessDenied('Destination audience expands access; reader refresh withheld')
    return targets


def _refresh_unchanged(targets, api):
    for role, target in targets.items():
        facts, info = repo_metadata(target['repo'], target['facts']['repository_id'], 'main', api, write=role == 'destination')
        if facts != target['facts'] or info.get('private') != target['info'].get('private') or git(target['repo'], 'remote', 'get-url', 'origin') != target['remote'] or audience(api, facts['repository'], info) != target['audience']:
            raise AccessDenied('Published reader target/origin/audience changed; checkpoint withheld')


def _refresh_readers(targets, namespace, directory, prior, api):
    database = directory / 'unused-reader-index.sqlite'
    # Check BOTH selected readers before either can fast-forward. Every Git and
    # dirty/branch guard remains owned by the existing sync implementation.
    for role, target in targets.items():
        preflight(target['repo'], target['remote'], 'main', namespace if role == 'source' else 'records', database)
    result = {}
    for role, target in targets.items():
        records = namespace if role == 'source' else 'records'
        def authorize(commit, role=role, target=target, records=records):
            if commit != target['facts']['commit']: raise AccessDenied('Unexpected authenticated refresh target')
            _refresh_unchanged(targets, api)
            if prior:
                old = prior['observed_source' if role == 'source' else 'observed_destination']['commit']
                _audit_history(target['repo'], old, commit, records)
                inventory = _inventory(target['repo'], target['facts'], records)
                _append_only(_plain(prior['inventory']) if role == 'source' else prior['destination_inventory'], inventory)
        result[role] = sync(target['repo'], target['remote'], 'main', records, database, contract='history',
                            expected_commit=target['facts']['commit'], authorize_target=authorize, build_index=False)
    _refresh_unchanged(targets, api)
    return result


def _cycle(source_repo, destination_repo, source_id, destination_id, source_ref, destination_ref,
           namespace, state_dir, execute, yes, api, previous=None, refresh=False):
    if source_ref != 'main' or destination_ref != 'main':
        raise ValueError('Canonical reconciliation requires source and destination main')
    if execute and (not yes or state_dir is None):
        raise ValueError('Checkpoint execution requires --state-dir and --yes')
    if yes and not execute: raise ValueError('--yes requires explicit checkpoint execution')
    if refresh and (not execute or not yes or state_dir is None):
        raise ValueError('Reader refresh requires --execute --yes and --state-dir')
    directory = _state_path(state_dir, (source_repo, destination_repo)) if state_dir is not None else None
    # Initial authenticated preflight occurs before any private-directory creation.
    targets = _refresh_targets(source_repo, destination_repo, source_id, destination_id, api) if refresh else None
    plan = {'source': targets['source']['facts'], 'destination': targets['destination']['facts']} if targets else plan_migration(
        source_repo, destination_repo, source_id, destination_id, source_ref, destination_ref, namespace, api)
    if not refresh and plan['audience_expansion']: raise AccessDenied('Destination audience expands access; reconciliation withheld')
    binding = {'source_id': source_id, 'destination_id': destination_id, 'source_ref': source_ref,
               'destination_ref': destination_ref, 'namespace': namespace,
               'source_repository': plan['source']['repository'], 'destination_repository': plan['destination']['repository']}
    if directory is not None and directory.exists(): _private(directory, True)
    if execute:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700); _private(directory, True)
    locking = nullcontext()
    if directory is not None and directory.exists():
        lock_path = directory / 'state.lock'
        if execute or lock_path.exists(): locking = _lock(directory, execute)
        elif (directory / 'state.json').exists(): raise ValueError('Checkpoint lock is missing; do not bypass its owner')
    with locking:
        prior = _load(directory, binding) if directory is not None and directory.exists() else previous
        refreshed = _refresh_readers(targets, namespace, directory, prior, api) if targets else None
        if refreshed:
            plan = plan_migration(source_repo, destination_repo, source_id, destination_id, source_ref, destination_ref, namespace, api)
            if plan['audience_expansion'] or any(plan[role] != target['facts'] for role, target in targets.items()):
                raise AccessDenied('Published snapshots changed after refresh; checkpoint withheld')
        source = _inventory(source_repo, plan['source'], namespace)
        destination = _inventory(destination_repo, plan['destination'], 'records')
        _inventory_shape(source); _inventory_shape(destination)
        if prior:
            if prior['binding'] != binding: raise ValueError('Reconciliation state source changed')
            _audit_history(source_repo, prior['observed_source']['commit'], plan['source']['commit'], namespace)
            _audit_history(destination_repo, prior['observed_destination']['commit'], plan['destination']['commit'], 'records')
            _append_only(_plain(prior['inventory']), source)
            _append_only(prior['destination_inventory'], destination)
        for path in source.keys() & destination.keys():
            if source[path] != destination[path]: raise ValueError('Source/destination canonical path/bytes/mode/IDs conflict')
        captured_at = datetime.now(timezone.utc).isoformat()
        changed = not prior or prior['observed_source']['commit'] != plan['source']['commit']
        sequence = prior['captures'][-1]['sequence'] + 1 if prior and changed else (prior['captures'][-1]['sequence'] if prior else 0)
        inventory = {path: {**item, 'seen_at': prior['inventory'][path]['seen_at'] if prior and path in prior['inventory'] else sequence}
                     for path, item in source.items()}
        captures = copy.deepcopy(prior['captures']) if prior else []
        if changed:
            captures.append({'sequence': sequence, 'source_commit': plan['source']['commit'],
                'captured_at': captured_at, 'inventory_sha256': digest(source), 'counts': _counts(source)})
        pending = sorted(source.keys() - destination.keys())
        watermark = None
        for capture in captures:
            subset = {path: item for path, item in inventory.items() if item['seen_at'] <= capture['sequence']}
            if all(path in destination and _plain({path: item})[path] == destination[path] for path, item in subset.items()):
                watermark = {**capture, 'verified_at': captured_at, 'destination_commit': plan['destination']['commit']}
        if watermark:
            # Private checkpoints are derived and locally mutable. Rebind the
            # selected capture to real source Git objects before acknowledging it.
            commit = watermark['source_commit']
            git(source_repo, 'merge-base', '--is-ancestor', commit, plan['source']['commit'])
            canonical = source if commit == plan['source']['commit'] else _inventory(source_repo, {**plan['source'], 'commit': commit}, namespace)
            subset = _plain({path: item for path, item in inventory.items() if item['seen_at'] <= watermark['sequence']})
            if canonical != subset or digest(canonical) != watermark['inventory_sha256'] or _counts(canonical) != watermark['counts']:
                raise ValueError('Captured source snapshot does not match canonical inventory')
            captures = [capture for capture in captures if capture['sequence'] >= watermark['sequence']]
        if len(captures) > 1024: raise ValueError('Too many unacknowledged source captures; drain or review reconciliation')
        proposal = plan_import(source_repo, destination_repo, source_id, destination_id,
                               source_ref, destination_ref, namespace, api) if pending else None
        if proposal and (proposal['manifest']['source'] != plan['source'] or proposal['manifest']['destination'] != plan['destination']):
            raise AccessDenied('Source/destination changed while proposing reconciliation')
        # Every observation/state result remains conditional on refreshed current
        # published snapshots and audience. A cached allow never serves a cycle.
        for which, write in (('source', False), ('destination', True)):
            facts, info = repo_facts(source_repo if which == 'source' else destination_repo,
                                    plan[which]['repository_id'], plan[which]['ref'], api, write=write)
            if facts != plan[which] or audience(api, facts['repository'], info) != plan[which + '_audience']:
                raise AccessDenied('Source/destination or audience changed during reconciliation')
        state = {'schema_version': 1, 'binding': binding, 'observed_source': plan['source'],
            'observed_destination': plan['destination'], 'inventory': inventory,
            'destination_inventory': destination, 'captures': captures, 'watermark': watermark, 'pending': pending}
        state['token'] = digest(state)
        if execute: _save(directory, state)
        pending_inventory = {path: source[path] for path in pending}
        oldest = next((capture for capture in captures if any(item['seen_at'] <= capture['sequence'] for path, item in inventory.items() if path in pending)), None)
        lag = max(0, (datetime.fromisoformat(captured_at) - datetime.fromisoformat(oldest['captured_at'])).total_seconds()) if oldest else 0
        result = {'schema_version': 1, 'operation': 'reconciliation', 'status': 'pending' if pending else 'caught_up',
            'source': plan['source'], 'destination': plan['destination'], 'observed': _counts(source),
            'pending': _counts(pending_inventory), 'outbox': [{'path': path, **source[path]} for path in pending],
            'destination_only': _counts({path: item for path, item in destination.items() if path not in source}),
            'verified_watermark': watermark, 'captured_snapshots': len(captures), 'lag_seconds': lag,
            'proposal': proposal, 'state_written': bool(execute), 'read_only': not execute,
            'records_copied': False, 'authorization_written': False, 'cutover': False,
            'readers_refreshed': refreshed is not None, 'refresh': refreshed}
        return result, state


def reconcile(source_repo, destination_repo, source_id, destination_id, source_ref='main',
              destination_ref='main', namespace='Brain-Bridge', state_dir=None, execute=False,
              yes=False, authority=None, refresh=False):
    """One-shot default observation; execution writes only private checkpoint metadata."""
    result, _ = _cycle(source_repo, destination_repo, source_id, destination_id, source_ref,
                        destination_ref, namespace, state_dir, execute, yes, authority or GitHubAuthority(), refresh=refresh)
    return result


def poll_reconciliation(source_repo, destination_repo, source_id, destination_id, source_ref='main',
                        destination_ref='main', namespace='Brain-Bridge', state_dir=None, execute=False,
                        yes=False, authority=None, cycles=1, interval=60, wait=time.sleep, refresh=False):
    """Bounded receipt stream; release the per-cycle lock before yielding/waiting."""
    if type(cycles) is not int or not 1 <= cycles <= 1000 or isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0 < interval <= 3600:
        raise ValueError('Reconciliation requires1–1000 cycles and interval(0,3600] seconds')
    api = authority or GitHubAuthority(); previous = None
    for cycle in range(cycles):
        receipt, previous = _cycle(source_repo, destination_repo, source_id, destination_id, source_ref,
            destination_ref, namespace, state_dir, execute, yes, api, previous, refresh=refresh)
        yield {**receipt, 'cycle': cycle + 1, 'cycles': cycles, 'stream': 'jsonl' if cycles > 1 else 'json'}
        if cycle + 1 < cycles: wait(interval)
