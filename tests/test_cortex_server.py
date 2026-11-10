# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Bounded real-process lifecycle tests; no private apps, data or services."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from brain_bridge import cortex_server as server

ROOT = Path(__file__).resolve().parents[1]


class CortexServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cortex-test-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.runtime = self.folder / 'runtime'
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('CORTEX_')}
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'
        self.addCleanup(self.stop)

    def cli(self, action, *options, env=None):
        return subprocess.run(
            [sys.executable, str(ROOT / 'cortex_server'), action,
             '--runtime-dir', str(self.runtime), *options],
            env=env or self.env, text=True, capture_output=True, timeout=15
        )

    def stop(self):
        if (self.runtime / 'state.json').is_file():
            result = self.cli('--stop')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def start(self):
        result = self.cli('--start', '--port', '0')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def get(self, url, **kwargs):
        return build_opener(ProxyHandler({})).open(Request(url, **kwargs), timeout=2)

    def write_state(self, **updates):
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        value = {
            'schema_version': 1, 'pid': os.getpid(), 'instance': '1' * 32,
            'token': '2' * 64, 'host': '127.0.0.1', 'port': port, 'root': str(ROOT)
        }
        value.update(updates)
        path = self.runtime / 'state.json'
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path, value

    def test_start_ready_static_assets_status_idempotency_stop_and_restart(self):
        initial = self.cli('--status')
        self.assertEqual(initial.returncode, 1)
        self.assertFalse(self.runtime.exists())
        self.runtime.mkdir(mode=0o700)
        log = self.runtime / 'server.log'
        log.write_text('x' * 65537)
        log.chmod(0o600)
        first = self.start()
        self.assertNotIn('token', first)
        with self.get(first['url']) as response:
            self.assertIn(b'Cortex', response.read())
            self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
        with self.get(first['url'] + 'app.mjs') as response:
            self.assertIn(b'bindApiStatus', response.read())
            self.assertIn('javascript', response.headers['Content-Type'])
        self.assertEqual(self.cli('--status').returncode, 0)
        repeated = self.cli('--start', '--port', '0', '--pretty')
        self.assertEqual(repeated.returncode, 0, repeated.stdout)
        self.assertEqual(json.loads(repeated.stdout)['pid'], first['pid'])
        self.assertEqual(json.loads(repeated.stdout)['url'], first['url'])
        stopped = self.cli('--stop')
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertEqual(self.cli('--stop').returncode, 0)
        self.assertEqual(self.cli('--status').returncode, 1)
        self.assertFalse((self.runtime / 'state.json').exists())
        with self.assertRaises(URLError):
            self.get(first['url'])
        self.assertIn('Owned static server started', (self.runtime / 'server.log').read_text())
        self.assertNotIn('2' * 64, (self.runtime / 'server.log').read_text())
        self.assertEqual(self.start()['status'], 'running')

    def test_static_root_does_not_expose_repository_control_or_directory_listing(self):
        started = self.start()
        for path in ('../README.md', '%2e%2e/README.md', '.git/config', 'api/', 'styles/', 'missing'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.get(started['url'] + path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.get(started['url'] + '_cortex/lifecycle')
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.get(started['url'] + '_cortex/lifecycle', data=b'', method='POST')
        error.exception.close()
        self.assertEqual(self.cli('--status').returncode, 0)

    def test_control_rejects_wrong_token_and_cross_origin_and_never_logs_token(self):
        started = self.start()
        state = server.read_state(self.runtime)
        for headers in (
            {'X-Cortex-Control': 'wrong'},
            {'X-Cortex-Control': '\u00e9'},
            {'X-Cortex-Control': state['token'], 'Origin': 'https://example.invalid'},
            {'X-Cortex-Control': state['token'], 'Host': 'example.invalid'}
        ):
            with self.assertRaises(HTTPError) as error:
                self.get(started['url'] + '_cortex/lifecycle', data=b'', method='POST', headers=headers)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        self.assertEqual(self.cli('--status').returncode, 0)
        self.assertNotIn(state['token'], (self.runtime / 'server.log').read_text())

    def test_stale_live_pid_is_not_signalled_and_stale_state_can_be_restarted(self):
        helper = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE)
        self.addCleanup(lambda: (helper.stdin.close(), helper.wait(timeout=5)))
        path, _ = self.write_state(pid=helper.pid)
        self.assertEqual(json.loads(self.cli('--status').stdout)['status'], 'stale')
        stopped = self.cli('--stop')
        self.assertEqual(stopped.returncode, 0, stopped.stdout)
        self.assertTrue(json.loads(stopped.stdout)['stale_state_removed'])
        self.assertIsNone(helper.poll())
        self.assertFalse(path.exists())
        self.write_state(pid=helper.pid)
        self.start()
        self.assertIsNone(helper.poll())

    def test_foreign_listener_is_not_stopped_and_state_is_retained(self):
        class Foreign(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.requests += 1
                if getattr(self.server, 'redirect', False):
                    self.send_response(302)
                    self.send_header('Location', '/redirect-target')
                    self.end_headers()
                    return
                body = b'{"pid":1,"instance":"foreign","root":"foreign"}'
                if getattr(self.server, 'oversized', False):
                    body = b' ' * 8193
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.server.unexpected_post = True
                self.send_error(403)

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Foreign) as foreign:
            foreign.requests = 0
            thread = threading.Thread(target=foreign.serve_forever, daemon=True)
            thread.start()
            try:
                path, _ = self.write_state(port=foreign.server_port)
                before = path.read_bytes()
                for action in ('--stop', '--start', '--status'):
                    result = self.cli(action)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn('ownership mismatch', result.stdout)
                    self.assertEqual(path.read_bytes(), before)
                foreign.redirect = True
                result = self.cli('--stop')
                self.assertEqual(result.returncode, 1)
                self.assertIn('redirects are not allowed', result.stdout)
                self.assertEqual(foreign.requests, 4)
                foreign.redirect = False
                foreign.oversized = True
                result = self.cli('--stop')
                self.assertEqual(result.returncode, 1)
                self.assertIn('Oversized', result.stdout)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(getattr(foreign, 'unexpected_post', False))
            finally:
                foreign.shutdown()
                thread.join()
                path.unlink()

    def test_static_symlinks_and_hidden_files_are_rejected_in_isolated_web_fixture(self):
        web = self.folder / 'web'
        web.mkdir()
        (web / 'index.html').write_text('fixture')
        (web / '.hidden').write_text('hidden fixture')
        outside = self.folder / 'outside.txt'
        outside.write_text('outside fixture')
        (web / 'escape.txt').symlink_to(outside)
        (web / 'alias.html').symlink_to(web / 'index.html')
        with patch.object(server, 'WEB', web), ThreadingHTTPServer(('127.0.0.1', 0), server.StaticHandler) as fixture:
            thread = threading.Thread(target=fixture.serve_forever, daemon=True)
            thread.start()
            try:
                for path in ('escape.txt', 'alias.html', '.hidden'):
                    with self.assertRaises(HTTPError) as error:
                        self.get(f'http://127.0.0.1:{fixture.server_port}/{path}')
                    self.assertEqual(error.exception.code, 404)
                    error.exception.close()
            finally:
                fixture.shutdown()
                thread.join()

    def test_port_collision_is_an_error_and_leaves_no_state_or_stranded_worker(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen()
            result = self.cli('--start', '--port', str(sock.getsockname()[1]))
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn('failed to start', result.stdout)
            self.assertFalse((self.runtime / 'state.json').exists())
            self.assertEqual(sock.getsockname()[0], '127.0.0.1')

    def test_invalid_configuration_foreign_and_corrupt_state_fail_closed(self):
        for port in ('-1', '65536', 'invalid'):
            result = self.cli('--start', '--port', port)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(self.runtime.exists())
        env = {**self.env, 'CORTEX_HOST': '0.0.0.0'}
        result = self.cli('--start', env=env)
        self.assertEqual(result.returncode, 2)
        for update in ({'root': '/foreign'}, {'pid': -1}, {'token': 'bad'}, {'schema_version': True}):
            path, _ = self.write_state(**update)
            before = path.read_bytes()
            result = self.cli('--stop')
            self.assertEqual(result.returncode, 1)
            self.assertEqual(path.read_bytes(), before)
            path.unlink()
        path, _ = self.write_state()
        path.write_text('{broken')
        self.assertIn('runtime JSON', self.cli('--stop').stdout)
        path.write_text(' ' * 65537)
        self.assertIn('size limit', self.cli('--stop').stdout)
        path.unlink()

    def test_runtime_state_cannot_live_in_web_or_follow_symlink(self):
        result = self.cli('--start', '--runtime-dir', str(ROOT / 'web'))
        self.assertEqual(result.returncode, 1)
        self.assertIn('outside the source checkout', result.stdout)
        target = self.folder / 'target'
        target.mkdir(mode=0o700)
        if os.name == 'nt':
            os.symlink(target, self.runtime, target_is_directory=True)
        else:
            self.runtime.symlink_to(target, target_is_directory=True)
        result = self.cli('--start')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Symlinked', result.stdout)
        self.runtime.unlink()
        self.runtime.mkdir(mode=0o700)
        for name in ('state.json', 'server.log'):
            destination = target / name
            destination.write_text('foreign fixture')
            link = self.runtime / name
            link.symlink_to(destination)
            result = self.cli('--start', '--port', '0')
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn('Symlinked', result.stdout)
            self.assertEqual(destination.read_text(), 'foreign fixture')
            link.unlink()

    def test_concurrent_commands_serialize_without_duplicate_servers(self):
        command = [sys.executable, str(ROOT / 'cortex_server'), '--start', '--port', '0', '--runtime-dir', str(self.runtime)]
        first = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        outputs = [process.communicate(timeout=15) for process in (first, second)]
        successes = []
        for process, (stdout, stderr) in zip((first, second), outputs):
            self.assertIn(process.returncode, (0, 1), stdout + stderr)
            value = json.loads(stdout)
            if process.returncode == 0:
                successes.append(value['pid'])
            else:
                self.assertIn('locked', value['error'])
        self.assertTrue(successes)
        self.assertEqual(len(set(successes)), 1)
        self.assertEqual(self.cli('--status').returncode, 0)

    def test_startup_timeout_and_invalid_handshake_close_owned_worker_without_signals(self):
        real_popen = subprocess.Popen
        for code in (
            'import sys; sys.stdin.readline(); sys.stdin.read()',
            'import sys; sys.stdin.readline(); print("{}",flush=True); sys.stdin.read()'
        ):
            processes = []

            def spawn(_command, **kwargs):
                process = real_popen([sys.executable, '-u', '-c', code], **kwargs)
                processes.append(process)
                return process

            with patch.object(server.subprocess, 'Popen', side_effect=spawn), patch.object(server, 'TIMEOUT', .3), patch.object(server.os, 'kill', side_effect=AssertionError('No PID signals')):
                with self.assertRaisesRegex(ValueError, 'readiness timed out|startup identity'):
                    server.operate('start', self.runtime, 0)
            self.assertTrue(all(process.poll() is not None for process in processes))
            self.assertFalse((self.runtime / 'state.json').exists())
        processes = []

        def record_spawn(command, **kwargs):
            process = real_popen(command, **kwargs)
            processes.append(process)
            return process

        with patch.object(server.subprocess, 'Popen', side_effect=record_spawn), patch.object(server, 'save_state', side_effect=OSError('fixture write failed')):
            with self.assertRaisesRegex(OSError, 'fixture write failed'):
                server.operate('start', self.runtime, 0)
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.assertFalse((self.runtime / 'state.json').exists())

    def test_launcher_help_version_invalid_override_and_environment_configuration(self):
        for option in ('--help', '--version'):
            result = subprocess.run([sys.executable, str(ROOT / 'cortex_server'), option], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertIn('cortex', result.stdout.lower())
        for override in ('', str(self.folder / 'missing')):
            result = self.cli('--start', env={**self.env, 'CORTEX_PYTHON': override})
            self.assertEqual(result.returncode, 2)
            self.assertIn('Python 3.11+', result.stderr)
        result = self.cli('--start', env={**self.env, 'CORTEX_PORT': '0', 'CORTEX_HOST': 'localhost'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('script_version', json.loads(result.stdout)['info'])


if __name__ == '__main__':
    unittest.main()
