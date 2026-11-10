# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Short-lived owner-private launch document; credentials never enter a URL."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile


def create_document(runtime, origin, credential):
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
  notice.textContent = 'This launch expired. Open Cortex again through its launcher.';
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
    notice.textContent = 'Cortex is ready in the new tab. You may close this launch page.';
  }
});
""".replace('ORIGIN', json.dumps(origin)).replace('CREDENTIAL', json.dumps(credential))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-{nonce}'; base-uri 'none'; form-action 'none'">
<title>Open Cortex securely</title></head><body>
<h1>Open Cortex</h1>
<p>This private launch expires in one minute. No Brain access grant is created.</p>
<button type="button">Open Cortex</button>
<p role="status">Open the trusted local tab, then select your configured Brain and Connect.</p>
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
