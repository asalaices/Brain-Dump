# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Continuous observation preserves pending captures without copying real data."""
import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch
from brain_bridge.reconciliation import reconcile, poll_reconciliation, _lock
from brain_bridge.managed import object_bytes
from brain_bridge.migration import digest
from brain_bridge.policy import AccessDenied
import test_migration as fixtures


class ReconciliationTests(unittest.TestCase):
    api = fixtures.MigrationTests.api
    authority = fixtures.MigrationTests.authority

    def setUp(self):
        fixtures.MigrationTests.setUp(self)
        self.root = self.root.resolve()
        self.state = self.root / 'private-checkpoint'
        path = self.destination / '.brain-bridge/identity.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'schema_version': 1, 'instance_uuid': '99999999-9999-4999-8999-999999999999', 'github_repository_id': '22'}))
        self.commit(self.destination)

    def commit(self, repo):
        fixtures.git(repo, 'add', '.')
        fixtures.git(repo, 'commit', '-qm', 'Synthetic reconciliation fixture')

    def observe(self, persist=False, **options):
        return reconcile(self.source, self.destination, '11', '22', state_dir=self.state,
                         execute=persist, yes=persist, authority=self.authority(), **options)

    def append_source(self, uid='22222222-2222-4222-8222-222222222222', day='03'):
        doc = copy.deepcopy(self.doc)
        doc['date'] = '2026-11-' + day
        doc['entry'].update(id=uid, timestamp='2026-11-' + day + 'T12:00:00-06:00')
        path = self.source / ('Brain-Bridge/2026/11/2026-11-' + day + '-12-00-00-' + uid + '.json')
        path.write_text(json.dumps(doc)); self.commit(self.source)
        return path

    def append_native(self):
        doc = copy.deepcopy(self.doc)
        uid = '99999999-9999-4999-8999-999999999999'
        doc.update(date='2026-11-05'); doc['entry'].update(id=uid, timestamp='2026-11-05T12:00:00-06:00')
        path = self.destination / ('records/2026/11/2026-11-05-12-00-00-' + uid + '.json')
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(doc)); self.commit(self.destination)
        return path

    def integrate_synthetic(self, receipt, select=lambda item: True):
        # Test-only canonical integration. The observer has no copying/merge API.
        value = receipt['proposal']['manifest']
        for item in value['files']:
            if not select(item): continue
            raw = object_bytes(self.source, 'show', value['source']['commit'] + ':' + item['source_path'])
            path = self.destination / item['target_path']
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.commit(self.destination)

    def test_default_is_no_mutation_and_pending_is_not_watermark(self):
        source_head = fixtures.git(self.source, 'rev-parse', 'HEAD')
        index = (self.destination / '.git/index').read_bytes()
        result = self.observe()
        self.assertEqual(result['status'], 'pending'); self.assertEqual(result['pending']['records'], 1)
        self.assertIsNone(result['verified_watermark'])
        self.assertFalse(result['state_written']); self.assertFalse(result['records_copied'])
        self.assertFalse(result['authorization_written']); self.assertFalse(self.state.exists())
        self.assertEqual(fixtures.git(self.source, 'rev-parse', 'HEAD'), source_head)
        self.assertEqual((self.destination / '.git/index').read_bytes(), index)
        self.assertFalse((self.destination / 'records' / self.relative).exists())
        self.assertNotIn(self.doc['entry']['title'], json.dumps(result))

    def test_source_append_during_batch_keeps_old_capture_until_canonical(self):
        first = self.observe(True)
        captured = first['source']['commit']
        self.append_source()
        second = self.observe(True)
        self.assertEqual(second['pending']['records'], 2)
        self.assertEqual(second['captured_snapshots'], 2); self.assertIsNone(second['verified_watermark'])
        self.integrate_synthetic(first)
        third = self.observe(True)
        self.assertEqual(third['pending']['records'], 1)
        self.assertEqual(third['verified_watermark']['source_commit'], captured)
        self.assertNotEqual(third['source']['commit'], captured)
        self.integrate_synthetic(third)
        final = self.observe(True)
        self.assertEqual(final['status'], 'caught_up'); self.assertEqual(final['pending']['files'], 0)
        self.assertEqual(final['verified_watermark']['source_commit'], second['source']['commit'])
        state = json.loads((self.state / 'state.json').read_text())
        self.assertEqual(len(state['inventory']), 2)
        self.assertEqual(state['inventory']['records/' + self.relative]['seen_at'], 0)
        self.assertNotIn(self.doc['entry']['title'], json.dumps(state))

    def test_backdated_entry_published_later_is_not_skipped(self):
        first=self.observe(True)
        older=self.append_source(day='01')
        second=self.observe(True)
        self.assertEqual(second['pending']['records'],2)
        path='records/'+older.relative_to(self.source/'Brain-Bridge').as_posix()
        self.assertIn(path,{item['path'] for item in second['outbox']})
        self.integrate_synthetic(second)
        final=self.observe(True)
        self.assertEqual(final['status'],'caught_up')
        self.assertEqual(final['verified_watermark']['source_commit'],second['source']['commit'])
        self.assertNotEqual(first['source']['commit'],second['source']['commit'])

    def test_review_ref_with_complete_payload_cannot_claim_main_watermark(self):
        first=self.observe(True)
        before=(self.state/'state.json').read_bytes()
        fixtures.git(self.destination,'checkout','-qb','synthetic-pending-review')
        self.integrate_synthetic(first)
        with self.assertRaisesRegex(ValueError,'requires source and destination main'):
            self.observe(True,destination_ref='synthetic-pending-review')
        self.assertEqual((self.state/'state.json').read_bytes(),before)

    def test_destination_append_preserves_native_and_regenerates_plan(self):
        first = self.observe(True)
        path = self.append_native(); raw = path.read_bytes()
        second = self.observe(True)
        self.assertEqual(second['destination_only']['records'], 1)
        self.assertEqual(second['pending']['records'], 1)
        self.assertNotEqual(first['proposal']['manifest']['manifest_token'], second['proposal']['manifest']['manifest_token'])
        self.assertNotEqual(first['destination']['commit'], second['destination']['commit'])
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(second['captured_snapshots'], 1)

    def test_crash_before_replace_keeps_old_checkpoint_and_restart_retries(self):
        first = self.observe(True)
        before = (self.state / 'state.json').read_bytes()
        self.append_source()
        with patch('brain_bridge.reconciliation.os.replace', side_effect=OSError('Synthetic crash before atomic replace')):
            with self.assertRaises(OSError): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)
        self.assertEqual(list(self.state.glob('.state-*')), [])
        restarted = self.observe(True)
        self.assertEqual(restarted['pending']['records'], 2)
        self.assertEqual(restarted['captured_snapshots'], 2)
        self.assertIsNone(restarted['verified_watermark'])
        if os.name == 'posix':
            self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
            for name in ('state.json', 'state.lock'):
                self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600)

    def test_pending_source_rewrite_and_transient_rewrite_fail_closed(self):
        self.observe(True); before = (self.state / 'state.json').read_bytes(); raw = self.record.read_bytes()
        doc = json.loads(raw); doc['entry']['title'] = 'Synthetic prohibited rewrite'
        self.record.write_text(json.dumps(doc)); self.commit(self.source)
        with self.assertRaises(ValueError): self.observe(True)
        self.record.write_bytes(raw); self.commit(self.source)
        with self.assertRaisesRegex(ValueError, 'between observations'): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_pending_source_delete_is_not_forgotten(self):
        self.append_source(); self.observe(True)
        before = (self.state / 'state.json').read_bytes()
        self.record.unlink(); self.commit(self.source)
        with self.assertRaises(ValueError): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_conflicting_id_and_raw_bytes_are_never_acknowledged(self):
        self.observe(True); before = (self.state / 'state.json').read_bytes()
        target = self.destination / 'records' / self.relative
        target.parent.mkdir(parents=True)
        doc = copy.deepcopy(self.doc); doc['entry']['title'] = 'Different immutable bytes'
        target.write_text(json.dumps(doc)); self.commit(self.destination)
        with self.assertRaises(ValueError): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)
        target.unlink()
        doc.update(date='2026-11-06'); doc['entry']['timestamp'] = '2026-11-06T12:00:00-06:00'
        other = self.destination / ('records/2026/11/2026-11-06-12-00-00-' + doc['entry']['id'] + '.json')
        other.write_text(json.dumps(doc)); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'ID collision'): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_provenance_overlay_must_also_be_canonical_before_watermark(self):
        self.doc['schema_version'] = 2; self.doc['entry'].pop('provenance')
        self.record.write_text(json.dumps(self.doc))
        uid = self.doc['entry']['id']
        overlay = {'schema_version': 1, 'kind': 'provenance_backfill', 'entry_id': uid,
            'ledger': 'Brain-Bridge/' + self.relative, 'ledger_sha256': hashlib.sha256(self.record.read_bytes()).hexdigest(),
            'recorded_at': '2026-11-03T12:00:00+00:00', 'attribution_source': 'Synthetic attribution',
            'provenance': {'users': [], 'repositories': [], 'issues': [], 'workflow_runs': []}}
        path = self.source / 'Brain-Bridge/metadata' / (hashlib.sha256(uid.encode()).hexdigest() + '.json')
        path.parent.mkdir(); path.write_text(json.dumps(overlay)); self.commit(self.source)
        first = self.observe(True)
        self.assertEqual(first['pending']['overlays'], 1)
        self.integrate_synthetic(first, lambda item: item['kind'] == 'record')
        second = self.observe(True)
        self.assertEqual(second['pending']['records'], 0); self.assertEqual(second['pending']['overlays'], 1)
        self.assertIsNone(second['verified_watermark'])
        self.integrate_synthetic(second)
        final = self.observe(True)
        self.assertEqual(final['status'], 'caught_up'); self.assertEqual(final['verified_watermark']['counts']['overlays'], 1)

    def test_denial_and_invalid_execution_do_not_initialize_state(self):
        self.destination_private = False
        for persist in (False, True):
            with self.subTest(persist=persist), self.assertRaises(AccessDenied): self.observe(persist)
        self.assertFalse(self.state.exists())
        with self.assertRaises(ValueError):
            reconcile(self.source, self.destination, '11', '22', execute=True, authority=self.authority())
        self.assertFalse(self.state.exists())

    def test_readonly_checkpoint_observation_never_initializes_lock_bytes(self):
        self.observe(True)
        path = self.state / 'state.lock'; path.write_bytes(b'')
        before = (self.state / 'state.json').read_bytes()
        if os.name == 'nt':
            with self.assertRaisesRegex(ValueError, 'uninitialized'): self.observe()
        else:
            self.assertFalse(self.observe()['state_written'])
        self.assertEqual(path.read_bytes(), b'')
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_shared_lock_contention_preserves_checkpoint(self):
        self.observe(True); before = (self.state / 'state.json').read_bytes()
        with _lock(self.state, False):
            with self.assertRaisesRegex(RuntimeError, 'locked by another worker'): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_bounded_poll_wait_releases_lock_and_observes_arrival(self):
        waited = []
        def wait(seconds):
            waited.append(seconds)
            with _lock(self.state, False): pass
            self.append_source()
        results = list(poll_reconciliation(self.source, self.destination, '11', '22',
            state_dir=self.state, execute=True, yes=True, authority=self.authority(), cycles=2, wait=wait))
        self.assertEqual(waited, [60])
        self.assertEqual([row['pending']['records'] for row in results], [1, 2])
        self.assertEqual([row['cycle'] for row in results], [1, 2])
        self.assertTrue(all(row['stream'] == 'jsonl' for row in results))

    def test_state_inside_any_identity_git_checkout_or_corrupt_state_fails_closed(self):
        identity = self.root / 'identity'; identity.mkdir(); fixtures.git(identity, 'init', '-q')
        with self.assertRaisesRegex(ValueError, 'outside Git'):
            reconcile(self.source, self.destination, '11', '22', state_dir=identity / 'checkpoint', authority=self.authority())
        with self.assertRaisesRegex(ValueError, 'outside Git'):
            reconcile(self.source, self.destination, '11', '22', state_dir=self.source.resolve() / '.git' / 'checkpoint', authority=self.authority())
        self.observe(True)
        path = self.state / 'state.json'; value = json.loads(path.read_text())
        value['pending'] = []; path.write_text(json.dumps(value))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'token/source binding'): self.observe(True)
        self.assertEqual(path.read_bytes(), before)

    def test_pending_review_branch_does_not_advance_canonical_watermark(self):
        first = self.observe(True)
        fixtures.git(self.destination, 'checkout', '-qb', 'synthetic-pending-review')
        self.integrate_synthetic(first)
        fixtures.git(self.destination, 'checkout', '-q', 'main')
        second = self.observe(True)
        self.assertEqual(second['pending']['records'], 1)
        self.assertIsNone(second['verified_watermark'])
        self.assertEqual(second['destination']['commit'], first['destination']['commit'])

    def test_force_rewritten_source_ancestry_is_rejected(self):
        self.observe(True); before = (self.state / 'state.json').read_bytes()
        fixtures.git(self.source, 'checkout', '--orphan', 'synthetic-rewrite')
        self.commit(self.source)
        fixtures.git(self.source, 'branch', '-f', 'main', 'HEAD')
        fixtures.git(self.source, 'checkout', '-q', 'main')
        with self.assertRaises((AccessDenied, ValueError)): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_destination_only_native_deletion_is_detected(self):
        native = self.append_native(); self.observe(True)
        before = (self.state / 'state.json').read_bytes()
        native.unlink(); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'between observations'): self.observe(True)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_locally_tampered_capture_cannot_forge_newer_watermark(self):
        first = self.observe(True)
        self.append_source(); self.observe(True)
        self.integrate_synthetic(first)
        path = self.state / 'state.json'; value = json.loads(path.read_text())
        # Recomputing a local token is not evidence that all newer source files
        # belonged to this older one-file capture or reached canonical main.
        value['captures'][0]['source_commit'] = value['observed_source']['commit']
        body = dict(value); body.pop('token'); value['token'] = digest(body)
        path.write_text(json.dumps(value)); before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Captured source snapshot'):
            self.observe(True)
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_poll_bounds_make_no_provider_calls(self):
        with patch('brain_bridge.reconciliation.plan_migration') as planner:
            for cycles, interval in ((0, 60), (1001, 60), (True, 60), (2, 0), (2, float('nan'))):
                with self.subTest(cycles=cycles, interval=interval), self.assertRaises(ValueError):
                    list(poll_reconciliation('source', 'destination', '11', '22', cycles=cycles, interval=interval))
            planner.assert_not_called()


if __name__ == '__main__': unittest.main()
