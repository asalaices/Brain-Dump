# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Migration is private, hash-bound, resumable and never a source cutover."""
import copy,hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from urllib.parse import unquote
from unittest.mock import patch
from brain_bridge.migration import plan_migration,apply_migration
from brain_bridge.managed import immutable_snapshot
from brain_bridge.authority import Grant
from brain_bridge.policy import AccessDenied

def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True,stderr=subprocess.DEVNULL).strip()
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.destination=self.root/'destination'
        for path in (self.source,self.destination):
            path.mkdir();git(path,'init','-q','-b','main');git(path,'config','user.name','Synthetic');git(path,'config','user.email','synthetic@example.invalid')
            git(path,'remote','add','origin','https://github.com/example/'+path.name+'.git')
        self.doc=json.loads((Path(__file__).resolve().parents[1]/'schemas/record.v3.synthetic.json').read_text())
        self.relative='2026/11/2026-11-02-12-00-00-'+self.doc['entry']['id']+'.json';self.record=self.source/'Brain-Bridge'/self.relative
        self.record.parent.mkdir(parents=True);self.record.write_text(json.dumps(self.doc))
        (self.destination/'records').mkdir();(self.destination/'records/.gitkeep').touch()
        for path in (self.source,self.destination):git(path,'add','.');git(path,'commit','-qm','synthetic snapshot')
        self.destination_private=True;self.destination_users=[1];self.destination_keys=[];self.fail_inventory=False
    def api(self,endpoint):
        source=endpoint.startswith('repos/example/source');root=self.source if source else self.destination;identifier=11 if source else 22
        if endpoint=='repos/example/'+root.name:return {'id':identifier,'private':True if source else self.destination_private,'permissions':{'pull':True,'push':not source},'owner':{'id':1,'type':'User'}}
        if '/commits/' in endpoint:return {'sha':git(root,'rev-parse','HEAD')}
        if '/collaborators?' in endpoint:
            if self.fail_inventory:raise AccessDenied('inventory unavailable')
            return [{'id':uid} for uid in ([1] if source else self.destination_users)]
        if '/keys?' in endpoint:return [] if source else self.destination_keys
        raise AssertionError(endpoint)
    def authority(self):
        outer=self
        class API:
            def api(self,endpoint):return outer.api(endpoint)
        return API()
    def plan(self):return plan_migration(self.source,self.destination,'11','22',authority=self.authority())
    def apply(self,plan,**kw):return apply_migration(self.source,self.destination,plan,authority=self.authority(),**kw)
    def test_plan_and_application_preserve_source_and_destination_index(self):
        plan=self.plan();self.assertFalse(plan['cutover']);self.assertEqual(plan['record_count'],1)
        self.assertFalse((self.destination/'records'/self.relative).exists())
        source=git(self.source,'rev-parse','HEAD');index=(self.destination/'.git/index').read_bytes()
        self.assertFalse(self.apply(plan)['executed'])
        receipt=self.apply(plan,execute=True,yes=True)
        self.assertFalse(receipt['cutover']);self.assertEqual(receipt['copied'],1)
        self.assertEqual(self.record.read_bytes(),(self.destination/'records'/self.relative).read_bytes())
        self.assertEqual(git(self.source,'rev-parse','HEAD'),source);self.assertFalse(git(self.source,'status','--porcelain'))
        self.assertEqual((self.destination/'.git/index').read_bytes(),index)
        again=self.apply(plan,execute=True,yes=True);self.assertEqual(again['copied'],0);self.assertEqual(again['already_identical'],1)
    def test_versioned_cli_plan_envelope_round_trips_without_affecting_token(self):
        plan=self.plan();wrapped={'plan':plan,'info':{'script':'brain_bridge','script_version':'0.2.0'}}
        self.assertEqual(self.apply(wrapped)['plan_token'],plan['plan_token'])
        legacy=dict(plan,info={'script':'brain_bridge'})
        self.assertEqual(self.apply(legacy)['plan_token'],plan['plan_token'])
        self.assertNotIn('info',plan)

    def test_application_requires_explicit_yes(self):
        with self.assertRaises(ValueError):self.apply(self.plan(),execute=True)
    def test_public_destination_rejected_before_reading_payloads(self):
        self.destination_private=False
        with patch('brain_bridge.migration.immutable_snapshot') as reader:
            with self.assertRaises(AccessDenied):self.plan()
            reader.assert_not_called()
    def test_unavailable_audience_and_expansion_block_copy(self):
        self.fail_inventory=True
        with self.assertRaises(AccessDenied):self.plan()
        self.fail_inventory=False;self.destination_users=[1,99];plan=self.plan();self.assertIn('user:99',plan['audience_expansion'])
        with self.assertRaises(AccessDenied):self.apply(plan,execute=True,yes=True)
        self.assertFalse((self.destination/'records'/self.relative).exists())
    def test_additional_deploy_key_is_an_audience_change(self):
        self.destination_keys=[{'key':'ssh-ed25519 synthetic-public-key-blob'}]
        plan=self.plan();self.assertTrue(any(value.startswith('deploy_key:') for value in plan['audience_expansion']))
        with self.assertRaises(AccessDenied):self.apply(plan,execute=True,yes=True)
    def test_tampered_and_stale_plans_are_rejected(self):
        plan=self.plan();bad=copy.deepcopy(plan);bad['files'][0]['target_path']='../outside.json'
        with self.assertRaises(ValueError):self.apply(bad,execute=True,yes=True)
        (self.source/'new-source-note.txt').write_text('synthetic change');git(self.source,'add','.');git(self.source,'commit','-qm','advance source')
        with self.assertRaises(ValueError):self.apply(plan,execute=True,yes=True)
    def test_unrelated_destination_changes_are_preserved(self):
        plan=self.plan();(self.destination/'owner-work.txt').write_text('preserve this')
        with self.assertRaises(ValueError):self.apply(plan,execute=True,yes=True)
        self.assertEqual((self.destination/'owner-work.txt').read_text(),'preserve this')
    def test_provenance_sidecar_survives_rehearsal_byte_for_byte(self):
        self.doc['schema_version']=2;self.doc['entry'].pop('provenance');self.record.write_text(json.dumps(self.doc))
        uid=self.doc['entry']['id'];overlay={'schema_version':1,'kind':'provenance_backfill','entry_id':uid,'ledger':'Brain-Bridge/'+self.relative,'ledger_sha256':hashlib.sha256(self.record.read_bytes()).hexdigest(),'recorded_at':'2026-11-03T12:00:00+00:00','attribution_source':'Synthetic explicit attribution','provenance':{'users':[],'repositories':[],'issues':[],'workflow_runs':[]}}
        path=self.source/'Brain-Bridge/metadata'/(hashlib.sha256(uid.encode()).hexdigest()+'.json');path.parent.mkdir();path.write_text(json.dumps(overlay))
        git(self.source,'add','.');git(self.source,'commit','-qm','synthetic legacy attribution')
        plan=self.plan();self.assertEqual(plan['overlay_count'],1);self.apply(plan,execute=True,yes=True)
        target=self.destination/'metadata'/path.name;self.assertEqual(path.read_bytes(),target.read_bytes())
        git(self.destination,'add','.');git(self.destination,'commit','-qm','synthetic reviewed rehearsal')
        snapshot=immutable_snapshot(self.destination,Grant('operator','22','example/destination',git(self.destination,'rev-parse','HEAD'),'main'))
        self.assertEqual(len(snapshot['records']),1);self.assertEqual(len(snapshot['overlays']),1)

if __name__=='__main__':unittest.main()
