# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Historical exceptions require a separate reviewed BASE and exact whole batch."""
import copy
import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from brain_bridge.authority import Grant
from brain_bridge.adapters import managed_create
from brain_bridge.contract import validate_record
from brain_bridge.historical_import import plan_import, validate_manifest, PREFIX
from brain_bridge.managed import immutable_snapshot, managed_index, managed_search, object_bytes
from brain_bridge.migration import digest
from brain_bridge.policy import AccessDenied
from brain_bridge.validation import validate_source
import test_migration as fixtures


class HistoricalImportTests(unittest.TestCase):
    api = fixtures.MigrationTests.api
    authority = fixtures.MigrationTests.authority

    def setUp(self):
        fixtures.MigrationTests.setUp(self)
        self.root = self.root.resolve()
        identity = self.destination / '.brain-bridge/identity.json'
        identity.parent.mkdir()
        identity.write_text(json.dumps({'schema_version': 1,
            'instance_uuid': '99999999-9999-4999-8999-999999999999', 'github_repository_id': '22'}))
        self.commit(self.destination)
        self.destination_base = fixtures.git(self.destination, 'rev-parse', 'HEAD')
        # Frozen v3 object analysis needs an exact, distinct pin.
        self.doc['entry']['analysis'] = {'summary': 'Synthetic frozen analysis object'}
        self.record.write_text(json.dumps(self.doc))
        self.source_paths = [self.record]
        first = copy.deepcopy(self.doc['entry'])
        first.update(id='legacy-synthetic-1', timestamp='2026-11-01T12:00:00-06:00', analysis='Historical prose')
        first.pop('provenance')
        other = copy.deepcopy(first); other['id'] = 'legacy-synthetic-2'
        historical = {'schema_version': 1, 'date': '2026-11-01', 'timezone': 'America/Chicago', 'entries': [first, other]}
        legacy = self.source / 'Brain-Bridge/2026/11/2026-11-01.json'
        legacy.write_text(json.dumps(historical)); self.source_paths.append(legacy)
        v2 = copy.deepcopy(self.doc)
        v2.update(schema_version=2, date='2026-11-03')
        v2['entry'].update(id='33333333-3333-4333-8333-333333333333', timestamp='2026-11-03T12:00:00-06:00')
        v2['entry'].pop('provenance')
        v2_path = self.source / 'Brain-Bridge/2026/11/2026-11-03-12-00-00-33333333-3333-4333-8333-333333333333.json'
        v2_path.write_text(json.dumps(v2)); self.source_paths.append(v2_path)
        provenance = {'users': [], 'repositories': [], 'issues': [], 'workflow_runs': []}
        overlay = {'schema_version': 1, 'kind': 'provenance_backfill', 'entry_id': first['id'],
            'ledger': 'Brain-Bridge/2026/11/2026-11-01.json', 'ledger_sha256': hashlib.sha256(legacy.read_bytes()).hexdigest(),
            'recorded_at': '2026-11-03T12:00:00+00:00', 'attribution_source': 'Synthetic explicit attribution',
            'provenance': provenance}
        overlay_path = self.source / 'Brain-Bridge/metadata' / (hashlib.sha256(first['id'].encode()).hexdigest() + '.json')
        overlay_path.parent.mkdir(); overlay_path.write_text(json.dumps(overlay))
        self.source_paths.append(overlay_path)
        pins = {'schema_version': 1, 'records': [{'path': 'Brain-Bridge/' + self.relative,
            'sha256': hashlib.sha256(self.record.read_bytes()).hexdigest(), 'kind': 'legacy_analysis_object'}]}
        config = self.source / '.brain-bridge/history-compatibility.json'
        config.parent.mkdir(); config.write_text(json.dumps(pins))
        self.commit(self.source)
        self.proposal = self.plan()

    def commit(self, repo):
        fixtures.git(repo, 'add', '.')
        fixtures.git(repo, 'commit', '-qm', 'Synthetic reviewed import fixture')

    def plan(self):
        return plan_import(self.source, self.destination, '11', '22', authority=self.authority())

    def retoken(self, manifest):
        body = dict(manifest); body.pop('manifest_token')
        value = {**body, 'manifest_token': digest(body)}
        return {'manifest': value, 'manifest_path': PREFIX + value['manifest_token'] + '.json'}

    def authorize(self, proposal=None, pins=True):
        proposal = self.proposal if proposal is None else proposal
        path = self.destination / proposal['manifest_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proposal['manifest']))
        if pins:
            config = self.destination / '.brain-bridge/history-compatibility.json'
            config.write_text(json.dumps({'schema_version': 1, 'records': proposal['manifest']['compatibility']}))
        self.commit(self.destination)
        return fixtures.git(self.destination, 'rev-parse', 'HEAD')

    def prepare_payload(self, proposal=None, omit=None):
        value = (proposal or self.proposal)['manifest']
        for item in value['files']:
            if item['target_path'] == omit: continue
            raw = object_bytes(self.source, 'show', value['source']['commit'] + ':' + item['source_path'])
            path = self.destination / item['target_path']
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def test_planner_is_authenticated_read_only_and_stable(self):
        before_source = fixtures.git(self.source, 'rev-parse', 'HEAD')
        index = (self.destination / '.git/index').read_bytes()
        self.assertEqual(self.plan(), self.proposal)
        self.assertTrue(self.proposal['read_only']); self.assertFalse(self.proposal['executed'])
        self.assertTrue(self.proposal['requires_reviewed_base'])
        self.assertFalse((self.destination / self.proposal['manifest_path']).exists())
        self.assertEqual((self.destination / '.git/index').read_bytes(), index)
        self.assertEqual(fixtures.git(self.source, 'rev-parse', 'HEAD'), before_source)
        self.assertEqual(self.proposal['manifest']['compatibility'][0]['kind'], 'legacy_analysis_object')

    def test_complete_reviewed_mixed_schema_batch_and_overlay_pass_without_source_credentials(self):
        base = self.authorize()
        stage1 = validate_source(self.destination, self.destination_base)
        self.assertFalse(stage1['historical_import'])
        self.prepare_payload(); self.commit(self.destination)
        with patch('brain_bridge.authority.GitHubAuthority.api', side_effect=AssertionError('CI cannot use provider credentials')):
            result = validate_source(self.destination, base)
        self.assertTrue(result['historical_import'])
        self.assertEqual(result['new_records'], 3); self.assertEqual(result['new_overlays'], 1)
        self.assertEqual(result['import_manifest_token'], self.proposal['manifest']['manifest_token'])
        for item in self.proposal['manifest']['files']:
            self.assertEqual((self.destination / item['target_path']).read_bytes(),
                             (self.source / item['source_path']).read_bytes())
        grant = Grant('synthetic', '22', 'example/destination', fixtures.git(self.destination, 'rev-parse', 'HEAD'), 'main', 'f' * 64, 'primary')
        class Reader:
            def snapshot(self, *args): return grant
        cache = self.root / 'cache'
        managed_index('identity', self.destination, cache, Reader())
        json_result = managed_search('identity', self.destination, 'frozen analysis', cache, 'json', Reader())
        sqlite_result = managed_search('identity', self.destination, 'frozen analysis', cache, 'sqlite', Reader())
        self.assertEqual(json_result['results'], sqlite_result['results'])
        self.assertEqual(json_result['results'][0]['pointer'], '/entry/analysis/summary')
        self.assertEqual(json.loads(self.record.read_text())['entry']['analysis'], {'summary': 'Synthetic frozen analysis object'})
        with self.assertRaises(ValueError): validate_record(self.doc)
        authored = copy.deepcopy(self.doc['entry'])
        authored.update(id='22222222-2222-4222-8222-222222222222', timestamp='2026-11-04T12:00:00-06:00', analysis=[])
        authored['context']['coverage_since'] = {'entry_id': self.doc['entry']['id'],
            'timestamp': self.doc['entry']['timestamp'], 'commit': grant.commit, 'ledger': 'Brain-Bridge/' + self.relative}
        entry_file = self.root / 'new-authored-entry.json'; entry_file.write_text(json.dumps(authored))
        draft = self.root / 'draft.json'
        planned = managed_create(self.destination, self.destination, 'primary', entry_file, draft, authority=Reader())
        self.assertEqual(planned['status'], 'plan'); self.assertFalse(draft.exists())

    def test_candidate_cannot_authorize_its_own_payload(self):
        self.prepare_payload(); self.authorize()
        with self.assertRaisesRegex(ValueError, 'reviewed before'):
            validate_source(self.destination, self.destination_base)

    def test_partial_extra_and_wrong_hash_batches_fail(self):
        base = self.authorize()
        omitted = self.proposal['manifest']['files'][0]['target_path']
        self.prepare_payload(omit=omitted); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'complete approved payload'):
            validate_source(self.destination, base)
        self.prepare_payload()
        target = self.destination / self.proposal['manifest']['files'][0]['target_path']
        target.write_bytes(target.read_bytes() + b' '); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'bytes/path/mode'):
            validate_source(self.destination, base)
        self.prepare_payload()
        (self.destination / 'records/2026/11/extra.json').write_text('{}'); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'complete approved payload'):
            validate_source(self.destination, base)

    def test_import_pr_cannot_edit_trust_workflow_pins_or_authorization(self):
        base = self.authorize(); self.prepare_payload()
        config = self.destination / '.brain-bridge/trust.json'
        config.write_text('{"unrelated":"policy change"}'); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'only its complete approved payload'):
            validate_source(self.destination, base)

    def test_changed_destination_ledger_requires_fresh_review(self):
        base = self.authorize()
        (self.destination / 'records/.new-immutable-note').write_text('Changed destination inventory')
        self.commit(self.destination)
        base = fixtures.git(self.destination, 'rev-parse', 'HEAD')
        self.prepare_payload(); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'ledger advanced'):
            validate_source(self.destination, base)

    def test_missing_identity_or_wrong_origin_prevents_authorized_import(self):
        base = self.authorize(); self.prepare_payload(); self.commit(self.destination)
        fixtures.git(self.destination, 'remote', 'set-url', 'origin', 'https://github.com/example/another-source.git')
        with self.assertRaises(AccessDenied): validate_source(self.destination, base)
        fixtures.git(self.destination, 'remote', 'set-url', 'origin', 'https://github.com/example/destination.git')
        # Identity at HEAD is not authority; the BASE identity is what is bound.
        fixtures.git(self.destination, 'checkout', base)
        identity = self.destination / '.brain-bridge/identity.json'; identity.unlink(); self.commit(self.destination)
        base = fixtures.git(self.destination, 'rev-parse', 'HEAD')
        self.prepare_payload(); self.commit(self.destination)
        with self.assertRaises(ValueError): validate_source(self.destination, base)

    def test_exact_compatibility_must_already_be_reviewed_in_base(self):
        base = self.authorize(pins=False); self.prepare_payload(); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'compatibility pins reviewed in BASE'):
            validate_source(self.destination, base)

    def test_authorized_file_mode_and_ids_are_verified(self):
        bad = copy.deepcopy(self.proposal['manifest'])
        bad['files'][0]['entry_ids'][0] = 'different-reviewed-id'
        proposal = self.retoken(bad)
        base = self.authorize(proposal); self.prepare_payload(proposal); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'identities/schema'):
            validate_source(self.destination, base)

    def test_malformed_duplicate_unknown_and_traversal_manifest_fields_fail(self):
        original = self.proposal['manifest']
        mutations = [lambda value: value.update(allow_any=True),
                     lambda value: value['files'][0].update(target_path='../outside.json'),
                     lambda value: value['files'][0].update(bytes=True),
                     lambda value: value['files'].append(copy.deepcopy(value['files'][0])),
                     lambda value: value['compatibility'][0].update(kind='allow_everything')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = copy.deepcopy(original); mutate(value)
                proposal = self.retoken(value)
                with self.assertRaises((ValueError, AccessDenied)):
                    validate_manifest(proposal['manifest'], proposal['manifest_path'])
        value = copy.deepcopy(original); value['source']['commit'] = 'a' * 40
        with self.assertRaisesRegex(ValueError, 'content token'):
            validate_manifest(value, self.proposal['manifest_path'])

    def test_authorization_stage_cannot_bundle_trust_or_workflow_changes(self):
        self.authorize()
        (self.destination / '.brain-bridge/trust.json').write_text('{"unrelated":"grant change"}')
        self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'authorization controls and exact history pins'):
            validate_source(self.destination, self.destination_base)

    def test_reviewed_authorization_bytes_and_existence_are_immutable(self):
        base = self.authorize()
        path = self.destination / self.proposal['manifest_path']
        path.write_bytes(path.read_bytes() + b' '); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'may not change or disappear'):
            validate_source(self.destination, base)
        path.unlink(); self.commit(self.destination)
        with self.assertRaisesRegex(ValueError, 'may not change or disappear'):
            validate_source(self.destination, base)

    def test_import_git_mode_must_match_exact_authorization(self):
        base = self.authorize(); self.prepare_payload(); self.commit(self.destination)
        target = self.proposal['manifest']['files'][0]['target_path']
        fixtures.git(self.destination, 'update-index', '--chmod=+x', target)
        fixtures.git(self.destination, 'commit', '-qm', 'Synthetic wrong imported executable mode')
        with self.assertRaisesRegex(ValueError, 'bytes/path/mode'):
            validate_source(self.destination, base)

    def test_duplicate_and_oversized_control_documents_are_rejected(self):
        path = self.destination / self.proposal['manifest_path']
        path.parent.mkdir(parents=True)
        original = json.dumps(self.proposal['manifest'])
        for raw in (original[:-1] + ',"kind":"historical_import"}', original + ' ' * 1048576):
            with self.subTest(size=len(raw)):
                path.write_text(raw); self.commit(self.destination)
                with self.assertRaises(ValueError):
                    validate_source(self.destination, self.destination_base)

    def test_symlink_git_manifest_is_never_an_authorization(self):
        path = self.proposal['manifest_path']
        oid = subprocess.check_output(['git', '-C', str(self.destination), 'hash-object', '-w', '--stdin'],
                                      input=b'../untrusted-control.json').decode().strip()
        fixtures.git(self.destination, 'update-index', '--add', '--cacheinfo', '120000,' + oid + ',' + path)
        fixtures.git(self.destination, 'commit', '-qm', 'Synthetic symlink control')
        with self.assertRaisesRegex(ValueError, 'regular Git blobs'):
            validate_source(self.destination, self.destination_base)

    def test_used_authorization_does_not_allow_another_historical_path(self):
        base = self.authorize(); self.prepare_payload(); self.commit(self.destination)
        self.assertTrue(validate_source(self.destination, base)['historical_import'])
        new_base = fixtures.git(self.destination, 'rev-parse', 'HEAD')
        legacy = next(item for item in self.proposal['manifest']['files'] if item['schema_version'] == 1 and item['kind'] == 'record')
        extra = self.destination / 'records/2026/11/2026-11-01-unapproved.json'
        extra.write_bytes((self.destination / legacy['target_path']).read_bytes()); self.commit(self.destination)
        with self.assertRaises(ValueError): validate_source(self.destination, new_base)

    def test_audience_expansion_and_missing_destination_identity_fail_planning(self):
        self.destination_users = [1, 99]
        with self.assertRaises(AccessDenied): self.plan()
        self.destination_users = [1]
        (self.destination / '.brain-bridge/identity.json').unlink(); self.commit(self.destination)
        with self.assertRaises(ValueError): self.plan()

    def test_manifest_from_working_files_never_authorizes_import(self):
        path = self.destination / self.proposal['manifest_path']
        path.parent.mkdir(); path.write_text(json.dumps(self.proposal['manifest']))
        self.prepare_payload()
        fixtures.git(self.destination, 'add', 'records', 'metadata')
        fixtures.git(self.destination, 'commit', '-qm', 'Synthetic payload without reviewed authorization')
        with self.assertRaises(ValueError): validate_source(self.destination, self.destination_base)


if __name__ == '__main__': unittest.main()
