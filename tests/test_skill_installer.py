# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Discovery integration without any external installer repository."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from brain_bridge.installation.discovery import reconcile_skill
from brain_bridge.installation.configuration import load_config, installation_lock

ROOT = Path(__file__).resolve().parents[1]


class SkillInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / 'independent public source'; self.repo.mkdir()
        self.source = self.repo / 'skills/brain-dump'
        shutil.copytree(ROOT / 'skills/brain-dump',self.source)
        self.home = self.root / 'new user'; self.home.mkdir()
        self.target = self.home / 'skills/brain-dump'
        for args in [('init','-q'),('config','user.name','Synthetic'),('config','user.email','test@example.invalid'),('config','commit.gpgsign','false'),('add','.'),('commit','-qm','public package')]:
            subprocess.run(['git','-C',str(self.repo),*args],check=True,capture_output=True)

    def call(self,operation='status',**kw):
        return reconcile_skill(self.source,self.target.parent,operation,**kw)

    def test_plan_and_status_do_not_create_directories(self):
        for op in ('status','install','uninstall'):
            self.assertFalse(self.call(op)['executed'])
        self.assertFalse(self.target.parent.exists())

    def test_real_install_repeat_and_uninstall_preserve_git_source(self):
        self.assertTrue(self.call('install',execute=True,yes=True)['changed'])
        self.assertEqual(self.target.resolve(),self.source)
        self.assertFalse(self.call('install',execute=True,yes=True)['changed'])
        self.assertTrue(self.call('uninstall',execute=True,yes=True)['changed'])
        self.assertTrue((self.source/'SKILL.md').is_file())

    def test_regular_directory_file_and_foreign_links_are_preserved(self):
        self.target.parent.mkdir()
        for kind in ('directory','file','link'):
            if kind=='directory':self.target.mkdir()
            elif kind=='file':self.target.write_text('owner data')
            else:self.target.symlink_to(self.root/'other',target_is_directory=True)
            for op in ('install','uninstall'):
                with self.assertRaisesRegex(ValueError,'non-owned'):self.call(op,execute=True,yes=True)
            if kind=='directory':self.target.rmdir()
            else:self.target.unlink()

    def test_dirty_or_untracked_skill_cannot_be_discovered(self):
        (self.source/'SKILL.md').write_text('unreviewed')
        with self.assertRaisesRegex(ValueError,'committed'):self.call('install',execute=True,yes=True)
        self.assertFalse(self.target.parent.exists())

    def test_wheel_copy_is_not_a_git_owned_source(self):
        copy=self.root/'artifact/brain-dump';shutil.copytree(self.source,copy)
        with self.assertRaisesRegex(ValueError,'tracked'):reconcile_skill(copy,self.target.parent,'status')

    def test_symlinked_parent_and_missing_confirmation_refuse(self):
        for flags in ({'execute':True},{'yes':True}):
            with self.assertRaises(ValueError):self.call('install',**flags)
        link=self.home/'redirect';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'Symlinked'):reconcile_skill(self.source,link/'skills','install',True,True)

    def test_concurrent_discovery_is_rejected_without_touching_target(self):
        self.target.parent.mkdir();(self.target.parent/'.brain-bridge-discovery.lock').mkdir()
        with self.assertRaisesRegex(ValueError,'active'):self.call('install',execute=True,yes=True)
        self.assertFalse(self.target.exists())

    def test_native_cli_has_equivalent_structured_output_without_shell(self):
        receipts=[]
        for flag in ('--json','--pretty'):
            result=subprocess.run([sys.executable,'-m','brain_bridge','skill-link','status','--source',str(self.source),'--skill-home',str(self.target.parent),flag],cwd=ROOT,text=True,capture_output=True,check=True)
            receipts.append(json.loads(result.stdout))
        self.assertEqual(receipts[0],receipts[1]);self.assertIn('script_version',receipts[0]['info'])


