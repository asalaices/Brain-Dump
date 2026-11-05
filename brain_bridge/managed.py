# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
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
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
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


def immutable_snapshot(repo, grant,records_prefix="records"):
    if records_prefix not in ("records","Brain-Bridge"):raise ValueError("Unsupported canonical namespace")
    metadata_prefix="metadata" if records_prefix=="records" else "Brain-Bridge/metadata"
    if object_bytes(repo,"cat-file","-t",grant.commit+":"+records_prefix).strip()!=b"tree":
        raise AccessDenied("Managed records must be a committed directory")
    listing = object_bytes(repo, "ls-tree", "-rz", grant.commit, "--", records_prefix+"/")
    items=[];seen=set()
    for row in listing.split(b"\0"):
        if not row: continue
        metadata,name=row.split(b"\t",1);mode,kind,oid=metadata.decode().split()
        name=name.decode()
        if not name.endswith(".json") or name.startswith(metadata_prefix+"/"):continue
        if mode not in ("100644","100755") or kind != "blob":
            raise AccessDenied("Canonical records must be regular Git blobs")
        if int(object_bytes(repo,"cat-file","-s",oid))>1048576:
            raise ValueError("Oversized canonical record")
        raw=object_bytes(repo,"cat-file","blob",oid)
        obj=json.loads(raw,object_pairs_hook=unique_object,parse_constant=reject_constant)
        relative=name.removeprefix(records_prefix+"/")
        validate_history(obj,"Brain-Bridge/"+relative)
        for entry in record_entries(obj):
            uid=entry["id"]
            if uid in seen:raise ValueError("Duplicate immutable entry ID")
            seen.add(uid)
        items.append((relative,hashlib.sha256(raw).hexdigest(),obj))
    from datetime import datetime
    from .contract import validate_provenance
    by_id={entry['id']:(name,digest,entry) for name,digest,envelope in items for entry in record_entries(envelope)}
    overlay_items=[];provenance={}
    listing=object_bytes(repo,"ls-tree","-rz",grant.commit,"--",metadata_prefix+"/")
    for row in listing.split(b"\0"):
        if not row:continue
        metadata,name=row.split(b"\t",1);mode,kind,oid=metadata.decode().split();name=name.decode()
        if not name.endswith('.json'):continue
        if mode not in ('100644','100755') or kind!='blob':raise ValueError('Metadata must be a regular Git blob')
        if int(object_bytes(repo,'cat-file','-s',oid))>1048576:raise ValueError('Oversized provenance metadata')
        raw=object_bytes(repo,'cat-file','blob',oid)
        data=json.loads(raw,object_pairs_hook=unique_object,parse_constant=reject_constant)
        if not isinstance(data,dict) or type(data.get('schema_version')) is not int or data['schema_version']!=1 or data.get('kind')!='provenance_backfill':raise ValueError('Unsupported provenance overlay')
        uid=data.get('entry_id')
        if not isinstance(uid,str) or uid not in by_id or name!=metadata_prefix+'/'+hashlib.sha256(uid.encode()).hexdigest()+'.json':raise ValueError('Overlay target/filename mismatch')
        path,digest,entry=by_id[uid]
        if 'provenance' in entry:raise ValueError('Overlay cannot replace native provenance')
        if data.get('ledger')!='Brain-Bridge/'+path or data.get('ledger_sha256')!=digest:raise ValueError('Overlay ledger/hash binding mismatch')
        if not isinstance(data.get('attribution_source'),str) or not data['attribution_source'].strip():raise ValueError('Overlay attribution source missing')
        try:
            moment=datetime.fromisoformat(data['recorded_at'])
            if moment.utcoffset() is None:raise ValueError('offset required')
        except (KeyError,TypeError,ValueError) as exc:raise ValueError('Invalid overlay timestamp') from exc
        validate_provenance(data.get('provenance'))
        provenance[uid]=data['provenance'];overlay_items.append(('metadata/'+name.removeprefix(metadata_prefix+'/'),hashlib.sha256(raw).hexdigest(),data))
    return {'records':items,'overlays':overlay_items,'provenance':provenance}


def immutable_records(repo,grant):
    return immutable_snapshot(repo,grant)['records']


def snapshot_documents(snapshot):
    return [('records/'+name,digest,obj) for name,digest,obj in snapshot['records']]+snapshot['overlays']


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
    items=snapshot_documents(immutable_snapshot(repo,grant))
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
    snapshot=immutable_snapshot(repo,grant)
    items=snapshot_documents(snapshot)
    if api.snapshot(identity_repo, source_repo) != grant:
        raise AccessDenied("Policy/source changed before indexing")
    count = rebuild_items(items, database, binding)
    if api.snapshot(identity_repo, source_repo) != grant:
        raise AccessDenied("Policy/source changed during indexing; cache must not be served")
    return {"indexed": count,"indexed_records":len(snapshot["records"]),"indexed_overlays":len(snapshot["overlays"]), "source_id": grant.source_id, "commit": grant.commit, "cache_key": grant.cache_key}


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


def managed_graph(identity_repo,source_repo,format='json',authority=None):
    from .graphs import evidence_graph,render_dot,render_mermaid
    if format not in ('json','dot','mermaid'):raise ValueError('Unknown graph format')
    api=authority or GitHubAuthority();grant=api.snapshot(identity_repo,source_repo)
    repo=reader_root(source_repo,grant);snapshot=immutable_snapshot(repo,grant)
    graph=evidence_graph(snapshot['records'],grant.source_id,overlays=snapshot['provenance'])
    if api.snapshot(identity_repo,source_repo)!=grant:raise AccessDenied('Policy/source changed during graph generation')
    result={'graph':graph,'source_id':grant.source_id,'commit':grant.commit,'format':format}
    if format!='json':result['content']=(render_dot if format=='dot' else render_mermaid)(graph)
    return result
