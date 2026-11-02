"""Validation of canonical master-01 Brain Bridge v3 JSON envelopes.

This module does not rewrite or discard fields; its job is pre-index validation.
"""
from datetime import datetime, date
from pathlib import PurePosixPath
from uuid import UUID
import re

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
    entry = record["entry"]
    if not isinstance(entry, dict):
        raise ContractError("entry must be an object")
    for key, expected in ENTRY_FIELDS.items():
        if key not in entry or not isinstance(entry[key], expected):
            raise ContractError(f"Missing or invalid entry.{key}")
    try:
        uid = UUID(entry["id"])
        moment = datetime.fromisoformat(entry["timestamp"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError("Invalid entry id or timestamp") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ContractError("Timestamp must carry a timezone offset")
    if moment.date() != day:
        raise ContractError("date and timestamp disagree")
    for key, required in {
        "validation": ("issues", "implementation", "publication"),
        "repository_state": ("repo", "branch", "baseline", "cutover"),
        "provenance": ("users", "repositories", "issues", "workflow_runs"),
    }.items():
        if not all(name in entry[key] for name in required):
            raise ContractError(f"Incomplete entry.{key}")
    if path is not None:
        m = FILE_PATTERN.fullmatch(PurePosixPath(path).as_posix())
        if not m or (m.group(1), m.group(2), m.group(3)) != (
            day.strftime("%Y"), day.strftime("%m"), day.isoformat()
        ) or m.group(7).lower() != str(uid) or (
            m.group(4), m.group(5), m.group(6)
        ) != (moment.strftime("%H"), moment.strftime("%M"), moment.strftime("%S")):
            raise ContractError("Path must match canonical dated record ID and timestamp")
    return record
