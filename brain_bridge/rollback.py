# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Read-only immutable rollback evidence; never authorizes routing changes."""
from .authority import GitHubAuthority, Grant, git
from .contract import record_entries
from .managed import immutable_snapshot
from .migration import audience, digest, repo_facts
from .policy import AccessDenied


def _facts(repo, identifier, ref, api):
    facts, info = repo_facts(repo, identifier, ref, api)
    facts = dict(facts, private=info.get('private'), permissions=info.get('permissions', {}),
                 checkout_commit=git(repo, 'rev-parse', 'HEAD'),
                 checkout_branch=git(repo, 'rev-parse', '--abbrev-ref', 'HEAD'))
    return facts, audience(api, facts['repository'], info)


def _inventory(snapshot):
    entries = {}
    for path, sha, envelope in snapshot['records']:
        for entry in record_entries(envelope):
            uid = entry['id']
            if uid in entries:
                raise ValueError('Duplicate immutable entry ID')
            entries[uid] = {'path': path, 'sha256': sha, 'entry_sha256': digest(entry)}
    return entries, {path: sha for path, sha, _ in snapshot['overlays']}


def _compare(source, destination):
    common = source.keys() & destination.keys()
    return {'identical': sorted(key for key in common if source[key] == destination[key]),
            'mismatched': sorted(key for key in common if source[key] != destination[key]),
            'source_only': sorted(source.keys() - destination.keys()),
            'destination_only': sorted(destination.keys() - source.keys())}


def plan_rollback_audit(source_repo, destination_repo, source_id, destination_id,
                        source_ref, destination_ref, authority=None):
    """Compare explicit published refs; never write, grant, or switch readers.

    Dirty worktrees are irrelevant: only immutable published objects are read.
    The resulting operator evidence must be kept private.
    """
    api = authority or GitHubAuthority()
    source, source_audience = _facts(source_repo, source_id, source_ref, api)
    destination, destination_audience = _facts(destination_repo, destination_id, destination_ref, api)
    if source['repository_id'] == destination['repository_id']:
        raise ValueError('Rollback source and destination must differ')
    if destination['private'] is not True:
        raise AccessDenied('Rollback destination must be private')
    snapshots = []
    for repo, facts, namespace in ((source_repo, source, 'Brain-Bridge'),
                                    (destination_repo, destination, 'records')):
        grant = Grant('rollback-audit-operator', facts['repository_id'],
                      facts['repository'], facts['commit'], facts['ref'])
        snapshots.append(immutable_snapshot(repo, grant, records_prefix=namespace))
    source_entries, source_overlays = _inventory(snapshots[0])
    destination_entries, destination_overlays = _inventory(snapshots[1])
    # Withhold the entire report if either authenticated view changes.
    after_source = _facts(source_repo, source_id, source_ref, api)
    after_destination = _facts(destination_repo, destination_id, destination_ref, api)
    if after_source != (source, source_audience) or after_destination != (destination, destination_audience):
        raise AccessDenied('Repository refs, permissions or audiences changed during audit')
    entries = _compare({uid: row['entry_sha256'] for uid, row in source_entries.items()},
                       {uid: row['entry_sha256'] for uid, row in destination_entries.items()})
    ledgers = _compare({path: sha for path, sha, _ in snapshots[0]['records']},
                       {path: sha for path, sha, _ in snapshots[1]['records']})
    overlays = _compare(source_overlays, destination_overlays)
    blockers = []
    if entries['destination_only']:
        blockers.append('destination_only_ids_require_reconciliation')
    if entries['mismatched']:
        blockers.append('divergent_same_id_content_requires_reconciliation')
    if ledgers['mismatched']:
        blockers.append('different_immutable_ledger_bytes_require_review')
    if any(overlays[key] for key in ('mismatched', 'source_only', 'destination_only')):
        blockers.append('provenance_overlay_differences_require_reconciliation')
    body = {'schema_version': 1, 'operation': 'rollback_audit',
            'source': source, 'destination': destination,
            'source_namespace': 'Brain-Bridge', 'destination_namespace': 'records',
            'source_audience': source_audience, 'destination_audience': destination_audience,
            'entries': entries, 'ledgers': ledgers, 'overlays': overlays,
            'source_entries': source_entries, 'destination_entries': destination_entries,
            'blockers': sorted(blockers), 'cutover': False, 'executed': False,
            'rollback_ready': False,
            'required_review': ['writer_quiescence_and_inflight_writes',
                                'reader_writer_routing_and_grants',
                                'application_grants_owner_review',
                                'operator_acceptance_of_reconciliation_and_resume_plan']}
    return dict(body, audit_fingerprint=digest(body))
