# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Reviewed, byte-preserving private migration rehearsals; never a cutover.

The operator explicitly supplies source/destination fingerprints. Authenticated
repository permissions and observable audience changes are checked before data
copy. Application grants still require owner review before cutover. Source Git objects are read only; no reader/writer routing is changed.
"""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote
from .authority import GitHubAuthority, Grant, github_slug, git
from .managed import immutable_snapshot, object_bytes
from .policy import AccessDenied, repository_id
from .contract import record_entries


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def reference(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*',value) or '..' in value or '//' in value or value.endswith('/'):
        raise ValueError('Migration requires an explicit safe branch reference')
    return value


def repo_facts(repo,expected_id,ref,api,write=False):
    repo=Path(repo).resolve(strict=True);expected_id=repository_id(expected_id);ref=reference(ref)
    if Path(git(repo,'rev-parse','--show-toplevel')).resolve()!=repo:raise ValueError('Migration path must be a checkout root')
    slug=github_slug(git(repo,'remote','get-url','origin'));info=api.api('repos/'+slug)
    if type(info.get('id')) is not int or str(info['id'])!=expected_id:raise AccessDenied('Migration repository identity mismatch')
    permissions=info.get('permissions',{})
    if permissions.get('pull') is not True or (write and permissions.get('push') is not True):raise AccessDenied('Migration repository permission unavailable')
    if write and info.get('private') is not True:raise AccessDenied('Migration destination must be private')
    head=api.api('repos/'+slug+'/commits/'+quote(ref,safe='')).get('sha')
    if not isinstance(head,str) or not re.fullmatch(r'[0-9a-f]{40}',head):raise AccessDenied('Published migration snapshot unavailable')
    if object_bytes(repo,'cat-file','-t',head).strip()!=b'commit':raise ValueError('Fetch the published snapshot before planning')
    return {'repository':slug,'repository_id':expected_id,'ref':ref,'commit':head},info


def audience(api,slug,info):
    owner=info.get('owner',{})
    if type(owner.get('id')) is not int or owner.get('type') not in ('User','Organization'):raise AccessDenied('Repository audience owner cannot be verified')
    users={str(owner['id'])};teams=set()
    def collect(endpoint):
        result=set()
        for page in range(1,21):
            rows=api.api(endpoint+('&' if '?' in endpoint else '?')+'per_page=100&page='+str(page))
            if not isinstance(rows,list):raise AccessDenied('Repository audience cannot be enumerated')
            for row in rows:
                if not isinstance(row,dict) or type(row.get('id')) is not int or row['id']<1:raise AccessDenied('Malformed repository audience')
                result.add(str(row['id']))
            if len(rows)<100:return result
        raise AccessDenied('Audience exceeds bounded inventory; explicit additional review required')
    users|=collect('repos/'+slug+'/collaborators?affiliation=all')
    if owner['type']=='Organization':teams=collect('repos/'+slug+'/teams')
    keys=set()
    for page in range(1,21):
        rows=api.api('repos/'+slug+'/keys?per_page=100&page='+str(page))
        if not isinstance(rows,list):raise AccessDenied('Deploy-key inventory unavailable')
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('key'),str):raise AccessDenied('Malformed deploy-key inventory')
            parts=row['key'].split()
            if len(parts)<2:raise AccessDenied('Malformed public deploy key')
            keys.add(hashlib.sha256((parts[0]+' '+parts[1]).encode()).hexdigest())
        if len(rows)<100:break
    else:raise AccessDenied('Deploy-key inventory exceeds review bound')
    return {'owner_id':str(owner['id']),'users':sorted(users),'teams':sorted(teams),'deploy_key_fingerprints':sorted(keys),'application_grants':'requires_owner_review_before_cutover'}


def plan_migration(source_repo,destination_repo,source_id,destination_id,source_ref='main',destination_ref='main',namespace='Brain-Bridge',authority=None,allow_partial=False):
    if namespace not in ('Brain-Bridge','records'):raise ValueError('Unsupported migration namespace')
    api=authority or GitHubAuthority()
    source,source_info=repo_facts(source_repo,source_id,source_ref,api)
    destination,destination_info=repo_facts(destination_repo,destination_id,destination_ref,api,write=True)
    if source['repository_id']==destination['repository_id']:raise ValueError('Migration source and destination must differ')
    if git(destination_repo,'rev-parse','HEAD')!=destination['commit']:raise ValueError('Destination checkout must match the reviewed published base')
    if not allow_partial and git(destination_repo,'status','--porcelain','--untracked-files=all'):raise ValueError('Destination checkout is dirty')
    source_audience=audience(api,source['repository'],source_info);destination_audience=audience(api,destination['repository'],destination_info)
    expansion=[]
    if source_info.get('private') is not False:
        if source_audience['owner_id']!=destination_audience['owner_id']:expansion.append('different_repository_owner')
        expansion += ['user:'+uid for uid in set(destination_audience['users'])-set(source_audience['users'])]
        expansion += ['team:'+uid for uid in set(destination_audience['teams'])-set(source_audience['teams'])]
        expansion += ['deploy_key:'+key for key in set(destination_audience['deploy_key_fingerprints'])-set(source_audience['deploy_key_fingerprints'])]
    source_snapshot=immutable_snapshot(source_repo,Grant('migration-operator',source_id,source['repository'],source['commit'],source_ref),records_prefix=namespace)
    target_snapshot=immutable_snapshot(destination_repo,Grant('migration-operator',destination_id,destination['repository'],destination['commit'],destination_ref))
    existing={('records/'+name):sha for name,sha,_ in target_snapshot['records']};existing.update({name:sha for name,sha,_ in target_snapshot['overlays']})
    target_ids={entry['id']:('records/'+name) for name,_,obj in target_snapshot['records'] for entry in record_entries(obj)}
    files=[];unchanged=0;total=0
    for name,sha,obj in source_snapshot['records']:
        target='records/'+name
        for entry in record_entries(obj):
            if entry['id'] in target_ids and target_ids[entry['id']]!=target:raise ValueError('Destination entry ID collision')
        source_path=namespace+'/'+name
        files.append({'kind':'record','source_path':source_path,'target_path':target,'sha256':sha})
    for name,sha,obj in source_snapshot['overlays']:
        source_path=('Brain-Bridge/'+name) if namespace=='Brain-Bridge' else name
        files.append({'kind':'provenance','source_path':source_path,'target_path':name,'sha256':sha})
    additions=[]
    for item in files:
        if item['target_path'] in existing:
            if existing[item['target_path']]!=item['sha256']:raise ValueError('Immutable destination bytes differ')
            unchanged+=1;continue
        size=int(object_bytes(source_repo,'cat-file','-s',source['commit']+':'+item['source_path']))
        total+=size;additions.append({**item,'bytes':size})
    if total>134217728:raise ValueError('Rehearsal exceeds 128 MiB; review a staged migration strategy')
    body={'schema_version':1,'operation':'private_migration_rehearsal','source':source,'destination':destination,'namespace':namespace,'source_audience':source_audience,'destination_audience':destination_audience,'audience_expansion':sorted(expansion),'files':sorted(additions,key=lambda item:item['target_path']),'unchanged_files':unchanged,'record_count':len(source_snapshot['records']),'entry_count':sum(len(record_entries(obj)) for _,_,obj in source_snapshot['records']),'overlay_count':len(source_snapshot['overlays']),'bytes_to_copy':total,'cutover':False}
    return {**body,'plan_token':digest(body)}


def apply_migration(source_repo,destination_repo,plan,execute=False,yes=False,authority=None):
    if execute and not yes:raise ValueError('Migration application requires --yes')
    if isinstance(plan,dict) and 'plan' in plan:
        if set(plan)-{'plan','info'}:raise ValueError('Unexpected plan envelope fields')
        plan=plan['plan']
    if not isinstance(plan,dict):raise ValueError('Expected a reviewed rehearsal plan')
    plan=dict(plan);plan.pop('info',None)
    if plan.get('operation')!='private_migration_rehearsal' or not isinstance(plan.get('source'),dict) or not isinstance(plan.get('destination'),dict):raise ValueError('Expected a reviewed rehearsal plan')
    for name in ('source','destination'):
        if not all(isinstance(plan[name].get(key),str) for key in ('repository_id','ref')):raise ValueError('Malformed migration snapshot identity')

    api=authority or GitHubAuthority()
    expected=plan_migration(source_repo,destination_repo,plan['source']['repository_id'],plan['destination']['repository_id'],plan['source']['ref'],plan['destination']['ref'],plan['namespace'],api,allow_partial=True)
    if expected!=plan:raise ValueError('Migration plan/snapshots changed; review a fresh plan')
    if plan['audience_expansion']:raise AccessDenied('Destination audience expands access; fix/review repository permissions before copying')
    if not execute:return {'status':'plan','plan_token':plan['plan_token'],'file_count':len(plan['files']),'executed':False,'cutover':False}
    root=Path(destination_repo).resolve(strict=True);allowed={item['target_path'] for item in plan['files']}
    status=object_bytes(root,'status','--porcelain=v1','-z','--untracked-files=all').split(b'\0')
    for row in status:
        if row and (row[:2] not in (b'??',b'A ',b' A') or row[3:].decode() not in allowed):raise ValueError('Unrelated destination changes must be preserved and reconciled')
    for item in plan['files']:
        path=root/item['target_path']
        if not path.resolve().is_relative_to(root) or any(parent.is_symlink() for parent in [path,*path.parents] if parent!=root and root in parent.parents):raise ValueError('Migration target contains a symlink')
        if path.exists() and (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']):raise ValueError('Destination file already exists with different bytes')
    copied=0;verified=0
    for item in plan['files']:
        path=root/item['target_path']
        if path.exists():verified+=1;continue
        raw=object_bytes(source_repo,'show',plan['source']['commit']+':'+item['source_path'])
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Source blob hash mismatch')
        path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.migration-',delete=False) as temporary:
            temporary.write(raw);temporary.flush();os.fsync(temporary.fileno());temporary_path=Path(temporary.name)
        try:os.link(temporary_path,path)
        finally:temporary_path.unlink(missing_ok=True)
        copied+=1
    # Read the complete candidate from the working files only for receipt hashes;
    # no Git staging, branch change, source edit or runtime activation is performed.
    for item in plan['files']:
        if hashlib.sha256((root/item['target_path']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Copied bytes changed during verification')
    return {'status':'rehearsal_files_prepared','executed':True,'copied':copied,'already_identical':verified,'plan_token':plan['plan_token'],'source_commit':plan['source']['commit'],'destination_base':plan['destination']['commit'],'cutover':False,'requires_private_review':True}
