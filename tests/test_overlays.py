# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Provenance sidecars remain immutable and participate in cache freshness."""
import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from brain_bridge.authority import Grant
from brain_bridge.managed import managed_index,managed_search,managed_graph,immutable_records

def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True,stderr=subprocess.DEVNULL).strip()
class API:
    def __init__(self,grant):self.grant=grant
    def snapshot(self,*args):return self.grant
class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.repo=self.root/'repo';self.repo.mkdir();self.cache=self.root/'cache'
        git(self.repo,'init','-q');git(self.repo,'config','user.name','Synthetic');git(self.repo,'config','user.email','synthetic@example.invalid')
        self.doc=json.loads((Path(__file__).resolve().parents[1]/'schemas/record.v3.synthetic.json').read_text())
        self.doc['schema_version']=2;self.doc['entry'].pop('provenance');self.uid=self.doc['entry']['id']
        self.relative='2026/11/2026-11-02-12-00-00-'+self.uid+'.json';self.path=self.repo/'records'/self.relative
        self.path.parent.mkdir(parents=True);self.path.write_text(json.dumps(self.doc))
        git(self.repo,'add','.');git(self.repo,'commit','-qm','synthetic legacy ledger');self.api=API(self.grant())
    def grant(self):return Grant('11111111-1111-4111-8111-111111111111-123','456','example/data',git(self.repo,'rev-parse','HEAD'),'main','f'*64)
    def overlay(self,**change):
        provenance={'users':[{'host':'github.com','login':'synthetic-user','role':'requester'}],'repositories':[],'issues':[],'workflow_runs':[]}
        data={'schema_version':1,'kind':'provenance_backfill','entry_id':self.uid,'ledger':'Brain-Bridge/'+self.relative,'ledger_sha256':hashlib.sha256(self.path.read_bytes()).hexdigest(),'recorded_at':'2026-11-03T12:00:00+00:00','attribution_source':'Synthetic explicit attribution','provenance':provenance}
        data.update(change);path=self.repo/'metadata'/(hashlib.sha256(self.uid.encode()).hexdigest()+'.json');path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(data))
        git(self.repo,'add','.');git(self.repo,'commit','-qm','synthetic attribution overlay');self.api.grant=self.grant()
    def test_overlay_search_graph_and_freshness_without_ledger_rewrite(self):
        original=self.path.read_bytes();first=managed_index('code',self.repo,self.cache,self.api);self.assertEqual(first['indexed'],1)
        self.overlay()
        with self.assertRaises(ValueError):managed_search('code',self.repo,'synthetic-user',self.cache,'sqlite',self.api)
        result=managed_search('code',self.repo,'synthetic-user',self.cache,authority=self.api)
        self.assertTrue(any(row['file'].startswith('metadata/') for row in result['results']))
        indexed=managed_index('code',self.repo,self.cache,self.api);self.assertEqual(indexed['indexed_overlays'],1)
        graph=managed_graph('code',self.repo,authority=self.api)['graph'];self.assertTrue(any(n['kind']=='actor' for n in graph['nodes']))
        self.assertEqual(self.path.read_bytes(),original);self.assertNotIn('provenance',immutable_records(self.repo,self.api.grant)[0][2]['entry'])
    def test_wrong_overlay_ledger_hash_rejected_before_index(self):
        self.overlay(ledger_sha256='0'*64)
        with self.assertRaises(ValueError):managed_index('code',self.repo,self.cache,self.api)
        self.assertFalse(self.cache.exists())
    def test_overlay_cannot_replace_native_provenance(self):
        self.doc['schema_version']=3;self.doc['entry']['provenance']={'users':[],'repositories':[],'issues':[],'workflow_runs':[]}
        self.path.write_text(json.dumps(self.doc));git(self.repo,'add','.');git(self.repo,'commit','-qm','synthetic native provenance')
        self.overlay()
        with self.assertRaises(ValueError):managed_index('code',self.repo,self.cache,self.api)

if __name__=='__main__':unittest.main()
