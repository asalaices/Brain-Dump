# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Named, read-only CI observations with provider-native identity and status.

No build trigger, message send, token store or automatic publication exists in
this module. Sources must be reviewed in the code repository's committed
connector registry. Provider credentials stay in existing gh/glab or environment
transports; response bodies and credential headers are never logged.
"""
import base64
import json
import os
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .authority import GitHubAuthority, github_slug, git, trusted_registration, content_at
from .policy import Identity, AccessDenied, document, repository_id

LIMIT=1048576
class ConnectorError(RuntimeError):pass


def https_url(value):
    if not isinstance(value,str) or any(c.isspace() for c in value):raise ConnectorError('Invalid registered HTTPS URL')
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or any(x in ('.','..') for x in p.path.split('/')):
        raise ConnectorError('Registered URL must be HTTPS without credentials or ambiguous components')
    return p


def number(value):
    if type(value) is int and value>0:return str(value)
    if isinstance(value,str) and re.fullmatch(r'[1-9][0-9]*',value):return value
    raise ConnectorError('Provider identifier must be a positive decimal ID')


def sha(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})',value):raise ConnectorError('Provider commit must be complete')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ConnectorError('Connector redirects are not allowed')


class Transport:
    def cli_json(self,tool,host,endpoint):
        if tool not in ('gh','glab'):raise ConnectorError('Unsupported credential transport')
        try:
            result=subprocess.run([tool,'api','--hostname',host,'--method','GET',endpoint],capture_output=True,timeout=60)
            if result.returncode or len(result.stdout)>LIMIT:raise ConnectorError('Authenticated provider request failed')
            return json.loads(result.stdout)
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:raise ConnectorError('Provider response unavailable') from exc

    def jenkins_json(self,url,username_env,token_env):
        https_url(url)
        user=os.environ.get(username_env);token=os.environ.get(token_env)
        if not user or not token or any(c in user+token for c in '\r\n'):raise AccessDenied('Named Jenkins credentials unavailable')
        header=base64.b64encode((user+':'+token).encode()).decode()
        request=Request(url,headers={'Authorization':'Basic '+header,'Accept':'application/json'},method='GET')
        try:
            with build_opener(NoRedirect()).open(request,timeout=30) as response:
                raw=response.read(LIMIT+1)
            if len(raw)>LIMIT:raise ConnectorError('Oversized provider response')
            return json.loads(raw)
        except ConnectorError:raise
        except Exception as exc:
            # Never include a provider body, request header or credential in an error.
            raise ConnectorError('Authenticated Jenkins request failed') from None


def load_connector(identity_repo,name,authority=None,with_context=False):
    api=authority or GitHubAuthority()
    identity,code_slug,code_commit=trusted_registration(identity_repo,api)
    config=document(content_at(api,code_slug,code_commit,'.brain-bridge/connectors.json'))
    if set(config)!={'schema_version','connectors'} or type(config.get('schema_version')) is not int or config['schema_version']!=1 or not isinstance(config['connectors'],list):raise AccessDenied('Invalid committed connector registry')
    names=set();selected=None
    for item in config['connectors']:
        if not isinstance(item,dict):raise AccessDenied('Malformed connector registration')
        provider=item.get('provider');common={'name','provider'}
        fields={'github':{'repository','repository_id'},'github_actions':{'repository','repository_id'},'gitlab':{'host','project_id'},'jenkins':{'job_url','username_env','token_env'}}
        if provider not in fields or set(item)!=common|fields[provider]:raise AccessDenied('Unsupported connector contract')
        label=item['name']
        if not isinstance(label,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',label) or label in names:raise AccessDenied('Invalid or duplicate connector name')
        names.add(label)
        if provider in ('github','github_actions'):
            if not isinstance(item['repository'],str) or github_slug('https://github.com/'+item['repository']+'.git')!=item['repository']:raise AccessDenied('Invalid GitHub connector repository')
            repository_id(item['repository_id'])
        elif provider=='gitlab':
            host=item['host']
            if not isinstance(host,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?',host):raise AccessDenied('Invalid GitLab connector host')
            repository_id(item['project_id'])
        else:
            https_url(item['job_url'])
            for key in ('username_env','token_env'):
                if not isinstance(item[key],str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*',item[key]):raise AccessDenied('Jenkins credentials must name environment variables')
        if label==name:selected=item
    if selected is None:raise AccessDenied('Connector is not explicitly registered')
    if api.api("repos/"+code_slug+"/commits/main").get("sha")!=code_commit:raise AccessDenied("Connector registration changed during authorization")
    if with_context:
        return {'spec':selected,'registration':{'identity_key':identity.key,'repository':code_slug,'commit':code_commit}}
    return selected


def observe(spec,run_id,transport=None):
    """Fetch one explicitly selected run; never infer success from submission."""
    run_id=number(run_id);io=transport or Transport();provider=spec['provider']
    if provider=='github_actions':
        repo=spec['repository'];meta=io.cli_json('gh','github.com','repos/'+repo)
        if str(meta.get('id'))!=spec['repository_id'] or meta.get('permissions',{}).get('pull') is not True:raise AccessDenied('GitHub connector source identity/permission mismatch')
        row=io.cli_json('gh','github.com','repos/'+repo+'/actions/runs/'+run_id)
        if number(row.get('id'))!=run_id:raise ConnectorError('Run identity mismatch')
        url=row.get('html_url');parts=https_url(url)
        if parts.netloc!='github.com' or parts.path!='/'+repo+'/actions/runs/'+run_id:raise ConnectorError('Run URL identity mismatch')
        return {'provider':'github_actions','host':'github.com','repository':repo,'repository_id':spec['repository_id'],'run_id':run_id,'run_attempt':number(row.get('run_attempt')),'workflow':row.get('name'),'head_sha':sha(row.get('head_sha')),'status':row.get('status'),'conclusion':row.get('conclusion'),'url':url,'artifacts':[]}
    if provider=='gitlab':
        host=spec['host'];project=spec['project_id'];meta=io.cli_json('glab',host,'projects/'+project)
        if number(meta.get('id'))!=project:raise AccessDenied('GitLab connector project identity mismatch')
        row=io.cli_json('glab',host,'projects/'+project+'/pipelines/'+run_id)
        if number(row.get('id'))!=run_id or number(row.get('project_id'))!=project:raise ConnectorError('Pipeline identity mismatch')
        url=row.get('web_url');parts=https_url(url)
        if parts.netloc!=host:raise ConnectorError('Pipeline URL host mismatch')
        return {'provider':'gitlab','host':host,'project_id':project,'project_path':meta.get('path_with_namespace'),'run_id':run_id,'head_sha':sha(row.get('sha')),'status':row.get('status'),'url':url,'artifacts':[]}
    if provider=='jenkins':
        job=spec['job_url'].rstrip('/')+'/';parts=https_url(job);build=job+run_id+'/'
        row=io.jenkins_json(build+'api/json',spec['username_env'],spec['token_env'])
        if number(row.get('number'))!=run_id or row.get('url')!=build:raise ConnectorError('Jenkins build identity mismatch')
        if type(row.get('building')) is not bool:raise ConnectorError('Jenkins build state unavailable')
        result=row.get('result')
        if result not in (None,'SUCCESS','FAILURE','UNSTABLE','ABORTED','NOT_BUILT','UNKNOWN'):raise ConnectorError('Unknown Jenkins result vocabulary')
        return {'provider':'jenkins','host':parts.netloc,'run_id':run_id,'job_url':job,'build_url':build,'building':row['building'],'result':result,'artifacts':[]}
    raise ConnectorError('Unsupported observation provider')


def observe_named(identity_repo,name,run_id,authority=None,transport=None):
    return observe(load_connector(identity_repo,name,authority),run_id,transport)
