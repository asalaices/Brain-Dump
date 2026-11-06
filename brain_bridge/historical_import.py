# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Two-stage, exact-byte historical import proposals; never copy or enroll data.

An authenticated operator proposes a manifest. Destination CI trusts only a
manifest already reviewed into BASE, not a candidate's self-authorization.
It verifies approved bytes offline; it does not attest live source permissions.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import PurePosixPath
from .authority import GitHubAuthority, Grant, git, github_slug
from .contract import record_entries, validate_history
from .managed import immutable_snapshot, object_bytes, history_compatibility
from .migration import plan_migration, repo_facts, audience, digest, reference
from .policy import AccessDenied, Identity, repository_id
from .store import unique_object, reject_constant

PREFIX = '.brain-bridge/imports/'
TOKEN = re.compile(r'[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
KINDS = ('legacy_github_issue_shape', 'legacy_analysis_object')
MAX_BYTES = 134217728


def regular_json(repo, commit, path, limit=1048576):
    row = object_bytes(repo, 'ls-tree', commit, '--', path)
    if not row:
        raise ValueError('Required committed import control is unavailable')
    mode, kind, oid = row.split(b'\t', 1)[0].decode().split()
    if mode not in ('100644', '100755') or kind != 'blob':
        raise ValueError('Import controls must be regular Git blobs')
    if int(object_bytes(repo, 'cat-file', '-s', oid)) > limit:
        raise ValueError('Oversized import control')
    raw = object_bytes(repo, 'cat-file', 'blob', oid)
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant), raw


def _facts(value):
    if not isinstance(value, dict) or set(value) != {'repository', 'repository_id', 'ref', 'commit'}:
        raise ValueError('Invalid import snapshot identity')
    if not isinstance(value['repository'], str) or github_slug('https://github.com/' + value['repository'] + '.git') != value['repository']:
        raise ValueError('Invalid import repository')
    repository_id(value['repository_id']); reference(value['ref'])
    if not isinstance(value['commit'], str) or not SHA.fullmatch(value['commit']):
        raise ValueError('Import snapshots require full commit IDs')


def _audience(value):
    if not isinstance(value, dict) or set(value) != {'owner_id', 'users', 'teams', 'deploy_key_fingerprints', 'application_grants'}:
        raise ValueError('Invalid import audience evidence')
    repository_id(value['owner_id'])
    for name in ('users', 'teams', 'deploy_key_fingerprints'):
        rows = value[name]
        if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows) or rows != sorted(set(rows)):
            raise ValueError('Invalid import audience inventory')
        for row in rows:
            if name == 'deploy_key_fingerprints':
                if not TOKEN.fullmatch(row): raise ValueError('Invalid deploy-key fingerprint')
            else: repository_id(row)
    if value['application_grants'] != 'requires_owner_review_before_cutover':
        raise ValueError('Import does not approve application grants or cutover')


def _path(value):
    if not isinstance(value, str): raise ValueError('Import paths must be strings')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or not re.fullmatch(r'(?:Brain-Bridge|records|metadata)/[A-Za-z0-9_./-]+\.json', value):
        raise ValueError('Invalid import file path')
    return path


