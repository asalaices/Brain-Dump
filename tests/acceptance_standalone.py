# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Real wheel/bootstrap acceptance in an isolated home; no private checkout.

Usage: python tests/acceptance_standalone.py --wheel ABSOLUTE_WHEEL
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel',required=True);args=parser.parse_args()
    wheel=Path(args.wheel).resolve()
    if os.name=='nt':
        print(json.dumps({'runtime_activation':'unsupported on Windows; negative coverage is in unit suite'}));return
    original=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='brain-independent-') as temporary:
        root=Path(temporary).resolve();home=root/'new-user';home.mkdir()
        source=root/'public-code'
        shutil.copytree(original,source,ignore=shutil.ignore_patterns('.git','__pycache__','*.egg-info','build','dist','.pytest_cache'))
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','COPILOT_SKILLS_HOME')}
        env.update(HOME=str(home),GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,PIP_CONFIG_FILE=os.devnull)
        def run(*command,cwd=root):
            result=subprocess.run([str(x) for x in command],cwd=cwd,env=env,text=True,capture_output=True,timeout=240)
            if result.returncode:raise AssertionError(result.stdout+'\n'+result.stderr)
            return result.stdout.strip()
        for command in [('init','-q'),('config','user.name','Synthetic'),('config','user.email','synthetic@example.invalid'),('config','commit.gpgsign','false'),('add','.'),('commit','-qm','independent public source')]:run('git','-C',source,*command)
        pin=run('git','-C',source,'rev-parse','HEAD')
        reported=run(sys.executable,source/'bootstrap.py','--version')
        assert reported.startswith('brain-bridge ')
        version=json.loads(run(sys.executable,'-m','brain_bridge','skill','--json',cwd=source))['info']['script_version']
        launcher=home/'bin/brain-bridge';runtime=home/'runtime'
        config={'schema_version':2,'host':'independent-laptop','home':str(home),'runtime_dir':str(runtime),'source_repo':str(source),'framework_commit':pin,'framework_version':version,'python':str(Path(sys.executable).resolve()),'python_version':'.'.join(map(str,sys.version_info[:3])),'setuptools_version':'84.2.1','launcher':str(launcher),'skill_home':str(home/'skills'),'skill':'skills/brain-dump','wheel':str(wheel),'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()}
        manifest=root/'installation.json';manifest.write_text(json.dumps(config))
        command=[sys.executable,source/'bootstrap.py','--config',manifest]
        plan=json.loads(run(*command));assert plan['effects']==[] and not runtime.exists()
        installed=json.loads(run(*command,'--operation','install','--execute','--yes'));assert installed['ok']
        assert (home/'skills/brain-dump').resolve()==source/'skills/brain-dump'
        verified=json.loads(run(*command,'--operation','verify'));assert verified['framework_commit']==pin
        repeated=json.loads(run(*command,'--operation','install','--execute','--yes'));assert not repeated['changed']
        python=runtime/'venv/bin/python'
        skill=json.loads(run(python,'-I','-m','brain_bridge','skill','--json'))
        assert skill['skill_name']=='brain-dump' and '\nname: brain-dump\n' in skill['content']
        assert not (source/'skills/brain-bridge').exists()
        assert skill['content']==(source/'skills/brain-dump/SKILL.md').read_text()
        bundled=Path(skill['path']).parent
        for name in ('OPERATOR.md','INSTALLATION.md','MANAGED-SOURCES.md'):
            guide=(bundled/'../../docs'/name).resolve()
            assert guide.is_file() and guide.read_text()==(source/'docs'/name).read_text()
        # Only tests from the public source are visible; -I excludes CWD/user paths.
        probe="""import sys,pathlib,unittest
import brain_bridge,brain_bridge.installation,brain_bridge.operator
assert pathlib.Path(brain_bridge.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())
sys.path.insert(0,sys.argv[1])
suite=unittest.TestSuite()
for name in ('test_adapters','test_publication','test_operator_publication'):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
result=unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and not result.skipped
"""
        run(python,'-I','-c',probe,source/'tests')
        print(json.dumps({'ok':True,'version':version,'master_checkout_required':False,'offline_wheel':True,'install_verified':True,'idempotent':True,'installed_submission_tests':True,'canonical_skill':'brain-dump','bundled_guides_verified':True,'bootstrap_version_without_config':True,'wheel_sha256':config['wheel_sha256']}))


if __name__=='__main__':main()
