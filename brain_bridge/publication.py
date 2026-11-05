# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Append-only private-source publication through a dedicated GitHub PR.

Plan is the default. Executing requires both explicit flags, independent read
and write grants, authenticated repository permissions and a stable upstream.
The caller's checkout, index and active branch are never switched or staged.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .authority import GitHubAuthority
from .contract import validate_record, validate_history, record_entries
from .managed import reader_root, immutable_records
from .policy import AccessDenied

SECRET = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[oprsu]_[A-Za-z0-9_]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b|\bAKIA[0-9A-Z]{16}\b')


def run_git(repo, *args, data=None, env=None, missing=False):
    result=subprocess.run(['git','-C',str(repo),*args],input=data,capture_output=True,timeout=90,env=env)
    if result.returncode:
        if missing:return None
        raise RuntimeError('Publication Git operation failed')
    return result.stdout


def candidate(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>1048576:
        raise ValueError('Record input must be a regular JSON file up to 1 MiB')
    raw=path.read_bytes()
    from .store import unique_object, reject_constant
    obj=json.loads(raw,object_pairs_hook=unique_object,parse_constant=reject_constant)
    validate_record(obj)
    entry=obj['entry'];local=datetime.fromisoformat(entry['timestamp']).astimezone(ZoneInfo(obj['timezone']))
    relative=local.strftime('%Y/%m/%Y-%m-%d-%H-%M-%S-')+entry['id']+'.json'
    validate_record(obj,'Brain-Bridge/'+relative)
    if SECRET.search(raw.decode()):raise ValueError('Potential credential material in record')
    return obj,raw,relative


def validate_anchor(repo, grant, entry):
    anchor=entry['context']['coverage_since'];base=anchor['commit']
    run_git(repo,'merge-base','--is-ancestor',base,grant.commit)
    path='records/'+anchor['ledger'].removeprefix('Brain-Bridge/')
    raw=run_git(repo,'show',base+':'+path)
    if len(raw)>1048576:raise ValueError('Oversized baseline record')
    from .store import unique_object, reject_constant
    obj=json.loads(raw,object_pairs_hook=unique_object,parse_constant=reject_constant)
    validate_history(obj,anchor['ledger'])
    if not any(e['id']==anchor['entry_id'] and e['timestamp']==anchor['timestamp'] for e in record_entries(obj)):
        raise ValueError('Coverage baseline does not match the published record')


class GitHubReviews:
    def command(self,*args):
        result=subprocess.run(['gh',*args],capture_output=True,text=True,timeout=90)
        if result.returncode:raise RuntimeError('GitHub review operation failed; publication branch is preserved')
        return result.stdout.strip()

    def propose(self,repo,branch,tip,path,digest,base="main"):
        rows=json.loads(self.command('pr','list','--repo',repo,'--head',branch,'--state','all','--json','url,state,headRefOid'))
        if rows:
            if len(rows)!=1 or rows[0]['headRefOid']!=tip or rows[0]['state']!='OPEN':
                raise RuntimeError('Existing record review needs reconciliation; no duplicate PR created')
            return rows[0]['url']
        body='Append exactly one immutable record.\n\nPath: '+path+'\nSHA-256: '+digest+'\n\nValidated contract, published coverage baseline, independent grants and authenticated source identity. No policy edits, replacements, direct-main push or automatic merge.'
        return self.command('pr','create','--repo',repo,'--base',base,'--head',branch,'--title','docs(memory): append '+branch.split('/')[-1],'--body',body)


def propose_record(identity_repo,source_repo,input_path,execute=False,yes=False,authority=None,reviews=None):
    if execute and not yes:raise ValueError('Publication execution requires --yes')
    obj,raw,relative=candidate(input_path)
    api=authority or GitHubAuthority()
    read=api.snapshot(identity_repo,source_repo,'read')
    write=api.snapshot(identity_repo,source_repo,'write')
    if read!=write:raise AccessDenied('Read/write policy changed during publication planning')
    repo=reader_root(source_repo,read)
    path='records/'+relative;digest=hashlib.sha256(raw).hexdigest();entry=obj['entry']
    items=immutable_records(repo,read)
    for name,existing_digest,existing in items:
        if name==relative:
            if existing_digest!=digest:raise ValueError('Immutable record path already exists with different bytes')
            if api.snapshot(identity_repo,source_repo,'write')!=write:raise AccessDenied('Policy changed')
            return {'status':'published','already_published':True,'path':path,'sha256':digest,'commit':read.commit}
        if any(e['id']==entry['id'] for e in record_entries(existing)):
            raise ValueError('Immutable entry ID already exists at another path')
    validate_anchor(repo,read,entry)
    branch='brain-bridge/'+entry['id']
    receipt={'status':'plan','path':path,'sha256':digest,'base_commit':read.commit,'branch':branch,'source_id':read.source_id}
    if not execute:return receipt
    if api.snapshot(identity_repo,source_repo,'write')!=write:raise AccessDenied('Trusted policy changed before publication')
    remote=run_git(repo,'ls-remote','--heads','origin',branch).decode().strip()
    if remote:
        tip=remote.split()[0]
        run_git(repo,'fetch','--no-tags','origin',branch)
        if run_git(repo,'show',tip+':'+path)!=raw:raise ValueError('Existing publication branch has different record bytes')
        if run_git(repo,'diff-tree','--no-commit-id','--name-status','--no-renames','-r',tip).decode().strip()!='A\t'+path:
            raise ValueError('Existing publication branch contains unrelated changes')
        run_git(repo,'merge-base','--is-ancestor',tip+'^',read.commit)
    else:
        with tempfile.TemporaryDirectory(prefix='brain-record-index-') as temporary:
            environment=dict(os.environ,GIT_INDEX_FILE=str(Path(temporary)/'index'))
            run_git(repo,'read-tree',read.commit,env=environment)
            blob=run_git(repo,'hash-object','-w','--stdin',data=raw).decode().strip()
            run_git(repo,'update-index','--add','--cacheinfo','100644',blob,path,env=environment)
            tree=run_git(repo,'write-tree',env=environment).decode().strip()
            tip=run_git(repo,'commit-tree',tree,'-p',read.commit,data=('docs(memory): append '+entry['id']+'\n').encode()).decode().strip()
        if api.snapshot(identity_repo,source_repo,'write')!=write:raise AccessDenied('Trusted policy changed before push')
        run_git(repo,'push','origin',tip+':refs/heads/'+branch)
    review=reviews or GitHubReviews()
    url=review.propose(read.source_slug,branch,tip,path,digest,read.branch)
    return {**receipt,'status':'pending_review','publication_commit':tip,'pull_request':url,'merged':False}
