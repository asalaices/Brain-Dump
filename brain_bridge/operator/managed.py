# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Managed CLI adapters and explicit operator promotion; no private-project imports."""
from pathlib import Path
import json
import re
import subprocess

PROFILE_PATH='.brain-bridge/managed-runtime.json'
MINIMUM=(0,8,0)
SUPPORTED_FAMILY=(0,8)


def _version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):raise ValueError('Managed runtime requires an exact supported version')
    return tuple(int(p) for p in value.split('.'))


def profile(root,control_json):
    value,commit=control_json(root,'origin/main',PROFILE_PATH)
    keys={'schema_version','cli','identity_repo','source_repo','source','cache_dir','minimum_version'}
    if not isinstance(value,dict) or set(value)!=keys or type(value['schema_version']) is not int or value['schema_version']!=1:raise ValueError('Reviewed committed managed runtime profile is missing or invalid')
    for key in ('cli','identity_repo','source_repo','cache_dir'):
        if not isinstance(value[key],str) or not Path(value[key]).is_absolute() or any(c in value[key] for c in '\r\n\0'):raise ValueError('Managed runtime profile paths must be explicit absolute paths')
    if not isinstance(value['source'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',value['source']) or _version(value['minimum_version'])<MINIMUM or _version(value['minimum_version'])[:2]!=SUPPORTED_FAMILY:raise ValueError('Managed profile requires a named source and reviewed minimum runtime')
    version=runtime_check(value)
    return {**value,'profile_commit':commit,'runtime_version':version}


def runtime_check(c):
    result=subprocess.run([c['cli'],'--version'],capture_output=True,text=True,timeout=30)
    match=re.fullmatch(r'brain-bridge (\d+\.\d+\.\d+)',result.stdout.strip())
    if result.returncode or not match or _version(match[1])<_version(c['minimum_version']) or _version(match[1])[:2]!=SUPPORTED_FAMILY:raise ValueError('Installed managed Brain runtime is unsupported; install the reviewed release before cutover')
    return match[1]


def invoke(c,action,*options):
    runtime_check(c)
    command=[c['cli'],action,'--identity-repo',c['identity_repo'],'--repo',c['source_repo'],*options,'--json']
    result=subprocess.run(command,capture_output=True,text=True,timeout=300)
    try:value=json.loads(result.stdout)
    except ValueError as exc:raise ValueError('Managed framework returned no valid receipt') from exc
    if result.returncode or not isinstance(value,dict) or 'error' in value:raise ValueError('Managed framework denied or failed the operation; no fallback is permitted')
    return value


def named(c,action,*options):
    return invoke(c,action,'--source',c['source'],*options)


def read(c,action):
    if action=='status' or action=='validate':
        value=named(c,'status','--cache-dir',c['cache_dir'])
        return {**value,'valid':True} if action=='validate' else value
    return named(c,action)


def synchronize(c):
    result=invoke(c,'managed-sync','--cache-dir',c['cache_dir'])
    status=read(c,'status')
    if status['source']['commit']!=result['commit']:raise ValueError('Source changed during managed synchronization; retry')
    return {**result,'source':status['source']}


def create(c,path,output,execute=False,yes=False):
    if not output:raise ValueError('Managed create requires --output outside source/identity repositories')
    options=['--entry',str(path),'--output',str(output)]
    if execute:options+=['--execute']
    if yes:options+=['--yes']
    return named(c,'create',*options)


def check_record(c,path):
    read(c,'status') # Match the explicit source alias before publisher planning.
    return invoke(c,'publish','--record',str(path))


def publish(root,path,c,initial,refresh_route,gh,execute=False,yes=False):
    """Explicit operator may merge; the ordinary publisher remains PR-only."""
    if execute and not yes:raise ValueError('Managed publication execution requires --yes')
    pending={'ok':False,'status':'pending','original_draft':str(path),'published':False,'canonical_verified':False}
    if initial['mode']=='paused':return {**pending,'reason':'publisher_paused','retained':True}
    if initial['mode']!='managed':raise ValueError('Managed publisher route is not active')
    planned=check_record(c,path)
    if not execute:return {**planned,'executed':False,'route_generation':initial['generation']}
    receipt=None
    try:
        refresh_route(initial)
        synchronize(c)
        receipt=invoke(c,'publish','--record',str(path),'--push','--yes')
        if receipt.get('source')!=c['source']:raise ValueError('Managed publisher source alias changed')
        if any(receipt.get(key)!=planned.get(key) for key in ('entry_id','path','sha256')):raise ValueError('Original draft identity or bytes changed after planning')
        pending.update({k:receipt[k] for k in ('entry_id','path','sha256','branch','publication_commit','pull_request') if k in receipt})
        if not receipt.get('published'):
            if receipt.get('status')!='pending_review' or not receipt.get('remote_verified'):raise ValueError('Managed publication is not independently remote verified')
            url=receipt.get('pull_request','');tip=receipt.get('publication_commit','');status=read(c,'status');slug=status['source']['repository']
            if not re.fullmatch('https://github\\.com/'+re.escape(slug)+r'/pull/[1-9][0-9]*',url) or not re.fullmatch('[0-9a-f]{40}',tip):raise ValueError('Unexpected managed publication identity')
            pr=json.loads(gh('gh','pr','view',url,'--repo',slug,'--json','state,headRefOid,headRefName,baseRefName,files'))
            files=pr.get('files',[])
            if pr.get('state')!='OPEN' or pr.get('headRefOid')!=tip or pr.get('headRefName')!=receipt.get('branch') or pr.get('baseRefName')!=status['source']['branch'] or len(files)!=1 or files[0].get('path')!=receipt['path'] or files[0].get('deletions')!=0:raise ValueError('Managed review is not the exact one-record publication')
            refresh_route(initial) # Fresh committed generation immediately before normal merge.
            gh('gh','pr','merge',url,'--repo',slug,'--merge','--match-head-commit',tip)
        synchronize(c)
        verified=invoke(c,'publish','--record',str(path),'--push','--yes')
        if not verified.get('published') or not verified.get('canonical_verified') or any(verified.get(key)!=receipt.get(key) for key in ('entry_id','path','sha256')):raise ValueError('Canonical retry did not verify the original record identity and bytes')
        exported=named(c,'export')
        if exported['source']['commit']!=verified['commit'] or sum(e.get('id')==verified['entry_id'] for e in exported['entries'])!=1:raise ValueError('Canonical entry uniqueness or source snapshot differs')
        return {**verified,'ok':True,'executed':True,'route_generation':initial['generation'],'original_draft':str(path),'source_operator_merged':bool(receipt.get('status')=='pending_review'),'checks':'advisory; normal repository merge policy remains enforced'}
    except (ValueError,OSError,RuntimeError,subprocess.SubprocessError,json.JSONDecodeError) as exc:
        return {**pending,'error_type':type(exc).__name__,'retained':True,'receipt':receipt}
