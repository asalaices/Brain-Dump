# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Guarded, explicitly invoked Git-to-SQLite synchronization."""
import subprocess
from pathlib import Path
from .store import rebuild, is_fresh, unique_object, reject_constant

class SyncError(RuntimeError):
    pass

def _git_bytes(repo, *args):
    try:
        result=subprocess.run(["git","-C",str(repo),*args],check=True,capture_output=True,timeout=90)
    except (subprocess.CalledProcessError,FileNotFoundError,subprocess.TimeoutExpired) as exc:
        raise SyncError("Required Git operation failed") from exc
    return result.stdout


def _git(repo,*args):
    return _git_bytes(repo,*args).decode().strip()

def preflight(repo, expected_remote, branch, records_dir, database):
    """Validate a selected existing clean reader without fetching or changing HEAD."""
    repo = Path(repo).expanduser().resolve(strict=True)
    if not repo.is_dir() or not (repo / ".git").is_dir() or (repo / ".git").is_symlink():
        raise SyncError("Only an existing standalone Git checkout is supported")
    if not expected_remote or not branch or branch.startswith("-") or "/" in branch:
        raise SyncError("Explicit remote identity and simple branch name required")
    if Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise SyncError("Repository path must be the checkout root")
    if _git(repo, "remote", "get-url", "origin") != expected_remote:
        raise SyncError("Remote identity mismatch")
    if _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD") != branch:
        raise SyncError("Checked-out branch mismatch")
    if _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise SyncError("Checkout is dirty; refusing to pull")
    record_root = (repo / records_dir).resolve(strict=True)
    if not record_root.is_dir() or not record_root.is_relative_to(repo):
        raise SyncError("Records directory must be inside the checkout")
    db = Path(database).expanduser().resolve()
    if db.is_relative_to(repo):
        raise SyncError("SQLite index must be outside the Git checkout")
    return repo,record_root,db


def sync(repo, expected_remote, branch, records_dir, database, contract=None, expected_commit=None, authorize_target=None, build_index=True):
    """Sync an existing clean checkout; never clone, reset, or force-pull."""
    repo,record_root,db=preflight(repo,expected_remote,branch,records_dir,database)
    _git(repo, "fetch", "--no-tags", "origin", branch)
    target = _git(repo, "rev-parse", "FETCH_HEAD")
    if expected_commit is not None and target != expected_commit:
        raise SyncError("Fetched commit differs from authenticated policy commit")
    _git(repo, "merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD")
    managed_history = contract == 'history' and not build_index and records_dir in ('records','Brain-Bridge')
    if managed_history:
        from .authority import Grant
        from .managed import immutable_snapshot
        immutable_snapshot(repo, Grant('sync-validation', '0', 'snapshot', target, branch),records_prefix=records_dir)
    if contract in ("v3", "history") and not managed_history:
        import json
        from .contract import validate_record, validate_history, record_entries
        seen_ids=set()
        validator=validate_record if contract=="v3" else validate_history
        prefix = record_root.relative_to(repo).as_posix() + "/"
        if _git(repo,"cat-file","-t",target+":"+prefix.rstrip("/"))!="tree":
            raise SyncError("Fetched records path must be a directory")
        listing=_git_bytes(repo,"ls-tree","-rz",target,"--",prefix)
        for row in listing.split(b"\0"):
            if not row:continue
            metadata,name=row.split(b"\t",1);mode,kind,oid=metadata.decode().split();name=name.decode()
            if not name.endswith(".json"):continue
            if mode not in ("100644","100755") or kind!="blob":
                raise SyncError("Record symlinks are not supported")
            if int(_git(repo,"cat-file","-s",oid))>1048576:
                raise SyncError("Oversized canonical record")
            obj=json.loads(_git_bytes(repo,"cat-file","blob",oid),object_pairs_hook=unique_object,parse_constant=reject_constant)
            validator(obj,"Brain-Bridge/"+name[len(prefix):])
            for entry in record_entries(obj):
                if entry['id'] in seen_ids:raise SyncError("Duplicate immutable entry ID")
                seen_ids.add(entry['id'])
    if authorize_target is not None:
        authorize_target(target)
    _git(repo, "merge", "--ff-only", target)
    head = _git(repo, "rev-parse", "HEAD")
    if not build_index:
        return {"commit": head, "indexed": None, "fresh": False}
    count = rebuild(record_root, db, contract=contract)
    if not is_fresh(record_root, db):
        raise SyncError("SQLite index verification failed")
    return {"commit": head, "indexed": count, "fresh": True}
