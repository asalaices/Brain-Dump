"""Strict cooperative identity and separate read/write grants.

GitHub enforces repository access. This module never treats a UUID as proof
of ownership and never grants access from a proposed working-tree policy.
"""
import json
import re
from dataclasses import dataclass
from uuid import UUID
from .store import unique_object, reject_constant

class AccessDenied(PermissionError):
    pass


def document(raw):
    try:
        obj = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise AccessDenied("Malformed identity or policy document") from exc
    if not isinstance(obj, dict):
        raise AccessDenied("Expected an object")
    return obj


def repository_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise AccessDenied("Repository ID must be a positive canonical decimal string")
    return value


@dataclass(frozen=True)
class Identity:
    instance_uuid: str
    github_repository_id: str

    @property
    def key(self):
        return self.instance_uuid + "-" + self.github_repository_id

    @classmethod
    def parse(cls, raw):
        obj = document(raw)
        if set(obj) != {"schema_version", "instance_uuid", "github_repository_id"} or type(obj.get("schema_version")) is not int or obj["schema_version"] != 1:
            raise AccessDenied("Unsupported identity contract")
        uid = obj["instance_uuid"]
        try:
            parsed = UUID(uid)
        except (ValueError, TypeError, AttributeError) as exc:
            raise AccessDenied("Invalid instance UUID") from exc
        if parsed.version != 4 or str(parsed) != uid:
            raise AccessDenied("Instance UUID must be canonical lowercase UUIDv4")
        return cls(uid, repository_id(obj["github_repository_id"]))

    def verify_repository(self, authenticated_repository_id):
        if self.github_repository_id != repository_id(str(authenticated_repository_id)):
            raise AccessDenied("Repository identity mismatch: copied fork identity is not authorized")


def identity_key(value):
    if not isinstance(value, str) or len(value) < 38:
        raise AccessDenied("Invalid policy identity key")
    uid, separator, repo = value[:36], value[36:37], value[37:]
    identity = Identity.parse(json.dumps({"schema_version": 1, "instance_uuid": uid, "github_repository_id": repo}))
    if separator != "-" or identity.key != value:
        raise AccessDenied("Invalid policy identity key")
    return value


@dataclass(frozen=True)
class Policy:
    readers: frozenset
    writers: frozenset

    @classmethod
    def parse(cls, raw):
        obj = document(raw)
        if set(obj) != {"schema_version", "default_policy", "reader_allow", "writer_allow"} or type(obj.get("schema_version")) is not int or obj["schema_version"] != 1 or obj.get("default_policy") != "deny":
            raise AccessDenied("Unsupported default-deny policy")
        groups = []
        for name in ("reader_allow", "writer_allow"):
            values = obj[name]
            if not isinstance(values, list):
                raise AccessDenied("Policy grants must be lists")
            keys = [identity_key(value) for value in values]
            if len(keys) != len(set(keys)):
                raise AccessDenied("Duplicate policy grant")
            groups.append(frozenset(keys))
        return cls(*groups)

    def require(self, identity, operation):
        if operation not in ("read", "write"):
            raise AccessDenied("Unknown operation")
        allowed = self.readers if operation == "read" else self.writers
        if identity.key not in allowed:
            raise AccessDenied("Identity lacks the explicit " + operation + " grant")
