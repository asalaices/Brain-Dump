# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Loopback source preview with owned lifecycle and an optional read-only Synapses pilot."""
import argparse
import errno
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import queue
import re
import secrets
import socket
from socketserver import TCPServer
import stat
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from . import __version__
from .connectors import NoRedirect
from .installation.discovery import safe
from .reconciliation import _lock as runtime_lock, _save as save_state
from .cortex_synapses import LocalSynapses, PREFIX, handle as handle_synapses, load_profile

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
TIMEOUT = 5
LOG = logging.getLogger('cortex_server')
CONTROL = '/_cortex/lifecycle'
PAIR_CONTROL = '/_cortex/pair'
LAUNCH_CONTROL = '/_cortex/open'


def private_file(path, limit=65536):
    safe(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or (limit is not None and info.st_size > limit):
        raise ValueError('Cortex runtime file must be regular and within its size limit.')
    if os.name != 'nt' and info.st_mode & 0o077:
        raise ValueError('Cortex runtime files must be private (mode 600).')


def validate_state(state):
    fields = {'schema_version', 'pid', 'instance', 'token', 'host', 'port', 'root'}
    if not isinstance(state, dict) or set(state) != fields:
        raise ValueError('Invalid Cortex runtime state; retained for inspection.')
    if type(state['schema_version']) is not int or state['schema_version'] != 1 or state['host'] != '127.0.0.1' or state['root'] != str(ROOT):
        raise ValueError('Cortex runtime state belongs to another checkout or host.')
    if type(state['pid']) is not int or state['pid'] <= 0 or type(state['port']) is not int or not 1 <= state['port'] <= 65535:
        raise ValueError('Invalid Cortex runtime PID or port.')
    if not isinstance(state['instance'], str) or not re.fullmatch(r'[a-f0-9]{32}', state['instance']):
        raise ValueError('Invalid Cortex instance identity.')
    if not isinstance(state['token'], str) or not re.fullmatch(r'[a-f0-9]{64}', state['token']):
        raise ValueError('Invalid Cortex control token.')
    return state


def read_state(runtime):
    path = runtime / 'state.json'
    if not path.exists() and not path.is_symlink():
        return None
    private_file(path)
    try:
        return validate_state(json.loads(path.read_text(encoding='utf-8')))
    except json.JSONDecodeError as error:
        raise ValueError('Invalid Cortex runtime JSON; retained for inspection.') from error


def control(state, stop=False, pair=None, launch=None):
    endpoint = LAUNCH_CONTROL if launch else PAIR_CONTROL if pair else CONTROL
    request = Request(
        f"http://127.0.0.1:{state['port']}{endpoint}",
        data=json.dumps({'launch': launch}).encode() if launch else json.dumps({'pair': pair}).encode() if pair else b'' if stop else None,
        method='POST' if stop or pair or launch else 'GET',
        headers={'X-Cortex-Control': state['token']}
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=TIMEOUT) as response:
            if stop:
                if response.status != 204:
                    raise ValueError('Cortex shutdown was not acknowledged.')
                return True
            body = response.read(8193)
            if len(body) > 8192:
                raise ValueError('Oversized Cortex identity response; state retained.')
            identity = json.loads(body)
    except URLError as error:
        if isinstance(error, HTTPError):
            error.close()
            if launch:
                raise ValueError(f'Browser launch control failed (HTTP {error.code}); verify the server version and configured profile. State retained.') from error
            if pair:
                raise ValueError(f'Browser pairing failed (HTTP {error.code}); verify the pending ID and server version. State retained.') from error
        if isinstance(error.reason, ConnectionRefusedError) or getattr(error.reason, 'errno', None) == errno.ECONNREFUSED:
            if pair or launch:
                raise ValueError('Cortex stopped before browser approval; no pairing was confirmed.') from error
            return False
        raise ValueError('Cortex ownership could not be verified; runtime state retained.') from error
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError('Cortex ownership could not be verified; runtime state retained.') from error
    if launch:
        fields = {'schema_version', 'status', 'launch_file'} if launch == 'issue' else {'schema_version', 'status'}
        if (not isinstance(identity, dict) or set(identity) != fields or identity.get('schema_version') != 1
                or identity.get('status') != ('launch_ready' if launch == 'issue' else 'launch_cancelled')
                or (launch == 'issue' and not isinstance(identity.get('launch_file'), str))):
            raise ValueError('Invalid Cortex browser launch response.')
        return identity
    if pair:
        if identity != {'schema_version': 1, 'status': 'paired', 'expires_in_seconds': 1800}:
            raise ValueError('Invalid Cortex browser pairing response.')
        return identity
    expected = {key: state[key] for key in ('pid', 'instance', 'root')}
    if identity != expected:
        raise ValueError('Cortex ownership mismatch; refusing lifecycle operation.')
    return True


class StaticHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        '.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, _format, *args):
        LOG.debug('HTTP request handled; request content omitted.')

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        super().end_headers()

    def authorized(self):
        host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != host or self.headers.get('Origin') not in (None, 'http://' + host):
            self.send_error(403)
            return False
        if not hmac.compare_digest(self.headers.get('X-Cortex-Control', '').encode(), self.server.identity['token'].encode()):
            self.send_error(403)
            return False
        return True

    def do_GET(self):
        if urlsplit(self.path).path != CONTROL:
            return super().do_GET()
        if self.authorized():
            body = json.dumps({key: self.server.identity[key] for key in ('pid', 'instance', 'root')}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith(PREFIX):
            handle_synapses(self)
        elif self.path not in (CONTROL, PAIR_CONTROL, LAUNCH_CONTROL):
            self.send_error(404)
        elif self.authorized():
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 256 or self.headers.get('Transfer-Encoding') is not None:
                    raise ValueError('Invalid control payload.')
                if self.path in (PAIR_CONTROL, LAUNCH_CONTROL):
                    if not length:
                        raise ValueError('Pairing requires a pending browser ID.')
                    self.connection.settimeout(TIMEOUT)
                    payload = json.loads(self.rfile.read(length))
                    if self.path == LAUNCH_CONTROL:
                        if payload == {'launch': 'issue'}:
                            result = self.server.synapses.launch(
                                self.server.runtime, f'http://127.0.0.1:{self.server.server_port}')
                        elif payload == {'launch': 'cancel'}:
                            self.server.synapses.cancel_launch()
                            result = {'schema_version': 1, 'status': 'launch_cancelled'}
                        else:
                            raise ValueError('Invalid launch request.')
                    else:
                        if not isinstance(payload, dict) or set(payload) != {'pair'} or not isinstance(payload['pair'], str):
                            raise ValueError('Invalid pairing request.')
                        result = self.server.synapses.pair(payload['pair'])
                    body = json.dumps(result).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if length:
                    raise ValueError('Shutdown does not accept a payload.')
            except (ValueError, OSError):
                self.send_error(400)
                return
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def send_head(self):
        parts = unquote(urlsplit(self.path).path).lstrip('/').split('/')
        if any(part.startswith('.') or '\\' in part or '\0' in part for part in parts):
            self.send_error(404)
            return None
        path = WEB.joinpath(*parts)
        if not path.resolve().is_relative_to(WEB) or any(item.is_symlink() for item in (path, *path.parents) if item.is_relative_to(WEB)):
            self.send_error(404)
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404)
        return None


class CortexHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # A fixed loopback identity must not block startup on reverse DNS.
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]


