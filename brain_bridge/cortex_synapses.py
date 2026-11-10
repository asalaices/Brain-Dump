# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Owner-paired, process-local read-only adapter for one named Brain source."""
from http.cookies import SimpleCookie, CookieError
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import re
import sqlite3
import stat
import subprocess
import threading
import time
from uuid import uuid4

from .adapters import managed_status
from .cortex_launch import create_document
from .installation.discovery import safe
from .policy import AccessDenied, AuthorizationUnavailable
from .store import unique_object, reject_constant
from .synapse import synapse_request

PREFIX = '/api/local/'
COOKIE = 'cortex_local'
LOG = logging.getLogger('cortex_server')
ERRORS = {
    'denied': 'Source access denied or reader not synchronized; results withheld.',
    'unavailable': 'Source authority is unavailable; results withheld.',
    'error': 'Authorized source operation failed; results withheld.'
}


def load_profile(path, root):
    """Routing hints only; the managed functions independently authorize reads."""
    path = Path(os.path.abspath(Path(path).expanduser()))
    safe(path)
    if path.is_relative_to(root):
        raise ValueError('Select an external consultation profile, not a source-checkout file.')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
        raise ValueError('Consultation profile must be a regular JSON file up to 8 KiB.')
    if os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise ValueError('Consultation profile must be owner-owned and not writable by others.')
    profile = json.loads(path.read_bytes(), object_pairs_hook=unique_object, parse_constant=reject_constant)
    keys = ('identity_repo', 'source_repo', 'source', 'cache_dir')
    if not isinstance(profile, dict) or any(not isinstance(profile.get(key), str) or not profile[key].strip() for key in keys):
        raise ValueError('Consultation profile needs identity_repo, source_repo, source and cache_dir.')
    selected = {key: profile[key] for key in keys}
    if len(selected['source']) > 128:
        raise ValueError('Configured source alias must be at most 128 characters.')
    for key in ('identity_repo', 'source_repo', 'cache_dir'):
        selected[key] = Path(selected[key]).expanduser()
        if not selected[key].is_absolute():
            raise ValueError('Consultation profile paths must be absolute.')
        safe(selected[key])
        if selected[key].resolve().is_relative_to(root):
            raise ValueError('Private source and cache paths must be outside this source checkout.')
    return selected


