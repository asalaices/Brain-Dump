#!/usr/bin/env python3
# script_version: 1.0.0
# Purpose: Verify Brain-Dump bootstrap registration, common runtime integrity, plans, ownership, and zero-interruption boundaries.
# Usage: python3 -m unittest discover -s tests/bootstrap -p test_bootstrap_foundation.py
# Output: test
# Prerequisites: Repository checkout; tests use temporary profiles and perform no installation.
# Failure: Assertion diagnostics and nonzero unittest status.
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]

class BootstrapFoundationTests(unittest.TestCase):
    def run_json(self,*command):
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        return json.loads(result.stdout)
    def test_common_runtime_matches_import_manifest(self):
        manifest=json.loads((ROOT/'bootstrap/manifests/common-runtime.json').read_text())
        for name,digest in manifest['files'].items():
            path=ROOT/name
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
    def test_phase_stack_and_menu_discovery(self):
        if os.name=='nt':return
        phases=self.run_json('bash','bootstrap/bootstrap.sh','--list-phases','--json')
        self.assertEqual([row['id'] for row in phases['phases']],['000','100'])
        stacks=self.run_json('bash','bootstrap/bootstrap.sh','--list-stacks','--json')
        self.assertEqual(stacks['stacks'],['brain-runtime'])
        plan=self.run_json('bash','bootstrap/bootstrap.sh','--stack','brain-runtime','--host','local','--plan','--json')
        self.assertEqual([row['phase'] for row in plan['phases']],['000-preflight','100-runtime'])
        menu=self.run_json(sys.executable,'bootstrap/boot_menu','--check','--json')
        self.assertEqual(menu['controller'],'bootstrap/bootstrap.sh')
    def test_stack_plan_has_no_effects_and_preserves_live_paths(self):
        if os.name=='nt':return
        result=self.run_json('bash','bootstrap/bootstrap.sh','--stack','brain-runtime','--host','local','--plan','--json')
        self.assertEqual(result['effects'],[])
        self.assertFalse(result['executed'])
        self.assertIn('existing MCP tunnels and services',result['preserved'])
    def test_runtime_phase_uses_existing_installation_owner(self):
        if os.name=='nt':return
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as directory:
            root=Path(directory);home=root/'home';home.mkdir()
            source=root/'source';source.mkdir()
            python=root/'python3';python.write_text('fixture\n');python.chmod(0o700)
            profile={
                'schema_version':2,'host':'synthetic','home':str(home),
                'runtime_dir':str(home/'runtime'),'source_repo':str(source),
                'framework_commit':'a'*40,'framework_version':'0.8.6',
                'python':str(python),'python_version':platform.python_version(),
                'setuptools_version':'84.2.1','launcher':str(home/'bin/brain-bridge'),
                'skill_home':str(home/'skills'),'skill':'skills/brain-dump'}
            path=root/'profile.json';path.write_text(json.dumps(profile))
            result=self.run_json('bash','bootstrap/phases/100-runtime.sh','--host','local','--config',str(path),'--plan','--json')
            self.assertEqual(result['bootstrap_owner'],'bootstrap/bootstrap.sh')
            self.assertFalse(result['service_changes'])
            self.assertFalse(result['production_route_changed'])
    def test_public_manifests_contain_no_external_resources(self):
        inventory=json.loads((ROOT/'manifests/external-files.json').read_text())
        self.assertEqual(inventory,{'schema_version':1,'files':[]})
        forbidden=('tunnel_','plugin_','B'+'earer ')
        for path in list((ROOT/'bootstrap/config').rglob('*.json'))+list((ROOT/'bootstrap/manifests').rglob('*.json'))+list((ROOT/'manifests').rglob('*.json')):
            if path.is_file():
                text=path.read_text(errors='ignore')
                self.assertFalse(any(value in text for value in forbidden),path)
    def test_committed_profile_schema_covers_existing_runtime_contract(self):
        schema=json.loads((ROOT/'bootstrap/config/runtime-profile.schema.json').read_text())
        required={'schema_version','host','home','runtime_dir','source_repo','framework_commit',
                  'framework_version','python','python_version','setuptools_version','launcher',
                  'skill_home','skill'}
        optional={'legacy_version','legacy_skill_sha256','operation','wheel','wheel_sha256'}
        self.assertEqual(set(schema['required']),required)
        self.assertEqual(set(schema['properties']),required|optional)
        self.assertEqual(schema['dependentRequired'],{'wheel':['wheel_sha256'],'wheel_sha256':['wheel']})
    def test_entrypoint_registry_preserves_compatibility_without_claiming_cutover(self):
        value=json.loads((ROOT/'bootstrap/entrypoints.json').read_text())
        entries={row['path']:row for row in value['entrypoints']}
        self.assertEqual(entries['bootstrap/bootstrap.sh']['kind'],'controller')
        self.assertEqual(entries['bootstrap.py']['kind'],'compatibility')
        self.assertIn('zero-interruption', (ROOT/'bootstrap/README.md').read_text().lower())
    def test_local_telemetry_redacts_fixture_markers_and_never_publishes(self):
        if os.name=='nt':return
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as directory:
            environment={**os.environ,'XDG_STATE_HOME':directory,'BRAIN_BOOTSTRAP_PYTHON':sys.executable}
            payload=('to'+'ken')+'=fixture-value\n'
            result=subprocess.run(
                ['bash','bootstrap/telemetry/mac-run.sh','--','printf',payload],
                cwd=ROOT,capture_output=True,text=True,env=environment)
            self.assertEqual(result.returncode,0,result.stderr)
            manifests=list(Path(directory).rglob('manifest.json'))
            self.assertEqual(len(manifests),1)
            manifest=json.loads(manifests[0].read_text())
            self.assertFalse(manifest['published'])
            sanitized=(manifests[0].parent/'execution.log').read_text()
            self.assertIn('[REDACTED]',sanitized)
            self.assertNotIn('fixture-value',sanitized)

if __name__=='__main__':unittest.main()
