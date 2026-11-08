# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Portable client discovery and canonical instruction ownership."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'docs/CONTRIBUTING.md'
SKILL = ROOT / 'skills/brain-dump/SKILL.md'
POINTERS = (
    ROOT / 'AGENTS.md',
    ROOT / 'CLAUDE.md',
    ROOT / '.github/instructions/brain-dump.instructions.md',
)
REFERENCES = SKILL.parent / 'references'


class AgentDiscoveryTests(unittest.TestCase):
    def test_each_client_discovers_the_same_two_owners(self):
        for pointer in POINTERS:
            with self.subTest(client=pointer.relative_to(ROOT)):
                text = pointer.read_text(encoding='utf-8')
                links = re.findall(r'\[[^\]]+\]\(([^)]+)\)', text)
                self.assertEqual(
                    {(pointer.parent / link).resolve() for link in links},
                    {CONTRACT, SKILL},
                )
                self.assertEqual(len(links), 2)
                self.assertNotIn('master-01', text)
                self.assertNotIn('/Users/', text)
        self.assertTrue(POINTERS[2].read_text(encoding='utf-8').startswith(
            '---\napplyTo: "**"\n---\n'))

    def test_instruction_document_links_resolve_from_the_containing_document(self):
        documents = (*POINTERS, CONTRACT, SKILL, ROOT / 'README.md',
                     REFERENCES / 'submission.md', REFERENCES / 'agent-adapters.md')
        for document in documents:
            for link in re.findall(r'\[[^\]]+\]\(([^)]+)\)',
                                   document.read_text(encoding='utf-8')):
                if '://' in link:
                    continue
                path, _, fragment = link.partition('#')
                target = (document.parent / path).resolve() if path else document
                with self.subTest(document=document.relative_to(ROOT), link=link):
                    self.assertTrue(target.is_file(), str(target))
                    if fragment:
                        headings = re.findall(r'^#+ (.+)$',
                                              target.read_text(encoding='utf-8'),
                                              re.MULTILINE)
                        anchors = {re.sub(r'[^\w -]', '', h.lower()).replace(' ', '-')
                                   for h in headings}
                        self.assertIn(fragment, anchors)

    def test_submission_delegates_checkpoint_triggers_to_the_skill(self):
        skill = SKILL.read_text(encoding='utf-8')
        submission = (REFERENCES / 'submission.md').read_text(encoding='utf-8')
        self.assertIn('## Automatic checkpoints', skill)
        self.assertIn('../SKILL.md#automatic-checkpoints', submission)
        self.assertNotIn('## Mandatory Brain Dump after every implementation commit',
                         submission)
        self.assertIn('read-only investigations', skill)
        self.assertIn('blockers and input needs', skill)
        self.assertIn('No recursive checkpoint loop', skill)