def validate_manifest(value, path):
    keys = {'schema_version', 'kind', 'source', 'destination', 'namespace', 'files', 'compatibility',
            'source_audience', 'destination_audience', 'audience_expansion', 'cutover', 'manifest_token'}
    if not isinstance(value, dict) or set(value) != keys or type(value['schema_version']) is not int or value['schema_version'] != 1 or value['kind'] != 'historical_import':
        raise ValueError('Invalid historical import manifest')
    token = value['manifest_token']
    if not isinstance(token, str) or not TOKEN.fullmatch(token) or path != PREFIX + token + '.json':
        raise ValueError('Import manifest filename/token mismatch')
    body = dict(value); body.pop('manifest_token')
    if digest(body) != token:
        raise ValueError('Import manifest content token mismatch')
    _facts(value['source']); _facts(value['destination'])
    if value['source']['repository_id'] == value['destination']['repository_id'] or value['destination']['ref'] != 'main':
        raise ValueError('Import requires distinct source/destination identities and destination main')
    if value['namespace'] not in ('Brain-Bridge', 'records') or value['cutover'] is not False or value['audience_expansion'] != []:
        raise ValueError('Import cannot expand access or switch production')
    _audience(value['source_audience']); _audience(value['destination_audience'])
    files = value['files']
    if not isinstance(files, list) or not 1 <= len(files) <= 1000:
        raise ValueError('Import requires one bounded nonempty exact file batch')
    seen = set(); ids = set(); total = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {'kind', 'source_path', 'target_path', 'sha256', 'bytes', 'mode', 'schema_version', 'entry_ids', 'entry_timestamps'}:
            raise ValueError('Invalid import file declaration')
        target = item['target_path']; _path(target); _path(item['source_path'])
        if item['kind'] == 'record':
            if not target.startswith('records/') or len(PurePosixPath(target).parts) != 4:
                raise ValueError('Import records require dated canonical paths')
            expected = value['namespace'] + '/' + target.removeprefix('records/')
            if type(item['schema_version']) is not int or item['schema_version'] not in (1, 2, 3):
                raise ValueError('Invalid imported record schema')
        elif item['kind'] == 'provenance':
            if not re.fullmatch(r'metadata/[0-9a-f]{64}\.json', target) or type(item['schema_version']) is not int or item['schema_version'] != 1:
                raise ValueError('Invalid imported provenance path/schema')
            expected = ('Brain-Bridge/' if value['namespace'] == 'Brain-Bridge' else '') + target
        else: raise ValueError('Unknown import file kind')
        if item['source_path'] != expected or target in seen:
            raise ValueError('Duplicate or remapped import file')
        seen.add(target)
        if item['mode'] not in ('100644', '100755') or not isinstance(item['sha256'], str) or not TOKEN.fullmatch(item['sha256']) or type(item['bytes']) is not int or not 1 <= item['bytes'] <= 1048576:
            raise ValueError('Invalid imported bytes/hash/mode')
        total += item['bytes']
        rows = item['entry_ids']; stamps = item['entry_timestamps']
        if not isinstance(rows, list) or not rows or any(not isinstance(uid, str) or not uid for uid in rows) or len(set(rows)) != len(rows) or not isinstance(stamps, list):
            raise ValueError('Invalid imported entry identities')
        if item['kind'] == 'record':
            if len(rows) != len(stamps) or ids.intersection(rows): raise ValueError('Duplicate imported entry identity')
            ids.update(rows)
            for stamp in stamps:
                if not isinstance(stamp, str) or datetime.fromisoformat(stamp).utcoffset() is None:
                    raise ValueError('Invalid imported entry timestamp')
        elif len(rows) != 1 or stamps:
            raise ValueError('Invalid provenance target declaration')
    if total > MAX_BYTES or files != sorted(files, key=lambda item: item['target_path']):
        raise ValueError('Import batch is oversized or unordered')
    pins = value['compatibility']
    if not isinstance(pins, list): raise ValueError('Invalid import compatibility evidence')
    pin_paths = set(); by_target = {item['target_path']: item for item in files}
    from .contract import FILE_PATTERN
    for pin in pins:
        if not isinstance(pin, dict) or set(pin) != {'path', 'sha256', 'kind'} or not isinstance(pin['path'], str) or not FILE_PATTERN.fullmatch(pin['path']) or pin['kind'] not in KINDS or pin['path'] in pin_paths:
            raise ValueError('Invalid exact import compatibility pin')
        item = by_target.get('records/' + pin['path'].removeprefix('Brain-Bridge/'))
        if item is None or pin['sha256'] != item['sha256']:
            raise ValueError('Import compatibility pin is not bound to its approved record')
        pin_paths.add(pin['path'])
    if pins != sorted(pins, key=lambda pin: pin['path']): raise ValueError('Unordered import compatibility evidence')
    return value


