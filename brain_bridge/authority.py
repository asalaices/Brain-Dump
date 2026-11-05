"""GitHub-authenticated, commit-bound metadata for managed Synapses access.

Only the existing gh credential transport is used; tokens are never accepted,
printed or persisted by this module. Policies come from the named upstream
branch, never from caller-edited files or a publication candidate.
"""
import base64
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from .policy import Identity, Policy, AccessDenied


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=90)
    if result.returncode:
        raise AccessDenied("Required Git metadata is unavailable")
    return result.stdout.decode().strip()


def github_slug(remote):
    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", remote)
    if not match:
        raise AccessDenied("Expected an explicitly named GitHub origin")
    slug=match[1]
    if any(part in (".","..") for part in slug.split("/")):
        raise AccessDenied("Invalid GitHub repository name")
    return slug


@dataclass(frozen=True)
class Grant:
    identity_key: str
    source_id: str
    source_slug: str
    commit: str
    branch: str
    policy_revision: str = ""

    @property
    def cache_key(self):
        value = json.dumps([self.identity_key, self.source_id, self.policy_revision or self.commit], separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()


class GitHubAuthority:
    def api(self, endpoint):
        try:
            result = subprocess.run(["gh", "api", "--hostname", "github.com", endpoint], capture_output=True, timeout=60)
            if result.returncode:
                raise AccessDenied("Authenticated GitHub metadata could not be refreshed")
            return json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise AccessDenied("Authenticated GitHub metadata is unavailable") from exc

    def snapshot(self, identity_repo, source_repo, operation="read", branch="main"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", branch):
            raise AccessDenied("Invalid trusted policy branch")
        code_slug = github_slug(git(identity_repo, "remote", "get-url", "origin"))
        identity = Identity.parse(git(identity_repo, "show", "HEAD:.brain-bridge/identity.json"))
        code_info = self.api("repos/" + code_slug)
        identity.verify_repository(code_info.get("id"))
        source_slug = github_slug(git(source_repo, "remote", "get-url", "origin"))
        from .policy import document, repository_id
        registry = document(git(identity_repo, "show", "HEAD:.brain-bridge/sources.json"))
        if set(registry)!={"schema_version","sources"} or type(registry.get("schema_version")) is not int or registry["schema_version"]!=1 or not isinstance(registry["sources"],list):
            raise AccessDenied("Invalid committed source registry")
        matches=[];names=set();identities=set()
        for source in registry["sources"]:
            if not isinstance(source,dict) or set(source)!={"name","github_repository","github_repository_id","branch"}:
                raise AccessDenied("Malformed registered source")
            name=source["name"]
            if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*",name) or name in names:
                raise AccessDenied("Duplicate or invalid source name")
            slug=source["github_repository"]
            trusted_branch=source["branch"]
            if not isinstance(slug,str) or github_slug("https://github.com/"+slug+".git")!=slug or not isinstance(trusted_branch,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*",trusted_branch):
                raise AccessDenied("Invalid registered source repository or branch")
            sid=repository_id(source["github_repository_id"])
            if sid in identities:raise AccessDenied("Duplicate registered source identity")
            identities.add(sid);names.add(name)
            if source["github_repository"]==source_slug and source["branch"]==branch:matches.append(source)
        if len(matches)!=1:
            raise AccessDenied("Source/branch is not explicitly registered")
        expected_source_id=matches[0]["github_repository_id"]
        info = self.api("repos/" + source_slug)
        permissions = info.get("permissions", {})
        if permissions.get("pull") is not True or (operation == "write" and permissions.get("push") is not True):
            raise AccessDenied("GitHub repository permissions do not permit this operation")
        source_id = info.get("id")
        if type(source_id) is not int or source_id < 1:
            raise AccessDenied("Source repository identity is unavailable")
        if str(source_id)!=expected_source_id:
            raise AccessDenied("Source repository ID mismatch")
        head = self.api("repos/" + source_slug + "/commits/" + branch).get("sha")
        if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
            raise AccessDenied("Policy commit is unavailable")
        data = self.api("repos/" + source_slug + "/contents/.brain-bridge/trust.json?ref=" + head)
        if data.get("encoding") != "base64" or data.get("type") != "file":
            raise AccessDenied("Trusted policy is not a regular JSON file")
        try:
            policy_raw = base64.b64decode(data["content"].replace("\n", ""), validate=True)
            policy = Policy.parse(policy_raw)
        except (ValueError, KeyError, TypeError) as exc:
            raise AccessDenied("Trusted policy could not be decoded") from exc
        policy.require(identity, operation)
        return Grant(identity.key, str(source_id), source_slug, head, branch, hashlib.sha256(policy_raw).hexdigest())


def initialize_identity(repo, execute=False, authority=None):
    """Plan or create an identity; existing identities are never regenerated."""
    repo = Path(repo).resolve(strict=True)
    slug = github_slug(git(repo, "remote", "get-url", "origin"))
    api = authority or GitHubAuthority()
    info = api.api("repos/" + slug)
    if type(info.get("id")) is not int or info["id"] < 1:
        raise AccessDenied("Authenticated repository ID is unavailable")
    path = repo / ".brain-bridge" / "identity.json"
    if path.is_symlink() or path.parent.is_symlink():
        raise AccessDenied("Identity path must not be a symlink")
    if path.exists():
        identity = Identity.parse(path.read_bytes());identity.verify_repository(info["id"])
        return {"status": "existing", "identity_key": identity.key}
    if not execute:
        return {"status": "plan", "repository": slug, "github_repository_id": str(info["id"]), "path": str(path)}
    value = {"schema_version": 1, "instance_uuid": str(uuid4()), "github_repository_id": str(info["id"])}
    path.parent.mkdir(exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
    return {"status": "created", "identity_key": Identity.parse(json.dumps(value)).key, "path": str(path), "requires_reviewed_pr": True}