def worker():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s cortex_server %(levelname)s %(message)s')
    config = json.loads(sys.stdin.readline(8193))
    if (not isinstance(config, dict) or not {'instance', 'token', 'port'} <= set(config)
            or set(config) - {'instance', 'token', 'port', 'profile', 'runtime'}
            or type(config['port']) is not int or not 0 <= config['port'] <= 65535):
        raise ValueError('Invalid Cortex startup configuration.')
    if not (WEB / 'index.html').is_file():
        raise ValueError('Cortex web assets are unavailable in this source checkout.')
    registered = threading.Event()

    def startup_deadline():
        if not registered.wait(TIMEOUT * 2):
            LOG.error('Unregistered worker exceeded its startup deadline; exiting.')
            os._exit(1)

    threading.Thread(target=startup_deadline, daemon=True).start()
    with CortexHTTPServer(('127.0.0.1', config['port']), StaticHandler) as server:
        server.daemon_threads = True
        identity = validate_state({
            'schema_version': 1, 'pid': os.getpid(), 'instance': config['instance'],
            'token': config['token'], 'host': '127.0.0.1',
            'port': server.server_port, 'root': str(ROOT)
        })
        server.identity = identity
        server.runtime = Path(config['runtime']) if config.get('runtime') else None
        server.synapses = LocalSynapses(load_profile(config['profile'], ROOT) if config.get('profile') else None)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        try:
            print(json.dumps({key: identity[key] for key in ('pid', 'port', 'instance', 'root')}), flush=True)
            # EOF on controller failure prevents an unregistered background orphan.
            if sys.stdin.readline(16) == 'start\n':
                registered.set()
                LOG.info('Owned static server started pid=%s port=%s', identity['pid'], identity['port'])
                thread.join()
        finally:
            server.synapses.cancel_launch()
            server.shutdown()
            thread.join()
            LOG.info('Owned static server stopped pid=%s', identity['pid'])
    return 0


