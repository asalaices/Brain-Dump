"""Brain Bridge CLI: explicit local utilities and authenticated managed sources."""
import argparse
import json
import sys
from .store import rebuild, search
from .sync import sync
from .authority import initialize_identity
from .managed import managed_search, managed_index, managed_sync

VERSION = '0.2.0'

def parser():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--version',action='version',version='brain-bridge '+VERSION)
    sub=cli.add_subparsers(dest='action',required=True)
    s=sub.add_parser('search',help='Local authorized JSON utility; no managed access enforcement')
    s.add_argument('--root',required=True);s.add_argument('--term',required=True)
    s.add_argument('--backend',choices=['json','sqlite','auto'],default='auto');s.add_argument('--db')
    i=sub.add_parser('index',help='Rebuild a local derived index after whole-batch validation')
    i.add_argument('--root',required=True);i.add_argument('--db',required=True);i.add_argument('--contract',choices=['v3','history'])
    g=sub.add_parser('sync',help='Explicit clean-checkout, fast-forward Git sync')
    g.add_argument('--repo',required=True);g.add_argument('--remote',required=True);g.add_argument('--branch',default='main')
    g.add_argument('--records',default='records');g.add_argument('--db',required=True);g.add_argument('--contract',choices=['v3','history'])
    identity=sub.add_parser('identity',help='Plan or initialize a verified repository identity; never grants access')
    identity.add_argument('--repo',required=True);identity.add_argument('--execute',action='store_true')
    for name in ['managed-search','managed-index','managed-sync']:
        command=sub.add_parser(name,help='Refresh authenticated upstream policy before managed source access')
        command.add_argument('--identity-repo',required=True);command.add_argument('--repo',required=True);command.add_argument('--cache-dir',required=True)
        if name=='managed-search':
            command.add_argument('--term',required=True);command.add_argument('--backend',choices=['json','sqlite','auto'],default='auto')
    for command in sub.choices.values():
        command.add_argument('--json',action='store_true',help='Emit JSON (the default)')
        command.add_argument('--pretty',action='store_true',help='Indent the same JSON document')
    return cli

def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.action=='identity':result=initialize_identity(args.repo,args.execute)
        elif args.action=='managed-search':result=managed_search(args.identity_repo,args.repo,args.term,args.cache_dir,args.backend)
        elif args.action=='managed-index':result=managed_index(args.identity_repo,args.repo,args.cache_dir)
        elif args.action=='managed-sync':result=managed_sync(args.identity_repo,args.repo,args.cache_dir)
        elif args.action=='index':result={'indexed':rebuild(args.root,args.db,args.contract)}
        elif args.action=='sync':result=sync(args.repo,args.remote,args.branch,args.records,args.db,args.contract)
        else:result={'results':search(args.root,args.term,args.backend,args.db)}
        result['info']={'script':'brain_bridge','script_version':VERSION}
        print(json.dumps(result,ensure_ascii=False,indent=2 if args.pretty else None));return 0
    except (ValueError,RuntimeError,OSError) as exc:
        print(json.dumps({'error':str(exc),'info':{'script':'brain_bridge','script_version':VERSION}}));return 1

if __name__=='__main__':raise SystemExit(main())