class LocalSynapses:
    def __init__(self, profile=None, clock=time.monotonic):
        self.profile = profile
        self.clock = clock
        self.sessions = {}
        self.bootstrap = None
        self.lock = threading.Lock()
        self.operation = threading.BoundedSemaphore(1)

    def _prune(self):
        now = self.clock()
        self.sessions = {key: value for key, value in self.sessions.items() if value['expires'] > now}

    def launch(self, runtime, origin):
        if self.profile is None:
            raise ValueError('Start Cortex with an external consultation profile before opening its connected UI.')
        if runtime is None:
            raise ValueError('Restart Cortex to enable its private native browser launcher.')
        with self.lock:
            self._cancel_launch()
            credential = secrets.token_hex(32)
            path, cleanup = create_document(runtime, origin, credential)
            self.bootstrap = {'credential': credential, 'expires': self.clock() + 60, 'cleanup': cleanup}
            timer = threading.Timer(60, self.cancel_launch, args=(credential,))
            timer.daemon = True
            self.bootstrap['timer'] = timer
            timer.start()
            return {'schema_version': 1, 'status': 'launch_ready', 'launch_file': str(path)}

    def _cancel_launch(self):
        if self.bootstrap is not None:
            self.bootstrap['timer'].cancel()
            self.bootstrap['cleanup']()
            self.bootstrap = None

    def cancel_launch(self, credential=None):
        with self.lock:
            if credential is None or (self.bootstrap and hmac.compare_digest(self.bootstrap['credential'], credential)):
                self._cancel_launch()

    def redeem(self, credential, browser_key):
        with self.lock:
            launch = self.bootstrap
            if launch and launch['expires'] <= self.clock():
                self._cancel_launch()
                launch = None
            if not launch or not hmac.compare_digest(launch['credential'], credential):
                return None, {'status': 'launch_required'}
            self._cancel_launch()
            token = secrets.token_hex(32)
            self.sessions = {token: {'status': 'trusted', 'pairing_id': uuid4().hex,
                                     'key': browser_key, 'expires': self.clock() + 1800}}
            return token, self._receipt(self.sessions[token])

    def _receipt(self, row):
        return {key: row[key] for key in ('status', 'pairing_id')} | {
            'expires_in_seconds': max(0, int(row['expires'] - self.clock())),
            'sources': [self.profile['source']]
        }

    def connect(self, token, browser_key, source):
        with self.lock:
            self._prune()
            row = self.sessions.get(token)
            if not row or not hmac.compare_digest(row['key'], browser_key) or row['status'] not in ('trusted', 'paired'):
                return 401, {'status': 'launch_required'}
            if source != self.profile['source']:
                return 403, {'status': 'denied'}
            row['status'] = 'paired'
            return 200, self._receipt(row)

    def session(self, token, browser_key):
        with self.lock:
            self._prune()
            row = self.sessions.get(token)
            return row['status'] if row and hmac.compare_digest(row['key'], browser_key) else None

    def begin(self, token, browser_key):
        with self.lock:
            self._prune()
            if token in self.sessions and hmac.compare_digest(self.sessions[token]['key'], browser_key):
                row = self.sessions[token]
            else:
                if len(self.sessions) >= 8:
                    return None, {'status': 'busy'}
                token = secrets.token_hex(32)
                row = {'status': 'pairing_required', 'pairing_id': uuid4().hex, 'key': browser_key,
                       'expires': self.clock() + 300}
                self.sessions[token] = row
            return token, {**{key: row[key] for key in ('status', 'pairing_id')},
                           'expires_in_seconds': max(0, int(row['expires'] - self.clock()))}

    def pair(self, request_id):
        with self.lock:
            self._prune()
            selected = next((token for token, row in self.sessions.items()
                             if row['pairing_id'] == request_id and row['status'] == 'pairing_required'), None)
            if selected is None:
                raise ValueError('No unexpired pending browser matches this pairing ID.')
            # One owner-approved tab per process.
            self.sessions = {selected: {**self.sessions[selected], 'status': 'paired',
                                        'expires': self.clock() + 1800}}
        return {'schema_version': 1, 'status': 'paired', 'expires_in_seconds': 1800}

    def disconnect(self, token, browser_key):
        with self.lock:
            row = self.sessions.get(token)
            if row and hmac.compare_digest(row['key'], browser_key):
                row['status'] = 'trusted'

    def read(self, token, operation, body, browser_key):
        if self.session(token, browser_key) != 'paired':
            return 401, {'status': 'pairing_required'}
        if not self.operation.acquire(blocking=False):
            return 429, {'status': 'busy'}
        try:
            request_id = str(uuid4())
            try:
                parameters = {**self.profile}
                parameters['source_name'] = parameters.pop('source')
                if operation == 'status':
                    result = {**managed_status(**parameters), 'status': 'ready'}
                else:
                    result = synapse_request(**parameters, term=body['query'],
                                             backend='auto', limit=5, excerpt_chars=240)
                if result.get('status') in ERRORS:
                    status = result['status']
                    LOG.warning('Local Synapses read returned %s; payload omitted.', status)
                    result = {'status': status, 'error': ERRORS[status]}
            except (AuthorizationUnavailable, AccessDenied, ValueError, RuntimeError,
                    OSError, sqlite3.Error, subprocess.TimeoutExpired) as error:
                status = ('unavailable' if isinstance(error, AuthorizationUnavailable) else
                          'denied' if isinstance(error, AccessDenied) else 'error')
                LOG.warning('Local Synapses read failed category=%s; payload omitted.', type(error).__name__)
                result = {'status': status, 'error': ERRORS[status]}
            if self.session(token, browser_key) != 'paired':
                return 401, {'status': 'pairing_required'}
            return {'denied': 403, 'unavailable': 503, 'error': 502}.get(result['status'], 200), {
                'schema_version': 1, 'request_id': request_id, 'read_only': True, **result
            }
        finally:
            self.operation.release()