def start(runtime, port, profile=None):
    token = secrets.token_hex(32)
    instance = secrets.token_hex(16)
    output = runtime / 'server.log'
    if output.exists() or output.is_symlink():
        private_file(output, limit=None)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'ab') as log:
        process = subprocess.Popen(
            [sys.executable, '-B', '-m', 'brain_bridge.cortex_server', '--worker'],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            start_new_session=True, close_fds=True
        )
    replies = queue.Queue()
    threading.Thread(target=lambda: replies.put(process.stdout.readline(8193)), daemon=True).start()
    state = None
    acknowledged = False
    try:
        config = {'instance': instance, 'token': token, 'port': port, 'runtime': str(runtime)}
        if profile is not None:
            config['profile'] = str(profile)
        process.stdin.write((json.dumps(config) + '\n').encode())
        process.stdin.flush()
        try:
            line = replies.get(timeout=TIMEOUT)
        except queue.Empty as error:
            raise ValueError('Cortex startup readiness timed out; inspect the private server log.') from error
        if not line:
            raise ValueError('Cortex failed to start (port collision or worker error); inspect the private server log.')
        ready = json.loads(line)
        if not isinstance(ready, dict) or set(ready) != {'pid', 'port', 'instance', 'root'}:
            raise ValueError('Invalid Cortex startup identity.')
        state = validate_state({
            'schema_version': 1, 'pid': process.pid, 'instance': instance,
            'token': token, 'host': '127.0.0.1', 'port': ready['port'], 'root': str(ROOT)
        })
        if ready != {key: state[key] for key in ('pid', 'port', 'instance', 'root')} or not control(state):
            raise ValueError('Cortex startup ownership/readiness verification failed.')
        save_state(runtime, state)
        process.stdin.write(b'start\n')
        process.stdin.flush()
        acknowledged = True
        return state
    finally:
        process.stdin.close()
        process.stdout.close()
        if not acknowledged:
            try:
                process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired as error:
                raise ValueError('Startup worker did not exit after control-pipe closure; no PID was signalled.') from error
            if state is not None and (runtime / 'state.json').exists():
                saved = read_state(runtime)
                if saved and saved['instance'] == instance:
                    (runtime / 'state.json').unlink()


