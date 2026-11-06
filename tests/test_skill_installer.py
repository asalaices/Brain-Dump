# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""The public skill wrapper delegates to an explicit Git-owned link installer."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class SkillInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.public = self.root / 'public source'
        self.owner = self.root / 'installer owner'
        self.public.mkdir(); self.owner.mkdir()
        self.skill = self.public / 'skills/brain-bridge'
        self.skill.mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / 'skills/brain-bridge'
        for name in ('SKILL.md', 'README.md', 'install.sh'):
            shutil.copy2(source / name, self.skill / name)
        for repo in (self.public, self.owner):
            self.git(repo, 'init', '-q')
            self.git(repo, 'config', 'user.name', 'Synthetic')
            self.git(repo, 'config', 'user.email', 'synthetic@example.invalid')
        bots = self.owner / 'intelli_bots'
        bots.mkdir()
        # This synthetic owner records delegation only. It has no link code.
        (bots / 'bot_local_skill_link.sh').write_text('#!/usr/bin/env bash\n'
            'printf "owner-called\\n"\n'
            'printf "arg:%s\\n" "$@"\n'
            'printf "target:%s\\n" "${COPILOT_SKILLS_HOME:-default}"\n'
            'exit "${SYNTHETIC_OWNER_EXIT:-0}"\n')
        (bots / 'bot_general.inc').write_text('# Synthetic shared runtime fixture\n')
        (bots / 'bot_general.py').write_text('# Synthetic shared runtime fixture\n')
        for repo in (self.public, self.owner):
            self.git(repo, 'add', '.')
            self.git(repo, 'commit', '-qm', 'Synthetic installer fixtures')

    def git(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args],
                                       text=True, stderr=subprocess.DEVNULL).strip()

    def call(self, *args, environment=None):
        return subprocess.run(['bash', (self.skill / 'install.sh').as_posix(), *map(str, args)],
                              capture_output=True, text=True,
                              env=dict(os.environ, **(environment or {})))

    def selected(self, *args, **kwargs):
        return self.call('--installer-root', self.owner.as_posix(), *args, **kwargs)

    def test_help_and_version_need_no_installer_or_filesystem_mutation(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        for flag in ('--help', '--version'):
            with self.subTest(flag=flag):
                result = self.call(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('owner-called', result.stdout)
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), before)

    def test_explicit_owner_receives_exact_operation_flags_and_own_source(self):
        result = self.selected('install', '--execute', '--yes', '--debug', '--log-file', 'chosen.log',
                               environment={'COPILOT_SKILLS_HOME': 'chosen-discovery'})
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = [row[4:] for row in result.stdout.splitlines() if row.startswith('arg:')]
        self.assertEqual(arguments[:-2], ['install', '--execute', '--yes', '--debug', '--log-file', 'chosen.log'])
        self.assertEqual(arguments[-2], '--source')
        self.assertTrue(arguments[-1].replace('\\', '/').endswith('/skills/brain-bridge'))
        self.assertIn('target:chosen-discovery', result.stdout)
        self.assertFalse((self.root / 'chosen-discovery').exists())

    def test_status_and_plan_are_delegated_without_invented_mutation_flags(self):
        for command in ('status', 'install', 'uninstall'):
            with self.subTest(command=command):
                result = self.selected(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('arg:' + command, result.stdout)
                self.assertNotIn('arg:--execute', result.stdout)
                self.assertNotIn('arg:--yes', result.stdout)

    def test_missing_owner_unknown_command_and_source_override_fail_closed(self):
        for args in [('status',), ('--installer-root', '/missing-synthetic-owner', 'install'),
                     ('--installer-root', self.owner.as_posix(), 'unknown'),
                     ('--installer-root', self.owner.as_posix(), 'install', '--source', '/other-source')]:
            with self.subTest(args=args):
                result = self.call(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('owner-called', result.stdout)

    def test_owner_must_be_checkout_root_and_have_tracked_regular_runtime(self):
        nested = self.owner / 'intelli_bots'
        result = self.call('--installer-root', nested.as_posix(), 'status')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('owner-called', result.stdout)
        runtime = self.owner / 'intelli_bots/bot_general.py'
        self.git(self.owner, 'rm', '--cached', 'intelli_bots/bot_general.py')
        result = self.selected('install', '--execute', '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('owner-called', result.stdout)
        self.assertTrue(runtime.is_file())

    def test_bundled_source_copy_cannot_become_discovery_source(self):
        outside = self.root / 'wheel-artifact/brain-bridge'
        shutil.copytree(self.skill, outside)
        result = subprocess.run(['bash', (outside / 'install.sh').as_posix(), '--installer-root',
                                 self.owner.as_posix(), 'install', '--execute', '--yes'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('owner-called', result.stdout)

    def test_conflict_or_failure_exit_status_is_preserved(self):
        result = self.selected('install', '--execute', '--yes', environment={'SYNTHETIC_OWNER_EXIT': '7'})
        self.assertEqual(result.returncode, 7)
        self.assertIn('owner-called', result.stdout)
        self.assertFalse((self.root / 'chosen-discovery').exists())

    def test_git_package_metadata_bundles_readme_and_wrapper(self):
        import tomllib
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / 'pyproject.toml').read_text())
        files = project['tool']['setuptools']['data-files']['share/brain-bridge/skills/brain-bridge']
        for name in ('README.md', 'SKILL.md', 'install.sh'):
            self.assertIn('skills/brain-bridge/' + name, files)
        from brain_bridge import __version__
        self.assertEqual(project['project']['version'], __version__)


if __name__ == '__main__':
    unittest.main()
