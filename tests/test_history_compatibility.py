# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Only committed exact-hash historical pins may adapt validation, never bytes."""
import hashlib
import json
import unittest
from brain_bridge.authority import Grant
from brain_bridge.contract import validate_record, validate_history, ContractError
from brain_bridge.managed import immutable_snapshot
import test_migration as fixtures


class HistoryCompatibilityTests(unittest.TestCase):
    setUp = fixtures.MigrationTests.setUp

    def commit(self):
        fixtures.git(self.source, 'add', '.')
        fixtures.git(self.source, 'commit', '-qm', 'synthetic historical pin')

    def snapshot(self):
        commit = fixtures.git(self.source, 'rev-parse', 'HEAD')
        return immutable_snapshot(self.source, Grant('test', '11', 'example/source', commit, 'main'), 'Brain-Bridge')

    def legacy(self):
        self.doc['entry']['provenance']['issues'] = [{'provider':'github', 'host':'github.com', 'repository':'example/source', 'number':12}]
        self.record.write_text(json.dumps(self.doc))
        self.commit()
        descriptor = self.source / '.brain-bridge/history-compatibility.json'
        descriptor.parent.mkdir(exist_ok=True)
        descriptor.write_text(json.dumps({'schema_version':1, 'records':[{'path':'Brain-Bridge/'+self.relative, 'sha256':hashlib.sha256(self.record.read_bytes()).hexdigest(), 'kind':'legacy_github_issue_shape'}]}))
        return descriptor

    def test_committed_pin_preserves_original_and_strict_new_writes(self):
        descriptor = self.legacy()
        with self.assertRaises(ValueError): self.snapshot()
        self.commit()
        raw = self.record.read_bytes()
        original = self.snapshot()['records'][0][2]
        self.assertEqual(original, self.doc)
        self.assertEqual(original['entry']['provenance']['issues'][0]['number'], 12)
        self.assertNotIn('relationship', original['entry']['provenance']['issues'][0])
        with self.assertRaises(ValueError): validate_record(original, 'Brain-Bridge/'+self.relative)
        self.assertEqual(self.record.read_bytes(), raw)
        descriptor.write_text('{}')
        self.assertEqual(self.snapshot()['records'][0][2], original)

    def test_changed_hash_and_unknown_configuration_fail_closed(self):
        descriptor = self.legacy(); self.commit()
        self.doc['entry']['title'] = 'Changed immutable bytes'
        self.record.write_text(json.dumps(self.doc)); self.commit()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): self.snapshot()
        descriptor.write_text(json.dumps({'schema_version':1,'records':[], 'unexpected':True})); self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_duplicate_keys_and_symlink_configuration_rejected(self):
        descriptor = self.legacy()
        descriptor.write_text('{"schema_version":1,"schema_version":1,"records":[]}'); self.commit()
        with self.assertRaises(ValueError): self.snapshot()
        descriptor.unlink()
        try: descriptor.symlink_to('../synthetic.json')
        except OSError: self.skipTest('Symlinks unavailable')
        self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def analysis_pin(self, kind='legacy_analysis_object'):
        self.doc['entry']['analysis'] = {'summary': 'Synthetic frozen object analysis'}
        self.record.write_text(json.dumps(self.doc)); self.commit()
        descriptor = self.source / '.brain-bridge/history-compatibility.json'
        descriptor.parent.mkdir(exist_ok=True)
        descriptor.write_text(json.dumps({'schema_version': 1, 'records': [{
            'path': 'Brain-Bridge/' + self.relative,
            'sha256': hashlib.sha256(self.record.read_bytes()).hexdigest(), 'kind': kind}]}))
        self.commit()
        return descriptor

    def test_analysis_object_pin_preserves_original_and_new_writes_stay_strict(self):
        descriptor = self.analysis_pin()
        raw = self.record.read_bytes()
        original = self.snapshot()['records'][0][2]
        self.assertEqual(original, self.doc)
        self.assertIsInstance(original['entry']['analysis'], dict)
        self.assertEqual(self.record.read_bytes(), raw)
        with self.assertRaises(ValueError): validate_record(original)
        doc = json.loads(descriptor.read_text()); doc['records'][0]['sha256'] = '0' * 64
        descriptor.write_text(json.dumps(doc)); self.commit()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): self.snapshot()

    def test_pin_kinds_do_not_enable_each_others_adaptations(self):
        self.analysis_pin('legacy_github_issue_shape')
        with self.assertRaises(ValueError): self.snapshot()
        descriptor = self.source / '.brain-bridge/history-compatibility.json'
        self.doc['entry']['analysis'] = {'summary': 'Synthetic object with invalid issue evidence'}
        self.doc['entry']['provenance']['issues'] = [{'host': 'github.com', 'repository': 'example/source', 'number': 12}]
        self.record.write_text(json.dumps(self.doc))
        descriptor.write_text(json.dumps({'schema_version': 1, 'records': [{
            'path': 'Brain-Bridge/' + self.relative, 'sha256': hashlib.sha256(self.record.read_bytes()).hexdigest(),
            'kind': 'legacy_analysis_object'}]})); self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_analysis_pin_requires_object_shape_like_the_legacy_reader(self):
        self.assertIsInstance(self.doc['entry']['analysis'], list)
        with self.assertRaisesRegex(ContractError, 'historical object'):
            validate_history(self.doc, legacy_analysis_object=True)

    def test_malformed_pinned_entry_is_contract_error_without_attribute_failure(self):
        for flag in ('legacy_analysis_object', 'legacy_github_issue_shape'):
            for malformed in (None, [], 'not-an-entry', 7):
                with self.subTest(flag=flag, malformed=malformed):
                    self.doc['entry'] = malformed
                    before = json.dumps(self.doc)
                    with self.assertRaises(ContractError): validate_history(self.doc, **{flag: True})
                    self.assertEqual(json.dumps(self.doc), before)
