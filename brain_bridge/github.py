# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Bounded GitHub evidence collection. GET only; no inferred task completion."""
import hashlib
import json
from datetime import datetime, timezone
from .connectors import Transport, ConnectorError, number, sha, load_connector, observe
from .policy import AccessDenied


def object_value(value):
    if not isinstance(value,dict):raise ConnectorError('Malformed GitHub object metadata')
    return value


def text(value, field, nullable=False):
    if value is None and nullable: return None
    if not isinstance(value,str): raise ConnectorError('Invalid GitHub '+field)
    return value


def parents(value):
    if not isinstance(value,list):raise ConnectorError('Missing GitHub commit parents')
    return value


def timestamp(value, nullable=False):
    if value is None and nullable: return None
    value=text(value,'timestamp')
    try:
        moment=datetime.fromisoformat(value.replace('Z','+00:00'))
        if moment.utcoffset() is None: raise ValueError()
    except ValueError as exc: raise ConnectorError('Invalid GitHub timestamp') from exc
    return value


def repository(spec, io):
    repo=spec['repository'];meta=io.cli_json('gh','github.com','repos/'+repo)
    if not isinstance(meta,dict) or number(meta.get('id'))!=spec['repository_id'] or meta.get('full_name')!=repo or not isinstance(meta.get('permissions'),dict) or meta['permissions'].get('pull') is not True:
        raise AccessDenied('GitHub connector repository identity/permission mismatch')
    return meta


def collect(spec,kind,identifier,transport=None,include_body=False):
    """Observe exactly one selected object; links and bodies remain untrusted data."""
    if spec.get('provider')!='github':raise ConnectorError('Expected a registered GitHub evidence connector')
    if kind not in ('issue','pull_request','commit','run'):raise ConnectorError('Unsupported GitHub evidence kind')
    selected=sha(identifier) if kind=='commit' else number(identifier)
    io=transport or Transport();repository(spec,io);repo=spec['repository']
    endpoint='repos/'+repo+'/'
    if kind=='run':
        item=observe(dict(spec,provider='github_actions'),selected,io)
        item['id']=selected
    else:
        segment={'issue':'issues/','pull_request':'pulls/','commit':'commits/'}[kind]
        row=io.cli_json('gh','github.com',endpoint+segment+selected)
        if not isinstance(row,dict):raise ConnectorError('Invalid GitHub object response')
        suffix={'issue':'issues/','pull_request':'pull/','commit':'commit/'}[kind]+selected
        url='https://github.com/'+repo+'/'+suffix
        if row.get('html_url')!=url:raise ConnectorError('GitHub object URL identity mismatch')
        if kind=='commit':
            if sha(row.get('sha'))!=selected:raise ConnectorError('Commit identity mismatch')
            commit=row.get('commit')
            if not isinstance(commit,dict):raise ConnectorError('Missing Git commit metadata')
            message=text(commit.get('message'),'commit message')
            item={'id':selected,'sha':selected,'url':url,'title':message.split('\n',1)[0],
                  'committed_at':timestamp(object_value(commit.get('committer')).get('date')),
                  'parents':[sha(object_value(parent).get('sha')) for parent in parents(row.get('parents'))]}
            if include_body:item['body']=message
        else:
            if number(row.get('number'))!=selected:raise ConnectorError('Issue/PR number mismatch')
            uid=number(row.get('id'))
            if row.get('state') not in ('open','closed'):raise ConnectorError('Invalid issue/PR state')
            item={'id':uid,'number':selected,'url':url,'title':text(row.get('title'),'title'),
                  'state':row['state'],'created_at':timestamp(row.get('created_at')),
                  'updated_at':timestamp(row.get('updated_at')),'closed_at':timestamp(row.get('closed_at'),True)}
            if include_body:item['body']=text(row.get('body'),'body',True)
            if kind=='issue':
                if 'pull_request' in row:raise ConnectorError('Selected issue is a pull request; request its PR identity explicitly')
                if row.get('repository_url')!='https://api.github.com/repos/'+repo:raise ConnectorError('Issue repository identity mismatch')
                item['state_reason']=row.get('state_reason')
            else:
                base=object_value(row.get('base'));source=object_value(base.get('repo'))
                if number(source.get('id'))!=spec['repository_id'] or source.get('full_name')!=repo:raise ConnectorError('PR base repository mismatch')
                if type(row.get('draft')) is not bool or type(row.get('merged')) is not bool:raise ConnectorError('Missing PR draft/merge state')
                item.update(draft=row['draft'],merged=row['merged'],merged_at=timestamp(row.get('merged_at'),True),
                            head_sha=sha(object_value(row.get('head')).get('sha')),base_sha=sha(base.get('sha')),
                            merge_commit_sha=sha(row['merge_commit_sha']) if row.get('merge_commit_sha') else None)
                if item['merged'] and (item['state']!='closed' or not item['merged_at']):raise ConnectorError('Inconsistent PR merge evidence')
    # Access revoked during collection means no payload may be returned.
    repository(spec,io)
    stable='github:'+spec['repository_id']+':'+kind+':'+item['id']
    payload={'provider':'github','repository':repo,'repository_id':spec['repository_id'],'kind':kind,'resource_id':stable,'object':item}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    result={'schema_version':1,**payload,'snapshot_sha256':digest,
            'observation_id':stable+'@'+digest,'observed_at':datetime.now(timezone.utc).isoformat(),
            'read_only':True,'task_status_inferred':False,'body_included':include_body}
    result['brain_evidence']=brain_evidence(result)
    return result


def brain_evidence(receipt):
    """Project observed evidence into record fields, without writing a record/task."""
    from .contract import validate_provenance
    repo=receipt['repository'];item=receipt['object'];kind=receipt['kind']
    provenance={'users':[],'repositories':[{'provider':'github','host':'github.com','full_name':repo,
                 'repository_id':receipt['repository_id']}],'issues':[],'workflow_runs':[]}
    if kind in ('issue','pull_request'):
        provenance['issues'].append({'provider':'github','host':'github.com','repository':repo,
            'number':item['number'],'relationship':'observed_'+kind,'url':item['url']})
    elif kind=='run':
        provenance['workflow_runs'].append({key:value for key,value in item.items() if key not in ('id',)})
    validate_provenance(provenance)
    reference={'type':'github_evidence','kind':kind,'resource_id':receipt['resource_id'],
               'observation_id':receipt['observation_id'],'snapshot_sha256':receipt['snapshot_sha256'],
               'url':item['url'],'observed_at':receipt['observed_at']}
    return {'provenance':provenance,'references':[reference],
            'task_evidence':[item['url']+' (observation '+receipt['observation_id']+')'],
            'task_mutations':[]}


def collect_named(identity_repo,name,kind,identifier,transport=None,authority=None,include_body=False):
    before=load_connector(identity_repo,name,authority,with_context=True)
    result=collect(before['spec'],kind,identifier,transport,include_body)
    if load_connector(identity_repo,name,authority,with_context=True)!=before:
        raise AccessDenied('Connector registration changed during collection; evidence withheld')
    return {**result,'connector':name,'registration':before['registration']}
