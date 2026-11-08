# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Named-source authoring and effective-history adapters; never switch routing.

Reads use immutable authorized Git objects. Creation plans by default and writes
only a complete, explicitly identified draft outside both repository checkouts.
Publication remains a separate PR-only operation.
"""
import copy
import hashlib
import json
import os
import tempfile
import stat
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .authority import GitHubAuthority
from .contract import record_entries, validate_record, active_profile
from .managed import reader_root, immutable_snapshot, snapshot_documents, cache_path
from .policy import AccessDenied
from .publication import SECRET, validate_anchor
from .store import unique_object, reject_constant, cache_fresh, cache_metadata


def named_snapshot(identity_repo, source_repo, source_name, api):
    if not isinstance(source_name, str) or not source_name:
        raise ValueError('An explicit registered source name is required')
    grant = api.snapshot(identity_repo, source_repo)
    if grant.source_name != source_name:
        raise AccessDenied('Requested source name does not match authenticated registration')
    repo = reader_root(source_repo, grant)
    return grant, repo, immutable_snapshot(repo, grant)


def source_receipt(grant):
    return {'name': grant.source_name, 'repository': grant.source_slug,
            'repository_id': grant.source_id, 'commit': grant.commit,
            'branch': grant.branch, 'policy_revision': grant.policy_revision}


def effective_entries(snapshot):
    entries = []
    for _, _, envelope in snapshot['records']:
        for original in record_entries(envelope):
            entry = copy.deepcopy(original)
            if 'provenance' not in entry and entry['id'] in snapshot['provenance']:
                entry['provenance'] = copy.deepcopy(snapshot['provenance'][entry['id']])
            entries.append(entry)
    return sorted(entries, key=lambda e: (datetime.fromisoformat(e['timestamp']).astimezone(timezone.utc), e['id']))


def unchanged(api, identity_repo, source_repo, grant, operation='read'):
    if api.snapshot(identity_repo, source_repo, operation) != grant:
        raise AccessDenied('Policy/source changed during adapter operation; results withheld')


def managed_export(identity_repo, source_repo, source_name, authority=None):
    api = authority or GitHubAuthority()
    grant, _, snapshot = named_snapshot(identity_repo, source_repo, source_name, api)
    entries = effective_entries(snapshot)
    unchanged(api, identity_repo, source_repo, grant)
    return {'schema_version': 1, 'entries': entries, 'count': len(entries),
            'records': len(snapshot['records']), 'overlays': len(snapshot['overlays']),
            'source': source_receipt(grant), 'read_only': True}


def managed_latest(identity_repo, source_repo, source_name, authority=None):
    exported = managed_export(identity_repo, source_repo, source_name, authority)
    return {key: value for key, value in exported.items() if key != 'entries'} | {
        'entry': exported['entries'][-1] if exported['entries'] else None}


def managed_status(identity_repo, source_repo, source_name, cache_dir, authority=None):
    api = authority or GitHubAuthority()
    grant, repo, snapshot = named_snapshot(identity_repo, source_repo, source_name, api)
    database, binding = cache_path(repo, cache_dir, grant)
    items = snapshot_documents(snapshot)
    fresh = cache_fresh(database, binding, {f: h for f, h, _ in items})
    metadata = cache_metadata(database, binding)
    unchanged(api, identity_repo, source_repo, grant)
    return {'schema_version': 1, 'source': source_receipt(grant), 'read_only': True,
            'source_verified': True, 'synchronized': True, 'cache_fresh': fresh,
            'indexed_commit': metadata.get('indexed_commit'), 'indexed_at': metadata.get('indexed_at'),
            'count': sum(len(record_entries(obj)) for _, _, obj in snapshot['records']),
            'records': len(snapshot['records']), 'overlays': len(snapshot['overlays'])}


def external_output(output, identity_repo, source_repo):
    # Resolve existing ancestors before containment checks. Reject symlinks rather
    # than following them; only the explicitly supplied external file is writable.
    path = Path(os.path.abspath(Path(output).expanduser()))
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Draft output must not contain symlinks')
    parent = path.parent.resolve(strict=True)
    for root in (identity_repo, source_repo):
        if path.is_relative_to(Path(root).resolve(strict=True)):
            raise ValueError('Draft output must be outside identity and source checkouts')
    if not parent.is_dir() or (path.exists() and not path.is_file()):
        raise ValueError('Draft output requires an existing directory and regular file')
    return path


def exact_existing(path, raw):
    # Open without following a last-component symlink and inspect that same
    # descriptor. A concurrent creator must never receive a false retry receipt.
    if path.is_symlink():
        raise ValueError('Draft output must not be a symlink')
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1048576:
            raise ValueError('Draft output must be a bounded regular file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            existing = stream.read(1048577)
        if existing != raw:
            raise ValueError('Refusing to overwrite different draft bytes')
        return True
    finally:
        os.close(descriptor)


def managed_create(identity_repo, source_repo, source_name, entry_path, output,
                   execute=False, yes=False, authority=None):
    if execute and not yes:
        raise ValueError('Draft creation execution requires --yes')
    api = authority or GitHubAuthority()
    grant, repo, snapshot = named_snapshot(identity_repo, source_repo, source_name, api)
    unchanged(api, identity_repo, source_repo, grant, 'write')
    destination = external_output(output, identity_repo, source_repo)
    source = Path(entry_path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 1048576:
        raise ValueError('Authored entry must be a regular JSON file up to 1 MiB')
    entry = json.loads(source.read_bytes(), object_pairs_hook=unique_object, parse_constant=reject_constant)
    # Require authored identity/time: generating them here would change retries.
    if not isinstance(entry, dict) or not isinstance(entry.get('timestamp'), str):
        raise ValueError('A complete authored entry with stable ID and timestamp is required')
    moment = datetime.fromisoformat(entry['timestamp'])
    if moment.utcoffset() is None:
        raise ValueError('Authored timestamp requires an offset')
    profile = active_profile()
    local = moment.astimezone(ZoneInfo(profile.default_timezone))
    envelope = {'schema_version': 3, 'date': local.date().isoformat(),
                'timezone': profile.default_timezone, 'entry': entry}
    validate_record(envelope)
    relative = local.strftime('%Y/%m/%Y-%m-%d-%H-%M-%S-') + entry['id'] + '.json'
    validate_record(envelope, 'Brain-Bridge/' + relative)
    raw = (json.dumps(envelope, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()
    if len(raw) > 1048576 or SECRET.search(raw.decode()):
        raise ValueError('Oversized draft or potential credential material')
    for _, _, existing in snapshot['records']:
        if any(e['id'] == entry['id'] for e in record_entries(existing)):
            raise ValueError('Immutable entry ID already exists; use original record for publication retry')
    validate_anchor(repo, grant, entry)
    exact_existing(destination, raw)
    unchanged(api, identity_repo, source_repo, grant)
    unchanged(api, identity_repo, source_repo, grant, 'write')
    result = {'schema_version': 1, 'status': 'plan', 'entry_id': entry['id'],
              'sha256': hashlib.sha256(raw).hexdigest(), 'path': 'records/' + relative,
              'output': str(destination), 'source': source_receipt(grant),
              'published': False, 'canonical_verified': False}
    if not execute:
        return result
    # Same-directory temporary file + exclusive hard link prevents partial writes
    # and overwrites even when another process races this exact destination.
    external_output(destination, identity_repo, source_repo)
    if exact_existing(destination, raw):
        return {**result, 'status': 'existing'}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.brain-draft-', delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if not exact_existing(destination, raw):
                raise ValueError('Concurrent draft output disappeared; retry unchanged input')
            return {**result, 'status': 'existing'}
        return {**result, 'status': 'created'}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