class DiscoveryMigrationTests(unittest.TestCase):
    setUp=SkillInstallerTests.setUp
    def test_migration_plans_then_replaces_only_exact_prior_link(self):
        from brain_bridge.installation.discovery import migrate_skill
        previous=self.root/'old repository/skills/brain-bridge'
        self.target.parent.mkdir();old=self.target.parent/'brain-bridge';old.symlink_to(previous,target_is_directory=True)
        self.assertFalse(migrate_skill(self.source,self.target.parent,previous)['executed'])
        self.assertTrue(old.is_symlink());self.assertFalse(self.target.exists())
        receipt=migrate_skill(self.source,self.target.parent,previous,True,True)
        self.assertTrue(receipt['changed']);self.assertEqual(self.target.resolve(),self.source);self.assertFalse(old.is_symlink())
        self.assertFalse(migrate_skill(self.source,self.target.parent,previous,True,True)['changed'])

    def test_migration_does_not_remove_foreign_previous_link(self):
        from brain_bridge.installation.discovery import migrate_skill
        self.target.parent.mkdir();old=self.target.parent/'brain-bridge';old.symlink_to(self.root/'foreign',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'foreign'):
            migrate_skill(self.source,self.target.parent,self.root/'old/brain-bridge',True,True)
        self.assertFalse(self.target.exists());self.assertEqual(os.readlink(old),str(self.root/'foreign'))

    def test_failed_old_link_removal_rolls_back_new_discovery(self):
        from brain_bridge.installation.discovery import migrate_skill
        from unittest.mock import patch
        previous=self.root/'old/brain-bridge';self.target.parent.mkdir();old=self.target.parent/'brain-bridge';old.symlink_to(previous,target_is_directory=True)
        actual=Path.unlink
        def unlink(path,*args,**kwargs):
            if path==old:raise OSError('synthetic unlink failure')
            return actual(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink),self.assertRaisesRegex(OSError,'synthetic'):
            migrate_skill(self.source,self.target.parent,previous,True,True)
        self.assertTrue(old.is_symlink());self.assertFalse(self.target.exists());self.assertFalse(self.target.is_symlink())


class InstallationProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.home=self.root/'new user';self.home.mkdir()
        self.path=self.root/'installation.json'
        python=self.root/'python3';python.write_text('fixture\n');python.chmod(0o700)
        self.c={'schema_version':2,'host':'my-laptop','home':str(self.home),'runtime_dir':str(self.home/'runtime'),'source_repo':str(self.root/'public-code'),'framework_commit':'a'*40,'framework_version':'0.8.5','python':str(python),'python_version':'.'.join(map(str,sys.version_info[:3])),'setuptools_version':'84.2.1','launcher':str(self.home/'bin/brain-bridge'),'skill_home':str(self.home/'skills'),'skill':'skills/brain-dump'}

    def load(self):
        self.path.write_text(json.dumps(self.c));return load_config(self.path)

    def test_new_user_has_no_required_legacy_or_owner_identity(self):
        c=self.load();self.assertIsNone(c['legacy_version']);self.assertEqual(c['legacy_skill_sha256'],{})

    def test_unsafe_paths_unknown_fields_and_floating_versions_refuse(self):
        for field,value in [('runtime_dir',str(self.root/'outside')),('runtime_dir',str(self.home/'..'/'outside')),('source_repo',self.c['runtime_dir']),('framework_commit','main'),('framework_version','latest'),('unknown','x')]:
            original=dict(self.c);self.c[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.load()
            self.c=original

    def test_lock_is_exclusive_and_released_on_failure(self):
        c=self.load()
        with self.assertRaisesRegex(ValueError,'synthetic failure'):
            with installation_lock(c):
                with self.assertRaisesRegex(ValueError,'active'):
                    with installation_lock(c):pass
                raise ValueError('synthetic failure')
        with installation_lock(c):pass

    def test_offline_checksum_pair_and_scalar_types_are_validated(self):
        for field,value in [('wheel',str(self.root/'missing.whl')),('framework_version',[]),('host',None)]:
            original=dict(self.c);self.c[field]=value
            with self.assertRaises(ValueError):self.load()
            self.c=original

    def test_plan_is_native_read_only_and_install_requires_confirmation(self):
        self.load()
        from brain_bridge.installation import dispatch
        before=list(self.home.iterdir())
        self.assertEqual(dispatch(self.path)['effects'],[])
        self.assertEqual(list(self.home.iterdir()),before)
        with self.assertRaisesRegex(ValueError,'requires'):dispatch(self.path,'install',execute=True)
        self.assertFalse(Path(self.c['runtime_dir']).exists())


if __name__=='__main__':unittest.main()
