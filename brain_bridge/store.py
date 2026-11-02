"""Portable JSON keyword scanner and optional derived SQLite index. No network operations."""
import hashlib
import os
import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = '2'

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

def records(root):
    base=Path(root).resolve(strict=True)
    if not base.is_dir(): raise ValueError("root must be a directory")
    for p in sorted(base.rglob("*.json")):
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(base): continue
        raw=p.read_bytes()
        if len(raw)>1048576: raise ValueError("oversized JSON record")
        yield p.relative_to(base).as_posix(),hashlib.sha256(raw).hexdigest(),json.loads(raw)

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
    return conn

def rebuild(root,database):
    items=list(records(root))
    conn=connect(database)
    try:
        with conn:
            conn.execute("DELETE FROM nodes")
            conn.execute("DELETE FROM files")
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",("schema_version",SCHEMA_VERSION))
            for f,h,obj in items:
                conn.execute("INSERT INTO files VALUES (?,?)",(f,h))
                conn.executemany("INSERT INTO nodes VALUES (?,?,?,?)",((f,p,k,v) for p,k,v in flatten(obj)))
        return len(items)
    finally: conn.close()

def is_fresh(root,database):
    """Validate every source hash and the index schema before trusting a cache."""
    current={f:h for f,h,_ in records(root)}
    p=Path(database).expanduser()
    if not p.is_file() or p.is_symlink(): return False
    try:
        conn=sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True)
        try:
            version=conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            indexed=dict(conn.execute("SELECT file,sha256 FROM files"))
            return version==(SCHEMA_VERSION,) and indexed==current
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
        return [dict(file=f,pointer=p,kind=k,value=v,sha256=h)
                for f,h,p,k,v in conn.execute("SELECT n.file,f.sha256,n.pointer,n.kind,n.value FROM nodes n JOIN files f ON f.file=n.file ORDER BY n.file,n.rowid")
                if term.casefold() in v.casefold()]
    finally:conn.close()
