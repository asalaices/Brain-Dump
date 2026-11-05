# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Synapse references must identify actual immutable evidence, never imagined memory."""
import contextlib
import copy
import hashlib
import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch
from uuid import UUID
import test_managed as fixtures
from brain_bridge.synapse import synapse_request,excerpt
from brain_bridge.managed import managed_index
from brain_bridge.policy import AccessDenied,AuthorizationUnavailable
from brain_bridge.__main__ import main

class SynapseTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ManagedTests('test_cache_and_json_reads_both_reauthorize')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.repo=self.fixture.repo;self.cache=self.fixture.cache;self.authority=self.fixture.authority
        self.authority.grant=replace(self.fixture.grant,source_name='primary',policy_revision='f'*64)
    def request(self,term='Synthetic',**kwargs):
        return synapse_request('config',self.repo,'primary',term,self.cache,authority=self.authority,**kwargs)
    def commit(self):
        fixtures.git(self.repo,'add','.');fixtures.git(self.repo,'commit','-qm','synthetic consult fixture')
        self.authority.grant=replace(self.authority.grant,commit=fixtures.git(self.repo,'rev-parse','HEAD'))
    def test_found_cites_actual_entry_pointer_timestamp_and_commit(self):
        receipt=self.request();self.assertEqual(receipt['status'],'found');UUID(receipt['request_id'])
        hit=next(x for x in receipt['matches'] if x['json_pointer']=='/entry/title')
        self.assertEqual(hit['entry_id'],'11111111-1111-4111-8111-111111111111')
        self.assertEqual(hit['record_timestamp'],'2026-11-02T12:00:00-06:00')
        self.assertIn('/blob/'+self.authority.grant.commit+'/',hit['source_url'])
        self.assertEqual(hit['provenance_source'],'native');self.assertIn('synapse request',receipt['disclosure'])
        self.assertEqual(receipt['source']['name'],'primary');self.assertEqual(receipt['corpus']['entries'],1)
    def test_no_match_never_claims_a_brain_reference(self):
        receipt=self.request('NoSuchSyntheticNeedle')
        self.assertEqual(receipt['status'],'no_match');self.assertEqual(receipt['matches'],[])
        self.assertNotIn('I found',receipt['disclosure']);self.assertTrue(receipt['freshness']['source_verified'])
    def test_unknown_alias_denied_before_search(self):
        with patch('brain_bridge.synapse.managed_search') as search:
            result=synapse_request('config',self.repo,'unregistered','Synthetic',self.cache,authority=self.authority)
        self.assertEqual(result['status'],'denied');search.assert_not_called();self.assertFalse(self.cache.exists())
    def test_initial_denial_opens_neither_records_nor_cache(self):
        with patch.object(self.authority,'snapshot',side_effect=AccessDenied('denied')),patch('brain_bridge.synapse.reader_root') as root:
            receipt=self.request()
        self.assertEqual(receipt['status'],'denied');self.assertEqual(receipt['matches'],[])
        root.assert_not_called();self.assertFalse(self.cache.exists())
    def test_unavailable_authority_is_distinct_from_no_match(self):
        with patch.object(self.authority,'snapshot',side_effect=AuthorizationUnavailable('upstream unavailable')):
            result=self.request()
        self.assertEqual(result['status'],'unavailable');self.assertEqual(result['matches'],[])
        self.assertNotIn('No matching',result['disclosure'])
    def test_revocation_after_citation_mapping_discards_all_evidence(self):
        grant=self.authority.grant
        with patch.object(self.authority,'snapshot',side_effect=[grant,grant,grant,AccessDenied('revoked')]):
            result=self.request()
        self.assertEqual(result['status'],'denied');self.assertEqual(result['matches'],[])
        self.assertNotIn('source',result);self.assertNotIn('I found',result['disclosure'])
    def test_json_and_sqlite_return_identical_bounded_citations(self):
        managed_index('config',self.repo,self.cache,self.authority)
        left=self.request(backend='json',limit=1);right=self.request(backend='sqlite',limit=1)
        self.assertEqual(left['matches'],right['matches']);self.assertTrue(left['truncated'])
        self.assertEqual(left['returned_matches'],1);self.assertEqual(left['total_matches'],right['total_matches'])
    def test_missing_explicit_index_returns_error_not_no_match(self):
        result=self.request(backend='sqlite')
        self.assertEqual(result['status'],'error');self.assertEqual(result['matches'],[])
    def test_multi_entry_legacy_pointer_resolves_correct_record(self):
        path=next((self.repo/'records').rglob('*.json'));doc=json.loads(path.read_text());entry=doc.pop('entry');entry.pop('provenance')
        first=copy.deepcopy(entry);first['id']='legacy-first';first['title']='Unrelated first entry'
        second=copy.deepcopy(entry);second['id']='legacy-second';second['title']='DistinctCitationNeedle'
        doc.update(schema_version=1,entries=[first,second]);path.write_text(json.dumps(doc));self.commit()
        receipt=self.request('DistinctCitationNeedle');self.assertEqual(receipt['status'],'found')
        self.assertEqual(receipt['matches'][0]['entry_id'],'legacy-second')
        self.assertEqual(receipt['matches'][0]['json_pointer'],'/entries/1/title')
        envelope=self.request('timezone')['matches'][0]
        self.assertEqual(envelope['match_scope'],'envelope');self.assertIsNone(envelope['entry_id'])
        self.assertEqual(envelope['associated_entry_ids'],['legacy-first','legacy-second'])
    def test_overlay_citation_binds_separate_source_and_immutable_ledger(self):
        path=next((self.repo/'records').rglob('*.json'));doc=json.loads(path.read_text());provenance=doc['entry'].pop('provenance');doc['schema_version']=2
        path.write_text(json.dumps(doc));uid=doc['entry']['id'];digest=hashlib.sha256(path.read_bytes()).hexdigest()
        sidecar={'schema_version':1,'kind':'provenance_backfill','entry_id':uid,'ledger':'Brain-Bridge/'+path.relative_to(self.repo/'records').as_posix(),
                 'ledger_sha256':digest,'attribution_source':'OverlayCitationNeedle','recorded_at':'2026-11-05T06:00:00Z','provenance':provenance}
        overlay=self.repo/'metadata'/(hashlib.sha256(uid.encode()).hexdigest()+'.json');overlay.parent.mkdir();overlay.write_text(json.dumps(sidecar));self.commit()
        result=self.request('OverlayCitationNeedle');hit=result['matches'][0]
        self.assertEqual(hit['match_scope'],'provenance_overlay');self.assertEqual(hit['entry_id'],uid)
        self.assertTrue(hit['source_path'].startswith('metadata/'));self.assertTrue(hit['ledger_path'].startswith('records/'))
        self.assertEqual(hit['ledger_sha256'],digest);self.assertEqual(hit['provenance_source'],'overlay')
    def test_explicit_supersession_is_retained_without_claiming_semantic_resolution(self):
        path=next((self.repo/'records').rglob('*.json'));doc=json.loads(path.read_text());doc['entry']['supersedes']=[doc['entry']['id']]
        path.write_text(json.dumps(doc));self.commit();result=self.request()
        self.assertTrue(any(x['superseded_by'] for x in result['matches']))
        self.assertEqual(result['conflict_assessment'],'not_performed')
    def test_unicode_excerpts_center_on_actual_character_positions(self):
        text='ß'*500+'target'+'z'*500;snippet=excerpt(text,'TARGET',40)
        self.assertIn('target',snippet['text']);self.assertLessEqual(len(snippet['text']),40);self.assertTrue(snippet['truncated'])
    def test_altered_cache_cannot_invent_a_committed_citation_and_rebuild_repairs_it(self):
        import sqlite3
        managed_index('config',self.repo,self.cache,self.authority)
        database=next(self.cache.glob('*.sqlite'))
        with sqlite3.connect(database) as conn:
            conn.execute("UPDATE nodes SET value='InventedCitationNeedle' WHERE pointer='/entry/title' AND kind='value'")
        result=self.request('InventedCitationNeedle')
        self.assertEqual(result['status'],'no_match');self.assertEqual(result['matches'],[])
        self.assertFalse(result['freshness']['cache_fresh']);self.assertEqual(result['freshness']['backend_used'],'json')
        explicit=self.request('InventedCitationNeedle',backend='sqlite')
        self.assertEqual(explicit['status'],'error');self.assertEqual(explicit['matches'],[])
        managed_index('config',self.repo,self.cache,self.authority)
        repaired=self.request(backend='sqlite')
        self.assertEqual(repaired['status'],'found');self.assertTrue(repaired['freshness']['cache_fresh'])
        self.assertTrue(any('Synthetic Brain Bridge example' in x['excerpt']['text'] for x in repaired['matches']))
    def test_deleted_index_rows_cannot_suppress_matching_references(self):
        import sqlite3
        expected=self.request(backend='json')['matches']
        managed_index('config',self.repo,self.cache,self.authority)
        with sqlite3.connect(next(self.cache.glob('*.sqlite'))) as conn:conn.execute('DELETE FROM nodes')
        result=self.request()
        self.assertEqual(result['status'],'found');self.assertEqual(result['matches'],expected)
        self.assertEqual(result['freshness']['backend_used'],'json')
    def test_sqlite_failure_and_invalid_row_types_return_error_receipts(self):
        import sqlite3
        managed_index('config',self.repo,self.cache,self.authority)
        with patch('brain_bridge.managed.sqlite_search',side_effect=sqlite3.DatabaseError('synthetic failure')):
            result=self.request(backend='sqlite')
        self.assertEqual(result['status'],'error');self.assertEqual(result['matches'],[])
        with sqlite3.connect(next(self.cache.glob('*.sqlite'))) as conn:conn.execute('UPDATE nodes SET value=NULL')
        result=self.request(backend='sqlite');self.assertEqual(result['status'],'error')
        fallback=self.request();self.assertEqual(fallback['status'],'found')
    def test_extra_entry_field_in_v1_is_not_attributed_to_an_unrelated_entry(self):
        path=next((self.repo/'records').rglob('*.json'));doc=json.loads(path.read_text());canonical=doc.pop('entry');canonical.pop('provenance')
        doc.update(schema_version=1,entries=[canonical],entry={'title':'EnvelopeOnlyNeedle'})
        path.write_text(json.dumps(doc));self.commit();hit=self.request('EnvelopeOnlyNeedle')['matches'][0]
        self.assertEqual(hit['match_scope'],'envelope');self.assertIsNone(hit['entry_id'])
        self.assertIsNone(hit['record_timestamp']);self.assertEqual(hit['json_pointer'],'/entry/title')

    def test_git_timeout_returns_error_receipt_without_echoing_command(self):
        import subprocess
        with patch('brain_bridge.synapse.reader_root',side_effect=subprocess.TimeoutExpired(['git','sensitive-private-path'],90)):
            result=self.request()
        self.assertEqual(result['status'],'error');self.assertEqual(result['matches'],[])
        self.assertNotIn('sensitive-private-path',result['error'])

    def test_invalid_limits_do_not_dispatch_authority(self):
        for kw in [{'limit':0},{'limit':True},{'excerpt_chars':1001},{'backend':'unknown'}]:
            with patch.object(self.authority,'snapshot') as authorization,self.assertRaises(ValueError):self.request(**kw)
            authorization.assert_not_called()
    def test_cli_denial_is_one_receipt_and_nonzero_exit(self):
        receipt={'status':'denied','matches':[],'request_id':'synthetic'};output=io.StringIO()
        with patch('brain_bridge.__main__.synapse_request',return_value=receipt),contextlib.redirect_stdout(output):
            code=main(['synapse','--identity-repo','config','--repo','data','--source','primary','--term','needle','--cache-dir','cache','--pretty'])
        self.assertEqual(code,1);self.assertEqual(json.loads(output.getvalue())['request_id'],'synthetic')

if __name__=='__main__':unittest.main()
