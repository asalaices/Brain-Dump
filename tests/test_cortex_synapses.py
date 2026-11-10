# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Synthetic loopback session/HTTP fixtures; never consult a live private source."""
from http.client import HTTPConnection
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from brain_bridge import cortex_server as server, cortex_synapses as local
from brain_bridge.policy import AccessDenied, AuthorizationUnavailable

PROFILE = {'identity_repo': '/synthetic/identity', 'source_repo': '/synthetic/reader',
           'source': 'example', 'cache_dir': '/synthetic/cache'}
PARAMETERS = {key: value for key, value in PROFILE.items() if key != 'source'} | {'source_name': 'example'}
SOURCE = {'name': 'example', 'repository': 'example/synthetic', 'commit': 'a' * 40}
STATUS = {'schema_version': 1, 'source': SOURCE, 'read_only': True, 'source_verified': True,
          'synchronized': True, 'cache_fresh': False, 'count': 2, 'records': 2, 'overlays': 0}
MATCH = {'source_url': 'https://github.com/example/synthetic/blob/' + 'a' * 40 + '/records/example.json',
         'excerpt': {'text': '<script>synthetic context</script>'}, 'json_pointer': '/entry/summary',
         'sha256': 'b' * 64, 'entry_id': 'synthetic-entry', 'record_timestamp': '2026-01-01T00:00:00Z'}
FOUND = {'schema_version': 1, 'request_id': 'synthetic-request', 'read_only': True,
         'status': 'found', 'source': SOURCE, 'freshness': {'source_verified': True, 'cache_fresh': False},
         'matches': [MATCH]}


