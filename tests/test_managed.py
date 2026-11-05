# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Managed reads must not bypass refreshed policy through local caches."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from brain_bridge.authority import Grant, initialize_identity
from brain_bridge.managed import managed_search, managed_index, managed_sync
from brain_bridge.policy import AccessDenied

KEY='11111111-1111-4111-8111-111111111111-123'
def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL,text=True).strip()

class FakeAuthority:
    def __init__(self,grant):self.grant=grant;self.calls=0
    def snapshot(self,*args):self.calls+=1;return self.grant

class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir();self.cache=self.root/'cache'
        git(self.repo,'init','-q');git(self.repo,'config','user.name','Synthetic');git(self.repo,'config','user.email','synthetic@example.invalid')
        fixture=Path(__file__).resolve().parents[1]/'schemas/record.v3.synthetic.json'
        path=self.repo/'records/2026/11/2026-11-02-12-00-00-11111111-1111-4111-8111-111111111111.json'
        path.parent.mkdir(parents=True);path.write_bytes(fixture.read_bytes())
        git(self.repo,'add','.');git(self.repo,'commit','-qm','synthetic fixture')
        self.grant=Grant(KEY,'456','example/data',git(self.repo,'rev-parse','HEAD'),'main')
        self.authority=FakeAuthority(self.grant)
    def test_cache_and_json_reads_both_reauthorize(self):
        managed_index('code',self.repo,self.cache,self.authority)
        for backend in ['json','sqlite','auto']:
            before=self.authority.calls
            result=managed_search('code',self.repo,'Synthetic',self.cache,backend,self.authority)
            self.assertTrue(result['results']);self.assertEqual(self.authority.calls,before+2)
    def test_ignored_loose_json_cannot_inject_managed_records(self):
        (self.repo/'.gitignore').write_text('records/injected.json\n')
        git(self.repo,'add','.gitignore');git(self.repo,'commit','-qm','ignore synthetic loose fixture')
        self.authority.grant=Grant(KEY,'456','example/data',git(self.repo,'rev-parse','HEAD'),'main')
        (self.repo/'records/injected.json').write_text('{"secret":"injected needle"}')
        result=managed_search('code',self.repo,'injected needle',self.cache,authority=self.authority)
        self.assertEqual(result['results'],[])

    def test_managed_sync_checks_policy_before_fetch_and_indexes_verified_objects(self):
        git(self.repo,'branch','-M','main')
        remote=self.root/'remote.git'
        subprocess.run(['git','clone','--bare',str(self.repo),str(remote)],check=True,capture_output=True)
        git(self.repo,'remote','add','origin',str(remote))
        result=managed_sync('code',self.repo,self.cache,self.authority)
        self.assertEqual(result['indexed'],1);self.assertTrue(result['fresh'])
        before=git(self.repo,'rev-parse','HEAD')
        with patch.object(self.authority,'snapshot',side_effect=AccessDenied('revoked')),patch('brain_bridge.sync._git') as transport:
            with self.assertRaises(AccessDenied):managed_sync('code',self.repo,self.cache,self.authority)
            transport.assert_not_called()
        self.assertEqual(before,git(self.repo,'rev-parse','HEAD'))

    def test_initial_denial_never_opens_records_or_cache(self):
        with patch.object(self.authority,'snapshot',side_effect=AccessDenied('revoked')),patch('brain_bridge.managed.reader_root') as root:
            with self.assertRaises(AccessDenied):managed_search('code',self.repo,'Synthetic',self.cache,authority=self.authority)
            root.assert_not_called();self.assertFalse(self.cache.exists())
    def test_revocation_during_read_withholds_results(self):
        with patch.object(self.authority,'snapshot',side_effect=[self.grant,AccessDenied('revoked')]):
            with self.assertRaises(AccessDenied):managed_search('code',self.repo,'Synthetic',self.cache,authority=self.authority)
    def test_trusted_head_change_withholds_results(self):
        newer=Grant(KEY,'456','example/data','a'*40,'main')
        with patch.object(self.authority,'snapshot',side_effect=[self.grant,newer]):
            with self.assertRaises(AccessDenied):managed_search('code',self.repo,'Synthetic',self.cache,authority=self.authority)
    def test_dirty_checkout_and_internal_cache_rejected(self):
        with self.assertRaises(AccessDenied):managed_index('code',self.repo,self.repo/'cache',self.authority)
        (self.repo/'untracked.txt').write_text('local')
        with self.assertRaises(AccessDenied):managed_search('code',self.repo,'Synthetic',self.cache,authority=self.authority)
    def test_malformed_record_rejected_before_serving(self):
        path=next((self.repo/'records').rglob('*.json'));doc=json.loads(path.read_text());doc['entry'].pop('provenance');path.write_text(json.dumps(doc))
        git(self.repo,'add','.');git(self.repo,'commit','-qm','malformed fixture')
        self.authority.grant=Grant(KEY,'456','example/data',git(self.repo,'rev-parse','HEAD'),'main')
        with self.assertRaises(ValueError):managed_search('code',self.repo,'Synthetic',self.cache,authority=self.authority)
    def test_identity_initialization_is_plan_first_and_idempotent(self):
        git(self.repo,'remote','add','origin','https://github.com/example/code.git')
        class API:
            def api(self,endpoint):return {'id':123}
        plan=initialize_identity(self.repo,authority=API());self.assertEqual(plan['status'],'plan')
        self.assertFalse((self.repo/'.brain-bridge').exists())
        first=initialize_identity(self.repo,True,API());second=initialize_identity(self.repo,True,API())
        self.assertEqual(first['identity_key'],second['identity_key']);self.assertEqual(second['status'],'existing')
        class Fork:
            def api(self,endpoint):return {'id':999}
        with self.assertRaises(AccessDenied):initialize_identity(self.repo,True,Fork())

if __name__=='__main__':unittest.main()
