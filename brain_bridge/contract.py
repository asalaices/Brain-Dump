# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Validation of canonical master-01 Brain Bridge v3 JSON envelopes.

This module does not rewrite or discard fields; its job is pre-index validation.
"""
from datetime import datetime, date
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import UUID
import re
import copy

ENTRY_FIELDS = {
    "id": str, "timestamp": str, "agent": str, "entry_type": str,
    "title": str, "context": dict, "conversation_summary": list,
    "observations": list, "realizations": list, "analysis": list,
    "proposals": list, "decisions": list, "questions_requiring_approval": list,
    "actions_taken": list, "validation": dict, "repository_state": dict,
    "references": list, "next_steps": list, "provenance": dict,
}
FILE_PATTERN = re.compile(
    r"^Brain-Bridge/(\d{4})/(\d{2})/(\d{4}-\d{2}-\d{2})-"
    r"(\d{2})-(\d{2})-(\d{2})-([0-9a-fA-F-]{36})\.json$"
)

class ContractError(ValueError):
    pass

def validate_record(record, path=None):
    if not isinstance(record, dict) or set(record) != {"schema_version", "date", "timezone", "entry"}:
        raise ContractError("Expected v3 envelope: schema_version, date, timezone, entry")
    if type(record["schema_version"]) is not int or record["schema_version"] != 3:
        raise ContractError("Only canonical schema_version 3 is supported")
    try:
        day = date.fromisoformat(record["date"])
    except (ValueError, TypeError) as exc:
        raise ContractError("Invalid date") from exc
    if not isinstance(record["timezone"], str) or not record["timezone"].strip():
        raise ContractError("Invalid timezone")
    if record["timezone"] != "America/Chicago":
        raise ContractError("The master-01 v3 profile requires America/Chicago")
    entry = record["entry"]
    if not isinstance(entry, dict):
        raise ContractError("entry must be an object")
    for key, expected in ENTRY_FIELDS.items():
        if key not in entry or not isinstance(entry[key], expected):
            raise ContractError(f"Missing or invalid entry.{key}")
    if entry["agent"] not in ("copilot","chatgpt"):
        raise ContractError("The master-01 v3 profile requires a supported publishing agent")
    validate_provenance(entry["provenance"])
    try:
        uid = UUID(entry["id"])
        moment = datetime.fromisoformat(entry["timestamp"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError("Invalid entry id or timestamp") from exc
    if uid.version != 4 or str(uid) != entry["id"]:
        raise ContractError("New entry IDs must be canonical UUIDv4")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ContractError("Timestamp must carry a timezone offset")
    try:
        local = moment.astimezone(ZoneInfo(record["timezone"]))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ContractError("Unknown record timezone") from exc
    if local.date() != day:
        raise ContractError("date and timestamp disagree")
    # validation and repository_state are extensible evidence objects. The
    # master-01 protocol does not mandate release-specific keys inside them.
    for name in ("users", "repositories", "issues", "workflow_runs"):
        if not isinstance(entry["provenance"].get(name), list):
            raise ContractError("Incomplete entry.provenance")
    anchor = entry["context"].get("coverage_since")
    if not isinstance(anchor, dict) or not all(
        isinstance(anchor.get(key), str) and anchor[key]
        for key in ("entry_id", "timestamp", "commit", "ledger")
    ):
        raise ContractError("context.coverage_since requires the published baseline")
    if not re.fullmatch(r"[0-9a-f]{40}", anchor["commit"]):
        raise ContractError("coverage_since.commit must be a full commit SHA")
    try:
        baseline_time = datetime.fromisoformat(anchor["timestamp"])
        if baseline_time.utcoffset() is None:
            raise ValueError("missing offset")
    except (ValueError, TypeError) as exc:
        raise ContractError("Invalid coverage_since timestamp") from exc
    ledger = PurePosixPath(anchor["ledger"])
    if ledger.is_absolute() or ".." in ledger.parts or not ledger.parts or ledger.parts[0] != "Brain-Bridge":
        raise ContractError("Coverage ledger must be a repository-relative Brain-Bridge path")
    if path is not None:
        m = FILE_PATTERN.fullmatch(PurePosixPath(path).as_posix())
        if not m or (m.group(1), m.group(2), m.group(3)) != (
            day.strftime("%Y"), day.strftime("%m"), day.isoformat()
        ) or m.group(7).lower() != str(uid) or (
            m.group(4), m.group(5), m.group(6)
        ) != (local.strftime("%H"), local.strftime("%M"), local.strftime("%S")):
            raise ContractError("Path must match canonical dated record ID and timestamp")
    return record


def validate_history(record, path=None, *, legacy_github_issue_shape=False):
    """Read historical v1/v2 without rewriting; new publication remains v3-only."""
    if not isinstance(record, dict) or type(record.get('schema_version')) is not int:
        raise ContractError('Invalid historical envelope')
    version=record['schema_version']
    if version==3:
        candidate = record
        if legacy_github_issue_shape:
            candidate = copy.deepcopy(record)
            provenance = candidate.get('entry', {}).get('provenance', {})
            if isinstance(provenance, dict) and isinstance(provenance.get('issues'), list):
                for issue in provenance['issues']:
                    if isinstance(issue, dict) and issue.get('provider', 'github') == 'github':
                        if type(issue.get('number')) is int and issue['number'] > 0:
                            issue['number'] = str(issue['number'])
                        if 'relationship' not in issue:
                            issue['relationship'] = 'unrecorded'
        validate_record(candidate,path)
        return record
    if version not in (1,2):
        raise ContractError('Unsupported historical schema')
    try:
        day=date.fromisoformat(record['date']);zone=ZoneInfo(record['timezone'])
    except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError) as exc:
        raise ContractError('Invalid historical date/timezone') from exc
    entries=record.get('entries') if version==1 else [record.get('entry')]
    if not isinstance(entries,list) or not entries:
        raise ContractError('Historical entries must be nonempty')
    ids=set()
    for entry in entries:
        if not isinstance(entry,dict):raise ContractError('Invalid historical entry')
        # Frozen legacy entries used both prose strings and structured lists.
        # Require the historical fields, but do not retrofit v3 value shapes.
        for key in ENTRY_FIELDS:
            if key!='provenance' and key not in entry:
                raise ContractError('Missing historical entry.'+key)
        if not isinstance(entry.get('id'),str) or not isinstance(entry.get('timestamp'),str):
            raise ContractError('Historical identity and timestamp must be strings')
        if not entry['id'] or entry['id'] in ids:raise ContractError('Invalid/duplicate historical ID')
        ids.add(entry['id'])
        try:
            stamp=datetime.fromisoformat(entry['timestamp'])
            if stamp.utcoffset() is None:raise ValueError('offset required')
        except (TypeError,ValueError) as exc:raise ContractError('Invalid historical timestamp') from exc
        if 'provenance' in entry:
            if not isinstance(entry['provenance'],dict) or not all(isinstance(entry['provenance'].get(k),list) for k in ('users','repositories','issues','workflow_runs')):
                raise ContractError('Invalid historical provenance')
    if path is not None:
        relative=PurePosixPath(path)
        if relative.is_absolute() or '..' in relative.parts or len(relative.parts)<4 or relative.parts[:3]!=('Brain-Bridge',day.strftime('%Y'),day.strftime('%m')) or not relative.name.endswith('.json'):
            raise ContractError('Historical path must match its date namespace')
    return record


def record_entries(record):
    return record['entries'] if record.get('schema_version')==1 else [record['entry']]


def validate_provenance(provenance):
    """Validate provider-qualified evidence while retaining native identifiers."""
    import json
    from urllib.parse import urlsplit
    collections={'users','repositories','issues','workflow_runs'}
    if not isinstance(provenance,dict) or set(provenance)!=collections:
        raise ContractError('Provenance must contain exactly its four collections')
    def text(row,key):
        value=row.get(key)
        if not isinstance(value,str) or not value.strip():raise ContractError('Invalid evidence field: '+key)
        return value
    def url(value):
        if not isinstance(value,str) or any(c.isspace() for c in value):raise ContractError('Invalid evidence URL')
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ContractError('Evidence URLs cannot carry credentials or query parameters')
        return parsed
    for collection,rows in provenance.items():
        if not isinstance(rows,list):raise ContractError('Evidence collections must be arrays')
        seen=set()
        for row in rows:
            if not isinstance(row,dict):raise ContractError('Evidence rows must be objects')
            provider=row.get('provider','github_actions' if collection=='workflow_runs' else 'github')
            if not isinstance(provider,str) or not provider.strip():raise ContractError('Invalid evidence provider')
            text(row,'host')
            if collection=='users':
                text(row,'role')
                if not any(isinstance(row.get(k),str) and row[k].strip() for k in ('login','user_id','account_id')):raise ContractError('Evidence user identity missing')
            elif collection=='repositories':
                text(row,'full_name');text(row,'repository_id')
            elif collection=='issues':
                for key in ('repository','number','relationship'):text(row,key)
            elif provider=='github_actions':
                for key in ('repository','run_id','run_attempt','workflow','head_sha'):text(row,key)
            elif provider=='jenkins':
                for key in ('job_url','build_url'):text(row,key)
                if 'result' not in row or row['result'] not in (None,'SUCCESS','FAILURE','UNSTABLE','ABORTED','NOT_BUILT','UNKNOWN'):raise ContractError('Invalid Jenkins result')
                for key in ('job_url','build_url'):
                    if url(row[key]).netloc!=row['host']:raise ContractError('Jenkins evidence host mismatch')
                if not re.search(r'/[0-9]+/?$',url(row['build_url']).path):raise ContractError('Jenkins build must be numbered')
            elif provider=='bitbucket_pipelines':
                text(row,'repository');text(row,'run_id')
            else:
                text(row,'run_id');text(row,'url')
            for key in ('repository_id','number','run_id','run_attempt','user_id','account_id'):
                if key in row:
                    value=text(row,key)
                    if provider in ('github','github_actions') and key!='account_id' and not re.fullmatch(r'[1-9][0-9]*',value):raise ContractError('GitHub evidence IDs must be positive decimal strings')
            for key in ('full_name','repository'):
                if key in row and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',text(row,key)):raise ContractError('Invalid evidence repository name')
            if 'head_sha' in row and not re.fullmatch(r'[0-9a-f]{40,64}',text(row,'head_sha')):raise ContractError('Evidence requires a complete commit ID')
            if 'result' in row and row['result'] is not None:text(row,'result')
            for key in ('url','job_url','build_url'):
                if key in row:url(row[key])
            if 'artifacts' in row:
                if not isinstance(row['artifacts'],list):raise ContractError('Artifacts must be an array')
                for artifact in row['artifacts']:
                    if not isinstance(artifact,dict):raise ContractError('Invalid artifact')
                    text(artifact,'name')
                    if 'url' in artifact:url(artifact['url'])
            fingerprint=json.dumps(row,sort_keys=True)
            if fingerprint in seen:raise ContractError('Duplicate evidence relationship')
            seen.add(fingerprint)
    return provenance
