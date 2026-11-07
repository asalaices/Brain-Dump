#!/usr/bin/env python3
# script_version: 1.0.0
# Purpose: Discover and run registered Brain-Dump offline checks with a versioned aggregate result.
# Usage: python3 tests/suite_runner.py [--component bootstrap|application|all] [--all] [--test PATH] [--offline] [--json|--pretty]
# Output: json
# Prerequisites: Python 3.11+ and repository test sources; live/manual tests are excluded.
# Failure: Failed checks exit 1 and invalid selections exit 2.
from __future__ import annotations
import os
import subprocess
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'intelli_bots'))
from bot_general import OutputArgumentParser, add_output_arguments, run_cli, script_interface, write_json_document
script_interface(__file__,purpose='Discover and run registered Brain-Dump offline checks.',output='json')

def inventory():
    rows=[]
    for path in sorted((ROOT/'tests').rglob('test_*')):
        if not path.is_file() or path.suffix!='.py' or any(part in ('live','manual') for part in path.parts):continue
        component='bootstrap' if 'bootstrap' in path.parts else 'application'
        rows.append((path.relative_to(ROOT).as_posix(),component))
    return rows

def main(argv=None):
    parser=OutputArgumentParser(description=__doc__)
    parser.add_argument('--component',choices=['bootstrap','application','all'],default='all')
    parser.add_argument('--all',action='store_true');parser.add_argument('--test',action='append',default=[])
    parser.add_argument('--offline',action='store_true');add_output_arguments(parser);args=parser.parse_args(argv)
    if not args.all and not args.test:parser.error('Select --all or one or more --test paths')
    if not args.offline:parser.error('Only explicit --offline execution is supported')
    known=inventory();selected=[row for row in known if args.component=='all' or row[1]==args.component]
    if args.test:
        requested=set(args.test);available={path for path,_ in selected}
        if requested-available:parser.error('Unknown test: '+', '.join(sorted(requested-available)))
        selected=[row for row in selected if row[0] in requested]
    results=[]
    for path,component in selected:
        environment={**os.environ,'BRAIN_BOOTSTRAP_PYTHON':sys.executable}
        completed=subprocess.run([sys.executable,'-m','unittest','discover','-s',str((ROOT/path).parent),'-p',Path(path).name],
                                 cwd=ROOT,capture_output=True,text=True,env=environment)
        result={'path':path,'component':component,'exit_code':completed.returncode}
        if completed.returncode:
            result['stdout_tail']=completed.stdout[-4000:]
            result['stderr_tail']=completed.stderr[-4000:]
        results.append(result)
    ok=all(row['exit_code']==0 for row in results)
    write_json_document({'ok':ok,'mode':'offline','results':results,'total':len(results)},script_path=Path(__file__),pretty=args.pretty)
    return 0 if ok else 1

if __name__=='__main__':raise SystemExit(run_cli(main,script_path=Path(__file__)))