def cookie_token(headers):
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get('Cookie', ''))
    except CookieError:
        return None
    value = cookie.get(COOKIE)
    return value.value if value else None


def reply(handler, code, body, token=None, clear=False):
    raw = json.dumps({'schema_version': 1, **body}, ensure_ascii=True).encode()
    if len(raw) > 262144:
        LOG.warning('Local Synapses response exceeded its byte limit; payload withheld.')
        code = 502
        raw = json.dumps({'schema_version': 1, 'status': 'error', 'error': ERRORS['error']}).encode()
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(raw)))
    if token is not None or clear:
        handler.send_header('Set-Cookie', f'{COOKIE}={token or ""}; Path={PREFIX}; HttpOnly; SameSite=Strict; Max-Age={0 if clear else 1800}')
    handler.end_headers()
    handler.wfile.write(raw)


def handle(handler):
    """Bounded same-origin POSTs; configured source selection never grants access."""
    try:
        length = int(handler.headers.get('Content-Length', '-1'))
        if not 2 <= length <= 4096:
            raise ValueError('Invalid body length')
        handler.connection.settimeout(3)
        # Consume bounded input before rejecting; unread bytes can reset Windows TCP.
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError('Incomplete body')
    except (ValueError, OSError):
        reply(handler, 400, {'status': 'invalid_request'})
        return
    host = f'127.0.0.1:{handler.server.server_port}'
    browser_key = handler.headers.get('X-Cortex-Browser', '')
    if (handler.headers.get('Host') != host or handler.headers.get('Origin') != 'http://' + host
            or handler.headers.get('X-Cortex-Read-Only') != '1'
            or not re.fullmatch('[a-f0-9]{64}', browser_key)):
        reply(handler, 403, {'status': 'denied'})
        return
    app = handler.server.synapses
    if app.profile is None:
        reply(handler, 503, {'status': 'not_configured'})
        return
    endpoint = handler.path.removeprefix(PREFIX)
    if endpoint not in ('bootstrap', 'session', 'disconnect', 'status', 'synapse'):
        reply(handler, 404, {'status': 'not_found'})
        return
    if handler.headers.get('Content-Type') != 'application/json' or handler.headers.get('Transfer-Encoding') is not None:
        reply(handler, 400, {'status': 'invalid_request'})
        return
    try:
        body = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
        shapes = {'bootstrap': {'credential'}, 'synapse': {'query'}}
        allowed = shapes.get(endpoint, set())
        if not isinstance(body, dict) or (set(body) != allowed and not (endpoint == 'session' and set(body) == {'source'})):
            raise ValueError('Unexpected fields')
        if endpoint == 'bootstrap' and (not isinstance(body['credential'], str) or not re.fullmatch('[a-f0-9]{64}', body['credential'])):
            raise ValueError('Invalid launch credential')
        if endpoint == 'session' and 'source' in body and (not isinstance(body['source'], str) or len(body['source']) > 128):
            raise ValueError('Invalid source')
        if endpoint == 'synapse' and (not isinstance(body['query'], str) or not body['query'].strip() or len(body['query']) > 512):
            raise ValueError('Invalid query')
    except (ValueError, UnicodeError, OSError):
        reply(handler, 400, {'status': 'invalid_request'})
        return
    token = cookie_token(handler.headers)
    if endpoint == 'bootstrap':
        selected, result = app.redeem(body['credential'], browser_key)
        reply(handler, 200 if selected else 401, result, token=selected)
    elif endpoint == 'session' and 'source' in body:
        code, result = app.connect(token, browser_key, body['source'])
        reply(handler, code, result)
    elif endpoint == 'session':
        selected, result = app.begin(token, browser_key)
        reply(handler, 200 if selected else 429, result, token=selected if selected != token else None)
    elif endpoint == 'disconnect':
        app.disconnect(token, browser_key)
        reply(handler, 200, {'status': 'disconnected'})
    else:
        code, result = app.read(token, endpoint, body, browser_key)
        reply(handler, code, result)
