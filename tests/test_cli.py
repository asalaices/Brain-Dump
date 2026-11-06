# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""The CLI is import-safe and JSON formatting does not change results."""
import contextlib
import importlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from brain_bridge.__main__ import main

class CLITests(unittest.TestCase):
    def test_import_does_not_dispatch(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):importlib.import_module('brain_bridge.__main__')
        self.assertEqual(output.getvalue(),'')
    def test_license_notice_names_the_original_author(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),self.assertRaises(SystemExit) as stopped:main(['--license'])
        self.assertEqual(stopped.exception.code,0)
        self.assertIn('Creative Software Development',output.getvalue());self.assertIn('AGPL-3.0-only',output.getvalue())

    def test_json_and_pretty_have_the_same_document(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/'synthetic.json').write_text('{"nested":["needle"]}')
            documents=[]
            for flag in ['--json','--pretty']:
                output=io.StringIO()
                with contextlib.redirect_stdout(output):code=main(['search','--root',t,'--term','needle',flag])
                self.assertEqual(code,0);documents.append(json.loads(output.getvalue()))
            self.assertEqual(documents[0],documents[1]);self.assertTrue(documents[0]['info']['script_version'])
    def test_publish_push_alias_matches_execute_and_defaults_to_plan(self):
        base = ['publish','--identity-repo','identity','--repo','source','--record','candidate.json']
        for flags, expected in (([],False),(['--push'],True),(['--execute'],True)):
            with self.subTest(flags=flags), patch('brain_bridge.__main__.propose_record',return_value={'status':'plan'}) as publish:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(base+flags+['--yes']),0)
                publish.assert_called_once_with('identity','source','candidate.json',expected,True)

    def test_failure_is_one_json_document(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=main(['search','--root','/does-not-exist/synthetic','--term','x','--json'])
        self.assertEqual(code,1);self.assertIn('error',json.loads(output.getvalue()))

if __name__=='__main__':unittest.main()
