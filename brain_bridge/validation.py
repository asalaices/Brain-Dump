# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Local CI validation of append-only source objects, without access enrollment."""
import json
from pathlib import Path
from .authority import Grant, git
from .contract import validate_record
from .managed import immutable_snapshot, object_bytes
from .publication import SECRET, validate_anchor
from .store import unique_object, reject_constant
from .historical_import import authorized_batch, import_controls, proposal_changes


def _files(repo, commit):
    rows = object_bytes(repo, 'ls-tree', '-rz', commit, '--', 'records/', 'metadata/')
    files = {}
    for row in rows.split(b'\0'):
        if not row:
            continue
        metadata, name = row.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('Ledger namespaces require regular Git blobs')
        files[name.decode()] = (mode, oid)
    return files


def validate_source(repo, base_ref, ref='HEAD'):
    """Compare immutable commits; never read loose records or change Git state.

    This explicit local utility does not authorize managed reads or writes.
    Bulk historical migrations require a separately reviewed acceptance path.
    """
    repo = Path(repo).resolve(strict=True)
    if Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
        raise ValueError('Source validation requires the checkout root')
    base = git(repo, 'rev-parse', '--verify', base_ref + '^{commit}')
    head = git(repo, 'rev-parse', '--verify', ref + '^{commit}')
    git(repo, 'merge-base', '--is-ancestor', base, head)
    before, after = _files(repo, base), _files(repo, head)
    for name, value in before.items():
        if after.get(name) != value:
            raise ValueError('Committed ledger files may not change, move or disappear')
    additions = sorted(after.keys() - before.keys())
    controls_before, controls_after = import_controls(repo, base), import_controls(repo, head)
    for path in controls_before:
        if object_bytes(repo, 'ls-tree', base, '--', path) != object_bytes(repo, 'ls-tree', head, '--', path):
            raise ValueError('Reviewed import authorizations may not change or disappear')
    if set(controls_after) - set(controls_before) and additions:
        raise ValueError('Historical import authorization must be reviewed before its payload PR')
    proposal_changes(repo, base, head, before, controls_before, controls_after, _files)
    approved = authorized_batch(repo, base, head, before, after, _files)
    new_records = 0
    grant = Grant('local-ci-validation', 'local', 'local/source', base, 'main')
    for name in additions:
        if not name.endswith('.json'):
            raise ValueError('New ledger files must be JSON records or provenance overlays')
        oid = after[name][1]
        if int(object_bytes(repo, 'cat-file', '-s', oid)) > 1048576:
            raise ValueError('Oversized ledger addition')
        raw = object_bytes(repo, 'cat-file', 'blob', oid)
        if SECRET.search(raw.decode()):
            raise ValueError('Potential credential material in ledger addition')
        obj = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
        if name.startswith('records/'):
            if approved is None:
                validate_record(obj, 'Brain-Bridge/' + name.removeprefix('records/'))
                validate_anchor(repo, grant, obj['entry'])
            new_records += 1
    # Whole-history validation catches duplicate IDs and malformed/hash-unbound
    # metadata. Only a complete BASE-approved import may bypass strict new writes.
    for commit in (base, head):
        snapshot = immutable_snapshot(repo, Grant('local-ci-validation', 'local', 'local/source', commit, 'main'))
    return {'valid': True, 'base_commit': base, 'commit': head,
            'new_records': new_records, 'new_overlays': len(additions) - new_records,
            'record_count': len(snapshot['records']), 'history_unchanged': True,
            'executed': False, 'historical_import': approved is not None,
            'import_manifest_token': approved['manifest_token'] if approved else None,
            'source_authentication': 'operator-planner-before-review' if approved else None}
