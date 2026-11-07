# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Moved operator promotion regressions; synthetic fixtures only."""
from pathlib import Path
import tempfile
import subprocess
import hashlib
import json
import unittest
from unittest.mock import patch
from brain_bridge.operator import managed as m

class ManagedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.draft=Path(self.tmp.name)/'original.json';self.draft.write_text('exact original draft')
        self.c={'source':'primary'};self.initial={'mode':'managed','reader':'managed','generation':2};self.merges=[];self.route_changed=False;self.denied=False;self.draft_changed=False;self.duplicate=False
        identity={'entry_id':'11111111-1111-4111-8111-111111111111','path':'records/2026/11/record.json','sha256':hashlib.sha256(self.draft.read_bytes()).hexdigest(),'source':'primary'}
        self.plan={**identity,'status':'plan','published':False}
        self.pending={**identity,'status':'pending_review','published':False,'canonical_verified':False,'remote_verified':True,'branch':'brain-bridge/'+identity['entry_id'],'publication_commit':'a'*40,'pull_request':'https://github.com/example/private/pull/1'}
        self.canonical={**identity,'status':'published','published':True,'canonical_verified':True,'commit':'b'*40}
        self.status={'source':{'repository':'example/private','branch':'main','commit':'b'*40}}
        self.executions=0
        self.patches=[patch.object(m,'invoke',side_effect=self.invoke),patch.object(m,'read',return_value=self.status),patch.object(m,'synchronize',return_value={}),patch.object(m,'named',side_effect=self.export)]
        for patcher in self.patches:patcher.start();self.addCleanup(patcher.stop)
    def invoke(self,c,action,*options):
        self.assertEqual(action,'publish')
        if '--push' not in options:return self.plan
        self.executions+=1
        if self.draft_changed:return {**self.pending,'sha256':'c'*64}
        return self.pending if self.executions==1 else self.canonical
    def export(self,c,action,*options):
        self.assertEqual(action,'export');entries=[{'id':self.canonical['entry_id']}]
        return {'source':{'commit':'b'*40},'entries':entries*2 if self.duplicate else entries}
    def refresh(self,initial):
        if self.route_changed:raise ValueError('route generation changed')
        return self.initial
    def gh(self,*args):
        if args[1:3]==('pr','view'):
            return json.dumps({'state':'OPEN','headRefOid':'a'*40,'headRefName':self.pending['branch'],'baseRefName':'main','files':[{'path':self.pending['path'],'deletions':0}]})
        if args[1:3]==('pr','merge'):
            self.merges.append(args)
            if self.denied:raise subprocess.CalledProcessError(1,args)
            self.assertNotIn('--admin',args);self.assertNotIn('--force',args);return ''
        self.fail('CI checks must not gate the normal exact-head merge')
    def publish(self,execute=True):return m.publish(Path(self.tmp.name),self.draft,self.c,self.initial,self.refresh,self.gh,execute,execute)
    def test_plan_never_merges_pushes_or_synchronizes(self):
        self.assertFalse(self.publish(False)['executed']);self.assertEqual(self.executions,0);self.assertEqual(self.merges,[])
    def test_success_uses_normal_exact_head_merge_then_canonical_retry(self):
        before=self.draft.read_bytes();result=self.publish();self.assertTrue(result['published']);self.assertTrue(result['canonical_verified']);self.assertEqual(self.executions,2)
        self.assertEqual(self.merges[0][-2:],('--match-head-commit','a'*40));self.assertEqual(before,self.draft.read_bytes())
    def test_generation_change_after_proposal_preserves_pending_for_retry(self):
        original=self.gh
        def gh(*args):
            value=original(*args)
            if args[1:3]==('pr','view'):self.route_changed=True
            return value
        result=m.publish(Path(self.tmp.name),self.draft,self.c,self.initial,self.refresh,gh,True,True)
        self.assertEqual(result['status'],'pending');self.assertEqual(self.merges,[]);self.assertEqual(result['entry_id'],self.pending['entry_id']);self.assertTrue(self.draft.is_file())
        self.route_changed=False;self.executions=0;self.assertTrue(self.publish()['published'])
    def test_normal_merge_refusal_preserves_original_and_pending_review(self):
        self.denied=True;result=self.publish();self.assertFalse(result['published']);self.assertTrue(result['retained']);self.assertEqual(result['pull_request'],self.pending['pull_request']);self.assertTrue(self.draft.is_file())
    def test_changed_draft_after_plan_is_not_promoted(self):
        self.draft_changed=True;result=self.publish();self.assertFalse(result['published']);self.assertEqual(self.merges,[])
    def test_duplicate_canonical_id_is_not_claimed_complete(self):
        self.duplicate=True;result=self.publish();self.assertFalse(result['published']);self.assertTrue(result['retained'])
    def test_paused_writer_never_touches_framework_or_reader_selection(self):
        result=m.publish(Path(self.tmp.name),self.draft,self.c,{**self.initial,'mode':'paused'},self.refresh,self.gh,True,True)
        self.assertEqual(result['reason'],'publisher_paused');self.assertEqual(self.executions,0);self.assertEqual(self.merges,[])
