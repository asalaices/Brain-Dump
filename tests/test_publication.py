# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Publication exercises real isolated Git objects with fake review transport."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from brain_bridge.authority import Grant
from brain_bridge.policy import AccessDenied
from brain_bridge.publication import propose_record, GitHubReviews

KEY='11111111-1111-4111-8111-111111111111-123'
def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL,text=True).strip()
class Authority:
    def __init__(self,grant):self.grant=grant;self.operations=[]
    def snapshot(self,code,source,operation='read'):self.operations.append(operation);return self.grant
class Reviews:
    def __init__(self):self.calls=[]
    def propose(self,*args):self.calls.append(args);return 'https://github.com/example/private-data/pull/1'
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.repo=self.root/'repo';self.repo.mkdir();self.remote=self.root/'remote.git'
        git(self.repo,'init','-q','-b','main');git(self.repo,'config','user.name','Synthetic');git(self.repo,'config','user.email','synthetic@example.invalid')
        doc=json.loads((Path(__file__).resolve().parents[1]/'schemas/record.v3.synthetic.json').read_text())
        self.baseline=copy.deepcopy(doc)
        self.relative='2026/11/2026-11-02-12-00-00-11111111-1111-4111-8111-111111111111.json'
        path=self.repo/'records'/self.relative;path.parent.mkdir(parents=True);path.write_text(json.dumps(doc))
        git(self.repo,'add','.');git(self.repo,'commit','-qm','synthetic published baseline')
        self.base=git(self.repo,'rev-parse','HEAD')
        subprocess.run(['git','clone','--bare',str(self.repo),str(self.remote)],capture_output=True,check=True)
        git(self.repo,'remote','add','origin',str(self.remote))
        self.authority=Authority(Grant(KEY,'456','example/private-data',self.base,'main','f'*64));self.reviews=Reviews()
        doc.update(date='2026-11-03');doc['entry'].update(id='22222222-2222-4222-8222-222222222222',timestamp='2026-11-03T12:00:00-06:00')
        doc['entry']['context']['coverage_since']={'entry_id':self.baseline['entry']['id'],'timestamp':self.baseline['entry']['timestamp'],'commit':self.base,'ledger':'Brain-Bridge/'+self.relative}
        self.input=self.root/'candidate.json';self.input.write_text(json.dumps(doc));self.doc=doc
    def propose(self,**kw):return propose_record('code',self.repo,self.input,authority=self.authority,reviews=self.reviews,**kw)
    def test_plan_does_not_push_or_create_review(self):
        before=(self.repo/'.git/index').read_bytes();receipt=self.propose()
        self.assertEqual(receipt['status'],'plan');self.assertEqual(self.reviews.calls,[])
        self.assertEqual(before,(self.repo/'.git/index').read_bytes())
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),self.base)
        self.assertFalse(git(self.repo,'ls-remote','--heads','origin',receipt['branch']))
        self.assertEqual(self.authority.operations,['read','write'])
    def test_execution_requires_yes(self):
        with self.assertRaises(ValueError):self.propose(execute=True)
        self.assertEqual(self.authority.operations,[])
    def test_execution_pushes_only_one_addition_and_preserves_checkout(self):
        before=(self.repo/'.git/index').read_bytes();result=self.propose(execute=True,yes=True)
        self.assertEqual(result['status'],'pending_review');self.assertFalse(result['merged'])
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),self.base);self.assertFalse(git(self.repo,'status','--porcelain'))
        self.assertEqual(before,(self.repo/'.git/index').read_bytes())
        tip=result['publication_commit'];self.assertEqual(git(self.repo,'diff-tree','--no-commit-id','--name-status','-r',tip),'A\t'+result['path'])
        self.assertEqual(git(self.repo,'rev-parse',tip+'^'),self.base)
        pushed=git(self.repo,'ls-remote','--heads','origin',result['branch']).split()[0]
        self.assertEqual(pushed,tip);self.assertEqual(len(self.reviews.calls),1)
    def test_retry_preserves_same_publication_commit(self):
        first=self.propose(execute=True,yes=True);second=self.propose(execute=True,yes=True)
        self.assertEqual(first['publication_commit'],second['publication_commit'])
    def test_existing_branch_with_different_bytes_is_not_overwritten(self):
        first=self.propose(execute=True,yes=True);self.doc['entry']['title']='Different synthetic bytes';self.input.write_text(json.dumps(self.doc))
        with self.assertRaises(ValueError):self.propose(execute=True,yes=True)
        self.assertEqual(git(self.repo,'ls-remote','--heads','origin',first['branch']).split()[0],first['publication_commit'])
    def test_duplicate_id_and_forged_baseline_are_rejected(self):
        self.doc['entry']['context']['coverage_since']['entry_id']='not-a-published-id';self.input.write_text(json.dumps(self.doc))
        with self.assertRaises(ValueError):self.propose()
        self.doc['entry']['id']=self.baseline['entry']['id'];self.input.write_text(json.dumps(self.doc))
        with self.assertRaises(ValueError):self.propose()
    def test_policy_change_before_push_prevents_publication(self):
        grant=self.authority.grant
        with patch.object(self.authority,'snapshot',side_effect=[grant,grant,AccessDenied('revoked')]):
            with self.assertRaises(AccessDenied):self.propose(execute=True,yes=True)
        self.assertFalse(git(self.repo,'ls-remote','--heads','origin','brain-bridge/*'))
    def test_credential_markers_rejected_before_authentication(self):
        self.doc['entry']['analysis']=['-----BEGIN '+'PRIVATE KEY-----'];self.input.write_text(json.dumps(self.doc))
        with self.assertRaises(ValueError):self.propose()
        self.assertEqual(self.authority.operations,[])
    def test_existing_open_review_is_reused(self):
        client=GitHubReviews()
        with patch.object(client,'command',return_value=json.dumps([{'url':'https://github.com/example/private-data/pull/1','headRefOid':'a'*40,'state':'OPEN'}])) as command:
            url=client.propose('example/private-data','brain-bridge/example','a'*40,'records/file.json','b'*64)
            self.assertEqual(url,'https://github.com/example/private-data/pull/1');self.assertEqual(command.call_count,1)

if __name__=='__main__':unittest.main()
