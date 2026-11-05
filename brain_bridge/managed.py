"""Managed reads use authenticated immutable Git objects, never loose JSON."""
import hashlib
import json
import subprocess
from pathlib import Path
from .authority import GitHubAuthority, git
from .policy import AccessDenied
from .contract import validate_history, record_entries
from .store import flatten, rebuild_items, cache_fresh, sqlite_search, unique_object, reject_constant


def reader_root(repo, grant):
    repo = Path(repo).resolve(strict=True)
    if git(repo, "rev-parse", "--show-toplevel") != str(repo):
        raise AccessDenied("Source must be an existing checkout root")
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise AccessDenied("Managed source checkout is dirty")
    if git(repo, "rev-parse", "HEAD") != grant.commit:
        raise AccessDenied("Source is not at the refreshed trusted policy commit; synchronize first")
    return repo


def object_bytes(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=90)
    if result.returncode:
        raise AccessDenied("Verified source object is unavailable")
    return result.stdout


def immutable_records(repo, grant):
    if object_bytes(repo,"cat-file","-t",grant.commit+":records").strip()!=b"tree":
        raise AccessDenied("Managed records must be a committed directory")
    listing = object_bytes(repo, "ls-tree", "-rz", grant.commit, "--", "records/")
    items=[];seen=set()
    for row in listing.split(b"\0"):
        if not row: continue
        metadata,name=row.split(b"\t",1);mode,kind,oid=metadata.decode().split()
        name=name.decode()
        if not name.endswith(".json"):continue
        if mode not in ("100644","100755") or kind != "blob":
            raise AccessDenied("Canonical records must be regular Git blobs")
        if int(object_bytes(repo,"cat-file","-s",oid))>1048576:
            raise ValueError("Oversized canonical record")
        raw=object_bytes(repo,"cat-file","blob",oid)
        obj=json.loads(raw,object_pairs_hook=unique_object,parse_constant=reject_constant)
        relative=name.removeprefix("records/")
        validate_history(obj,"Brain-Bridge/"+relative)
        for entry in record_entries(obj):
            uid=entry["id"]
            if uid in seen:raise ValueError("Duplicate immutable entry ID")
            seen.add(uid)
        items.append((relative,hashlib.sha256(raw).hexdigest(),obj))
    return items


def cache_path(source_repo, cache_dir, grant):
    database = Path(cache_dir).expanduser().resolve() / (grant.cache_key + ".sqlite")
    if database.is_relative_to(Path(source_repo).resolve()):
        raise AccessDenied("Managed cache must be outside the source checkout")
    binding="github://"+grant.source_id+"/"+grant.identity_key+"@"+(grant.policy_revision or grant.commit)
    return database,binding


def managed_search(identity_repo, source_repo, term, cache_dir, backend="auto", authority=None):
    if not term or backend not in ("json","sqlite","auto"):
        raise ValueError("Nonempty term and supported backend required")
    api = authority or GitHubAuthority()
    grant = api.snapshot(identity_repo, source_repo)
    repo = reader_root(source_repo, grant)
    database,binding = cache_path(source_repo,cache_dir,grant)
    items=immutable_records(repo,grant)
    if backend!="json" and cache_fresh(database,binding,{f:h for f,h,_ in items}):
        results=sqlite_search(database,term)
    elif backend=="sqlite":
        raise ValueError("Managed cache missing or stale; run managed-index")
    else:
        results=[dict(file=f,pointer=p,kind=k,value=v,sha256=h) for f,h,obj in items
                 for p,k,v in flatten(obj) if term.casefold() in v.casefold()]
    if api.snapshot(identity_repo, source_repo) != grant:
        raise AccessDenied("Policy/source changed during the read; results withheld")
    return {"results": results, "source_id": grant.source_id, "commit": grant.commit, "cache_key": grant.cache_key}


def managed_index(identity_repo, source_repo, cache_dir, authority=None):
    api = authority or GitHubAuthority()
    grant = api.snapshot(identity_repo, source_repo)
    repo = reader_root(source_repo, grant)
    database,binding = cache_path(source_repo,cache_dir,grant)
    items=immutable_records(repo,grant)
    if api.snapshot(identity_repo, source_repo) != grant:
        raise AccessDenied("Policy/source changed before indexing")
    count = rebuild_items(items, database, binding)
    if api.snapshot(identity_repo, source_repo) != grant:
        raise AccessDenied("Policy/source changed during indexing; cache must not be served")
    return {"indexed": count, "source_id": grant.source_id, "commit": grant.commit, "cache_key": grant.cache_key}


def managed_sync(identity_repo, source_repo, cache_dir, authority=None):
    from .sync import sync
    api=authority or GitHubAuthority()
    grant=api.snapshot(identity_repo,source_repo)
    database,_=cache_path(source_repo,cache_dir,grant)
    remote=git(source_repo,"remote","get-url","origin")
    def refresh(target):
        if target!=grant.commit or api.snapshot(identity_repo,source_repo)!=grant:
            raise AccessDenied("Trusted source/policy changed before fast-forward")
    result=sync(source_repo,remote,grant.branch,"records",database,contract="history",
                expected_commit=grant.commit,authorize_target=refresh,build_index=False)
    indexed=managed_index(identity_repo,source_repo,cache_dir,api)
    return {**result,**indexed,"fresh":True}
