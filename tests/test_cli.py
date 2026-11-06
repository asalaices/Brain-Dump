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

    def test_managed_adapter_cli_dispatch_and_json_pretty_parity(self):
        base=['--identity-repo','identity','--repo','source','--source','primary']
        for action, function, extra, expected in [
            ('export','managed_export',[],('identity','source','primary')),
            ('latest','managed_latest',[],('identity','source','primary')),
            ('status','managed_status',['--cache-dir','cache'],('identity','source','primary','cache')),
            ('create','managed_create',['--entry','entry.json','--output','draft.json'],
             ('identity','source','primary','entry.json','draft.json',False,False))]:
            documents=[]
            for flag in ['--json','--pretty']:
                with self.subTest(action=action,flag=flag), patch('brain_bridge.__main__.'+function,return_value={'status':'synthetic'}) as adapter:
                    output=io.StringIO()
                    with contextlib.redirect_stdout(output):self.assertEqual(main([action]+base+extra+[flag]),0)
                    adapter.assert_called_once_with(*expected);documents.append(json.loads(output.getvalue()))
            self.assertEqual(documents[0],documents[1])

    def test_import_plan_is_read_only_and_dispatches_explicit_identities(self):
        base = ['import-plan', '--source-repo', 'source', '--destination-repo', 'destination',
                '--source-id', '11', '--destination-id', '22']
        for flag in ('--json', '--pretty'):
            with self.subTest(flag=flag), patch('brain_bridge.__main__.plan_import', return_value={'read_only': True, 'executed': False}) as plan:
                output = io.StringIO()
                with contextlib.redirect_stdout(output): self.assertEqual(main(base + [flag]), 0)
                plan.assert_called_once_with('source', 'destination', '11', '22', 'main', 'main', 'Brain-Bridge')
                self.assertFalse(json.loads(output.getvalue())['executed'])

    def test_failure_is_one_json_document(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=main(['search','--root','/does-not-exist/synthetic','--term','x','--json'])
        self.assertEqual(code,1);self.assertIn('error',json.loads(output.getvalue()))

if __name__=='__main__':unittest.main()
