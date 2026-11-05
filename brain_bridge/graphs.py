# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Deterministic evidence graphs; no task inference or tracker mutations."""
import hashlib
import html
import json
from .contract import record_entries


def node_id(kind,key):return 'n'+hashlib.sha256((kind+':'+key).encode()).hexdigest()


def evidence_graph(items,source_id,tasks=None,overlays=None):
    nodes={};edges=set();known_records=set();references=set()
    def node(kind,key,label,**fields):
        identifier=node_id(kind,key)
        nodes[identifier]={'id':identifier,'kind':kind,'label':str(label),**fields}
        return identifier
    source=node('source',source_id,source_id)
    for path,digest,envelope in items:
        for entry in record_entries(envelope):
            record=node('record',source_id+':'+entry['id'],entry['title'],entry_id=entry['id'],file=path,sha256=digest,timestamp=entry['timestamp'])
            known_records.add(entry['id']);edges.add((source,record,'contains'))
            anchor=entry.get('context',{}).get('coverage_since',{}) if isinstance(entry.get('context'),dict) else {}
            if isinstance(anchor,dict) and isinstance(anchor.get('entry_id'),str):
                key=anchor['entry_id'];references.add(key)
                target=node_id('record',source_id+':'+key);edges.add((record,target,'covers_since'))
            supersedes=entry.get('supersedes',[])
            if not isinstance(supersedes,list):raise ValueError('Supersedes must be explicit reference IDs')
            for old in supersedes:
                if isinstance(old,str):
                    references.add(old);edges.add((record,node_id('record',source_id+':'+old),'supersedes'))
            for reference in entry.get('references',[]):
                if isinstance(reference,dict) and reference.get('type')=='github_evidence':
                    fields=('observation_id','resource_id','snapshot_sha256','url','observed_at','kind')
                    if not all(isinstance(reference.get(field),str) and reference[field] for field in fields):
                        raise ValueError('Malformed GitHub evidence reference')
                    target=node('github_evidence',reference['observation_id'],reference['resource_id'],
                                evidence_kind=reference['kind'],**{field:reference[field] for field in fields if field!='kind'})
                    edges.add((record,target,'evidenced_by'))
            provenance=entry.get('provenance',(overlays or {}).get(entry['id'],{}))
            nodes[record]['provenance_source']='native' if 'provenance' in entry else ('overlay' if entry['id'] in (overlays or {}) else 'unavailable')
            if not isinstance(provenance,dict):continue
            attributions=[]
            for actor in provenance.get('users',[]):
                if not isinstance(actor,dict):raise ValueError('Invalid actor attribution')
                native=actor.get('user_id',actor.get('account_id',actor.get('login')))
                key=actor.get('provider','github')+':'+actor['host']+':'+str(native)
                target=node('actor',key,actor['host']+'/'+str(actor.get('login',native)))
                edges.add((record,target,'references_actor'))
                attributions.append({'actor':target,'role':actor['role']})
            nodes[record]['attributions']=attributions
            for repo in provenance.get('repositories',[]):
                key=repo['host']+':'+repo['repository_id']
                target=node('repository',key,repo['host']+'/'+repo['full_name'],provider=repo.get('provider','github'),repository_id=repo['repository_id'])
                edges.add((record,target,'references'))
            for run in provenance.get('workflow_runs',[]):
                provider=run.get('provider','github_actions');identity=run.get('run_id',run.get('build_url'))
                key=provider+':'+run['host']+':'+str(identity)+':'+run.get('repository','')+':'+run.get('run_attempt','')
                target=node('workflow',key,provider+' '+str(identity),provider=provider,observed_result=run.get('conclusion',run.get('result')))
                edges.add((record,target,'evidenced_by'))
    for reference in references-known_records:
        node('record',source_id+':'+reference,'Unresolved record '+reference,entry_id=reference,unresolved=True)
    unresolved=[];cycles=[]
    if tasks is not None:
        required={'project_id','revision','items'}
        if not isinstance(tasks,dict) or not required<=set(tasks) or type(tasks['revision']) is not int or not isinstance(tasks['items'],list):raise ValueError('Expected a projected authoritative task snapshot')
        project=tasks['project_id'];lookup={}
        for task in tasks['items']:
            if not isinstance(task,dict) or not isinstance(task.get('id'),str) or task.get('status') not in ('Open','WIP','Blocked','Cancelled','Done') or not isinstance(task.get('depends',[]),list):raise ValueError('Malformed authoritative task projection')
            if task['id'] in lookup:raise ValueError('Duplicate task projection identity')
            lookup[task['id']]=task
            node('task',project+':'+task['id'],task.get('label',task['id'])+': '+task.get('title',''),status=task['status'],task_id=task['id'],observed_revision=tasks['revision'])
        for uid,task in lookup.items():
            for prerequisite in task.get('depends',[]):
                if not isinstance(prerequisite,str):raise ValueError('Task dependency IDs must be strings')
                if prerequisite not in lookup:
                    node('task',project+':'+prerequisite,'Unresolved task '+prerequisite,task_id=prerequisite,unresolved=True)
                    unresolved.append(prerequisite)
                edges.add((node_id('task',project+':'+uid),node_id('task',project+':'+prerequisite),'depends_on'))
        colors={}
        for start in sorted(lookup):
            if colors.get(start)==2:continue
            path=[start];positions={start:0};colors[start]=1
            stack=[(start,iter(lookup[start].get('depends',[])))]
            while stack:
                uid,dependencies=stack[-1]
                try:dependency=next(dependencies)
                except StopIteration:
                    stack.pop();positions.pop(uid,None);path.pop();colors[uid]=2;continue
                if dependency not in lookup:continue
                if colors.get(dependency)==1:
                    cycles.append(path[positions[dependency]:]+[dependency])
                elif colors.get(dependency)!=2:
                    positions[dependency]=len(path);path.append(dependency);colors[dependency]=1
                    stack.append((dependency,iter(lookup[dependency].get('depends',[]))))
    return {'nodes':sorted(nodes.values(),key=lambda n:n['id']),'edges':[{'from':a,'to':b,'relation':r} for a,b,r in sorted(edges)],'unresolved_tasks':sorted(set(unresolved)),'task_cycles':cycles}


def render_dot(graph):
    lines=['digraph brain_bridge {']
    for node in graph['nodes']:lines.append('  '+node['id']+' [label='+json.dumps(node['label'],ensure_ascii=False)+'];')
    for edge in graph['edges']:lines.append('  '+edge['from']+' -> '+edge['to']+' [label='+json.dumps(edge['relation'])+'];')
    return '\n'.join(lines+['}'])


def render_mermaid(graph):
    lines=['flowchart TD']
    for node in graph['nodes']:
        label=html.escape(' '.join(node['label'].split()),quote=True).replace('"','&quot;').replace('\\','&#92;').replace('%','&#37;').replace('`','&#96;')
        lines.append('  '+node['id']+'["'+label+'"]')
    for edge in graph['edges']:lines.append('  '+edge['from']+' -->|'+edge['relation']+'| '+edge['to'])
    return '\n'.join(lines)
