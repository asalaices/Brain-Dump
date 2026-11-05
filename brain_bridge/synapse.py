# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Authorized, cited synapse requests. Receipts are context, never authority."""
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4
import sqlite3
import subprocess
from .authority import GitHubAuthority
from .contract import record_entries
from .managed import managed_search,reader_root,immutable_snapshot
from .policy import AccessDenied,AuthorizationUnavailable


def excerpt(value,term,size):
    """Bound the quote around a match, accounting for Unicode casefold expansion."""
    index=value.casefold().find(term.casefold());position=0;consumed=0
    if index>=0:
        for position,char in enumerate(value):
            consumed+=len(char.casefold())
            if consumed>index:break
    start=max(0,position-size//3);end=min(len(value),start+size)
    return {'text':value[start:end],'start':start,'end':end,'truncated':start>0 or end<len(value)}


def synapse_request(identity_repo,source_repo,source_name,term,cache_dir,backend='auto',limit=20,excerpt_chars=240,authority=None):
    if not isinstance(term,str) or not term.strip() or len(term)>512:raise ValueError('Query must contain 1–512 characters')
    if not isinstance(source_name,str) or not source_name:raise ValueError('An explicit registered source name is required')
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('Result limit must be 1–100')
    if type(excerpt_chars) is not int or not 40<=excerpt_chars<=1000:raise ValueError('Excerpt length must be 40–1000 characters')
    if backend not in ('json','sqlite','auto'):raise ValueError('Unknown backend')
    receipt={'schema_version':1,'request_id':str(uuid4()),'requested_at':datetime.now(timezone.utc).isoformat(),
             'requested_source':source_name,'query':term,'read_only':True,'matches':[],
             'conflict_assessment':'not_performed','authority':'recorded context only'}
    api=authority or GitHubAuthority()
    try:
        grant=api.snapshot(identity_repo,source_repo)
        if grant.source_name!=source_name:raise AccessDenied('Requested source name does not match authenticated registration')
        search=managed_search(identity_repo,source_repo,term,cache_dir,backend,api)
        if search['commit']!=grant.commit or search['source_id']!=grant.source_id:
            raise AccessDenied('Source changed while consulting; results withheld')
        snapshot=immutable_snapshot(reader_root(source_repo,grant),grant)
        files={};entries={};superseded={}
        for path,digest,envelope in snapshot['records']:
            rows=record_entries(envelope);files['records/'+path]=(digest,envelope,rows)
            for row in rows:
                entries[row['id']]=('records/'+path,digest,row)
                for old in row.get('supersedes',[]) if isinstance(row.get('supersedes',[]),list) else []:
                    if isinstance(old,str):superseded.setdefault(old,[]).append(row['id'])
        overlays={path:obj for path,_,obj in snapshot['overlays']}
        matches=[]
        ordered=sorted(search['results'],key=lambda hit:(hit['file'],hit['pointer'],hit['kind'],hit['value']))
        for hit in ordered[:limit]:
            file=hit['file'];pointer=hit['pointer'];selected=None;ledger=None;ledger_digest=None;scope='envelope';associated=[]
            if file in overlays:
                uid=overlays[file]['entry_id'];ledger,ledger_digest,selected=entries[uid];scope='provenance_overlay';associated=[selected]
            else:
                ledger=file;ledger_digest,envelope,associated=files[file]
                parts=pointer.split('/')
                if envelope['schema_version']!=1 and len(parts)>1 and parts[1]=='entry':selected=associated[0];scope='entry'
                elif envelope['schema_version']==1 and len(parts)>2 and parts[1]=='entries' and parts[2].isdigit():
                    selected=associated[int(parts[2])];scope='entry'
            url='https://github.com/'+grant.source_slug+'/blob/'+grant.commit+'/'
            uid=selected['id'] if selected else None
            matches.append({'source_path':file,'json_pointer':pointer,'match_kind':hit['kind'],
                'excerpt':excerpt(hit['value'],term,excerpt_chars),'sha256':hit['sha256'],
                'source_url':url+quote(file,safe='/'),'ledger_path':ledger,'ledger_sha256':ledger_digest,
                'record_url':url+quote(ledger,safe='/'),'match_scope':scope,
                'entry_id':uid,'record_timestamp':selected['timestamp'] if selected else None,
                'associated_entry_ids':[row['id'] for row in associated] if selected is None else [uid],
                'superseded_by':sorted(superseded.get(uid,[])) if uid else [],
                'provenance_source':('native' if 'provenance' in selected else ('overlay' if uid in snapshot['provenance'] else 'unavailable')) if selected else 'not_entry_specific'})
        if api.snapshot(identity_repo,source_repo)!=grant:raise AccessDenied('Policy/source changed while citing; results withheld')
        found=bool(matches)
        return {**receipt,'status':'found' if found else 'no_match','matches':matches,
                'total_matches':len(ordered),'returned_matches':len(matches),'truncated':len(ordered)>limit,
                'completed_at':datetime.now(timezone.utc).isoformat(),
                'source':{'name':grant.source_name,'repository':grant.source_slug,'repository_id':grant.source_id,
                          'commit':grant.commit,'branch':grant.branch,'policy_revision':grant.policy_revision},
                'freshness':{key:search[key] for key in ('source_verified','backend_used','cache_fresh','indexed_commit','indexed_at')},
                'corpus':{'record_files':len(snapshot['records']),'entries':len(entries),'provenance_overlays':len(snapshot['overlays'])},
                'disclosure':'I found this reference in the Brain after a synapse request.' if found else 'No matching reference was found in the authorized Brain source.'}
    except AuthorizationUnavailable as exc:
        return {**receipt,'status':'unavailable','error':str(exc),'disclosure':'The Brain source could not be authorized upstream; no references are being reported.'}
    except AccessDenied as exc:
        return {**receipt,'status':'denied','error':str(exc),'disclosure':'The Brain request was denied; no references are being reported.'}
    except (ValueError,RuntimeError,OSError,sqlite3.Error,subprocess.TimeoutExpired) as exc:
        return {**receipt,'status':'error','error':'Operation timed out; no references are being reported' if isinstance(exc,subprocess.TimeoutExpired) else str(exc),'disclosure':'The Brain request failed; no references are being reported.'}
