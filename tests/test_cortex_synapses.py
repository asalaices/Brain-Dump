# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Synthetic local pairing/HTTP fixtures; never consult a live private source."""
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

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
        self.temporary = tempfile.TemporaryDirectory(prefix='cortex-launch-test-')
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name).resolve()
        self.runtime.chmod(0o700)
        self.http.runtime = self.runtime
        self.addCleanup(self.app.cancel_launch)
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

    def pending(self):
        code, result, headers = self.post('session')
        self.assertEqual(code, 200)
        self.assertEqual(result['status'], 'pairing_required')
        self.assertNotIn('token', result)
        return result['pairing_id'], headers['Set-Cookie'].split(';')[0]

    def paired(self):
        request_id, cookie = self.pending()
        server.control(self.state, pair=request_id)
        return cookie

    def bootstrap(self):
        result = server.control(self.state, launch='issue')
        path = Path(result['launch_file'])
        html = path.read_text()
        credential = re.search(r'let credential = "([a-f0-9]{64})";', html).group(1)
        self.assertNotIn(credential, json.dumps(result))
        return credential, path, html

    def trusted(self):
        credential, path, _ = self.bootstrap()
        code, result, headers = self.post('bootstrap', {'credential': credential})
        self.assertEqual((code, result['status']), (200, 'trusted'))
        self.assertFalse(path.exists())
        self.assertEqual(result['sources'], ['example'])
        return headers['Set-Cookie'].split(';')[0]

    def test_native_launch_uses_private_file_not_credential_url_and_cleans_on_redemption(self):
        (self.runtime / 'state.json').write_text(json.dumps(self.state))
        (self.runtime / 'state.json').chmod(0o600)
        with patch.object(server.webbrowser, 'open', return_value=True) as opened:
            result, code = server.operate('open', self.runtime, 8080)
        self.assertEqual(code, 0)
        self.assertEqual(result['browser'], 'launch_requested')
        self.assertNotIn('launch_file', result)
        uri = opened.call_args.args[0]
        self.assertTrue(uri.startswith(self.runtime.as_uri()))
        self.assertTrue(uri.endswith('.html'))
        self.assertNotIn('?', uri)
        self.assertNotIn('#', uri)
        path = next(self.runtime.glob('launch-*.html'))
        raw = path.read_text()
        credential = re.search(r'let credential = "([a-f0-9]{64})";', raw).group(1)
        self.assertNotIn(credential, uri + json.dumps(result))
        self.assertIn('content="no-referrer"', raw)
        self.assertIn("child.postMessage({type: 'cortex-bootstrap', credential}, origin)", raw)
        self.assertNotIn('localStorage', raw)
        self.assertNotIn('location.hash', raw)
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.post('bootstrap', {'credential': credential})[0], 200)
        self.assertFalse(path.exists())

    def test_native_launch_failure_cancels_bootstrap_and_leaves_server_running(self):
        (self.runtime / 'state.json').write_text(json.dumps(self.state))
        (self.runtime / 'state.json').chmod(0o600)
        for error in (False, OSError('synthetic native failure')):
            with patch.object(server.webbrowser, 'open', side_effect=error if isinstance(error, Exception) else None,
                              return_value=error):
                with self.assertRaises((ValueError, OSError)):
                    server.operate('open', self.runtime, 8080)
            self.assertEqual(list(self.runtime.glob('launch-*.html')), [])
            self.assertIsNone(self.app.bootstrap)
            self.assertTrue(server.control(self.state))

    def test_bootstrap_wrong_origin_host_key_and_replay_cannot_read_or_consume_valid_launch(self):
        credential, path, _ = self.bootstrap()
        for fields in ({'Origin': 'null'}, {'Origin': 'http://127.0.0.1:9999'},
                       {'Host': 'example.invalid'}, {'X-Cortex-Browser': ''}):
            self.assertEqual(self.post('bootstrap', {'credential': credential}, headers=fields)[0], 403)
            self.assertTrue(path.exists())
        self.assertEqual(self.post('bootstrap', {'credential': '0' * 64})[0], 401)
        self.assertTrue(path.exists())
        code, result, headers = self.post('bootstrap', {'credential': credential})
        self.assertEqual(code, 200)
        self.assertEqual(result['status'], 'trusted')
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.post('bootstrap', {'credential': credential})[0], 401)
        self.assertEqual(self.post('status', cookie=cookie)[0], 401)
        self.assertEqual(self.post('session', {'source': 'example'}, cookie,
                                   headers={'X-Cortex-Browser': '4' * 64})[0], 401)
        self.status.assert_not_called()

    def test_bootstrap_expiry_replacement_and_timer_race_preserve_new_launch(self):
        now = [0]
        self.app.clock = lambda: now[0]
        old, path, _ = self.bootstrap()
        latest, second, _ = self.bootstrap()
        self.assertFalse(path.exists())
        self.app.cancel_launch(old)
        self.assertTrue(second.exists())
        self.assertEqual(self.post('bootstrap', {'credential': old})[0], 401)
        now[0] = 61
        self.assertEqual(self.post('bootstrap', {'credential': latest})[0], 401)
        self.assertFalse(second.exists())
        self.assertIsNone(self.app.bootstrap)

    def test_bootstrap_atomic_single_use_even_under_concurrent_redemption(self):
        credential, path, _ = self.bootstrap()
        barrier = threading.Barrier(3)
        results = []
        def redeem(key):
            barrier.wait(timeout=3)
            results.append(self.app.redeem(credential, key))
        threads = [threading.Thread(target=redeem, args=(digit * 64,)) for digit in ('3', '4')]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sum(token is not None for token, _ in results), 1)
        self.assertFalse(path.exists())

    def test_configured_source_only_connect_disconnect_and_reconnect_still_reauthorize(self):
        cookie = self.trusted()
        for source in ('other', '/private/path', 'https://other.invalid'):
            self.assertEqual(self.post('session', {'source': source}, cookie)[0], 403)
        self.status.assert_not_called()
        self.assertEqual(self.post('session', {'source': 'example'}, cookie)[1]['status'], 'paired')
        self.assertEqual(self.post('status', cookie=cookie)[0], 200)
        self.assertEqual(self.post('disconnect', cookie=cookie)[0], 200)
        self.assertEqual(self.post('status', cookie=cookie)[0], 401)
        self.assertEqual(self.post('session', {'source': 'example'}, cookie)[0], 200)
        self.status.side_effect = AccessDenied('private source revoked')
        with self.assertLogs(local.LOG, level='WARNING'):
            self.assertEqual(self.post('status', cookie=cookie)[0], 403)
        self.assertEqual(self.status.call_count, 2)

    def test_cleanup_never_deletes_replacement_or_foreign_content(self):
        _, path, _ = self.bootstrap()
        path.write_text('foreign replacement')
        self.app.cancel_launch()
        self.assertEqual(path.read_text(), 'foreign replacement')

    def test_unconfigured_bootstrap_and_untrusted_native_control_fail_closed(self):
        self.app.profile = None
        with self.assertRaises(ValueError):
            server.control(self.state, launch='issue')
        self.assertEqual(list(self.runtime.glob('launch-*.html')), [])
        self.app.profile = PROFILE
        for body in ({}, {'credential': 'bad'}, {'credential': 'a' * 64, 'source_repo': '/other'}):
            self.assertEqual(self.post('bootstrap', body)[0], 400)

    def test_owner_control_pairs_only_selected_browser_and_cookie_is_private(self):
        first_id, first = self.pending()
        second_id, second = self.pending()
        code, body, _ = self.post('status', cookie=first)
        self.assertEqual((code, body['status']), (401, 'pairing_required'))
        self.status.assert_not_called()
        self.assertEqual(server.control(self.state, pair=first_id)['status'], 'paired')
        self.assertTrue(server.control(self.state))
        self.assertEqual(self.post('session', cookie=first)[1]['status'], 'paired')
        self.assertEqual(self.post('status', cookie=second)[0], 401)
        with self.assertRaises(ValueError):
            server.control(self.state, pair=second_id)
        code, result, headers = self.post('status', cookie=first)
        self.assertEqual(code, 200)
        self.assertFalse(result['cache_fresh'])
        self.assertEqual(result['source'], SOURCE)
        self.status.assert_called_once_with(**PARAMETERS)
        self.assertIn('no-store', headers['Cache-Control'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        _, _, cookie_headers = self.post('session')
        for attribute in ('HttpOnly', 'SameSite=Strict', 'Path=/api/local/'):
            self.assertIn(attribute, cookie_headers['Set-Cookie'])
        self.assertNotIn('token', json.dumps(result))

    def test_pairing_an_old_worker_cannot_be_interpreted_as_shutdown(self):
        class LegacyHandler(server.StaticHandler):
            def do_POST(self):
                if self.path == server.CONTROL:
                    self.server.unexpected_stop = True
                    return super().do_POST()
                self.send_error(404)
        self.http.RequestHandlerClass = LegacyHandler
        self.http.unexpected_stop = False
        with self.assertRaisesRegex(ValueError, 'server version'):
            server.control(self.state, pair='a' * 32)
        self.assertFalse(self.http.unexpected_stop)
        self.assertTrue(server.control(self.state))

    def test_worker_exit_before_pairing_is_an_error_not_a_false_success(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        stopped = {**self.state, 'port': port}
        self.assertFalse(server.control(stopped))
        with self.assertRaisesRegex(ValueError, 'no pairing was confirmed'):
            server.control(stopped, pair='a' * 32)

    def test_pairing_via_real_cli_uses_private_control_without_printing_credentials(self):
        request_id, cookie = self.pending()
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary).resolve() / 'runtime'
            runtime.mkdir(mode=0o700)
            path = runtime / 'state.json'
            path.write_text(json.dumps(self.state))
            path.chmod(0o600)
            process = subprocess.run(
                [sys.executable, str(server.ROOT / 'cortex_server'), '--pair', request_id,
                 '--runtime-dir', str(runtime)], capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(json.loads(process.stdout)['status'], 'paired')
            self.assertNotIn(self.state['token'], process.stdout + process.stderr)
        self.assertEqual(self.post('status', cookie=cookie)[0], 200)

    def test_origin_host_csrf_methods_and_control_reject_untrusted_callers(self):
        cookie = self.paired()
        for fields in (
            {'Origin': 'http://example.invalid'}, {'Origin': ''},
            {'Host': 'example.invalid'}, {'X-Cortex-Read-Only': ''}, {'X-Cortex-Browser': ''}
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.post('status', cookie=cookie, headers=fields)[0], 403)
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
        self.addCleanup(connection.close)
        connection.request('GET', local.PREFIX + 'status')
        response = connection.getresponse()
        self.assertEqual(response.status, 404)
        response.read()
        self.status.assert_not_called()

    def test_bounded_schema_rejects_paths_sources_commands_and_malformed_requests(self):
        cookie = self.paired()
        for body in ({}, {'query': ''}, {'query': ' '}, {'query': None}, {'query': 12},
                     {'query': 'x' * 513}, {'query': 'x', 'source_repo': '/other'},
                     {'query': 'x', 'operation': 'publish'}, {'query': 'x', 'source': 'other'}):
            with self.subTest(body=body):
                self.assertEqual(self.post('synapse', body=body, cookie=cookie)[0], 400)
        for raw in (b'{', b'[]', b'{"query":"a","query":"b"}', b'{"query":NaN}', b'\xff', b'x' * 4097):
            self.assertEqual(self.post('synapse', cookie=cookie, raw=raw)[0], 400)
        self.assertEqual(self.post('status', cookie=cookie, headers={'Content-Type': 'text/plain'})[0], 400)
        self.assertEqual(self.post('export', cookie=cookie)[0], 404)
        self.assertEqual(self.post('status?source=other', cookie=cookie)[0], 404)
        self.synapse.assert_not_called()
        self.status.assert_not_called()

    def test_cited_query_delegates_bounded_existing_engine_and_preserves_receipt(self):
        cookie = self.paired()
        code, receipt, _ = self.post('synapse', {'query': 'synthetic context'}, cookie)
        self.assertEqual(code, 200)
        self.assertEqual(receipt, FOUND)
        self.synapse.assert_called_once_with(**PARAMETERS, term='synthetic context', backend='auto', limit=5, excerpt_chars=240)
        self.synapse.return_value = {**FOUND, 'status': 'no_match', 'matches': []}
        self.assertEqual(self.post('synapse', {'query': 'absent'}, cookie)[1]['status'], 'no_match')

    def test_denied_unavailable_error_do_not_leak_private_diagnostics_or_cached_results(self):
        cookie = self.paired()
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

    def test_disconnect_expiry_and_approval_replacement_revoke_access(self):
        cookie = self.paired()
        self.assertEqual(self.post('disconnect', cookie=cookie)[1]['status'], 'disconnected')
        self.assertEqual(self.post('status', cookie=cookie)[0], 401)
        now = [0]
        self.app.clock = lambda: now[0]
        request_id, cookie = self.pending()
        now[0] = 301
        with self.assertRaises(ValueError):
            self.app.pair(request_id)
        cookie = self.paired()
        now[0] += 1801
        self.assertEqual(self.post('status', cookie=cookie)[0], 401)
        cookie = self.paired()
        next_id, next_cookie = self.pending()
        self.app.pair(next_id)
        self.assertEqual(self.post('status', cookie=cookie)[0], 401)
        self.assertEqual(self.post('status', cookie=next_cookie)[0], 200)

    def test_concurrency_is_bounded_and_revocation_during_read_withholds_result(self):
        cookie = self.paired()
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
        self.assertEqual(result[0], (401, {'status': 'pairing_required'}))
        self.assertFalse(thread.is_alive())
        self.assertTrue(self.app.operation.acquire(blocking=False))
        self.app.operation.release()

    def test_cookie_stolen_by_other_loopback_port_does_not_authorize_another_tab(self):
        cookie = self.paired()
        foreign = {'X-Cortex-Browser': '4' * 64}
        self.assertEqual(self.post('status', cookie=cookie, headers=foreign)[0], 401)
        self.assertEqual(self.post('session', cookie=cookie, headers=foreign)[1]['status'], 'pairing_required')
        self.post('disconnect', cookie=cookie, headers=foreign)
        self.assertEqual(self.post('status', cookie=cookie)[0], 200)

    def test_oversized_source_response_is_withheld(self):
        self.status.return_value = {**STATUS, 'unexpected': 'sensitive-fixture' * 30000}
        with self.assertLogs(local.LOG, level='WARNING'):
            code, result, _ = self.post('status', cookie=self.paired())
        self.assertEqual(code, 502)
        self.assertNotIn('sensitive-fixture', json.dumps(result))

    def test_pending_sessions_are_bounded_and_profile_is_opt_in(self):
        self.http.synapses.profile = None
        self.assertEqual(self.post('session')[0], 503)
        self.assertEqual(self.app.sessions, {})
        self.http.synapses.profile = PROFILE
        for _ in range(8):
            self.pending()
        self.assertEqual(self.post('session')[0], 429)
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
                    pending = json.loads(response.read())
                    self.assertEqual(cli('--pair', pending['pairing_id']).returncode, 0)
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

    def test_cli_pair_and_profile_errors_are_explicit_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / 'runtime'
            for arguments, expected in (
                (['--pair', 'not-an-id'], 2),
                (['--pair', 'a' * 32], 1),
                (['--status', '--synapses-profile', 'not-loaded'], 2),
                (['--start', '--synapses-profile', str(Path(temporary) / 'missing')], 1)
            ):
                result = subprocess.run([sys.executable, str(server.ROOT / 'cortex_server'), *arguments,
                                         '--runtime-dir', str(runtime)], capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertFalse(runtime.exists())