class LocalSynapsesTests(unittest.TestCase):
    def setUp(self):
        self.app = local.LocalSynapses(dict(PROFILE))
        self.http = server.CortexHTTPServer(('127.0.0.1', 0), server.StaticHandler)
        self.http.daemon_threads = True
        self.http.synapses = self.app
        self.temporary = tempfile.TemporaryDirectory(prefix='cortex-session-test-')
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name).resolve()
        self.runtime.chmod(0o700)
        self.state = {
            'schema_version': 1, 'pid': os.getpid(), 'instance': '1' * 32, 'token': '2' * 64,
            'host': '127.0.0.1', 'port': self.http.server_port, 'root': str(server.ROOT)
        }
        self.http.identity = self.state
        thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .01})
        thread.start()
        self.addCleanup(lambda: (self.http.shutdown(), thread.join(timeout=3), self.http.server_close()))
        self.status = self.enterContext(patch.object(local, 'managed_status', autospec=True, return_value=dict(STATUS)))
        self.synapse = self.enterContext(patch.object(local, 'synapse_request', autospec=True, return_value=dict(FOUND)))

    def post(self, endpoint, body=None, cookie=None, headers=None, raw=None):
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
        self.addCleanup(connection.close)
        fields = {'Origin': f'http://127.0.0.1:{self.http.server_port}', 'Content-Type': 'application/json',
                  'X-Cortex-Read-Only': '1', 'X-Cortex-Browser': '3' * 64}
        if cookie:
            fields['Cookie'] = cookie
        fields.update(headers or {})
        connection.request('POST', local.PREFIX + endpoint,
                           body=raw if raw is not None else json.dumps(body or {}).encode(), headers=fields)
        response = connection.getresponse()
        return response.status, json.loads(response.read()), dict(response.getheaders())

    def connected(self):
        code, result, headers = self.post('session')
        self.assertEqual((code, result['status']), (200, 'connected'))
        self.assertEqual(result['sources'], ['example'])
        self.assertNotIn('token', result)
        self.assertNotIn('key', result)
        return headers['Set-Cookie'].split(';')[0]

    def test_in_page_connect_resume_status_and_disconnect_need_no_launcher(self):
        cookie = self.connected()
        self.status.assert_not_called()
        code, result, headers = self.post('resume', cookie=cookie)
        self.assertEqual((code, result['status']), (200, 'connected'))
        self.assertNotIn('Set-Cookie', headers)
        code, result, headers = self.post('status', cookie=cookie)
        self.assertEqual((code, result['source']), (200, SOURCE))
        self.status.assert_called_once_with(**PARAMETERS)
        self.assertFalse(result['cache_fresh'])
        self.assertIn('no-store', headers['Cache-Control'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        code, result, headers = self.post('disconnect', cookie=cookie)
        self.assertEqual((code, result['status']), (200, 'disconnected'))
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        for operation in ('resume', 'status', 'disconnect'):
            self.assertEqual(self.post(operation, cookie=cookie)[0], 401)
        self.assertEqual(self.app.sessions, {})
        self.assertEqual(list(self.runtime.glob('launch-*.html')), [])

    def test_cookie_is_private_port_named_and_never_appears_in_json(self):
        _, result, headers = self.post('session')
        cookie = headers['Set-Cookie']
        self.assertTrue(cookie.startswith(f'cortex_local_{self.http.server_port}='))
        for attribute in ('HttpOnly', 'SameSite=Strict', 'Path=/api/local/', 'Max-Age=1800'):
            self.assertIn(attribute, cookie)
        self.assertNotIn(cookie.split(';')[0].split('=')[1], json.dumps(result))

    def test_refresh_cannot_extend_fixed_expiry_and_old_cookie_cannot_be_replayed(self):
        now = [0]
        self.app.clock = lambda: now[0]
        cookie = self.connected()
        now[0] = 900
        code, receipt, headers = self.post('resume', cookie=cookie)
        self.assertEqual((code, receipt['expires_in_seconds']), (200, 900))
        self.assertNotIn('Set-Cookie', headers)
        now[0] = 1800
        for operation in ('resume', 'status'):
            self.assertEqual(self.post(operation, cookie=cookie)[0], 401)
        self.assertEqual(self.app.sessions, {})
        self.status.assert_not_called()

    def test_connect_rotates_injected_or_existing_ids_and_invalidates_old_session(self):
        cookie = self.connected()
        for _ in range(12):
            code, result, headers = self.post('session', cookie=cookie, headers={'X-Cortex-Browser': '4' * 64})
            self.assertEqual((code, result['status']), (200, 'connected'))
            new_cookie = headers['Set-Cookie'].split(';')[0]
            self.assertNotEqual(new_cookie, cookie)
            self.assertEqual(self.post('resume', cookie=cookie)[0], 401)
            cookie = new_cookie
            self.assertEqual(len(self.app.sessions), 1)
        injected = f'cortex_local_{self.http.server_port}=' + '0' * 64
        code, _, headers = self.post('session', cookie=injected)
        self.assertEqual(code, 200)
        self.assertNotEqual(headers['Set-Cookie'].split(';')[0], injected)
        self.assertEqual(self.post('status', cookie=injected)[0], 401)

    def test_cross_port_stolen_or_injected_cookie_without_origin_csrf_key_is_insufficient(self):
        cookie = self.connected()
        foreign = {'X-Cortex-Browser': '4' * 64}
        for operation in ('resume', 'status', 'disconnect'):
            code, _, headers = self.post(operation, cookie=cookie, headers=foreign)
            self.assertEqual(code, 401)
            self.assertNotIn('Set-Cookie', headers)
        self.status.assert_not_called()
        self.assertEqual(self.post('status', cookie=cookie)[0], 200)
        wrong_name = cookie.replace(str(self.http.server_port), '1', 1)
        self.assertEqual(self.post('resume', cookie=wrong_name)[0], 401)
        self.assertEqual(self.post('resume', cookie='malformed; =')[0], 401)

    def test_origin_host_custom_headers_forms_and_cross_port_requests_reject_before_sessions(self):
        for fields in (
            {'Origin': 'http://example.invalid'}, {'Origin': ''}, {'Origin': 'null'},
            {'Origin': f'http://127.0.0.1:{self.http.server_port + 1}'},
            {'Origin': f'http://localhost:{self.http.server_port}'},
            {'Host': 'example.invalid'}, {'Host': f'localhost:{self.http.server_port}'},
            {'X-Cortex-Read-Only': ''}, {'X-Cortex-Browser': ''}, {'X-Cortex-Browser': 'bad'}
        ):
            for operation in ('session', 'resume', 'disconnect', 'status'):
                with self.subTest(fields=fields, operation=operation):
                    self.assertEqual(self.post(operation, headers=fields)[0], 403)
        for content_type in ('text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data'):
            self.assertEqual(self.post('session', headers={'Content-Type': content_type})[0], 400)
        self.assertEqual(self.app.sessions, {})
        self.status.assert_not_called()
        self.synapse.assert_not_called()

    def test_navigation_preflight_and_retired_routes_cannot_establish_sessions(self):
        for method in ('GET', 'OPTIONS'):
            connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
            self.addCleanup(connection.close)
            connection.request(method, local.PREFIX + 'session', headers={
                'Origin': 'http://127.0.0.1:9999', 'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type,x-cortex-browser,x-cortex-read-only'})
            response = connection.getresponse()
            self.assertIn(response.status, (404, 501))
            self.assertIsNone(response.getheader('Set-Cookie'))
            self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
            response.read()
        for endpoint in ('launch', 'bootstrap', 'export', 'status?source=other'):
            self.assertEqual(self.post(endpoint)[0], 404)
        for path in ('/_cortex/open', '/_cortex/pair'):
            connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
            self.addCleanup(connection.close)
            connection.request('POST', path, body=b'{}')
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
        self.assertEqual(self.app.sessions, {})

    def test_optional_open_opens_only_ordinary_url_without_files_or_authorization(self):
        (self.runtime / 'state.json').write_text(json.dumps(self.state))
        (self.runtime / 'state.json').chmod(0o600)
        with patch.object(server.webbrowser, 'open', return_value=True) as opened:
            result, code = server.operate('open', self.runtime, 8080)
        self.assertEqual(code, 0)
        opened.assert_called_once_with(f'http://127.0.0.1:{self.http.server_port}/', new=2)
        self.assertNotIn('launch_file', result)
        self.assertEqual(self.app.sessions, {})
        self.assertEqual(list(self.runtime.glob('launch-*.html')), [])
        for error in (False, OSError('synthetic native failure')):
            with patch.object(server.webbrowser, 'open', side_effect=error if isinstance(error, Exception) else None,
                              return_value=error):
                with self.assertRaises((ValueError, OSError)):
                    server.operate('open', self.runtime, 8080)
            self.assertTrue(server.control(self.state))

    def test_rejection_consumes_only_bounded_body_before_reply_without_authorizing(self):
        fields = {'Content-Length': '2', 'Content-Type': 'application/json',
                  'Origin': f'http://127.0.0.1:{self.http.server_port}',
                  'Host': f'127.0.0.1:{self.http.server_port}',
                  'X-Cortex-Read-Only': '1', 'X-Cortex-Browser': '3' * 64}
        for overrides, code in (
            ({'Origin': 'http://example.invalid'}, 403), ({'Host': 'example.invalid'}, 403),
            ({'X-Cortex-Read-Only': ''}, 403), ({'X-Cortex-Browser': ''}, 403),
            ({'Content-Type': 'text/plain'}, 400), ({'Transfer-Encoding': 'chunked'}, 400)
        ):
            with self.subTest(headers=overrides):
                handler = SimpleNamespace(headers=fields | overrides, server=self.http,
                                          connection=Mock(), rfile=BytesIO(b'{}'),
                                          path=local.PREFIX + 'status')
                with patch.object(local, 'reply') as response:
                    local.handle(handler)
                self.assertEqual(handler.rfile.tell(), 2)
                handler.connection.settimeout.assert_called_once_with(3)
                response.assert_called_once_with(
                    handler, code, {'status': 'denied' if code == 403 else 'invalid_request'})
        handler.headers = fields | {'Content-Length': '4097'}
        handler.rfile = BytesIO(b'x' * 4097)
        with patch.object(local, 'reply') as response:
            local.handle(handler)
        self.assertEqual(handler.rfile.tell(), 0)
        response.assert_called_once_with(handler, 400, {'status': 'invalid_request'})
        self.status.assert_not_called()
        self.synapse.assert_not_called()

    def test_bounded_schema_rejects_browser_selected_paths_sources_ids_and_commands(self):
        cookie = self.connected()
        for endpoint in ('session', 'resume', 'disconnect', 'status'):
            for body in ({'path': '/synthetic'}, {'source': 'other'}, {'browser_id': 'a' * 64},
                         {'credential': 'b' * 64}, {'source_repo': '/other'}):
                self.assertEqual(self.post(endpoint, body, cookie)[0], 400)
        for body in ({}, {'query': ''}, {'query': ' '}, {'query': None}, {'query': 12},
                     {'query': 'x' * 513}, {'query': 'x', 'source_repo': '/other'},
                     {'query': 'x', 'operation': 'publish'}, {'query': 'x', 'source': 'other'}):
            self.assertEqual(self.post('synapse', body=body, cookie=cookie)[0], 400)
        for raw in (b'{', b'[]', b'{"query":"a","query":"b"}', b'{"query":NaN}', b'\xff', b'x' * 4097):
            self.assertEqual(self.post('synapse', cookie=cookie, raw=raw)[0], 400)
        self.synapse.assert_not_called()
        self.status.assert_not_called()

    def test_cited_query_delegates_bounded_existing_engine_and_preserves_receipt(self):
        cookie = self.connected()
        code, receipt, _ = self.post('synapse', {'query': 'synthetic context'}, cookie)
        self.assertEqual(code, 200)
        self.assertEqual(receipt, FOUND)
        self.synapse.assert_called_once_with(**PARAMETERS, term='synthetic context', backend='auto', limit=5, excerpt_chars=240)
        self.synapse.return_value = {**FOUND, 'status': 'no_match', 'matches': []}
        self.assertEqual(self.post('synapse', {'query': 'absent'}, cookie)[1]['status'], 'no_match')

    def test_every_read_rechecks_upstream_authority_and_redacts_failures(self):
        cookie = self.connected()
        self.assertEqual(self.post('status', cookie=cookie)[0], 200)
        for exception, expected in ((AccessDenied, (403, 'denied')),
                                    (AuthorizationUnavailable, (503, 'unavailable')),
                                    (ValueError, (502, 'error'))):
            self.status.side_effect = exception('/private/path secret-query private-excerpt')
            with self.assertLogs(local.LOG, level='WARNING') as logs:
                code, result, _ = self.post('status', cookie=cookie)
            self.assertEqual((code, result['status']), expected)
            self.assertNotIn('source', result)
            self.assertNotIn('/private/path', json.dumps(result) + str(logs.output))
            self.assertNotIn('secret-query', json.dumps(result) + str(logs.output))
        for status, code in (('denied', 403), ('unavailable', 503), ('error', 502)):
            self.synapse.return_value = {**FOUND, 'status': status, 'error': '/private/path'}
            with self.assertLogs(local.LOG, level='WARNING'):
                actual, result, _ = self.post('synapse', {'query': 'private query'}, cookie)
            self.assertEqual(actual, code)
            self.assertNotIn('matches', result)
            self.assertNotIn('/private/path', json.dumps(result))

    def test_concurrency_is_bounded_and_revocation_during_read_withholds_result(self):
        cookie = self.connected()
        token = cookie.split('=', 1)[1]
        entered, release = threading.Event(), threading.Event()
        def held(**kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Fixture deadline')
            return STATUS
        self.status.side_effect = held
        result = []
        thread = threading.Thread(target=lambda: result.append(self.app.read(token, 'status', {}, '3' * 64)))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.app.read(token, 'status', {}, '3' * 64)[0], 429)
            self.app.disconnect(token, '3' * 64)
        finally:
            release.set()
            thread.join(timeout=4)
        self.assertEqual(result[0], (401, {'status': 'connection_required'}))
        self.assertFalse(thread.is_alive())
        self.assertTrue(self.app.operation.acquire(blocking=False))
        self.app.operation.release()

    def test_oversized_source_response_is_withheld(self):
        self.status.return_value = {**STATUS, 'unexpected': 'sensitive-fixture' * 30000}
        with self.assertLogs(local.LOG, level='WARNING'):
            code, result, _ = self.post('status', cookie=self.connected())
        self.assertEqual(code, 502)
        self.assertNotIn('sensitive-fixture', json.dumps(result))

    def test_sessions_are_bounded_profile_is_opt_in_and_expired_capacity_is_reclaimed(self):
        self.app.profile = None
        self.assertEqual(self.post('session')[0], 503)
        self.assertEqual(self.app.sessions, {})
        self.app.profile = PROFILE
        now = [0]
        self.app.clock = lambda: now[0]
        for _ in range(8):
            self.connected()
        self.assertEqual(self.post('session')[0], 429)
        now[0] = 1800
        self.connected()
        self.assertEqual(len(self.app.sessions), 1)
        self.status.assert_not_called()


class ProfileTests(unittest.TestCase):
    def test_profile_reaches_real_worker_and_repeated_start_cannot_silently_reconfigure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            profile = folder / 'profile.json'
            profile.write_text(json.dumps({**PROFILE, 'identity_repo': str(folder / 'identity'),
                                          'source_repo': str(folder / 'reader'), 'cache_dir': str(folder / 'cache')}))
            runtime = folder / 'runtime'
            env = {key: value for key, value in os.environ.items() if not key.startswith('CORTEX_')}
            def cli(*args):
                return subprocess.run([sys.executable, str(server.ROOT / 'cortex_server'), *args,
                                       '--runtime-dir', str(runtime)], env=env, capture_output=True, text=True, timeout=15)
            started = cli('--start', '--port', '0', '--synapses-profile', str(profile))
            self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
            try:
                port = int(json.loads(started.stdout)['url'].split(':')[-1].strip('/'))
                connection = HTTPConnection('127.0.0.1', port, timeout=3)
                try:
                    connection.request('POST', local.PREFIX + 'session', body=b'{}', headers={
                        'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json',
                        'X-Cortex-Read-Only': '1', 'X-Cortex-Browser': '3' * 64})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())['status'], 'connected')
                finally:
                    connection.close()
                self.assertEqual(cli('--start', '--synapses-profile', str(profile)).returncode, 1)
                self.assertEqual(cli('--status').returncode, 0)
            finally:
                stopped = cli('--stop')
                self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)

    def test_external_profile_is_routing_only_and_never_executes_cli_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            profile = folder / 'profile.json'
            profile.write_text(json.dumps({**PROFILE, 'identity_repo': str(folder / 'identity'),
                                          'source_repo': str(folder / 'reader'), 'cache_dir': str(folder / 'cache'),
                                          'cli': '/must/not/execute', 'ignored': 'not authority'}))
            result = local.load_profile(profile, server.ROOT)
            self.assertEqual(set(result), set(PROFILE))
            self.assertEqual(result['source'], 'example')
            self.assertEqual(result['source_repo'], folder / 'reader')
            for content in ('{}', '[]', '{"source":NaN}', '{"source":"x","source":"y"}',
                            json.dumps({**PROFILE, 'cache_dir': 'relative'}),
                            json.dumps({**PROFILE, 'source_repo': str(server.ROOT)})):
                profile.write_text(content)
                with self.assertRaises(ValueError):
                    local.load_profile(profile, server.ROOT)
            profile.write_text('x' * 8193)
            with self.assertRaises(ValueError):
                local.load_profile(profile, server.ROOT)
            if os.name != 'nt':
                profile.chmod(0o666)
                with self.assertRaises(ValueError):
                    local.load_profile(profile, server.ROOT)
            with self.assertRaises(ValueError):
                local.load_profile(server.ROOT / 'package-profile.json', server.ROOT)

    def test_cli_retired_pair_and_profile_errors_are_explicit_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / 'runtime'
            for arguments, expected in (
                (['--pair', 'not-an-id'], 2), (['--pair', 'a' * 32], 2), (['--open'], 1),
                (['--status', '--synapses-profile', 'not-loaded'], 2),
                (['--start', '--synapses-profile', str(Path(temporary) / 'missing')], 1)
            ):
                result = subprocess.run([sys.executable, str(server.ROOT / 'cortex_server'), *arguments,
                                         '--runtime-dir', str(runtime)], capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertFalse(runtime.exists())
