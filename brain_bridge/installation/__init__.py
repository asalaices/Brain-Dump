# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Pinned runtime lifecycle, extracted from the registered installation owner.

No project imports, credentials, grants, route changes or service installation.
"""
from pathlib import Path
from .discovery import reconcile_skill
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import tarfile
import uuid


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command,timeout=180,env=None):
    result=subprocess.run([str(x) for x in command],capture_output=True,text=True,timeout=timeout,env=env)
    if result.returncode:raise ValueError('Brain runtime operation failed: '+Path(str(command[0])).name)
    return result.stdout.strip()


def plan(c):
    return {'ok':True,'host':c['host'],'operation':c.get('operation','brain-bridge-runtime'),'action':'plan','effects':[],
            'framework_commit':c['framework_commit'],'framework_version':c['framework_version'],
            'planned_actions':['Validate clean pinned framework and owner Python','Build pinned package into a versioned environment and record wheel hash','Verify CLI and bundled skill before activation','Preserve known legacy environment and identical copied Codex skill','Activate stable environment/launcher and Git-owned discovery through packaged ownership checks','Verify and write private ownership receipt; roll back activation on failure'],
            'preserved':['consultation configuration','reader and cache','trust grants','Copilot legacy discovery','publishing routes'],
            'service_changes':False,'production_route_changed':False}


def safe(path,allow_link=False):
    path=Path(path)
    for item in (path,*path.parents):
        if item.is_symlink() and not (item==path and allow_link):raise ValueError('Symlinked Brain owner path refused: '+str(item))
    if path.exists() and hasattr(os,'getuid') and path.stat().st_uid!=os.getuid():raise ValueError('Brain owner path belongs to another user')


def paths(c):
    base=Path(c['runtime_dir']);source=Path(c['source_repo'])
    return base,source,base/'environments'/(c['framework_commit']+'-py'+c['python_version']),Path(c['skill_home'])/'brain-bridge',source/c['skill']


def source_state(c):
    _,source,_,_,skill=paths(c)
    if run(['git','-C',source,'rev-parse','--show-toplevel'])!=str(source.resolve()):raise ValueError('Framework source must be a Git checkout root')
    if run(['git','-C',source,'status','--porcelain','--untracked-files=all']):raise ValueError('Framework source is not the exact clean release')
    # Build code is always archived from the reviewed immutable pin, never HEAD.
    # Unrelated clean development commits must not invalidate an installed CLI.
    try:
        pin=run(['git','-C',source,'rev-parse',c['framework_commit']+'^{commit}'])
        if pin!=c['framework_commit']:raise ValueError('Release pin differs')
        run(['git','-C',source,'merge-base','--is-ancestor',pin,'HEAD'])
    except ValueError as exc:
        raise ValueError('Pinned framework release is unavailable or outside source history') from exc
    # Discovery is a live Git-owned link: its whole tracked tree must still be
    # exactly the reviewed skill, including file modes and all references.
    current=run(['git','-C',source,'rev-parse','HEAD:'+c['skill']])
    reviewed=run(['git','-C',source,'rev-parse',pin+':'+c['skill']])
    if current!=reviewed:raise ValueError('Git-owned Brain skill differs from the reviewed release')
    for relative in ('SKILL.md','README.md','install.sh','references/agent-adapters.md'):
        path=skill/relative;safe(path)
        if not path.is_file():raise ValueError('Incomplete Git-owned skill package')
        run(['git','-C',source,'ls-files','--error-unmatch','--',str(path.relative_to(source))])
    return source,skill


def skill_state(c):
    _,_,_,target,source=paths(c);safe(target,allow_link=True)
    if target.is_symlink():
        if os.readlink(target)!=str(source):raise ValueError('Codex skill belongs to a different source')
        return 'linked'
    if not target.exists():return 'missing'
    if not target.is_dir() or not c['legacy_skill_sha256']:raise ValueError('Conflicting skill directory or file')
    actual=set()
    for file in target.rglob('*'):
        if file.is_symlink():raise ValueError('Copied skill contains symlinks')
        if file.is_file():actual.add(file.relative_to(target).as_posix())
        elif not file.is_dir():raise ValueError('Copied skill contains unsupported objects')
    if actual!=set(c['legacy_skill_sha256']) or any(digest(target/name)!=sha for name,sha in c['legacy_skill_sha256'].items()):raise ValueError('Codex copied skill differs from reviewed migration pins')
    return 'legacy_copy'


def installed_version(environment):
    return run([Path(environment)/'bin/python','-I','-c','import importlib.metadata as m; print(m.version("brain-bridge-framework"))'])


def owned_managed_environment(base,target):
    target=Path(target)
    if not target.is_absolute() or target.parent!=base/'environments':raise ValueError('Stable environment belongs to another owner')
    safe(target)
    marker=target/'.brain-bridge-environment.json';receipt=base/'install-receipt.json'
    for path in (marker,receipt):
        safe(path)
        if not path.is_file() or path.stat().st_size>65536:raise ValueError('Managed environment ownership receipt missing')
    env=json.loads(marker.read_text());owner=json.loads(receipt.read_text())
    if not isinstance(env,dict) or not isinstance(owner,dict) or owner.get('environment')!=str(target) or owner.get('framework_commit')!=env.get('source_commit') or owner.get('framework_version')!=env.get('version') or owner.get('wheel_sha256')!=env.get('wheel_sha256') or installed_version(target)!=env.get('version'):raise ValueError('Managed environment ownership differs')
    return env


def environment_state(c):
    base,_,desired,_,_=paths(c);active=base/'venv';safe(active,allow_link=True)
    if active.is_symlink():
        target=Path(os.readlink(active))
        if target==desired:return 'linked'
        owned_managed_environment(base,target)
        return 'managed_link'
    if not active.exists():return 'missing'
    if c['legacy_version'] is None or not active.is_dir() or installed_version(active)!=c['legacy_version']:raise ValueError('Unknown existing Brain environment')
    return 'legacy_directory'


def install_receipt(base,c):
    path=Path(base)/'install-receipt.json'
    if not path.exists() and not path.is_symlink():return {}
    safe(path)
    if not path.is_file() or path.stat().st_size>65536:raise ValueError('Invalid existing install receipt')
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or value.get('schema_version')!=1 or value.get('operation')!=c.get('operation','brain-bridge-runtime') or value.get('host')!=c['host'] or not re.fullmatch('[0-9a-f]{40}',str(value.get('framework_commit',''))) or not re.fullmatch('[0-9a-f]{64}',str(value.get('wheel_sha256',''))):raise ValueError('Existing install receipt belongs to another owner')
    return value


def preflight(root,c,install=False):
    if platform.system() not in ('Darwin','Linux'):raise ValueError('Runtime activation currently supports macOS and Linux; Windows toolchain activation is not implemented')
    base,source,desired,target,skill=paths(c)
    for path in (base,base/'environments',base/'backups',desired,Path(c['launcher']).parent,Path(c['skill_home'])):safe(path)
    source_state(c)
    install_receipt(base,c)
    if run([c['python'],'--version'])!='Python '+c['python_version']:raise ValueError('Owner Python version mismatch')
    launcher=Path(c['launcher']);safe(launcher,allow_link=True)
    if launcher.is_symlink() and os.readlink(launcher)!=str(base/'venv/bin/brain-bridge'):raise ValueError('Launcher belongs to another owner')
    if launcher.exists() and not launcher.is_symlink():raise ValueError('Refusing non-owned launcher')
    return {'ok':True,'environment':environment_state(c),'skill':skill_state(c),'install':bool(install)}


def environment_receipt(c,environment):
    path=Path(environment)/'.brain-bridge-environment.json'
    if not path.is_file() or path.is_symlink():raise ValueError('Versioned environment has no ownership receipt')
    value=json.loads(path.read_text())
    if set(value)!={'schema_version','source_commit','version','python_version','wheel_sha256'} or value['schema_version']!=1 or value['source_commit']!=c['framework_commit'] or value['version']!=c['framework_version'] or value['python_version']!=c['python_version'] or not re.fullmatch('[0-9a-f]{64}',value['wheel_sha256']):raise ValueError('Versioned environment ownership differs')
    if installed_version(environment)!=c['framework_version']:raise ValueError('Installed package version differs')
    return value


def private_json(path,value):
    path=Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent,mode='w',delete=False,prefix='.brain-receipt-') as stream:
        temporary=Path(stream.name);os.chmod(temporary,0o600);json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def ensure_environment(c):
    base,source,desired,_,_=paths(c)
    if desired.exists():return environment_receipt(c,desired),False
    desired.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    desired.mkdir(mode=0o700)
    try:
        run([c['python'],'-m','venv',desired],timeout=180)
        python=desired/'bin/python'
        if c.get('wheel'):
            wheel=Path(c['wheel'])
            if digest(wheel)!=c['wheel_sha256']:raise ValueError('Offline wheel checksum differs')
            wheel_hash=digest(wheel)
            run([python,'-m','pip','install','--disable-pip-version-check','--no-input','--no-index','--no-deps',wheel],timeout=180)
        else:
            run([python,'-m','pip','install','--disable-pip-version-check','--no-input','setuptools=='+c['setuptools_version']],timeout=600)
            with tempfile.TemporaryDirectory(dir=base,prefix='.brain-wheel-') as temporary:
                archive=Path(temporary)/'source.tar';tree=Path(temporary)/'source';tree.mkdir()
                run(['git','-C',source,'archive','--format=tar','--output='+str(archive),c['framework_commit']])
                with tarfile.open(archive) as bundle:
                    members=bundle.getmembers()
                    if any(not (m.isfile() or m.isdir()) or Path(m.name).is_absolute() or '..' in Path(m.name).parts for m in members):raise ValueError('Unsupported release archive content')
                    bundle.extractall(tree,members=members,filter='data')
                run([python,'-m','pip','wheel','--disable-pip-version-check','--no-input','--no-build-isolation','--no-deps','--wheel-dir',temporary,tree],timeout=600)
                wheels=list(Path(temporary).glob('brain_bridge_framework-*.whl'))
                if len(wheels)!=1:raise ValueError('Expected one framework wheel')
                wheel_hash=digest(wheels[0]);run([python,'-m','pip','install','--disable-pip-version-check','--no-input','--no-deps',wheels[0]],timeout=180)
        if installed_version(desired)!=c['framework_version']:raise ValueError('Built package version mismatch')
        if run([desired/'bin/brain-bridge','--version'])!='brain-bridge '+c['framework_version']:raise ValueError('Built launcher version mismatch')
        bundled=json.loads(run([desired/'bin/brain-bridge','skill','--json']))
        if bundled.get('activates_sources') is not False:raise ValueError('Bundled skill unexpectedly configures sources')
        value={'schema_version':1,'source_commit':c['framework_commit'],'version':c['framework_version'],'python_version':c['python_version'],'wheel_sha256':wheel_hash}
        private_json(desired/'.brain-bridge-environment.json',value)
        return value,True
    except Exception:
        shutil.rmtree(desired)
        raise


def atomic_link(path,target):
    path=Path(path);temporary=path.parent/('.brain-link-'+uuid.uuid4().hex)
    try:temporary.symlink_to(target);os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def verify(root,c):
    preflight(root,c)
    base,_,desired,target,source=paths(c)
    if not (base/'venv').is_symlink() or (base/'venv').resolve()!=desired:raise ValueError('Stable runtime is not the pinned environment')
    if not Path(c['launcher']).is_symlink() or os.readlink(c['launcher'])!=str(base/'venv/bin/brain-bridge'):raise ValueError('Stable CLI launcher missing')
    if skill_state(c)!='linked':raise ValueError('Git-owned Codex discovery not installed')
    value=environment_receipt(c,desired)
    if run([c['launcher'],'--version'])!='brain-bridge '+c['framework_version']:raise ValueError('Active CLI version mismatch')
    return {'ok':True,'host':c['host'],'operation':c.get('operation','brain-bridge-runtime'),'action':'verify','framework_commit':c['framework_commit'],'framework_version':c['framework_version'],'environment':str(desired),'skill_target':str(source),'wheel_sha256':value['wheel_sha256'],'production_route_changed':False,'service_changes':False}


def install(root,c):
    before=preflight(root,c,install=True)
    base,_,desired,target,source=paths(c);active=base/'venv';launcher=Path(c['launcher'])
    base.mkdir(mode=0o700,parents=True,exist_ok=True)
    value,created=ensure_environment(c)
    backups=base/'backups';backups.mkdir(mode=0o700,exist_ok=True);backups.chmod(0o700)
    env_backup=None;skill_backup=None
    previous_receipt=install_receipt(base,c)
    old_active=os.readlink(active) if active.is_symlink() else None
    old_launcher=os.readlink(launcher) if launcher.is_symlink() else None
    changed_active=False;changed_launcher=False;changed_skill=False
    try:
        # Recheck all ownership after potentially slow builds, before activation.
        current=preflight(root,c,install=True)
        if current!=before:raise ValueError('Runtime or skill ownership changed during build')
        if before['environment']=='legacy_directory':
            env_backup=backups/('venv-'+c['legacy_version']+'-'+uuid.uuid4().hex);active.rename(env_backup)
        if not active.is_symlink() or Path(os.readlink(active))!=desired:atomic_link(active,desired);changed_active=True
        launcher.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if not launcher.is_symlink():atomic_link(launcher,str(base/'venv/bin/brain-bridge'));changed_launcher=True
        if before['skill']=='legacy_copy':
            skill_backup=backups/('codex-brain-bridge-'+uuid.uuid4().hex);target.rename(skill_backup)
        if before['skill']!='linked':
            changed_skill=True
            reconcile_skill(source,c['skill_home'],'install',execute=True,yes=True)
        result=verify(root,c)
        receipt={**result,'schema_version':1,'python_version':c['python_version'],'previous_environment':before['environment'],'previous_skill':before['skill'],'legacy_environment_backup':str(env_backup) if env_backup else previous_receipt.get('legacy_environment_backup'),'legacy_skill_backup':str(skill_backup) if skill_backup else previous_receipt.get('legacy_skill_backup'),'launcher':str(launcher)}
        receipt['activation']={
            'environment':{
                'path':str(active),
                'before':{
                    'state':before['environment'],
                    'target':old_active if old_active is not None else (str(active) if before['environment']=='legacy_directory' else None),
                    'source_commit':previous_receipt.get('framework_commit') if old_active is not None else None,
                    'version':previous_receipt.get('framework_version') if old_active is not None else (c['legacy_version'] if before['environment']=='legacy_directory' else None)},
                'after':{'target':str(desired),'source_commit':c['framework_commit'],'version':c['framework_version']},
                'legacy_backup':receipt['legacy_environment_backup']},
            'launcher':{'path':str(launcher),'before_target':old_launcher,'after_target':str(base/'venv/bin/brain-bridge')}}
        private_json(base/'install-receipt.json',receipt)
        return {**result,'action':'install','changed':created or changed_active or changed_launcher or changed_skill,'receipt':str(base/'install-receipt.json')}
    except Exception:
        if changed_skill and target.is_symlink() and os.readlink(target)==str(source):target.unlink()
        if skill_backup is not None and not target.exists() and not target.is_symlink():skill_backup.rename(target)
        if changed_launcher and launcher.is_symlink():launcher.unlink()
        if old_launcher is not None and not launcher.exists() and not launcher.is_symlink():launcher.symlink_to(old_launcher)
        if changed_active and active.is_symlink():active.unlink()
        if env_backup is not None and not active.exists() and not active.is_symlink():env_backup.rename(active)
        elif old_active is not None and not active.exists() and not active.is_symlink():active.symlink_to(old_active)
        if created and desired.exists() and not (active.is_symlink() and active.resolve()==desired):shutil.rmtree(desired)
        raise


def dispatch(config_path,operation='plan',execute=False,yes=False):
    from .configuration import load_config,installation_lock
    c=load_config(config_path)
    if operation not in ('plan','preflight','install','verify'):raise ValueError('Unknown installation operation')
    if operation!='install' and (execute or yes):raise ValueError('Only install accepts execution flags')
    if yes and not execute:raise ValueError('--yes requires --execute')
    if operation=='plan' or (operation=='install' and not execute):return plan(c)
    if operation=='preflight':return preflight(None,c)
    if operation=='verify':return verify(None,c)
    if not yes:raise ValueError('Installation requires --execute --yes')
    with installation_lock(c):return install(None,c)
