# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Short-lived owner-private launch document; credentials never enter a URL."""
import hashlib
from html import escape
import json
import os
from pathlib import Path
import secrets
import tempfile
import webbrowser


def open_document(path):
    if not webbrowser.open(path.as_uri(), new=2):
        raise ValueError('The native browser did not accept the private approval page.')


def create_document(runtime, origin, credential, source):
    nonce = secrets.token_hex(16)
    script = """
const origin = ORIGIN;
let credential = CREDENTIAL;
let child;
let transferred = false;
const button = document.querySelector('button');
const notice = document.querySelector('[role="status"]');
const timer = setTimeout(() => {
  credential = null;
  button.disabled = true;
  notice.textContent = 'This approval expired. Return to Cortex and click Connect to Brain again.';
}, 60000);
button.addEventListener('click', () => {
  child = window.open(origin + '/', '_blank');
  if (!child) {
    notice.textContent = 'Browser blocked the new tab. Allow this local launch to open Cortex, then retry.';
    return;
  }
  button.disabled = true;
  notice.textContent = 'Opening the trusted local Cortex tab...';
});
window.addEventListener('message', event => {
  if (!child || event.source !== child || event.origin !== origin) return;
  if (event.data?.type === 'cortex-ready' && credential && !transferred) {
    child.postMessage({type: 'cortex-bootstrap', credential}, origin);
    credential = null;
    transferred = true;
  } else if (event.data?.type === 'cortex-bootstrap-complete' && transferred) {
    clearTimeout(timer);
    notice.textContent = 'Approved. Cortex is connecting in the new tab. You may close this approval page.';
  }
});
""".replace('ORIGIN', json.dumps(origin)).replace('CREDENTIAL', json.dumps(credential))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-{nonce}'; base-uri 'none'; form-action 'none'">
<title>Approve Cortex connection</title></head><body>
<h1>Connect Cortex to your Brain</h1>
<p>Approve a read-only connection to <strong>{escape(source)}</strong>
through Cortex at {escape(origin)}. Existing Brain permissions still apply;
this does not create an access grant.</p>
<button type="button">Approve connection</button>
<p role="status">Approval expires in one minute. The connected Cortex tab opens automatically.</p>
<p><a href="{escape(origin)}/" rel="noreferrer">Back to Cortex</a></p>
<script nonce="{nonce}">{script}</script>
</body></html>
"""
    descriptor, name = tempfile.mkstemp(prefix='launch-', suffix='.html', dir=runtime)
    path = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(html)
    except OSError:
        path.unlink()
        raise
    expected_size = path.stat().st_size
    expected = hashlib.sha256(path.read_bytes()).digest()

    def cleanup():
        # Never erase a replacement/foreign file at the same path.
        if (not path.is_symlink() and path.is_file() and path.stat().st_size == expected_size
                and hashlib.sha256(path.read_bytes()).digest() == expected):
            path.unlink()

    return path, cleanup
