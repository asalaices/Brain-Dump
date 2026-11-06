# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Managed legacy adapters preserve authorization, history and authored identity."""
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from brain_bridge.authority import Grant
from brain_bridge.policy import AccessDenied
from brain_bridge.managed import managed_index
from brain_bridge.adapters import managed_create, managed_export, managed_latest, managed_status


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()


class Authority:
    def __init__(self, grant):
        self.grant = grant
        self.operations = []

    def snapshot(self, identity, source, operation='read'):
        self.operations.append(operation)
        return self.grant


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.cache = self.root / 'cache'
        self.identity = self.root / 'identity'
        self.identity.mkdir()
        git(self.identity, 'init', '-q', '-b', 'main')
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Synthetic')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        self.doc = json.loads((Path(__file__).resolve().parents[1] / 'schemas/record.v3.synthetic.json').read_text())
        self.relative = '2026/11/2026-11-02-12-00-00-' + self.doc['entry']['id'] + '.json'
        self.record = self.repo / 'records' / self.relative
        self.record.parent.mkdir(parents=True)
        self.record.write_text(json.dumps(self.doc))
        self.commit()
        self.api = Authority(self.grant())
        self.entry = copy.deepcopy(self.doc['entry'])
        self.entry.update(id='22222222-2222-4222-8222-222222222222', timestamp='2026-11-03T12:00:00-06:00')
        self.entry['context']['coverage_since'] = {
            'entry_id': self.doc['entry']['id'], 'timestamp': self.doc['entry']['timestamp'],
            'commit': self.api.grant.commit, 'ledger': 'Brain-Bridge/' + self.relative,
        }
        self.authored = self.root / 'authored.json'
        self.output = self.root / 'draft.json'
        self.write_entry()

    def commit(self):
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Synthetic adapter fixture')

    def grant(self):
        return Grant('11111111-1111-4111-8111-111111111111-123', '456', 'example/private-data',
                     git(self.repo, 'rev-parse', 'HEAD'), 'main', 'f' * 64, 'primary')

    def refresh(self):
        self.commit()
        self.api.grant = self.grant()

    def write_entry(self):
        self.authored.write_text(json.dumps(self.entry))

    def create(self, **options):
        return managed_create(self.identity, self.repo, 'primary', self.authored, self.output,
                              authority=self.api, **options)

    def test_export_latest_and_status_reauthorize_without_mutation(self):
        before = self.record.read_bytes()
        index = (self.repo / '.git/index').read_bytes()
        exported = managed_export(self.identity, self.repo, 'primary', authority=self.api)
        latest = managed_latest(self.identity, self.repo, 'primary', authority=self.api)
        status = managed_status(self.identity, self.repo, 'primary', self.cache, authority=self.api)
        self.assertEqual(exported['entries'], [self.doc['entry']])
        self.assertEqual(exported['count'], 1)
        self.assertEqual(latest['entry'], exported['entries'][-1])
        self.assertEqual(latest['count'], 1)
        self.assertTrue(status['source_verified'])
        self.assertTrue(status['synchronized'])
        self.assertTrue(status['read_only'])
        self.assertFalse(status['cache_fresh'])
        self.assertIsNone(status['indexed_commit'])
        self.assertEqual(exported['source']['commit'], self.api.grant.commit)
        self.assertGreaterEqual(len(self.api.operations), 6)
        self.assertFalse(self.cache.exists())
        self.assertEqual(self.record.read_bytes(), before)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)
        self.assertFalse(git(self.repo, 'status', '--porcelain'))

    def test_all_adapters_require_matching_named_source(self):
        calls = [
            lambda: managed_export(self.identity, self.repo, 'wrong', authority=self.api),
            lambda: managed_latest(self.identity, self.repo, 'wrong', authority=self.api),
            lambda: managed_status(self.identity, self.repo, 'wrong', self.cache, authority=self.api),
            lambda: managed_create(self.identity, self.repo, 'wrong', self.authored, self.output,
                                   execute=True, yes=True, authority=self.api),
        ]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(AccessDenied):
                call()
        self.assertFalse(self.output.exists())

    def test_revocation_withholds_reads_and_prevents_output(self):
        grant = self.api.grant
        with patch.object(self.api, 'snapshot', side_effect=[grant, AccessDenied('revoked')]):
            with self.assertRaises(AccessDenied):
                managed_export(self.identity, self.repo, 'primary', authority=self.api)
        with patch.object(self.api, 'snapshot', side_effect=[grant, grant, AccessDenied('revoked')]):
            with self.assertRaises(AccessDenied):
                self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())

    def test_dirty_or_stale_source_never_serves_or_creates(self):
        loose = self.repo / 'untracked.json'
        loose.write_text('{}')
        with self.assertRaises(AccessDenied):
            managed_export(self.identity, self.repo, 'primary', authority=self.api)
        with self.assertRaises(AccessDenied):
            self.create(execute=True, yes=True)
        loose.unlink()
        self.api.grant = replace(self.api.grant, commit='a' * 40)
        with self.assertRaises(AccessDenied):
            managed_latest(self.identity, self.repo, 'primary', authority=self.api)
        self.assertFalse(self.output.exists())

    def test_effective_overlay_preserves_historical_prose_and_original_bytes(self):
        self.doc['schema_version'] = 2
        self.doc['entry'].pop('provenance')
        self.doc['entry']['analysis'] = 'Synthetic historical prose retained exactly'
        self.record.write_text(json.dumps(self.doc))
        raw = self.record.read_bytes()
        uid = self.doc['entry']['id']
        provenance = {'users': [{'host': 'github.com', 'login': 'synthetic-reader', 'role': 'requester'}],
                      'repositories': [], 'issues': [], 'workflow_runs': []}
        metadata = self.repo / 'metadata' / (hashlib.sha256(uid.encode()).hexdigest() + '.json')
        metadata.parent.mkdir()
        metadata.write_text(json.dumps({'schema_version': 1, 'kind': 'provenance_backfill', 'entry_id': uid,
            'ledger': 'Brain-Bridge/' + self.relative, 'ledger_sha256': hashlib.sha256(raw).hexdigest(),
            'recorded_at': '2026-11-03T12:00:00+00:00', 'attribution_source': 'Synthetic attribution',
            'provenance': provenance}))
        self.refresh()
        result = managed_export(self.identity, self.repo, 'primary', authority=self.api)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['entries'][0]['provenance'], provenance)
        self.assertEqual(result['entries'][0]['analysis'], self.doc['entry']['analysis'])
        self.assertEqual(self.record.read_bytes(), raw)
        self.assertNotIn('provenance', json.loads(self.record.read_text())['entry'])
        malformed = json.loads(metadata.read_text()); malformed['ledger_sha256'] = '0' * 64
        metadata.write_text(json.dumps(malformed)); self.refresh()
        with self.assertRaises(ValueError):
            managed_export(self.identity, self.repo, 'primary', authority=self.api)

    def test_export_uses_utc_order_and_id_tie_breaker(self):
        entries = []
        for uid, stamp in [('44444444-4444-4444-8444-444444444444', '2026-11-01T01:30:00-06:00'),
                           ('33333333-3333-4333-8333-333333333333', '2026-11-01T01:30:00-05:00'),
                           ('22222222-2222-4222-8222-222222222222', '2026-11-01T06:30:00+00:00')]:
            entry = copy.deepcopy(self.doc['entry']); entry.update(id=uid, timestamp=stamp)
            entries.append(entry)
        historical = {'schema_version': 1, 'date': '2026-11-01', 'timezone': 'America/Chicago', 'entries': entries}
        path = self.repo / 'records/2026/11/2026-11-01.json'
        path.write_text(json.dumps(historical)); self.refresh()
        exported = managed_export(self.identity, self.repo, 'primary', authority=self.api)
        self.assertEqual([e['id'] for e in exported['entries']],
                         [entries[2]['id'], entries[1]['id'], entries[0]['id'], self.doc['entry']['id']])
        self.assertEqual(managed_latest(self.identity, self.repo, 'primary', authority=self.api)['entry'],
                         exported['entries'][-1])

    def test_status_keeps_cache_provenance_distinct_from_source_commit(self):
        indexed = managed_index(self.identity, self.repo, self.cache, self.api)
        (self.repo / 'README').write_text('Synthetic unrelated documentation')
        self.refresh()
        status = managed_status(self.identity, self.repo, 'primary', self.cache, authority=self.api)
        self.assertTrue(status['cache_fresh'])
        self.assertEqual(status['indexed_commit'], indexed['indexed_commit'])
        self.assertNotEqual(status['source']['commit'], status['indexed_commit'])

    def test_empty_committed_corpus_has_no_latest(self):
        self.record.unlink()
        (self.record.parent / 'README').write_text('Synthetic empty canonical namespace')
        self.refresh()
        result = managed_export(self.identity, self.repo, 'primary', authority=self.api)
        latest = managed_latest(self.identity, self.repo, 'primary', authority=self.api)
        self.assertEqual(result['entries'], [])
        self.assertEqual(result['count'], 0)
        self.assertIsNone(latest['entry'])
        self.assertEqual(latest['count'], 0)

    def test_mismatched_writer_grant_prevents_create(self):
        grant = self.api.grant
        with patch.object(self.api, 'snapshot', side_effect=[grant, replace(grant, policy_revision='e' * 64)]):
            with self.assertRaises(AccessDenied):
                self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())

    def test_create_plan_and_exact_retry_preserve_authored_identity(self):
        index = (self.repo / '.git/index').read_bytes()
        plan = self.create()
        self.assertEqual(plan['status'], 'plan')
        self.assertFalse(plan['published'])
        self.assertFalse(self.output.exists())
        created = self.create(execute=True, yes=True)
        raw = self.output.read_bytes()
        again = self.create(execute=True, yes=True)
        self.assertEqual(created['status'], 'created')
        self.assertEqual(again['status'], 'existing')
        self.assertEqual(created['entry_id'], self.entry['id'])
        self.assertEqual(created['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(created['sha256'], again['sha256'])
        self.assertEqual(json.loads(raw)['entry'], self.entry)
        if os.name == 'posix':
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.read_bytes(), raw)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)
        self.assertFalse(git(self.repo, 'status', '--porcelain'))

    def test_create_accepts_exact_pinned_historical_anchor_without_rewriting_it(self):
        self.doc['entry']['provenance']['issues'] = [{'host': 'github.com', 'repository': 'example/data', 'number': 7}]
        self.record.write_text(json.dumps(self.doc))
        raw = self.record.read_bytes()
        rules = self.repo / '.brain-bridge/history-compatibility.json'
        rules.parent.mkdir()
        rules.write_text(json.dumps({'schema_version': 1, 'records': [{'path': 'Brain-Bridge/' + self.relative,
            'sha256': hashlib.sha256(raw).hexdigest(), 'kind': 'legacy_github_issue_shape'}]}))
        self.refresh()
        self.entry['context']['coverage_since']['commit'] = self.api.grant.commit
        self.write_entry()
        self.assertEqual(self.create(execute=True, yes=True)['status'], 'created')
        self.assertEqual(self.record.read_bytes(), raw)
        self.assertIsInstance(json.loads(self.record.read_text())['entry']['provenance']['issues'][0]['number'], int)

    def test_create_rejects_duplicate_json_fields(self):
        self.authored.write_text('{"id":"one","id":"two"}')
        with self.assertRaises(ValueError):
            self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())

    def test_create_rechecks_existing_bytes_after_authorization_roundtrips(self):
        count=0
        def authorize(*args):
            nonlocal count
            count+=1
            if count==4:self.output.write_bytes(b'unrelated concurrent output')
            return self.api.grant
        with patch.object(self.api,'snapshot',side_effect=authorize):
            with self.assertRaises(ValueError):self.create(execute=True,yes=True)
        self.assertEqual(self.output.read_bytes(),b'unrelated concurrent output')

    def test_create_rejects_overflowing_json_numbers_without_output(self):
        self.entry['analysis']=[float('inf')]
        self.authored.write_text(json.dumps(self.entry).replace('Infinity','1e999'))
        with self.assertRaises(ValueError):self.create(execute=True,yes=True)
        self.assertFalse(self.output.exists())

    def test_created_draft_uses_existing_pr_publication_and_canonical_retry(self):
        from brain_bridge.publication import propose_record
        remote=self.root/'remote.git'
        subprocess.run(['git','clone','--bare',str(self.repo),str(remote)],check=True,capture_output=True)
        git(self.repo,'remote','add','origin',str(remote))
        class Reviews:
            def __init__(self):self.calls=0
            def propose(self,*args):self.calls+=1;return 'https://github.com/example/private-data/pull/1'
        reviews=Reviews()
        created=self.create(execute=True,yes=True)
        before=self.output.read_bytes()
        def publish():
            return propose_record(self.identity,self.repo,self.output,True,True,self.api,reviews)
        pending=publish();again=publish()
        self.assertEqual(pending['publication_commit'],again['publication_commit'])
        self.assertEqual(pending['sha256'],created['sha256'])
        self.assertFalse(pending['published']);self.assertTrue(pending['remote_verified'])
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),self.api.grant.commit)
        git(remote,'update-ref','refs/heads/main',pending['publication_commit'],self.api.grant.commit)
        git(self.repo,'merge','--ff-only',pending['publication_commit'])
        self.api.grant=self.grant()
        canonical=publish()
        self.assertTrue(canonical['published']);self.assertTrue(canonical['canonical_verified'])
        self.assertEqual(canonical['entry_id'],self.entry['id'])
        self.assertEqual(canonical['sha256'],created['sha256'])
        self.assertEqual(self.output.read_bytes(),before)
        exported=managed_export(self.identity,self.repo,'primary',authority=self.api)
        self.assertEqual(exported['entries'][-1],self.entry)

    def test_create_requires_explicit_execution_confirmation(self):
        with self.assertRaises(ValueError):
            self.create(execute=True)
        self.assertFalse(self.output.exists())

    def test_create_never_regenerates_identity_or_overwrites_conflicts(self):
        self.entry.pop('id'); self.write_entry()
        with self.assertRaises(ValueError):
            self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())
        self.entry['id'] = '22222222-2222-4222-8222-222222222222'; self.write_entry()
        self.output.write_text('existing unrelated content')
        with self.assertRaises((ValueError, FileExistsError)):
            self.create(execute=True, yes=True)
        self.assertEqual(self.output.read_text(), 'existing unrelated content')

    def test_create_rejects_output_inside_source_or_through_symlink(self):
        self.output = self.repo / 'draft.json'
        with self.assertRaises((ValueError, AccessDenied)):
            self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())
        self.output = self.identity / 'draft.json'
        with self.assertRaises((ValueError, AccessDenied)):
            self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())
        if hasattr(Path, 'symlink_to'):
            link = self.root / 'draft-link.json'
            try:
                link.symlink_to(self.root / 'outside.json')
            except OSError:
                return  # Windows runners need not permit creating symlinks.
            self.output = link
            with self.assertRaises((ValueError, AccessDenied)):
                self.create(execute=True, yes=True)
            self.assertFalse((self.root / 'outside.json').exists())

    def test_create_rejects_forged_destination_anchor_and_duplicate_id(self):
        self.entry['context']['coverage_since']['entry_id'] = 'missing-baseline'
        self.write_entry()
        with self.assertRaises(ValueError):
            self.create(execute=True, yes=True)
        self.entry['context']['coverage_since']['entry_id'] = self.doc['entry']['id']
        self.entry['context']['coverage_since']['commit'] = 'a' * 40
        self.write_entry()
        with self.assertRaises((ValueError, RuntimeError)):
            self.create(execute=True, yes=True)
        self.entry['context']['coverage_since']['commit'] = self.api.grant.commit
        self.entry['id'] = self.doc['entry']['id']; self.write_entry()
        with self.assertRaises(ValueError):
            self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())

    def test_create_rejects_malformed_entry_and_secret_markers(self):
        self.entry['analysis'] = 'wrong new-entry type'; self.write_entry()
        with self.assertRaises(ValueError):
            self.create(execute=True, yes=True)
        self.entry['analysis'] = ['-----BEGIN ' + 'PRIVATE KEY-----']; self.write_entry()
        with self.assertRaises(ValueError):
            self.create(execute=True, yes=True)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
