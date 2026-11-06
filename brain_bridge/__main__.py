# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Brain Bridge CLI: explicit local utilities and authenticated managed sources."""
import argparse
import json
import sys
import sqlite3
import subprocess
from .store import rebuild, search
from .sync import sync
from .authority import initialize_identity
from .publication import propose_record
from .connectors import observe_named
from .github import collect_named
from .synapse import synapse_request
from .skill import bundled_skill
from .adapters import managed_create, managed_export, managed_latest, managed_status
from .migration import plan_migration,apply_migration
from .historical_import import plan_import
from .reconciliation import poll_reconciliation
from .rollback import plan_rollback_audit
from .validation import validate_source
from .managed import managed_search, managed_index, managed_sync, managed_graph

from . import __version__ as VERSION

def parser():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--version',action='version',version='brain-bridge '+VERSION)
    cli.add_argument('--license',action='version',help='Show copyright, license and warranty notice',version='Copyright (C) 2026 Creative Software Development. AGPL-3.0-only; no warranty. See LICENSE and NOTICE, https://www.gnu.org/licenses/agpl-3.0.html')
    sub=cli.add_subparsers(dest='action',required=True)
    sub.add_parser('skill',help='Locate and read the bundled consult skill; never install globally or grant access')
    validation=sub.add_parser('validate-source',help='Local CI: require strict v3 additions and immutable published ledger bytes')
    validation.add_argument('--repo',required=True);validation.add_argument('--base-ref',required=True);validation.add_argument('--ref',default='HEAD')
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
    for name in ('create', 'latest', 'export', 'status'):
        adapter=sub.add_parser(name,help='Named-source managed '+name+' adapter; never switch production or merge')
        adapter.add_argument('--identity-repo',required=True);adapter.add_argument('--repo',required=True)
        adapter.add_argument('--source',required=True)
        if name=='create':
            adapter.add_argument('--entry',required=True,help='Complete authored entry JSON with stable UUIDv4 and timestamp')
            adapter.add_argument('--output',required=True,help='Draft file outside identity/source checkouts; never overwritten')
            adapter.add_argument('--execute',action='store_true');adapter.add_argument('--yes',action='store_true')
        elif name=='status':adapter.add_argument('--cache-dir',required=True)
    consult=sub.add_parser('synapse',help='Consult a named authorized Brain source and return bounded cited references')
    consult.add_argument('--identity-repo',required=True);consult.add_argument('--repo',required=True)
    consult.add_argument('--source',required=True);consult.add_argument('--term',required=True);consult.add_argument('--cache-dir',required=True)
    consult.add_argument('--backend',choices=['json','sqlite','auto'],default='auto')
    consult.add_argument('--limit',type=int,default=20);consult.add_argument('--excerpt-chars',type=int,default=240)
    migration=sub.add_parser('migrate-plan',help='Inventory a private byte-preserving rehearsal; never switch production')
    migration.add_argument('--source-repo',required=True);migration.add_argument('--destination-repo',required=True);migration.add_argument('--source-id',required=True);migration.add_argument('--destination-id',required=True)
    migration.add_argument('--source-ref',default='main');migration.add_argument('--destination-ref',default='main');migration.add_argument('--namespace',choices=['Brain-Bridge','records'],default='Brain-Bridge')
    historical=sub.add_parser('import-plan',help='Propose authenticated exact historical import authorization; never copy, push or grant')
    historical.add_argument('--source-repo',required=True);historical.add_argument('--destination-repo',required=True)
    historical.add_argument('--source-id',required=True);historical.add_argument('--destination-id',required=True)
    historical.add_argument('--source-ref',default='main');historical.add_argument('--destination-ref',default='main')
    historical.add_argument('--namespace',choices=['Brain-Bridge','records'],default='Brain-Bridge')
    reconciliation=sub.add_parser('reconcile',help='Observe historical catch-up; one-shot JSON or bounded JSONL polling, never copy or authorize')
    for name in ('source-repo','destination-repo','source-id','destination-id'):
        reconciliation.add_argument('--'+name,required=True)
    reconciliation.add_argument('--source-ref',default='main');reconciliation.add_argument('--destination-ref',default='main')
    reconciliation.add_argument('--namespace',choices=['Brain-Bridge','records'],default='Brain-Bridge')
    reconciliation.add_argument('--state-dir',help='Optional external private metadata checkpoint; no source record content')
    reconciliation.add_argument('--execute',action='store_true',help='Write checkpoint metadata only; requires --state-dir and --yes')
    reconciliation.add_argument('--yes',action='store_true')
    reconciliation.add_argument('--refresh',action='store_true',help='Explicitly fetch/validate/fast-forward the two selected clean readers; requires --execute --yes and --state-dir')
    reconciliation.add_argument('--cycles',type=int,default=1,help='1–1000 cycles; more than1 explicitly emits JSONL')
    reconciliation.add_argument('--interval',type=float,default=60,help='Polling interval seconds, default60; no scheduler is installed')
    audit=sub.add_parser('rollback-audit',help='Read immutable rollback evidence; never change routing or grants')
    for name in ('source-repo','destination-repo','source-id','destination-id','source-ref','destination-ref'):
        audit.add_argument('--'+name,required=True)
    apply=sub.add_parser('migrate-apply',help='Apply an exact reviewed plan to a private working copy only')
    apply.add_argument('--source-repo',required=True);apply.add_argument('--destination-repo',required=True);apply.add_argument('--plan',required=True);apply.add_argument('--execute',action='store_true');apply.add_argument('--yes',action='store_true')
    graph=sub.add_parser('graph',help='Generate authorized record/evidence graphs as JSON, DOT or Mermaid')
    graph.add_argument('--identity-repo',required=True);graph.add_argument('--repo',required=True);graph.add_argument('--format',choices=['json','dot','mermaid'],default='json')
    observation=sub.add_parser('observe',help='Read one run from a committed named CI connector; never trigger jobs')
    observation.add_argument('--identity-repo',required=True);observation.add_argument('--connector',required=True);observation.add_argument('--run-id',required=True)
    collection=sub.add_parser('collect',help='Read one selected GitHub object from a reviewed named connector; never update tasks')
    collection.add_argument('--identity-repo',required=True);collection.add_argument('--connector',required=True)
    collection.add_argument('--kind',choices=['issue','pull_request','commit','run'],required=True)
    collection.add_argument('--id',required=True);collection.add_argument('--include-body',action='store_true',help='Explicitly include untrusted issue/PR body or commit message')
    publication=sub.add_parser('publish',help='Plan an append-only private-source record PR; never merge or push main')
    publication.add_argument('--identity-repo',required=True);publication.add_argument('--repo',required=True);publication.add_argument('--record',required=True)
    publication.add_argument('--execute','--push',dest='execute',action='store_true',help='Push one verified immutable record branch and propose a PR; requires --yes, never merges')
    publication.add_argument('--yes',action='store_true')
    for command in sub.choices.values():
        command.add_argument('--json',action='store_true',help='Emit JSON (the default)')
        command.add_argument('--pretty',action='store_true',help='Indent the same JSON document')
    return cli

