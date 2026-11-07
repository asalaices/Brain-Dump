#!/usr/bin/env python3
# script_version: 1.0.0
# Purpose: Resolve registered Brain-Dump phase/stack dependencies and run them serially through the public controller.
# Usage: python3 bootstrap/assets/controller.py --host local [--phase ID|--stack NAME] [--plan|--verify|--install --execute] [--config PROFILE] [--json|--pretty]
# Output: json
# Prerequisites: Registered phases.conf, stack manifests, Bash, and Python 3.11+.
# Failure: Invalid graphs/options exit 2; failed phases stop dependents and return nonzero.
from __future__ import annotations
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'intelli_bots'))
from bot_general import OutputArgumentParser, add_output_arguments, run_cli, script_interface, write_json_document
script_interface(__file__,purpose='Resolve registered Brain-Dump phase and stack dependencies and run them serially.',output='json')

def phases():
    rows={}
    for raw in (ROOT/'bootstrap/phases.conf').read_text(encoding='utf-8').splitlines():
        line=raw.strip()
        if not line or line.startswith('#'):continue
        number,name,needs,systems=line.split('|')
        if number in rows or not number.isdigit() or len(number)!=3:raise ValueError('Invalid or duplicate phase registration')
        script=ROOT/'bootstrap/phases'/f'{number}-{name}.sh'
        if not script.is_file() or script.is_symlink():raise ValueError('Registered phase script missing: '+number)
        rows[number]={'id':number,'name':name,'needs':[x for x in needs.split(',') if x],
                      'platforms':[x for x in systems.split(',') if x],'script':script}
    for row in rows.values():
        if any(need not in rows for need in row['needs']):raise ValueError('Unknown phase dependency: '+row['id'])
    return rows

def select_phase(rows,requested):
    matches=[key for key,row in rows.items() if requested in (key,row['name'],key+'-'+row['name'])]
    if len(matches)!=1:raise ValueError('Unknown or ambiguous phase: '+requested)
    selected=set()
    visiting=set()
    ordered=[]
    def add(key):
        if key in selected:return
        if key in visiting:raise ValueError('Cyclic phase dependency: '+key)
        visiting.add(key)
        for need in rows[key]['needs']:add(need)
        visiting.remove(key);selected.add(key);ordered.append(rows[key])
    add(matches[0])
    return ordered

def load_stack(name,rows):
    if not name or '/' in name or name.startswith('.'):raise ValueError('Invalid stack name')
    path=ROOT/'bootstrap/stacks'/(name+'.json')
    if not path.is_file() or path.is_symlink():raise ValueError('Unknown stack: '+name)
    value=json.loads(path.read_text(encoding='utf-8'))
    if set(value)!= {'schema_version','name','steps'} or value['schema_version']!=1 or value['name']!=name or not isinstance(value['steps'],list):
        raise ValueError('Invalid stack manifest')
    selected=[];known=set();selected_phases=set()
    for step in value['steps']:
        if (set(step)!= {'id','phase','needs','critical'} or not isinstance(step['id'],str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]*',step['id']) or not isinstance(step['needs'],list)
                or not isinstance(step['critical'],bool) or step['phase'] not in rows):
            raise ValueError('Invalid stack step')
        if step['id'] in known or any(need not in known for need in step['needs']):raise ValueError('Invalid stack dependency order')
        if any(need not in selected_phases for need in rows[step['phase']]['needs']):
            raise ValueError('Stack omits or misorders registered phase dependency: '+step['phase'])
        known.add(step['id']);selected_phases.add(step['phase'])
        selected.append({**rows[step['phase']],'step_id':step['id'],'critical':step['critical']})
    return selected

def action(args):
    if args.install:return 'install' if args.execute else 'plan'
    if args.verify:return 'verify'
    return 'plan'

def command(row,args,selected_action):
    result=['/bin/bash',str(row['script']),'--host',args.host,'--'+selected_action,'--json']
    if args.config:result += ['--config',str(Path(args.config).resolve())]
    if selected_action=='install':result.append('--execute')
    return result

def main(argv=None):
    parser=OutputArgumentParser(description=__doc__)
    parser.add_argument('--host',default='local',choices=['local'])
    choice=parser.add_mutually_exclusive_group()
    choice.add_argument('--phase');choice.add_argument('--stack')
    choice.add_argument('--list-phases',action='store_true');choice.add_argument('--list-stacks',action='store_true')
    operation=parser.add_mutually_exclusive_group()
    operation.add_argument('--plan',action='store_true');operation.add_argument('--verify',action='store_true');operation.add_argument('--install',action='store_true')
    parser.add_argument('--execute',action='store_true');parser.add_argument('--config')
    add_output_arguments(parser)
    args=parser.parse_args(argv)
    if args.execute and not args.install:parser.error('--execute requires --install')
    rows=phases()
    if args.list_phases:
        write_json_document({'ok':True,'phases':[{k:v for k,v in row.items() if k!='script'} for row in rows.values()]},script_path=Path(__file__),pretty=args.pretty);return 0
    if args.list_stacks:
        names=[]
        for path in sorted((ROOT/'bootstrap/stacks').glob('*.json')):
            load_stack(path.stem,rows);names.append(path.stem)
        write_json_document({'ok':True,'stacks':names},script_path=Path(__file__),pretty=args.pretty);return 0
    if args.stack:selected=load_stack(args.stack,rows)
    elif args.phase:selected=select_phase(rows,args.phase)
    else:selected=list(rows.values())
    current=platform.system().lower()
    selected_action=action(args)
    planned=[]
    for row in selected:
        if current not in row['platforms']:raise ValueError('Phase '+row['id']+' does not support '+current)
        planned.append({'phase':row['id']+'-'+row['name'],'action':selected_action})
    if selected_action=='plan':
        write_json_document({'ok':True,'host':args.host,'action':'plan','executed':False,'effects':[],
                             'selection':args.stack or args.phase or 'all','phases':planned,
                             'preserved':['installed Brain runtime','authorized readers and cache','grants and publishing routes','existing MCP tunnels and services']},
                            script_path=Path(__file__),pretty=args.pretty);return 0
    results=[]
    for row in selected:
        completed=subprocess.run(command(row,args,selected_action),cwd=ROOT,capture_output=True,text=True)
        try:document=json.loads(completed.stdout)
        except json.JSONDecodeError:document={'error':'Phase returned invalid structured output'}
        results.append({'phase':row['id']+'-'+row['name'],'exit_code':completed.returncode,'result':document})
        if completed.returncode:break
    ok=len(results)==len(selected) and all(row['exit_code']==0 for row in results)
    write_json_document({'ok':ok,'host':args.host,'action':selected_action,'executed':selected_action=='install',
                         'selection':args.stack or args.phase or 'all','results':results},
                        script_path=Path(__file__),pretty=args.pretty)
    return 0 if ok else 1

if __name__=='__main__':raise SystemExit(run_cli(main,script_path=Path(__file__)))
