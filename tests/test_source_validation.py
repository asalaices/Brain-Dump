# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Destination CI checks immutable Git objects, strict additions and anchors."""
import hashlib
import json
import unittest
from brain_bridge.publication import candidate
from brain_bridge.validation import validate_source
import test_publication as fixtures


class SourceValidationTests(unittest.TestCase):
    setUp = fixtures.PublicationTests.setUp

    def commit(self):
        fixtures.git(self.repo, 'add', '.')
        fixtures.git(self.repo, 'commit', '-qm', 'synthetic destination change')

    def append(self):
        _, raw, relative = candidate(self.input)
        path = self.repo / 'records' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def test_strict_addition_passes_and_loose_files_do_not_affect_receipt(self):
        self.append(); self.commit()
        before = (self.repo / '.git/index').read_bytes()
        receipt = validate_source(self.repo, self.base)
        self.assertEqual(receipt['new_records'], 1)
        self.assertTrue(receipt['history_unchanged']); self.assertFalse(receipt['executed'])
        (self.repo / 'records/loose.json').write_text('{}')
        self.assertEqual(validate_source(self.repo, self.base), receipt)
        self.assertEqual((self.repo / '.git/index').read_bytes(), before)

    def test_existing_record_edits_and_deletions_fail(self):
        path = self.repo / 'records' / self.relative
        path.write_bytes(path.read_bytes() + b' '); self.commit()
        with self.assertRaises(ValueError): validate_source(self.repo, self.base)
        path.unlink(); self.commit()
        with self.assertRaises(ValueError): validate_source(self.repo, self.base)

    def test_history_pin_cannot_relax_new_write_contract(self):
        path = self.append()
        doc = json.loads(path.read_text())
        doc['entry']['provenance']['issues'] = [{'provider':'github', 'host':'github.com', 'repository':'example/source', 'number':12}]
        path.write_text(json.dumps(doc))
        config = self.repo / '.brain-bridge/history-compatibility.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'schema_version':1,'records':[{'path':'Brain-Bridge/'+path.relative_to(self.repo/'records').as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'kind':'legacy_github_issue_shape'}]}))
        self.commit()
        with self.assertRaises(ValueError): validate_source(self.repo, self.base)

    def test_forged_anchor_and_invalid_overlay_fail(self):
        path = self.append(); doc = json.loads(path.read_text())
        doc['entry']['context']['coverage_since']['entry_id'] = 'forged'
        path.write_text(json.dumps(doc)); self.commit()
        with self.assertRaises(ValueError): validate_source(self.repo, self.base)
        path.unlink()
        metadata = self.repo / 'metadata'; metadata.mkdir()
        (metadata/'invalid.json').write_text('{}'); self.commit()
        with self.assertRaises(ValueError): validate_source(self.repo, self.base)

    def test_credentials_in_addition_fail_without_disclosing_value(self):
        path = self.append(); doc = json.loads(path.read_text())
        doc['entry']['analysis'] = ['-----BEGIN ' + 'PRIVATE KEY-----']
        path.write_text(json.dumps(doc)); self.commit()
        with self.assertRaisesRegex(ValueError, '^Potential credential material in ledger addition$'):
            validate_source(self.repo, self.base)

    def test_analysis_pin_cannot_self_authorize_a_new_write(self):
        path = self.append(); doc = json.loads(path.read_text())
        doc['entry']['analysis'] = {'summary': 'Not a canonical new-write array'}
        path.write_text(json.dumps(doc))
        config = self.repo / '.brain-bridge/history-compatibility.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'schema_version': 1, 'records': [{
            'path': 'Brain-Bridge/' + path.relative_to(self.repo / 'records').as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'kind': 'legacy_analysis_object'}]}))
        self.commit()
        with self.assertRaises(ValueError): validate_source(self.repo, self.base)

    def test_overflowing_raw_addition_fails_shared_strict_contract(self):
        path = self.append(); doc = json.loads(path.read_text())
        doc['entry']['analysis'] = [float('inf')]
        path.write_text(json.dumps(doc).replace('Infinity', '1e999')); self.commit()
        with self.assertRaisesRegex(ValueError, 'finite JSON'):
            validate_source(self.repo, self.base)