def runtime_info():
    return {'script':'brain_bridge','script_version':VERSION,'license':'AGPL-3.0-only','copyright':'2026 Creative Software Development'}

def main(argv=None):
    cli=parser();args=cli.parse_args(argv)
    if args.action=='reconcile' and args.cycles != 1 and args.pretty:
        cli.error('--pretty is supported only for one-shot reconciliation; polling emits JSONL')
    try:
        if args.action=='reconcile':
            for receipt in poll_reconciliation(args.source_repo,args.destination_repo,args.source_id,args.destination_id,
                    args.source_ref,args.destination_ref,args.namespace,args.state_dir,args.execute,args.yes,
                    cycles=args.cycles,interval=args.interval,refresh=args.refresh):
                receipt['info']=runtime_info()
                print(json.dumps(receipt,ensure_ascii=False,indent=2 if args.pretty else None),flush=True)
            return 0
        if args.action=='skill':result=bundled_skill()
        elif args.action=='validate-source':result=validate_source(args.repo,args.base_ref,args.ref)
        elif args.action=='create':result=managed_create(args.identity_repo,args.repo,args.source,args.entry,args.output,args.execute,args.yes)
        elif args.action=='export':result=managed_export(args.identity_repo,args.repo,args.source)
        elif args.action=='latest':result=managed_latest(args.identity_repo,args.repo,args.source)
        elif args.action=='status':result=managed_status(args.identity_repo,args.repo,args.source,args.cache_dir)
        elif args.action=='synapse':result=synapse_request(args.identity_repo,args.repo,args.source,args.term,args.cache_dir,args.backend,args.limit,args.excerpt_chars)
        elif args.action=='import-plan':result=plan_import(args.source_repo,args.destination_repo,args.source_id,args.destination_id,args.source_ref,args.destination_ref,args.namespace)
        elif args.action=='rollback-audit':result=plan_rollback_audit(args.source_repo,args.destination_repo,args.source_id,args.destination_id,args.source_ref,args.destination_ref)
        elif args.action=='migrate-plan':result={'plan':plan_migration(args.source_repo,args.destination_repo,args.source_id,args.destination_id,args.source_ref,args.destination_ref,args.namespace)}
        elif args.action=='migrate-apply':
            with open(args.plan) as file:plan=json.load(file)
            result=apply_migration(args.source_repo,args.destination_repo,plan,args.execute,args.yes)
        elif args.action=='graph':result=managed_graph(args.identity_repo,args.repo,args.format)
        elif args.action=='collect':result=collect_named(args.identity_repo,args.connector,args.kind,args.id,include_body=args.include_body)
        elif args.action=='observe':result=observe_named(args.identity_repo,args.connector,args.run_id)
        elif args.action=='publish':result=propose_record(args.identity_repo,args.repo,args.record,args.execute,args.yes)
        elif args.action=='identity':result=initialize_identity(args.repo,args.execute)
        elif args.action=='managed-search':result=managed_search(args.identity_repo,args.repo,args.term,args.cache_dir,args.backend)
        elif args.action=='managed-index':result=managed_index(args.identity_repo,args.repo,args.cache_dir)
        elif args.action=='managed-sync':result=managed_sync(args.identity_repo,args.repo,args.cache_dir)
        elif args.action=='index':result={'indexed':rebuild(args.root,args.db,args.contract)}
        elif args.action=='sync':result=sync(args.repo,args.remote,args.branch,args.records,args.db,args.contract)
        else:result={'results':search(args.root,args.term,args.backend,args.db)}
        result['info']=runtime_info()
        print(json.dumps(result,ensure_ascii=False,indent=2 if args.pretty else None));return 1 if args.action=='synapse' and result['status'] not in ('found','no_match') else 0
    except (ValueError,RuntimeError,OSError,sqlite3.Error,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error':'Operation timed out; no result reported' if isinstance(exc,subprocess.TimeoutExpired) else str(exc),'info':runtime_info()}));return 1

if __name__=='__main__':raise SystemExit(main())
