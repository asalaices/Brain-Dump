# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Portable JSON keyword scanner and optional derived SQLite index. No network operations."""
import hashlib
import os
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .contract import validate_record, validate_history, record_entries

SCHEMA_VERSION = '3'

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON numbers are not canonical")


def flatten(obj, path=""):
    if isinstance(obj, dict):
        for k,v in obj.items():
            p=path+"/"+str(k).replace("~","~0").replace("/","~1")
            yield p,"key",str(k)
            yield from flatten(v,p)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):
            yield from flatten(v,path+"/"+str(i))
    else:
        yield path,"value",json.dumps(obj,ensure_ascii=False) if isinstance(obj,(bool,type(None))) else str(obj)

def records(root, contract=None):
    base=Path(root).resolve(strict=True)
    if not base.is_dir(): raise ValueError("root must be a directory")
    seen_ids = set()
    for p in sorted(base.rglob("*.json")):
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(base): continue
        raw=p.read_bytes()
        if len(raw)>1048576: raise ValueError("oversized JSON record")
        rel = p.relative_to(base).as_posix()
        obj = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
        if contract in ("v3", "history"):
            validator=validate_record if contract=="v3" else validate_history
            validator(obj, rel if rel.startswith("Brain-Bridge/") else "Brain-Bridge/" + rel)
            for entry in record_entries(obj):
                uid=entry["id"]
                if uid in seen_ids:raise ValueError("Duplicate immutable entry ID")
                seen_ids.add(uid)
        elif contract is not None:
            raise ValueError("Unsupported JSON contract")
        yield rel,hashlib.sha256(raw).hexdigest(),obj

def json_search(root,term):
    if not term: raise ValueError("term required")
    return [dict(file=f,pointer=p,kind=k,value=v,sha256=h) for f,h,obj in records(root)
            for p,k,v in flatten(obj) if term.casefold() in v.casefold()]

def connect(database):
    p=Path(database).expanduser()
    p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if p.is_symlink(): raise ValueError("database symlink not allowed")
    conn=sqlite3.connect(str(p))
    if os.name == "posix": os.chmod(p,0o600)
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS files (file TEXT PRIMARY KEY, sha256 TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS nodes (file TEXT,pointer TEXT,kind TEXT,value TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS nodes_by_file ON nodes(file)")
    return conn

def rebuild(root,database,contract=None):
    items=list(records(root, contract=contract))
    return rebuild_items(items, database, str(Path(root).resolve(strict=True)))

def rebuild_items(items, database, binding, indexed_commit=None):
    # Materialize/flatten before opening SQLite: malformed batches cannot touch
    # an existing index or leave a new empty database behind.
    prepared={f:(h,list(flatten(obj))) for f,h,obj in items}
    conn=connect(database)
    try:
        conn.execute("BEGIN IMMEDIATE")
        old_binding=conn.execute("SELECT value FROM meta WHERE key='source_root'").fetchone()
        old_version=conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        previous=dict(conn.execute("SELECT file,sha256 FROM files"))
        reusable=old_binding==(binding,) and old_version==(SCHEMA_VERSION,)
        changed={f for f,(digest,_) in prepared.items() if not reusable or previous.get(f)!=digest}
        indexed_nodes={}
        for file,pointer,kind,value in conn.execute("SELECT file,pointer,kind,value FROM nodes ORDER BY rowid"):
            indexed_nodes.setdefault(file,[]).append((pointer,kind,value))
        changed.update(file for file,(_,nodes) in prepared.items() if indexed_nodes.get(file,[])!=nodes)
        removed=(set(previous)|set(indexed_nodes))-set(prepared)
        with conn:
            for f in removed|changed:
                conn.execute("DELETE FROM nodes WHERE file=?",(f,))
                conn.execute("DELETE FROM files WHERE file=?",(f,))
            for f in changed:
                digest,nodes=prepared[f]
                conn.execute("INSERT INTO files VALUES (?,?)",(f,digest))
                conn.executemany("INSERT INTO nodes VALUES (?,?,?,?)",((f,p,k,v) for p,k,v in nodes))
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",("schema_version",SCHEMA_VERSION))
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",("source_root",binding))
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",("indexed_at",datetime.now(timezone.utc).isoformat()))
            if indexed_commit is None:
                conn.execute("DELETE FROM meta WHERE key='indexed_commit'")
            else:
                conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",("indexed_commit",indexed_commit))
        return len(prepared)
    finally:conn.close()

def is_fresh(root,database):
    """Validate every source hash and the index schema before trusting a cache."""
    current={f:h for f,h,_ in records(root)}
    return cache_fresh(database, str(Path(root).resolve(strict=True)), current)

def cache_fresh(database, binding, current):
    p=Path(database).expanduser()
    if not p.is_file() or p.is_symlink(): return False
    try:
        conn=sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True)
        try:
            version=conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            indexed=dict(conn.execute("SELECT file,sha256 FROM files"))
            bound=conn.execute("SELECT value FROM meta WHERE key='source_root'").fetchone()
            return version==(SCHEMA_VERSION,) and bound==(binding,) and indexed==current
        finally: conn.close()
    except (OSError,sqlite3.Error): return False

def search(root,term,backend="auto",database=None):
    if backend not in ("json","sqlite","auto"): raise ValueError("unknown backend")
    if backend=="json": return json_search(root,term)
    if backend=="sqlite" and not database: raise ValueError("database required")
    if database and is_fresh(root,database):
        try: return sqlite_search(database,term)
        except (OSError,sqlite3.Error):
            if backend=="sqlite": raise
    if backend=="sqlite": raise RuntimeError("SQLite index missing or stale: run index first")
    return json_search(root,term)

def sqlite_search(database,term):
    if not term: raise ValueError("term required")
    p=Path(database).expanduser()
    if not p.is_file() or p.is_symlink(): raise FileNotFoundError("index missing")
    conn=sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True)
    try:
        results=[]
        for f,h,p,k,v in conn.execute("SELECT n.file,f.sha256,n.pointer,n.kind,n.value FROM nodes n JOIN files f ON f.file=n.file ORDER BY n.file,n.rowid"):
            if not all(isinstance(value,str) for value in (f,h,p,k,v)):
                raise sqlite3.DatabaseError("Index contains invalid row types")
            if term.casefold() in v.casefold():results.append(dict(file=f,pointer=p,kind=k,value=v,sha256=h))
        return results
    finally:conn.close()


def cache_metadata(database, binding):
    """Read diagnostic metadata only; it never grants access or proves freshness."""
    p=Path(database).expanduser()
    if not p.is_file() or p.is_symlink(): return {}
    try:
        conn=sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True)
        try:
            values=dict(conn.execute("SELECT key,value FROM meta"))
            if values.get("source_root")!=binding or values.get("schema_version")!=SCHEMA_VERSION:
                return {}
            return {key:values.get(key) for key in ("indexed_commit","indexed_at")}
        finally: conn.close()
    except (OSError,sqlite3.Error): return {}
