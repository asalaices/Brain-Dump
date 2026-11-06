# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Real published Git advances refresh separate clean readers without remote writes."""
import copy
import hashlib
import importlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from brain_bridge.migration import repo_facts, repo_metadata
from brain_bridge.policy import AccessDenied
from brain_bridge.reconciliation import reconcile, poll_reconciliation
from brain_bridge.sync import SyncError
import test_migration as fixtures

sync_module = importlib.import_module('brain_bridge.sync')


class RefreshTests(unittest.TestCase):
    authority = fixtures.MigrationTests.authority

    def setUp(self):
        fixtures.MigrationTests.setUp(self)
        self.root = self.root.resolve()
        identity = self.destination / '.brain-bridge/identity.json'
        identity.parent.mkdir()
        identity.write_text(json.dumps({'schema_version': 1, 'instance_uuid': '99999999-9999-4999-8999-999999999999', 'github_repository_id': '22'}))
        self.commit(self.destination)
        self.bare = {}
        self.readers = {}
        for role, writer in (('source', self.source), ('destination', self.destination)):
            bare = self.root / (role + '.git')
            self.command('clone', '--bare', str(writer), str(bare))
            reader = self.root / (role + '-reader')
            self.command('clone', '--no-local', '--branch', 'main', str(bare), str(reader))
            fixtures.git(reader, 'remote', 'set-url', 'origin', 'https://github.com/example/' + role + '.git')
            self.bare[role] = bare; self.readers[role] = reader
        self.state = self.root / 'private-refresh-state'
        self.actual_git = sync_module._git_bytes
        self.fetches = []

    def command(self, *args):
        return subprocess.check_output(['git', *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self, repo):
        fixtures.git(repo, 'add', '.')
        fixtures.git(repo, 'commit', '-qm', 'Synthetic published refresh fixture')

    def api(self, endpoint):
        if '/commits/' in endpoint:
            role = 'source' if endpoint.startswith('repos/example/source/') else 'destination'
            return {'sha': fixtures.git(self.bare[role], 'rev-parse', 'refs/heads/main')}
        return fixtures.MigrationTests.api(self, endpoint)

    def transport(self, repo, *args):
        if args and args[0] == 'fetch':
            self.assertEqual(args, ('fetch', '--no-tags', 'origin', 'main'))
            role = next(role for role, reader in self.readers.items() if reader.resolve() == Path(repo).resolve())
            self.fetches.append(role)
            # Only transport is replaced: origin metadata, fetched objects,
            # expected SHA, immutable validation and actual FF are all real.
            return self.actual_git(repo, 'fetch', '--no-tags', str(self.bare[role]), 'main')
        return self.actual_git(repo, *args)

    def observe(self, refresh=True):
        with patch('brain_bridge.sync._git_bytes', side_effect=self.transport):
            return reconcile(self.readers['source'], self.readers['destination'], '11', '22',
                             state_dir=self.state, execute=True, yes=True, refresh=refresh, authority=self.authority())

    def publish_source_append(self):
        doc = copy.deepcopy(self.doc); doc.update(date='2026-11-03')
        doc['entry'].update(id='22222222-2222-4222-8222-222222222222', timestamp='2026-11-03T12:00:00-06:00')
        path = self.source / 'Brain-Bridge/2026/11/2026-11-03-12-00-00-22222222-2222-4222-8222-222222222222.json'
        path.write_text(json.dumps(doc)); self.commit(self.source)
        fixtures.git(self.source, 'push', str(self.bare['source']), 'main')
        return fixtures.git(self.source, 'rev-parse', 'HEAD')

    def publish_destination_native(self):
        doc = copy.deepcopy(self.doc); doc.update(date='2026-11-05')
        doc['entry'].update(id='99999999-9999-4999-8999-999999999999', timestamp='2026-11-05T12:00:00-06:00')
        path = self.destination / 'records/2026/11/2026-11-05-12-00-00-99999999-9999-4999-8999-999999999999.json'
        path.parent.mkdir(parents=True); path.write_text(json.dumps(doc)); self.commit(self.destination)
        fixtures.git(self.destination, 'push', str(self.bare['destination']), 'main')
        return fixtures.git(self.destination, 'rev-parse', 'HEAD')

    def test_metadata_can_authorize_missing_object_but_default_facts_cannot(self):
        expected = self.publish_source_append()
        reader = self.readers['source']; before = fixtures.git(reader, 'rev-parse', 'HEAD')
        facts, _ = repo_metadata(reader, '11', 'main', self.authority())
        self.assertEqual(facts['commit'], expected)
        with self.assertRaises((AccessDenied, ValueError)): repo_facts(reader, '11', 'main', self.authority())
        self.assertEqual(fixtures.git(reader, 'rev-parse', 'HEAD'), before)
        self.assertEqual(self.fetches, [])

    def test_next_poll_fetches_source_append_and_destination_native_advance(self):
        published = {}
        def wait(seconds):
            self.assertEqual(seconds, 60)
            published['source'] = self.publish_source_append()
            published['destination'] = self.publish_destination_native()
            for role in self.readers:
                self.assertNotEqual(fixtures.git(self.readers[role], 'rev-parse', 'HEAD'), published[role])
        with patch('brain_bridge.sync._git_bytes', side_effect=self.transport):
            rows = list(poll_reconciliation(self.readers['source'], self.readers['destination'], '11', '22',
                state_dir=self.state, execute=True, yes=True, refresh=True, authority=self.authority(), cycles=2, wait=wait))
        self.assertEqual([row['pending']['records'] for row in rows], [1, 2])
        self.assertEqual(rows[1]['destination_only']['records'], 1)
        for role in self.readers:
            self.assertEqual(fixtures.git(self.readers[role], 'rev-parse', 'HEAD'), published[role])
        self.assertTrue(rows[1]['readers_refreshed']); self.assertIsNone(rows[1]['verified_watermark'])
        self.assertEqual(rows[1]['captured_snapshots'], 2)
        self.assertFalse((self.state / 'unused-reader-index.sqlite').exists())
        self.assertEqual(self.fetches, ['source', 'destination', 'source', 'destination'])

    def test_refresh_requires_all_execution_flags_before_provider_access(self):
        with patch('brain_bridge.reconciliation.repo_metadata') as metadata:
            for execute, yes, state in ((False, False, self.state), (True, False, self.state), (True, True, None)):
                with self.subTest(execute=execute, yes=yes, state=state), self.assertRaises(ValueError):
                    reconcile(self.readers['source'], self.readers['destination'], '11', '22',
                              refresh=True, execute=execute, yes=yes, state_dir=state, authority=self.authority())
            metadata.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_dirty_destination_blocks_both_fastforwards(self):
        source_before = fixtures.git(self.readers['source'], 'rev-parse', 'HEAD')
        self.publish_source_append()
        dirty = self.readers['destination'] / 'owner-work.txt'; dirty.write_text('Preserve owner work')
        with self.assertRaises(SyncError): self.observe()
        self.assertEqual(fixtures.git(self.readers['source'], 'rev-parse', 'HEAD'), source_before)
        self.assertEqual(self.fetches, []); self.assertEqual(dirty.read_text(), 'Preserve owner work')
        self.assertFalse((self.state / 'state.json').exists())

    def test_wrong_origin_and_wrong_numeric_identity_never_fetch_or_ff(self):
        before = fixtures.git(self.readers['source'], 'rev-parse', 'HEAD')
        self.publish_source_append()
        fixtures.git(self.readers['source'], 'remote', 'set-url', 'origin', 'file:///untrusted-source.git')
        with self.assertRaises(AccessDenied): self.observe()
        self.assertEqual(self.fetches, [])
        fixtures.git(self.readers['source'], 'remote', 'set-url', 'origin', 'https://github.com/example/source.git')
        with self.assertRaises(AccessDenied):
            reconcile(self.readers['source'], self.readers['destination'], '999', '22',
                state_dir=self.state, execute=True, yes=True, refresh=True, authority=self.authority())
        self.assertEqual(fixtures.git(self.readers['source'], 'rev-parse', 'HEAD'), before)
        self.assertFalse((self.state / 'state.json').exists())

    def test_wrong_advertised_commit_or_drift_never_updates_checkpoint(self):
        self.observe(); before = (self.state / 'state.json').read_bytes()
        old_head = fixtures.git(self.readers['source'], 'rev-parse', 'HEAD')
        advertised = self.publish_source_append()
        # Local bare transport intentionally serves the old tip despite a new
        # authenticated API SHA. The expected-commit sync guard must reject it.
        fixtures.git(self.bare['source'], 'update-ref', 'refs/heads/main', old_head, advertised)
        original_api = self.api
        def api(endpoint):
            if endpoint.startswith('repos/example/source/commits/'): return {'sha': advertised}
            return original_api(endpoint)
        with patch.object(self, 'api', side_effect=api):
            with self.assertRaises(SyncError): self.observe()
        self.assertEqual(fixtures.git(self.readers['source'], 'rev-parse', 'HEAD'), old_head)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_auth_target_drift_before_ff_leaves_state_and_head_unchanged(self):
        self.observe(); before = (self.state / 'state.json').read_bytes()
        old_head = fixtures.git(self.readers['source'], 'rev-parse', 'HEAD')
        self.publish_source_append()
        original = self.transport; changed = False
        def drift(repo, *args):
            nonlocal changed
            result = original(repo, *args)
            if args and args[0] == 'fetch' and not changed:
                changed = True
                (self.source / 'new-published-note').write_text('Synthetic target drift')
                self.commit(self.source); fixtures.git(self.source, 'push', str(self.bare['source']), 'main')
            return result
        with patch('brain_bridge.sync._git_bytes', side_effect=drift):
            with self.assertRaises(AccessDenied):
                reconcile(self.readers['source'], self.readers['destination'], '11', '22', state_dir=self.state,
                          execute=True, yes=True, refresh=True, authority=self.authority())
        self.assertEqual(fixtures.git(self.readers['source'], 'rev-parse', 'HEAD'), old_head)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_invalid_remote_history_is_rejected_before_reader_ff(self):
        self.observe(); before = (self.state / 'state.json').read_bytes()
        old_head = fixtures.git(self.readers['source'], 'rev-parse', 'HEAD')
        self.doc['entry']['analysis'] = {'unreviewed': 'No compatibility pin'}
        self.record.write_text(json.dumps(self.doc)); self.commit(self.source)
        fixtures.git(self.source, 'push', str(self.bare['source']), 'main')
        with self.assertRaises(ValueError): self.observe()
        self.assertEqual(fixtures.git(self.readers['source'], 'rev-parse', 'HEAD'), old_head)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_observed_remote_rewrite_is_rejected_before_reader_ff(self):
        self.observe(); before = (self.state / 'state.json').read_bytes()
        old_head = fixtures.git(self.readers['source'], 'rev-parse', 'HEAD')
        self.doc['entry']['title'] = 'Prohibited rewrite of captured published record'
        self.record.write_text(json.dumps(self.doc)); self.commit(self.source)
        fixtures.git(self.source, 'push', str(self.bare['source']), 'main')
        with self.assertRaisesRegex(ValueError, 'between observations'): self.observe()
        self.assertEqual(fixtures.git(self.readers['source'], 'rev-parse', 'HEAD'), old_head)
        self.assertEqual((self.state / 'state.json').read_bytes(), before)

    def test_brain_bridge_pin_aware_history_validates_before_fastforward(self):
        self.doc['entry']['analysis'] = {'summary': 'Synthetic historical shape'}
        self.record.write_text(json.dumps(self.doc))
        config = self.source / '.brain-bridge/history-compatibility.json'; config.parent.mkdir()
        config.write_text(json.dumps({'schema_version': 1, 'records': [{
            'path': 'Brain-Bridge/' + self.relative, 'sha256': hashlib.sha256(self.record.read_bytes()).hexdigest(),
            'kind': 'legacy_analysis_object'}]}))
        self.commit(self.source); fixtures.git(self.source, 'push', str(self.bare['source']), 'main')
        result = self.observe()
        self.assertTrue(result['readers_refreshed'])
        self.assertEqual((self.readers['source'] / 'Brain-Bridge' / self.relative).read_bytes(), self.record.read_bytes())


if __name__ == '__main__': unittest.main()
