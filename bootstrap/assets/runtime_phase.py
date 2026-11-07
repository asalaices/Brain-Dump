#!/usr/bin/env python3
# script_version: 1.0.0
# Purpose: Route pinned Brain runtime plan, verification, and installation through numbered bootstrap phase 100.
# Usage: python3 bootstrap/assets/runtime_phase.py --host local --config PROFILE [--plan|--verify|--install --execute] [--json|--pretty]
# Output: json
# Prerequisites: Successful phase 000 and a reviewed schema-2 runtime profile.
# Failure: Existing installation dispatch errors are preserved; no service, grant, route, or tunnel mutation is added.
from __future__ import annotations
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'intelli_bots'))
from bot_general import OutputArgumentParser, add_output_arguments, run_cli, script_interface, write_json_document
from brain_bridge.installation import dispatch
script_interface(__file__,purpose='Route pinned Brain runtime lifecycle through numbered bootstrap phase 100.',output='json')

def main(argv=None):
    parser=OutputArgumentParser(description=__doc__)
    parser.add_argument('--host',choices=['local'],default='local');parser.add_argument('--config',required=True)
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--plan',action='store_true');action.add_argument('--verify',action='store_true');action.add_argument('--install',action='store_true')
    parser.add_argument('--execute',action='store_true');add_output_arguments(parser);args=parser.parse_args(argv)
    if args.execute and not args.install:parser.error('--execute requires --install')
    selected='install' if args.install and args.execute else 'verify' if args.verify else 'plan'
    result=dispatch(args.config,selected,execute=selected=='install',yes=selected=='install')
    result={'phase':'100-runtime','bootstrap_owner':'bootstrap/bootstrap.sh',**result}
    write_json_document(result,script_path=Path(__file__),pretty=args.pretty);return 0

if __name__=='__main__':raise SystemExit(run_cli(main,script_path=Path(__file__)))
