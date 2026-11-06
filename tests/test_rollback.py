# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Synthetic immutable rollback audits have no mutation path."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from brain_bridge.managed import immutable_snapshot
from brain_bridge.policy import AccessDenied
from brain_bridge.rollback import plan_rollback_audit
import test_migration as fixtures
git = fixtures.git


class RollbackTests(unittest.TestCase):
    setUp = fixtures.MigrationTests.setUp
    api = fixtures.MigrationTests.api
    authority = fixtures.MigrationTests.authority

    def audit(self, authority=None):
        return plan_rollback_audit(self.source, self.destination, '11', '22',
                                   'main', 'main', authority or self.authority())

    def copy_record(self):
        path = self.destination / 'records' / self.relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.record.read_bytes())
        self.commit(self.destination)
        return path

    def commit(self, repo):
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'synthetic audit fixture')

    def state(self):
        return {str(repo): {str(path.relative_to(repo)): path.read_bytes()
                           for path in repo.rglob('*') if path.is_file()}
                for repo in (self.source, self.destination)}

    def test_parity_is_deterministic_evidence_never_resume_authorization(self):
        self.copy_record()
        before = self.state()
        audit = self.audit()
        self.assertEqual(audit, self.audit())
        self.assertEqual(audit['entries']['identical'], [self.doc['entry']['id']])
        self.assertEqual(audit['blockers'], [])
        self.assertFalse(audit['rollback_ready'])
        self.assertFalse(audit['cutover'])
        self.assertFalse(audit['executed'])
        self.assertIn('writer_quiescence_and_inflight_writes', audit['required_review'])
        self.assertTrue(audit['destination']['private'])
        self.assertEqual(audit['source']['checkout_branch'], 'main')
        self.assertFalse(audit['source']['permissions']['push'])
        self.assertEqual(before, self.state())

    def test_source_and_destination_only_and_divergence_are_explicit(self):
        uid = self.doc['entry']['id']
        self.assertEqual(self.audit()['entries']['source_only'], [uid])
        path = self.copy_record()
        other = copy.deepcopy(self.doc)
        other['entry']['title'] = 'Synthetic divergent content'
        path.write_text(json.dumps(other))
        self.commit(self.destination)
        audit = self.audit()
        self.assertEqual(audit['entries']['mismatched'], [uid])
        self.assertIn('divergent_same_id_content_requires_reconciliation', audit['blockers'])
        other['entry']['id'] = '22222222-2222-4222-8222-222222222222'
        path.unlink()
        new_path = path.with_name(path.name.replace(uid, other['entry']['id']))
        new_path.write_text(json.dumps(other))
        self.commit(self.destination)
        audit = self.audit()
        self.assertEqual(audit['entries']['destination_only'], [other['entry']['id']])
        self.assertIn('destination_only_ids_require_reconciliation', audit['blockers'])

    def test_duplicate_ids_fail_closed(self):
        self.copy_record()
        duplicate = self.destination / 'records' / '2026/11' / ('duplicate-' + self.record.name)
        duplicate.write_bytes(self.record.read_bytes())
        self.commit(self.destination)
        with self.assertRaises(ValueError):
            self.audit()

    def test_only_pinned_namespaces_are_read_and_dirty_work_is_preserved(self):
        self.copy_record()
        (self.source / 'unrelated.json').write_text('not canonical JSON')
        self.commit(self.source)
        self.record.write_text('uncommitted invalid JSON')
        (self.destination / 'unrelated.json').write_text('operator work')
        before = self.state()
        audit = self.audit()
        self.assertEqual(len(audit['entries']['identical']), 1)
        self.assertEqual(before, self.state())

    def test_private_destination_and_available_permissions_required_before_payloads(self):
        self.destination_private = False
        with patch('brain_bridge.rollback.immutable_snapshot') as reader:
            with self.assertRaises(AccessDenied):
                self.audit()
            reader.assert_not_called()
        self.destination_private = True
        base = self.api
        class API:
            def api(inner, endpoint):
                value = base(endpoint)
                if endpoint == 'repos/example/destination':
                    value.pop('permissions')
                return value
        with self.assertRaises(AccessDenied):
            self.audit(API())
        self.fail_inventory = True
        with self.assertRaises(AccessDenied):
            self.audit()

    def test_ref_audience_permission_and_privacy_drift_withhold_report(self):
        for drift in ('ref', 'audience', 'permission', 'privacy'):
            with self.subTest(drift=drift):
                counts = {}
                base = self.api
                class API:
                    def api(inner, endpoint):
                        counts[endpoint] = counts.get(endpoint, 0) + 1
                        value = base(endpoint)
                        if counts[endpoint] > 1 and endpoint.startswith('repos/example/destination'):
                            if drift == 'ref' and '/commits/' in endpoint:
                                return {'sha': 'a' * 40}
                            if drift == 'audience' and '/collaborators?' in endpoint:
                                return [{'id': 1}, {'id': 99}]
                            if endpoint == 'repos/example/destination':
                                if drift == 'permission':
                                    value['permissions']['push'] = not value['permissions']['push']
                                if drift == 'privacy':
                                    value['private'] = False
                        return value
                with self.assertRaises((AccessDenied, ValueError)):
                    self.audit(API())

    def test_numeric_identity_and_explicit_ref_scope(self):
        with self.assertRaises(AccessDenied):
            plan_rollback_audit(self.source, self.destination, '99', '22', 'main', 'main', self.authority())
        with self.assertRaises(ValueError):
            plan_rollback_audit(self.source, self.destination, '11', '22', '../main', 'main', self.authority())

    def test_overlay_differences_are_reported(self):
        self.doc['schema_version'] = 2
        self.doc['entry'].pop('provenance')
        self.record.write_text(json.dumps(self.doc))
        uid = self.doc['entry']['id']
        overlay = {'schema_version': 1, 'kind': 'provenance_backfill', 'entry_id': uid,
                   'ledger': 'Brain-Bridge/' + self.relative,
                   'ledger_sha256': hashlib.sha256(self.record.read_bytes()).hexdigest(),
                   'recorded_at': '2026-11-03T12:00:00+00:00',
                   'attribution_source': 'Synthetic explicit attribution',
                   'provenance': {'users': [], 'repositories': [], 'issues': [], 'workflow_runs': []}}
        path = self.source / 'Brain-Bridge/metadata' / (hashlib.sha256(uid.encode()).hexdigest() + '.json')
        path.parent.mkdir()
        path.write_text(json.dumps(overlay))
        self.commit(self.source)
        self.copy_record()
        audit = self.audit()
        self.assertEqual(audit['overlays']['source_only'], ['metadata/' + path.name])
        self.assertIn('provenance_overlay_differences_require_reconciliation', audit['blockers'])
        target = self.destination / 'metadata' / path.name
        target.parent.mkdir()
        target.write_bytes(path.read_bytes())
        self.commit(self.destination)
        self.assertEqual(self.audit()['overlays']['identical'], ['metadata/' + path.name])
        overlay['attribution_source'] = 'Different synthetic attribution'
        target.write_text(json.dumps(overlay))
        self.commit(self.destination)
        self.assertEqual(self.audit()['overlays']['mismatched'], ['metadata/' + path.name])


if __name__ == '__main__':
    unittest.main()