def operate(action, runtime, port, profile=None, pair=None):
    runtime = Path(os.path.abspath(runtime))
    safe(runtime)
    if runtime.is_relative_to(ROOT):
        raise ValueError('Cortex runtime state must be outside the source checkout.')
    if not runtime.exists():
        if action in ('pair', 'open'):
            raise ValueError('Start Cortex with an external Synapses profile before opening a trusted tab.')
        if action != 'start':
            return {'status': 'stopped'}, 1 if action == 'status' else 0
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        safe(runtime)
    if not runtime.is_dir() or (os.name != 'nt' and runtime.stat().st_mode & 0o077):
        raise ValueError('Select a private Cortex runtime directory (mode 700).')
    with runtime_lock(runtime, create=True):
        state = read_state(runtime)
        running = state is not None and control(state)
        if action == 'status':
            return public_state(state) if running else {'status': 'stale' if state else 'stopped'}, 0 if running else 1
        if action == 'pair':
            if not running:
                raise ValueError('Cortex is not running; no browser was paired.')
            return control(state, pair=pair), 0
        if action == 'open':
            if not running:
                raise ValueError('Start Cortex with a consultation profile before opening the connected UI.')
            result = control(state, launch='issue')
            path = Path(result['launch_file'])
            try:
                if path.parent != runtime or not re.fullmatch(r'launch-[\w-]+\.html', path.name):
                    raise ValueError('Invalid private Cortex launch file.')
                private_file(path)
                if not webbrowser.open(path.as_uri(), new=2):
                    raise ValueError('The native browser did not accept the private launch page.')
            except (OSError, ValueError, webbrowser.Error):
                control(state, launch='cancel')
                raise
            return {**public_state(state), 'browser': 'launch_requested',
                    'message': 'Click Open Cortex on the private launch page, then select your Brain and Connect.'}, 0
        if action == 'stop':
            if running:
                control(state, stop=True)
                deadline = time.monotonic() + TIMEOUT
                while True:
                    try:
                        with socket.create_connection(('127.0.0.1', state['port']), timeout=TIMEOUT):
                            pass
                    except ConnectionRefusedError:
                        break
                    except ConnectionResetError:
                        # A closing listener can reset a probe; still require refusal.
                        pass
                    if time.monotonic() >= deadline:
                        raise ValueError('Cortex did not stop; state retained. No PID was signalled.')
                    time.sleep(.05)
            if state:
                (runtime / 'state.json').unlink()
            return {'status': 'stopped', 'stale_state_removed': state is not None and not running}, 0
        if running and profile is not None:
            raise ValueError('Cortex is already running; stop/start to apply a Synapses profile.')
        if not running:
            if state:
                (runtime / 'state.json').unlink()
            state = start(runtime, port, profile) if profile is not None else start(runtime, port)
        return {**public_state(state), 'log': str(runtime / 'server.log')}, 0


def public_state(state):
    return {'status': 'running', 'pid': state['pid'], 'url': f"http://127.0.0.1:{state['port']}/"}


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ['--worker']:
        return worker()
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for action in ('start', 'stop', 'status'):
        actions.add_argument('--' + action, action='store_true')
    actions.add_argument('--open', action='store_true', help='Open a private one-click launch page for the running configured Cortex server.')
    actions.add_argument('--pair', metavar='BROWSER_ID', help='Legacy diagnostic pairing; normal browser access uses --open.')
    parser.add_argument('--synapses-profile', type=Path, help='External consultation routing profile; --start only.')
    parser.add_argument('--version', action='version', version='cortex_server ' + __version__)
    parser.add_argument('--port', type=int, default=os.environ.get('CORTEX_PORT', '8080'))
    default_runtime = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'brain-dump' / ('cortex-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
    parser.add_argument('--runtime-dir', type=Path, default=os.environ.get('CORTEX_RUNTIME_DIR', default_runtime))
    parser.add_argument('--json', action='store_true', help='Emit JSON (the default).')
    parser.add_argument('--pretty', action='store_true', help='Indent the same JSON document.')
    args = parser.parse_args(arguments)
    if args.synapses_profile is not None and not args.start:
        parser.error('--synapses-profile is supported only with --start.')
    if args.pair is not None and not re.fullmatch('[a-f0-9]{32}', args.pair):
        parser.error('--pair requires the pending browser ID displayed by Cortex.')
    if not 0 <= args.port <= 65535:
        parser.error('Port must be 0..65535; 0 selects an available ephemeral port.')
    host = os.environ.get('CORTEX_HOST', '127.0.0.1')
    if host not in ('127.0.0.1', 'localhost'):
        parser.error('Cortex serves only loopback (127.0.0.1 or localhost).')
    from .__main__ import runtime_info
    try:
        action = 'pair' if args.pair else next(name for name in ('start', 'stop', 'status', 'open') if getattr(args, name))
        if args.synapses_profile is not None:
            load_profile(args.synapses_profile, ROOT)
        result, code = operate(action, args.runtime_dir, args.port, args.synapses_profile, args.pair)
    except (OSError, ValueError, RuntimeError) as error:
        result, code = {'status': 'error', 'error': str(error)}, 1
    result['info'] = {**runtime_info(), 'script': 'cortex_server'}
    print(json.dumps(result, indent=2 if args.pretty else None))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
