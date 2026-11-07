#!/usr/bin/env python3
# script_version: 1.0.0
# Purpose: Validate local Brain-Dump bootstrap prerequisites without changing runtime, sources, routes, or services.
# Usage: python3 bootstrap/assets/preflight_phase.py --host local [--plan|--verify|--install --execute] [--config PROFILE] [--json|--pretty]
# Output: json
# Prerequisites: Python 3.11+ and Git; profile validation is delegated to the existing installation owner.
# Failure: Nonzero exit for unsupported platform/interpreter, missing Git, or invalid selected profile.
from __future__ import annotations
import argparse
import json
from pathlib import Path
import platform
import shutil
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'intelli_bots'))
from bot_general import OutputArgumentParser, add_output_arguments, run_cli, script_interface, write_json_document
from brain_bridge.installation.configuration import load_config
script_interface(__file__,purpose='Validate local Brain-Dump bootstrap prerequisites without changing managed state.',output='json')

def main(argv=None):
    parser=OutputArgumentParser(description=__doc__)
    parser.add_argument('--host',choices=['local'],default='local')
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--plan',action='store_true');action.add_argument('--verify',action='store_true');action.add_argument('--install',action='store_true')
    parser.add_argument('--execute',action='store_true');parser.add_argument('--config')
    add_output_arguments(parser);args=parser.parse_args(argv)
    selected='install' if args.install and args.execute else 'verify' if args.verify else 'plan'
    if args.execute and not args.install:parser.error('--execute requires --install')
    if selected=='plan':
        result={'ok':True,'phase':'000-preflight','action':'plan','executed':False,'effects':[],
                'planned_actions':['Validate supported local platform','Require Python 3.11+ and Git','Validate selected installation profile through the existing owner']}
    else:
        if platform.system() not in ('Darwin','Linux'):raise ValueError('Brain bootstrap currently supports macOS and Linux')
        if sys.version_info < (3,11):raise ValueError('Python 3.11+ is required')
        if shutil.which('git') is None:raise ValueError('Git is required')
        profile=load_config(args.config) if args.config else None
        result={'ok':True,'phase':'000-preflight','action':selected,'executed':False,
                'platform':platform.system().lower(),'python':platform.python_version(),'git':shutil.which('git'),
                'profile_host':profile['host'] if profile else None,'service_changes':False,'production_route_changed':False}
    write_json_document(result,script_path=Path(__file__),pretty=args.pretty);return 0

if __name__=='__main__':raise SystemExit(run_cli(main,script_path=Path(__file__)))
