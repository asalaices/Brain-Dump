# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Only committed exact-hash historical pins may adapt validation, never bytes."""
import hashlib
import json
import unittest
from brain_bridge.authority import Grant
from brain_bridge.contract import validate_record
from brain_bridge.managed import immutable_snapshot
from tests import test_migration as fixtures


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
