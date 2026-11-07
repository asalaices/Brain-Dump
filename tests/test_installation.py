# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Portable lifecycle regressions moved from the private host integration."""
def synthetic_config():
    return {'schema_version':2,'host':'synthetic-host','home':'/synthetic',
        'runtime_dir':'/synthetic/runtime','source_repo':'/synthetic/source',
        'framework_commit':'a'*40,'framework_version':'0.8.5','python':'/synthetic/python',
        'python_version':'3.11.18','setuptools_version':'84.2.1',
        'launcher':'/synthetic/bin/brain-bridge','skill_home':'/synthetic/skills',
        'skill':'skills/brain-dump','legacy_version':'0.3.0',
        'legacy_skill_sha256':{},'operation':'brain-bridge-runtime'}

import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from brain_bridge import installation as b
from pathlib import Path
SOURCE_STATE=b.source_state
RUN=b.run
ENSURE_ENVIRONMENT=b.ensure_environment


class BrainRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.home=self.root/'home';self.home.mkdir()
        self.config=synthetic_config();c=self.config
        c.update(home=str(self.home),runtime_dir=str(self.home/'runtime'),source_repo=str(self.root/'source'),launcher=str(self.home/'bin/brain-bridge'),skill_home=str(self.home/'codex/skills'),python=str(self.home/'python'))
        self.base,self.source,self.desired,self.target,self.skill=b.paths(c)
        self.skill.mkdir(parents=True);(self.skill/'references').mkdir()
        for relative in ('SKILL.md','README.md','install.sh','references/agent-adapters.md'):(self.skill/relative).write_text('synthetic '+relative)
        c['legacy_skill_sha256']={name:b.digest(self.skill/name) for name in ('SKILL.md','references/agent-adapters.md')}
        self.base.mkdir();old=self.base/'venv';(old/'bin').mkdir(parents=True);(old/'bin/python').write_text('old python')
        launcher=Path(c['launcher']);launcher.parent.mkdir();launcher.symlink_to(old/'bin/brain-bridge')
        self.target.mkdir(parents=True);(self.target/'references').mkdir()
        for name in c['legacy_skill_sha256']:(self.target/name).write_bytes((self.skill/name).read_bytes())
        self.original_files={str(p):p.read_bytes() for p in self.target.rglob('*') if p.is_file()}
        self.commands=[]
        self.patches=[patch.object(b.platform,'system',return_value='Darwin'),patch.object(b,'source_state',return_value=(self.source,self.skill)),patch.object(b,'run',side_effect=self.fake_run),patch.object(b,'installed_version',side_effect=self.version),patch.object(b,'ensure_environment',side_effect=self.build),patch.object(b,'reconcile_skill',side_effect=self.fake_skill)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def fake_skill(self,source,home,operation,**kwargs):
        self.target.parent.mkdir(parents=True,exist_ok=True);self.target.symlink_to(self.skill)
    def version(self,path):
        marker=Path(path)/'.brain-bridge-environment.json'
        return json.loads(marker.read_text())['version'] if marker.is_file() else self.config['legacy_version']
    def fake_run(self,args,timeout=180,env=None):
        self.commands.append([str(a) for a in args])
        if list(args)[-1:] == ['--version']:
            return 'Python '+self.config['python_version'] if str(args[0])==self.config['python'] else 'brain-bridge '+self.config['framework_version']
        if any(str(x).endswith('/skills/brain-dump/install.sh') for x in args):
            self.target.parent.mkdir(parents=True,exist_ok=True);self.target.symlink_to(self.skill)
        return ''
    def build(self,c):
        if self.desired.exists():return b.environment_receipt(c,self.desired),False
        (self.desired/'bin').mkdir(parents=True);(self.desired/'bin/python').write_text('new python')
        value={'schema_version':1,'source_commit':c['framework_commit'],'version':c['framework_version'],'python_version':c['python_version'],'wheel_sha256':'a'*64}
        b.private_json(self.desired/'.brain-bridge-environment.json',value)
        return value,True
    def test_plan_has_no_subprocess_or_filesystem_effects(self):
        before=set(self.root.rglob('*'));result=b.plan(self.config)
        self.assertEqual(result['effects'],[]);self.assertFalse(result['service_changes']);self.assertFalse(result['production_route_changed'])
        self.assertEqual(before,set(self.root.rglob('*')));self.assertEqual(self.commands,[])
    def test_install_preserves_known_old_state_and_installs_git_owned_skill(self):
        result=b.install(self.root,self.config)
        self.assertTrue(result['ok']);self.assertTrue(result['changed'])
        self.assertEqual((self.base/'venv').resolve(),self.desired);self.assertEqual(self.target.resolve(),self.skill)
        receipt=json.loads((self.base/'install-receipt.json').read_text())
        self.assertEqual(Path(receipt['legacy_environment_backup'],'bin/python').read_text(),'old python')
        oldskill=Path(receipt['legacy_skill_backup'])
        for name in self.config['legacy_skill_sha256']:self.assertEqual((oldskill/name).read_bytes(),(self.skill/name).read_bytes())
        self.assertEqual((self.base/'install-receipt.json').stat().st_mode&0o777,0o600)
        activation=receipt['activation']
        self.assertEqual(activation['environment']['before'],{'state':'legacy_directory','target':str(self.base/'venv'),'source_commit':None,'version':self.config['legacy_version']})
        self.assertEqual(activation['environment']['after']['target'],str(self.desired))
        self.assertEqual(activation['environment']['legacy_backup'],receipt['legacy_environment_backup'])
        self.assertEqual(activation['launcher']['before_target'],str(self.base/'venv/bin/brain-bridge'))
        self.assertEqual(activation['launcher']['after_target'],str(self.base/'venv/bin/brain-bridge'))
        self.assertFalse(result['production_route_changed']);self.assertFalse(result['service_changes'])
    def test_repeat_install_reuses_verified_environment(self):
        b.install(self.root,self.config);backups=set((self.base/'backups').iterdir())
        result=b.install(self.root,self.config)
        self.assertFalse(result['changed']);self.assertEqual(backups,set((self.base/'backups').iterdir()))
    def test_idempotent_install_retains_legacy_backup_receipt(self):
        b.install(self.root,self.config);before=json.loads((self.base/'install-receipt.json').read_text())
        b.install(self.root,self.config);after=json.loads((self.base/'install-receipt.json').read_text())
        self.assertEqual(before['legacy_environment_backup'],after['legacy_environment_backup'])
        self.assertEqual(before['legacy_skill_backup'],after['legacy_skill_backup'])
    def test_later_reviewed_release_replaces_only_owned_managed_link(self):
        b.install(self.root,self.config);old=self.desired
        old_commit=self.config['framework_commit'];old_version=self.config['framework_version']
        self.config['framework_commit']='b'*40;self.config['framework_version']='0.8.1';self.desired=b.paths(self.config)[2]
        result=b.install(self.root,self.config)
        self.assertTrue(result['changed']);self.assertEqual((self.base/'venv').resolve(),self.desired)
        self.assertTrue(old.is_dir())
        activation=json.loads((self.base/'install-receipt.json').read_text())['activation']['environment']
        self.assertEqual(activation['before']['target'],str(old))
        self.assertEqual(activation['before']['source_commit'],old_commit)
        self.assertEqual(activation['before']['version'],old_version)
        self.assertEqual(activation['after'],{'target':str(self.desired),'source_commit':self.config['framework_commit'],'version':self.config['framework_version']})
    def test_failed_later_release_restores_previous_managed_link(self):
        b.install(self.root,self.config);old=self.desired
        self.config['framework_commit']='b'*40;self.config['framework_version']='0.8.1';self.desired=b.paths(self.config)[2]
        with patch.object(b,'verify',side_effect=ValueError('synthetic upgrade failure')):
            with self.assertRaisesRegex(ValueError,'upgrade failure'):b.install(self.root,self.config)
        self.assertEqual((self.base/'venv').resolve(),old);self.assertFalse(self.desired.exists())

    def test_modified_copied_skill_refuses_before_build(self):
        (self.target/'SKILL.md').write_text('unrelated edits')
        with patch.object(b,'ensure_environment') as build:
            with self.assertRaisesRegex(ValueError,'differs'):b.install(self.root,self.config)
            build.assert_not_called()
        self.assertFalse(self.desired.exists());self.assertFalse((self.base/'venv').is_symlink())
    def test_unrelated_install_receipt_refuses_before_build(self):
        receipt=self.base/'install-receipt.json';receipt.write_text('{"unrelated":"preserve"}')
        with patch.object(b,'ensure_environment') as build:
            with self.assertRaisesRegex(ValueError,'another owner'):b.install(self.root,self.config)
            build.assert_not_called()
        self.assertEqual(receipt.read_text(),'{"unrelated":"preserve"}')

    def test_unknown_environment_or_launcher_refuses(self):
        with patch.object(b,'installed_version',return_value='9.9.9'):
            with self.assertRaisesRegex(ValueError,'Unknown'):b.install(self.root,self.config)
        launcher=Path(self.config['launcher']);launcher.unlink();launcher.write_text('unrelated executable')
        with self.assertRaisesRegex(ValueError,'non-owned launcher'):b.install(self.root,self.config)
        self.assertEqual(launcher.read_text(),'unrelated executable')
    def test_other_skill_link_is_never_replaced(self):
        import shutil
        shutil.rmtree(self.target);self.target.symlink_to(self.root/'other')
        with self.assertRaisesRegex(ValueError,'different source'):b.install(self.root,self.config)
        self.assertEqual(os.readlink(self.target),str(self.root/'other'))
    def test_failed_activation_restores_environment_skill_and_launcher(self):
        with patch.object(b,'verify',side_effect=ValueError('synthetic final failure')):
            with self.assertRaisesRegex(ValueError,'synthetic final'):b.install(self.root,self.config)
        self.assertFalse((self.base/'venv').is_symlink());self.assertEqual((self.base/'venv/bin/python').read_text(),'old python')
        self.assertFalse(self.target.is_symlink());self.assertTrue(self.target.is_dir())
        for path,raw in self.original_files.items():self.assertEqual(Path(path).read_bytes(),raw)
        self.assertEqual(os.readlink(self.config['launcher']),str(self.base/'venv/bin/brain-bridge'))
        self.assertFalse(self.desired.exists());self.assertFalse((self.base/'install-receipt.json').exists())
    def test_failed_skill_install_restores_copied_directory(self):
        def fail(args,**kwargs):
            raise ValueError('synthetic shared owner failure')
            return self.fake_run(args,**kwargs)
        with patch.object(b,'reconcile_skill',side_effect=ValueError('synthetic shared owner failure')):
            with self.assertRaisesRegex(ValueError,'shared owner'):b.install(self.root,self.config)
        self.assertFalse((self.base/'venv').is_symlink());self.assertTrue(self.target.is_dir());self.assertFalse(self.target.is_symlink())
    def test_verify_rejects_uninstalled_state(self):
        with self.assertRaisesRegex(ValueError,'not the pinned'):b.verify(self.root,self.config)
    def test_unsupported_host_refuses_before_build(self):
        with patch.object(b.platform,'system',return_value='Windows'),patch.object(b,'ensure_environment') as build:
            with self.assertRaisesRegex(ValueError,'Windows'):b.install(self.root,self.config)
            build.assert_not_called()
    def test_source_state_checks_actual_git_commit_and_dirtiness(self):
        import subprocess
        def git(*args):return subprocess.check_output(['git','-C',str(self.source),*args],text=True).strip()
        git('init','-q');git('config','user.name','Synthetic');git('config','user.email','synthetic@example.invalid')
        git('add','.');git('commit','-qm','synthetic pinned package')
        self.config['framework_commit']=git('rev-parse','HEAD')
        with patch.object(b,'run',side_effect=RUN):
            self.assertEqual(SOURCE_STATE(self.config),(self.source,self.skill))
            (self.skill/'README.md').write_text('changed tracked package')
            with self.assertRaisesRegex(ValueError,'exact clean release'):SOURCE_STATE(self.config)
            git('checkout','--','.')
            self.config['framework_commit']='a'*40
            with self.assertRaisesRegex(ValueError,'Pinned framework release'):SOURCE_STATE(self.config)
    def test_unknown_existing_versioned_directory_is_preserved(self):
        self.desired.mkdir(parents=True);(self.desired/'unrelated').write_text('keep')
        with self.assertRaisesRegex(ValueError,'ownership receipt'):ENSURE_ENVIRONMENT(self.config)
        self.assertEqual((self.desired/'unrelated').read_text(),'keep')
    def test_failed_environment_build_cleans_only_its_new_directory(self):
        with patch.object(b,'run',side_effect=ValueError('synthetic build failure')):
            with self.assertRaisesRegex(ValueError,'build failure'):ENSURE_ENVIRONMENT(self.config)
        self.assertFalse(self.desired.exists());self.assertEqual((self.base/'venv/bin/python').read_text(),'old python')
    def test_ownership_change_during_build_aborts_before_activation(self):
        original=b.preflight;calls=0
        def preflight(*args,**kwargs):
            nonlocal calls
            result=original(*args,**kwargs);calls+=1
            if calls==2:result['skill']='missing'
            return result
        with patch.object(b,'preflight',side_effect=preflight):
            with self.assertRaisesRegex(ValueError,'ownership changed'):b.install(self.root,self.config)
        self.assertFalse((self.base/'venv').is_symlink());self.assertFalse(self.target.is_symlink())

    def test_source_drift_is_rejected(self):
        with patch.object(b,'source_state',side_effect=ValueError('source drift')),patch.object(b,'ensure_environment') as build:
            with self.assertRaisesRegex(ValueError,'source drift'):b.install(self.root,self.config)
            build.assert_not_called()

    def _pin_source_git(self):
        import subprocess
        def git(*args):return subprocess.check_output(['git','-C',str(self.source),*args],text=True).strip()
        git('init','-q');git('config','user.name','Synthetic');git('config','user.email','synthetic@example.invalid');git('config','commit.gpgsign','false')
        (self.source/'runtime.py').write_text('reviewed code')
        git('add','.');git('commit','-qm','reviewed release')
        self.config['framework_commit']=git('rev-parse','HEAD');self.desired=b.paths(self.config)[2]
        return git
    def test_clean_documentation_or_code_head_advance_preserves_pinned_runtime(self):
        git=self._pin_source_git()
        for name,content in [('README','new documentation'),('runtime.py','uninstalled development code')]:
            (self.source/name).write_text(content);git('add','.');git('commit','-qm','unrelated development advance')
            with patch.object(b,'run',side_effect=RUN):self.assertEqual(SOURCE_STATE(self.config),(self.source,self.skill))
    def test_committed_skill_change_is_not_accepted_as_the_installed_profile(self):
        git=self._pin_source_git();(self.skill/'SKILL.md').write_text('unreviewed discovery instructions');git('add','.');git('commit','-qm','changed live skill')
        with patch.object(b,'run',side_effect=RUN):
            with self.assertRaisesRegex(ValueError,'skill differs'):SOURCE_STATE(self.config)
    def test_release_pin_outside_current_history_is_rejected(self):
        git=self._pin_source_git();pin=self.config['framework_commit']
        git('checkout','--orphan','unrelated');git('rm','-rf','.');(self.source/'unrelated').write_text('other history');git('add','.');git('commit','-qm','unrelated root')
        self.assertNotEqual(pin,git('rev-parse','HEAD'))
        with patch.object(b,'run',side_effect=RUN):
            with self.assertRaisesRegex(ValueError,'outside source history'):SOURCE_STATE(self.config)
    def test_build_archive_uses_reviewed_pin_not_new_development_head(self):
        git=self._pin_source_git();pin=self.config['framework_commit'];(self.source/'runtime.py').write_text('uninstalled development code');git('add','.');git('commit','-qm','later code')
        archives=[]
        def run(args,timeout=180,env=None):
            if str(args[0])=='git':
                archives.append([str(x) for x in args]);return RUN(args,timeout=timeout,env=env)
            if 'wheel' in [str(x) for x in args]:
                self.assertEqual((Path(args[-1])/'runtime.py').read_text(),'reviewed code')
                raise ValueError('verified pinned archive; stop synthetic build')
            return ''
        with patch.object(b,'run',side_effect=run):
            with self.assertRaisesRegex(ValueError,'verified pinned archive'):ENSURE_ENVIRONMENT(self.config)
        self.assertEqual(archives[0][-1],pin);self.assertFalse(self.desired.exists());self.assertEqual((self.base/'venv/bin/python').read_text(),'old python')

if __name__=='__main__':unittest.main()
