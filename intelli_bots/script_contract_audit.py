#!/usr/bin/env python3
# script_version: 1.1.1
# Purpose: Inventory every first-party script interface and common-runtime contract without executing it.
# Usage: python3 intelli_bots/script_contract_audit.py --root PATH [--json|--pretty] [--check]
# Output: json
"""Audit every first-party script without executing it. Usage: --root PATH [--root PATH] --json [--pretty] [--check]."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'intelli_bots'))
from bot_general import BotRuntime, script_interface, OutputArgumentParser
script_interface(__file__,purpose='Inventory every first-party script interface and common-runtime contract without executing it.',output='json')
RUNTIME=BotRuntime(Path(__file__))
VERSION='1.1.1'
EXTENSIONS={'.py','.sh','.bash','.zsh','.mjs','.js','.cjs','.pl','.rb','.lua','.awk','.ps1','.inc'}
VERSION_RE=re.compile(r'^(?:#|//|--|;)\s*script_version:\s*(\d+\.\d+\.\d+)\s*$',re.M)


def candidates(root):
    if (root/'.git').exists():
        raw=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root)
        paths=[root/name for name in sorted(set(raw.decode().split('\0'))- {''})]
    else:
        paths=sorted(p for p in root.rglob('*') if p.is_file() and not any(x in p.parts for x in ('__pycache__','.git','node_modules','.venv')))
    for p in paths:
        if p.is_symlink():
            yield p,'symlink_not_followed';continue
        if not p.is_file():continue
        with p.open('rb') as stream:prefix=stream.read(256)
        if p.suffix in EXTENSIONS or prefix.startswith(b'#!'):
            yield p,None


def inspect(path,root,issue=None,_owners=()):
    """Inspect implemented adapters/options and declared roles; never execute source.

    Role classification prevents request-body JSON or test fixtures from being
    mistaken for a CLI output mode. It does not waive required metadata/logging.
    """
    if issue:return {'path':str(path.relative_to(root)),'issues':[issue]}
    raw=path.read_bytes()
    try:s=raw.decode('utf-8')
    except UnicodeDecodeError:return {'path':str(path.relative_to(root)),'issues':['script_not_utf8']}
    lines=s.splitlines();header='\n'.join(lines[:70])
    versions=list(VERSION_RE.finditer('\n'.join(lines[:35])))
    version=versions[0] if len(versions)==1 else None
    declared=re.search(r'^(?:#|//|--) Output: (\w+)',header,re.M)
    role=declared.group(1) if declared else None
    purpose_match=re.search(r'^(?:#|//|--) Purpose: (.+)$',header,re.M)
    purpose=bool(purpose_match and len(purpose_match.group(1).strip())>=15)
    usage=bool(re.search(r'^(?:#|//|--) Usage: .+',header,re.M))
    helper=False;logging_evidence=False;options=set();structured=False;common_writer=False
    tree=None;syntax_error=False;cli_boundary=False
    if path.suffix=='.py' or (lines and 'python' in lines[0]):
        try:tree=ast.parse(s)
        except SyntaxError:syntax_error=True
        if tree is not None:
            doc=ast.get_docstring(tree) or ''
            purpose=purpose or len(doc.split('\n')[0])>=15
            usage=usage or 'Usage:' in doc
            aliases=set();writer_aliases=set();parser_aliases=set();boundary_aliases=set()
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom) and node.module and (node.module=='bot_general' or node.module.endswith('.bot_runtime')):
                    logging_evidence=True
                    aliases.update(n.asname or n.name for n in node.names if n.name=='script_interface')
                    writer_aliases.update(n.asname or n.name for n in node.names if n.name in {'write_json_document','emit_document','run_cli'})
                    parser_aliases.update(n.asname or n.name for n in node.names if n.name=='ContractArgumentParser')
                    boundary_aliases.update(n.asname or n.name for n in node.names if n.name=='run_cli')
            for node in ast.walk(tree):
                if not isinstance(node,ast.Call):continue
                if isinstance(node.func,ast.Name) and node.func.id in aliases:
                    helper=True
                    actual=next((k.value.value for k in node.keywords if k.arg=='output' and isinstance(k.value,ast.Constant) and isinstance(k.value.value,str)),None)
                    if role is None:role=actual
                    elif actual is not None and role!=actual:role='mismatched'
                name=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
                if name in boundary_aliases:cli_boundary=True
                if name=='add_argument':options.update(a.value for a in node.args if isinstance(a,ast.Constant) and isinstance(a.value,str) and a.value.startswith('--'))
                if name=='add_output_arguments' or name in parser_aliases:options.update({'--json','--pretty'})
                if name in {'write_json','write_json_document','emit_json'} or name in writer_aliases:structured=True
                if name in {'write_json','write_json_document'} or name in writer_aliases:common_writer=True
            # Shared runtime implementation is recognized by its implementation,
            # not a filename/path exception.
            if any(isinstance(n,ast.ClassDef) and n.name=='BotRuntime' for n in tree.body):logging_evidence=True
    else:
        helper=bool(re.search(r'(?m)^\s*bot_(?:posix_)?interface\s+',s))
        logging_evidence=bool(re.search(r'(?:source|\.)[^\n]*(?:bot_general|bot_posix)\.inc|^bot_(?:posix_)?log\(\)',s,re.M))
        if helper and 'bot_posix.inc' in s and re.search(r'^\s*\.\s+',s,re.M):logging_evidence=True
        for line in lines:
            if re.match(r'^\s*(?:--[\w-]+)(?:\|[^)]*)?\)',line):options.update(re.findall(r'--[a-z][a-z-]*',line.split(')',1)[0]))
        common_writer=bool(re.search(r'\bbot_json\s+',s))
        structured=common_writer
    if path.suffix in {'.js','.mjs','.cjs'}:
        # A concrete shared adapter call/import is required, never header-only evidence.
        js_adapter=bool(re.search(r'\bscriptInterface\s*\(',s) and
                        ('bot_general.cjs' in s or ('module.exports' in s and 'function scriptInterface' in s)))
        if js_adapter:
            helper=True;logging_evidence=True
            if role=='json':options.update({'--json','--pretty'})
            if re.search(r'\bwriteJson\s*\(',s):structured=True;common_writer=True
    if path.suffix=='.pl' and re.search(r'\bbot_interface\s*\(',s) and ('bot_general.pl' in s or 'sub bot_interface' in s):
        helper=True;logging_evidence=True
    # Native embedded parsers delegate diagnostics to their actual common-runtime owner.
    # Validate both the declared owner and a real backlink, without a path allowlist.
    logging_owner=re.search(r'^(?:#|//|--) Logging-Owner: (\S+)$',header,re.M)
    if logging_owner:
        owner_path=(root/logging_owner[1]).resolve()
        if owner_path.is_relative_to(root.resolve()) and owner_path.is_file():
            owner_source=owner_path.read_text()
            if path.name in owner_source and 'bot_general.inc' in owner_source:
                logging_evidence=True
    if path.suffix in {'.awk','.lua'}:
        # These are actual argv branches before the existing parser/callback work.
        if '--help' in s and '--version' in s and ('ARGV[' in s or 'arg[' in s):
            options.update({'--help','--version'})
    # Unmodified callers remain reportable while migration is underway.
    doc_help=bool(re.search(r'ArgumentParser\(|argparse\.|unittest\.main\(|GetOptions\(',s))
    help_found=helper or '--help' in options or usage or doc_help
    version_option=helper or '--version' in options or bool(re.search(r'^\s*--version\)',s,re.M))
    json_interface='--json' in options
    pretty_interface='--pretty' in options
    info_evidence=common_writer or bool(re.search(r'[\"\']info[\"\']\s*:',s))
    owner_error=None
    owner=re.search(r'^# Output-Owner: ([^\s:]+)(?::([A-Za-z_]\w*))?$',header,re.M)
    if owner:
        target=(root/owner.group(1)).resolve()
        function=owner.group(2)
        if not target.is_relative_to(root.resolve()) or not target.is_file() or target in _owners:
            owner_error='invalid_or_cyclic_output_owner'
        else:
            backend=target.read_text()
            wired=(function is not None and re.search(r'\b'+re.escape(function)+r'\s+["\']?\$@',s) and re.search(r'^'+re.escape(function)+r'\(\)',backend,re.M)) or (function is None and (owner.group(1) in s) and ('exec ' in s or 'runpy.run_path' in s))
            if not wired:owner_error='output_owner_not_wired'
            else:
                inherited=inspect(target,root,_owners=(*_owners,path.resolve()))
                json_interface=inherited['json_option'];pretty_interface=inherited['pretty_option']
                info_evidence=inherited['json_info_source_evidence']
    issues=[]
    if owner_error:issues.append(owner_error)
    if syntax_error:issues.append('invalid_python_syntax')
    if not logging_evidence:issues.append('common_logging_requires_verification')
    if not purpose:issues.append('missing_purpose_header')
    if not usage:issues.append('missing_usage_contract')
    if not version:issues.append('missing_or_duplicate_script_version')
    if not help_found:issues.append('missing_help_evidence')
    if not version_option:issues.append('missing_version_option_evidence')
    allowed={'test','library','text','json','jsonl','protocol','service','wrapper','artifact'}
    if role not in allowed:issues.append('missing_or_invalid_output_contract')
    if role in {'json','jsonl'}:
        if tree is not None and not cli_boundary:issues.append('json_without_common_cli_boundary')
        if not json_interface:issues.append('missing_json_output_option')
        if not pretty_interface:issues.append('json_without_pretty')
        if not info_evidence:issues.append('json_info_requires_verification')
    elif structured and role is None:issues.append('structured_output_role_requires_review')
    return {'path':str(path.relative_to(root)),'sha256':hashlib.sha256(raw).hexdigest(),
            'script_version':version.group(1) if version else None,'output_contract':role,
            'common_interface_helper':helper,'common_cli_boundary':cli_boundary,'header_evidence':purpose,'usage_evidence':usage,
            'common_logging_evidence':logging_evidence,'help_evidence':help_found,
            'version_option_evidence':version_option,'json_option':json_interface,
            'structured_output_evidence':structured,'pretty_option':pretty_interface,
            'json_info_source_evidence':info_evidence,'issues':issues}


def audit(roots):
    inventories=[];runtime_hashes={}
    for candidate in roots:
        candidate=Path(candidate).expanduser().resolve()
        for directory in ('intelli_bots','bots'):
            for name in ('bot_general.py','bot_general.inc','bot_posix.inc','bot_general.cjs'):
                source=candidate/directory/name
                if name not in runtime_hashes and source.is_file() and not source.is_symlink():
                    runtime_hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    for root in roots:
        root=Path(root).expanduser().resolve()
        if not root.is_dir():raise ValueError('Missing audit root: '+str(root))
        rows=[inspect(p,root,issue) for p,issue in candidates(root)]
        for row in rows:
            expected=runtime_hashes.get(Path(row['path']).name)
            if expected and row.get('sha256') and row['sha256']!=expected:
                row['issues'].append('common_runtime_copy_drift')
        inventories.append({'root':str(root),'scripts':rows})
    rows=[row for inventory in inventories for row in inventory['scripts']]
    counts={}
    for row in rows:
        for issue in row['issues']:counts[issue]=counts.get(issue,0)+1
    return {'info':{'script':'script_contract_audit.py','script_version':VERSION,'method':'source-only; no script execution; evidence is not proof of working help/version/JSON','exemptions':[],'common_runtime_sha256':runtime_hashes},'summary':{'scripts':len(rows),'with_findings':sum(bool(row['issues']) for row in rows),'findings_by_kind':counts},'inventories':inventories}


def main(argv=None):
    parser=OutputArgumentParser(description=__doc__,script_path=__file__)
    parser.add_argument('--root',action='append',required=True,help='Repository or first-party script directory; repeat for multiple roots')
    parser.add_argument('--json',action='store_true',help='Emit JSON including info.script_version')
    parser.add_argument('--pretty',action='store_true',help='Indent JSON; implies --json')
    parser.add_argument('--check',action='store_true',help='Fail if any script has a finding; no exemptions')
    parser.add_argument('--version',action='version',version='%(prog)s '+VERSION)
    args=parser.parse_args(argv)
    try:
        report=audit(args.root)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        report={'info':{'script':'script_contract_audit.py','script_version':VERSION},'error':str(error)}
        print(json.dumps(report,indent=2 if args.pretty else None) if args.json or args.pretty else str(error));return 2
    if args.json or args.pretty:print(json.dumps(report,indent=2 if args.pretty else None,sort_keys=True))
    else:
        print(json.dumps(report['summary'],indent=2))
        for inventory in report['inventories']:
            for row in inventory['scripts']:
                if row['issues']:print(inventory['root']+'/'+row['path']+': '+', '.join(row['issues']))
    return 1 if args.check and report['summary']['with_findings'] else 0


if __name__ == '__main__':
    from bot_general import run_cli as _contract_run_cli
    def _contract_entry():
        raise SystemExit(main())
    raise SystemExit(_contract_run_cli(_contract_entry,script_path=__file__,argv=None))