def plan_import(source_repo, destination_repo, source_id, destination_id,
                source_ref='main', destination_ref='main', namespace='Brain-Bridge', authority=None):
    """Authenticate immutable source bytes and audience; propose, never authorize."""
    api = authority or GitHubAuthority()
    plan = plan_migration(source_repo, destination_repo, source_id, destination_id,
                          source_ref, destination_ref, namespace, api)
    if plan['audience_expansion']:
        raise AccessDenied('Destination audience expands access; no import authorization proposed')
    if destination_ref != 'main': raise ValueError('Reviewed historical import targets destination main only')
    _, identity_raw = regular_json(destination_repo, plan['destination']['commit'], '.brain-bridge/identity.json', 65536)
    Identity.parse(identity_raw).verify_repository(destination_id)
    snapshot = immutable_snapshot(source_repo, Grant('import-planner', source_id, plan['source']['repository'], plan['source']['commit'], source_ref), namespace)
    records = {'records/' + name: obj for name, _, obj in snapshot['records']}
    overlays = {name: obj for name, _, obj in snapshot['overlays']}
    files = []
    for item in plan['files']:
        row = object_bytes(source_repo, 'ls-tree', plan['source']['commit'], '--', item['source_path'])
        mode, kind, _ = row.split(b'\t', 1)[0].decode().split()
        if kind != 'blob' or mode not in ('100644', '100755'): raise ValueError('Imported source must be a regular Git blob')
        obj = records[item['target_path']] if item['kind'] == 'record' else overlays[item['target_path']]
        entries = record_entries(obj) if item['kind'] == 'record' else []
        files.append({**item, 'mode': mode, 'schema_version': obj['schema_version'],
                      'entry_ids': [entry['id'] for entry in entries] if entries else [obj['entry_id']],
                      'entry_timestamps': [entry['timestamp'] for entry in entries]})
    source_pins = history_compatibility(source_repo, plan['source']['commit'])
    imported = {item['target_path'] for item in files}
    compatibility = sorted([{'path': path, **pin} for path, pin in source_pins.items()
                            if 'records/' + path.removeprefix('Brain-Bridge/') in imported], key=lambda pin: pin['path'])
    body = {key: plan[key] for key in ('source', 'destination', 'namespace', 'source_audience', 'destination_audience', 'audience_expansion', 'cutover')}
    body.update(schema_version=1, kind='historical_import', files=files, compatibility=compatibility)
    value = {**body, 'manifest_token': digest(body)}
    path = PREFIX + value['manifest_token'] + '.json'
    validate_manifest(value, path)
    # A plan captures a stable observed authorization/audience snapshot. It is
    # not permission to copy, and branch/audience drift requires a fresh review.
    for which, write in (('source', False), ('destination', True)):
        facts, info = repo_facts(source_repo if which == 'source' else destination_repo,
                                 plan[which]['repository_id'], plan[which]['ref'], api, write=write)
        if facts != plan[which] or audience(api, facts['repository'], info) != plan[which + '_audience']:
            raise AccessDenied('Import source/destination or audience changed while planning')
    return {'manifest_path': path, 'manifest': value, 'read_only': True, 'executed': False,
            'requires_reviewed_base': True, 'cutover': False}


def import_controls(repo, commit):
    for directory in ('.brain-bridge', '.brain-bridge/imports'):
        row = object_bytes(repo, 'ls-tree', commit, '--', directory)
        if row and row.split()[0] != b'040000': raise ValueError('Import control namespace must be a directory')
    listing = object_bytes(repo, 'ls-tree', '-rz', commit, '--', PREFIX)
    manifests = {}
    for row in listing.split(b'\0'):
        if not row: continue
        _, name = row.split(b'\t', 1); name = name.decode()
        if len(manifests) >= 100 or not re.fullmatch(re.escape(PREFIX) + r'[0-9a-f]{64}\.json', name):
            raise ValueError('Invalid or excessive import authorization files')
        value, _ = regular_json(repo, commit, name)
        manifests[name] = validate_manifest(value, name)
    return manifests


