# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Execute the shipped author/PR/retry recipe against real synthetic Git."""
import contextlib
import copy
import hashlib
import io
import json
import re
import shlex
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import test_adapters as fixtures
from test_publication import Reviews
from brain_bridge.__main__ import main, parser
from brain_bridge.policy import AccessDenied


class SubmissionRecipeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AdapterTests('test_export_latest_and_status_reauthorize_without_mutation')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.remote = f.root / 'remote.git'
        subprocess.run(['git', 'clone', '--bare', str(f.repo), str(self.remote)], check=True, capture_output=True)
        fixtures.git(f.repo, 'remote', 'add', 'origin', str(self.remote))
        self.reviews = Reviews()
        self.variables = {'$IDENTITY_REPO': str(f.identity), '$READER_REPO': str(f.repo),
            '$SOURCE': 'primary', '$CACHE_DIR': str(f.cache), '$ENTRY': str(f.authored),
            '$DRAFT': str(f.output), '$BASELINE_ID': f.doc['entry']['id']}
        reference = Path(__file__).resolve().parents[1] / 'skills/brain-bridge/references/submission.md'
        self.commands = [[self.variables.get(token, token) for token in shlex.split(line)[1:]]
                         for line in re.findall(r'^brain-bridge .+$', reference.read_text(), re.MULTILINE)]
        for module in ('adapters', 'publication', 'managed', 'synapse'):
            p = patch('brain_bridge.' + module + '.GitHubAuthority', return_value=f.api)
            p.start(); self.addCleanup(p.stop)
        p = patch('brain_bridge.publication.GitHubReviews', return_value=self.reviews)
        p.start(); self.addCleanup(p.stop)

    def run_command(self, command):
        output = io.StringIO()
        with contextlib.redirect_stdout(output): code = main(command)
        return code, json.loads(output.getvalue())

    def test_shipped_recipe_plans_then_proposes_and_verifies_same_draft(self):
        f = self.fixture
        self.assertEqual([parser().parse_args(c).action for c in self.commands],
            ['status', 'latest', 'synapse', 'create', 'create', 'publish', 'publish',
             'managed-sync', 'publish', 'export'])
        base = f.api.grant.commit
        for command in self.commands[:2]:
            code, receipt = self.run_command(command); self.assertEqual(code, 0)
            self.assertEqual(receipt['source']['name'], 'primary')
        code, citation = self.run_command(self.commands[2]); self.assertEqual(code, 0)
        hit = next(m for m in citation['matches'] if m['json_pointer'] == '/entry/id')
        entry = copy.deepcopy(f.entry)
        entry['context']['coverage_since'] = {'entry_id': hit['entry_id'],
            'timestamp': hit['record_timestamp'], 'commit': citation['source']['commit'],
            'ledger': 'Brain-Bridge/' + hit['ledger_path'].removeprefix('records/')}
        f.authored.write_text(json.dumps(entry))
        code, plan = self.run_command(self.commands[3]); self.assertEqual(code, 0)
        self.assertFalse(f.output.exists()); self.assertFalse(plan['published'])
        code, created = self.run_command(self.commands[4]); self.assertEqual(code, 0)
        raw = f.output.read_bytes(); self.assertEqual(created['entry_id'], entry['id'])
        code, planned = self.run_command(self.commands[5]); self.assertEqual(code, 0)
        self.assertEqual(self.reviews.calls, []); self.assertFalse(planned['remote_verified'])
        code, pending = self.run_command(self.commands[6]); self.assertEqual(code, 0)
        self.assertEqual(pending['source'], 'primary'); self.assertEqual(pending['status'], 'pending_review')
        self.assertFalse(pending['published']); self.assertFalse(pending['canonical_verified'])
        self.assertTrue(pending['remote_verified']); self.assertEqual(fixtures.git(self.remote, 'rev-parse', 'main'), base)
        self.assertEqual(fixtures.git(f.repo, 'rev-parse', 'HEAD'), base)
        self.assertEqual(pending['sha256'], hashlib.sha256(raw).hexdigest())
        # Simulate the owner's separate canonical review; the recipe did not merge.
        fixtures.git(self.remote, 'update-ref', 'refs/heads/main', pending['publication_commit'], base)
        f.api.grant = replace(f.api.grant, commit=pending['publication_commit'])
        code, synced = self.run_command(self.commands[7]); self.assertEqual(code, 0)
        self.assertEqual(synced['commit'], pending['publication_commit']); self.assertTrue(synced['fresh'])
        code, published = self.run_command(self.commands[8]); self.assertEqual(code, 0)
        self.assertTrue(published['published']); self.assertTrue(published['canonical_verified'])
        self.assertEqual(published['entry_id'], pending['entry_id']); self.assertEqual(published['sha256'], pending['sha256'])
        code, exported = self.run_command(self.commands[9]); self.assertEqual(code, 0)
        self.assertEqual(exported['source']['commit'], published['commit'])
        self.assertEqual(sum(e['id'] == entry['id'] for e in exported['entries']), 1)
        self.assertEqual(f.output.read_bytes(), raw); self.assertEqual(len(self.reviews.calls), 1)
        self.assertFalse(fixtures.git(f.repo, 'status', '--porcelain'))

    def test_read_permission_does_not_authorize_documented_create(self):
        original = self.fixture.api.snapshot
        def read_only(identity, source, operation='read'):
            if operation == 'write': raise AccessDenied('Synthetic read-only enrollment')
            return original(identity, source, operation)
        with patch.object(self.fixture.api, 'snapshot', side_effect=read_only):
            code, receipt = self.run_command(self.commands[4])
        self.assertEqual(code, 1); self.assertIn('error', receipt)
        self.assertFalse(self.fixture.output.exists()); self.assertEqual(self.reviews.calls, [])


if __name__ == '__main__': unittest.main()