def destination_binding(repo, base, value, before, files_at):
    _, raw_identity = regular_json(repo, base, '.brain-bridge/identity.json', 65536)
    identity = Identity.parse(raw_identity)
    if identity.github_repository_id != value['destination']['repository_id'] or github_slug(git(repo, 'remote', 'get-url', 'origin')) != value['destination']['repository']:
        raise AccessDenied('Import destination does not match trusted BASE identity/origin')
    old_base = value['destination']['commit']
    git(repo, 'merge-base', '--is-ancestor', old_base, base)
    if files_at(repo, old_base) != before:
        raise ValueError('Destination ledger advanced after import planning; review a fresh manifest')


def proposal_changes(repo, base, head, before, controls_before, controls_after, files_at):
    new = set(controls_after) - set(controls_before)
    if not new: return
    changed = set(object_bytes(repo, 'diff', '--name-only', '--no-renames', '-z', base, head).decode().strip('\0').split('\0'))
    allowed = set(controls_before) | new | {'.brain-bridge/history-compatibility.json'}
    if changed - allowed:
        raise ValueError('Import authorization PR may change only authorization controls and exact history pins')
    pins = history_compatibility(repo, head)
    for path in new:
        value = controls_after[path]
        destination_binding(repo, base, value, before, files_at)
        for pin in value['compatibility']:
            if pins.get(pin['path']) != {'sha256': pin['sha256'], 'kind': pin['kind']}:
                raise ValueError('Import authorization requires its exact compatibility pins')


def authorized_batch(repo, base, head, before, after, files_at):
    """Return a BASE-approved exact batch, or None for ordinary strict writes."""
    additions = set(after) - set(before)
    manifests = list(import_controls(repo, base).values())
    if not additions: return None
    # Only a complete BASE-authorized payload can enter the historical path.
    # Partial/extra old-format payloads remain subject to strict-write rejection.
    potential = [value for value in manifests if {item['target_path'] for item in value['files']} == additions]
    matching = [value for value in potential if files_at(repo, value['destination']['commit']) == before]
    if potential and not matching:
        raise ValueError('Destination ledger advanced after import planning; review a fresh manifest')
    if not matching:
        if any(additions.intersection(item['target_path'] for item in value['files']) for value in manifests):
            raise ValueError('Historical import must match one complete approved payload')
        return None
    if len(matching) != 1: raise ValueError('Ambiguous historical import authorization')
    value = matching[0]
    destination_binding(repo, base, value, before, files_at)
    changed = set(object_bytes(repo, 'diff', '--name-only', '--no-renames', '-z', base, head).decode().strip('\0').split('\0'))
    if changed != additions:
        raise ValueError('Historical import PR may change only its complete approved payload')
    pins = history_compatibility(repo, base)
    for pin in value['compatibility']:
        if pins.get(pin['path']) != {'sha256': pin['sha256'], 'kind': pin['kind']}:
            raise ValueError('Historical import requires exact compatibility pins reviewed in BASE')
    for item in value['files']:
        mode, oid = after[item['target_path']]
        raw = object_bytes(repo, 'cat-file', 'blob', oid)
        if mode != item['mode'] or len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Historical import bytes/path/mode differ from BASE authorization')
        obj = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
        if not isinstance(obj, dict): raise ValueError('Imported JSON must be an object')
        if item['kind'] == 'record':
            logical = 'Brain-Bridge/' + item['target_path'].removeprefix('records/')
            pin = pins.get(logical)
            validate_history(obj, logical,
                             legacy_github_issue_shape=bool(pin and pin['kind'] == 'legacy_github_issue_shape'),
                             legacy_analysis_object=bool(pin and pin['kind'] == 'legacy_analysis_object'))
        entries = record_entries(obj) if item['kind'] == 'record' else []
        ids = [entry['id'] for entry in entries] if entries else [obj.get('entry_id')]
        if obj.get('schema_version') != item['schema_version'] or ids != item['entry_ids'] or [entry['timestamp'] for entry in entries] != item['entry_timestamps']:
            raise ValueError('Historical import entry identities/schema differ from BASE authorization')
    return value
