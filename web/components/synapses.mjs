// SPDX-License-Identifier: AGPL-3.0-only
import {HttpError} from '../api/client.mjs';
import {BrowserSessionError, citationUrl, createSynapsesClient} from '../api/synapses.mjs';

export function renderMatches(documentTarget, target, receipt) {
  target.replaceChildren();
  for (const match of receipt.matches) {
    const item = documentTarget.createElement('li');
    const quote = documentTarget.createElement('p');
    quote.textContent = match.excerpt.text;
    const link = documentTarget.createElement('a');
    link.href = citationUrl(match.source_url);
    link.textContent = `${match.entry_id ?? 'Envelope'} ${match.json_pointer}`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    const provenance = documentTarget.createElement('p');
    provenance.textContent = `Recorded: ${match.record_timestamp ?? 'envelope-level'}; SHA-256: ${match.sha256}` +
      (match.superseded_by?.length ? `; superseded by ${match.superseded_by.join(', ')}` : '');
    item.append(quote, link, provenance);
    target.append(item);
  }
}

export function bindSynapses({
  activity, documentTarget, getOrigin = () => window.location.origin,
  fetchImpl = (...args) => globalThis.fetch(...args),
  windowTarget = globalThis.window, getStorage = () => windowTarget.localStorage,
  getSessionStorage = () => windowTarget.sessionStorage
}) {
  const select = id => documentTarget.querySelector(`#${id}`);
  const connect = select('synapses-connect');
  const disconnect = select('synapses-disconnect');
  const form = select('synapses-form');
  const query = select('synapses-query');
  const submit = select('synapses-search');
  const notice = select('synapses-notice');
  const source = select('synapses-source');
  const results = select('synapses-results');
  const brain = select('synapses-brain');
  const brainControl = select('synapses-brain-control');
  const preference = select('synapses-preference');
  const client = createSynapsesClient({origin: getOrigin(), activity, fetchImpl, getSessionStorage});
  let controller;
  let expires;
  let generation = 0;
  let connected = false;
  let localSession = false;

  function clear() {
    source.textContent = '';
    results.replaceChildren();
  }

  function controls(busy = false) {
    connect.disabled = busy;
    brainControl.hidden = !localSession;
    brain.disabled = true;
    submit.disabled = busy || !connected;
    form.hidden = !connected;
    disconnect.hidden = !localSession;
  }

  function forget() {
    generation += 1;
    controller?.abort();
    clearTimeout(expires);
    connected = false;
    localSession = false;
    clear();
    query.value = '';
    connect.textContent = 'Connect to Brain';
    controls();
  }

  function dropSession() {
    forget();
    try {
      client.clearSession();
      return '';
    } catch {
      return ' Browser session storage could not be cleared; close this tab and check site storage settings.';
    }
  }

  function session(receipt) {
    localSession = true;
    brain.replaceChildren();
    const option = documentTarget.createElement('option');
    option.value = receipt.sources[0];
    option.textContent = receipt.sources[0];
    brain.append(option);
    brain.value = receipt.sources[0];
    clearTimeout(expires);
    expires = setTimeout(() => {
      const storageError = dropSession();
      notice.textContent = 'Connection expired. Click Connect to Brain to reconnect; displayed private data was cleared.' + storageError;
    }, receipt.expires_in_seconds * 1000);
    notice.textContent = 'Checking existing access to your configured Brain...';
    controls(true);
  }

  function remember() {
    try {
      const previous = getStorage().getItem('cortex.source');
      preference.textContent = previous !== null && previous !== brain.value ?
        'The previous Brain is not configured; connected to the server-selected Brain shown above.' : '';
      getStorage().setItem('cortex.source', brain.value);
    } catch {
      preference.textContent = 'Source preference storage is unavailable. The connection is unaffected.';
    }
  }

  function describeSource(receipt) {
    const fresh = receipt.freshness ?? receipt;
    source.textContent = `Source: ${receipt.source.name}; commit: ${receipt.source.commit}. ` +
      `Source verified${receipt.status === 'ready' ? ' and synchronized' : ''}. ` +
      `Derived cache: ${fresh.cache_fresh ? 'fresh' : 'stale or absent'}. ` +
      `Request: ${receipt.request_id}. Context is not authority or task acceptance.`;
  }

  async function run(operation, body = {}) {
    controller?.abort();
    const active = new AbortController();
    controller = active;
    const current = ++generation;
    const timeout = setTimeout(() => active.abort(), 90000);
    clear();
    controls(true);
    notice.textContent = 'Waiting for the local read-only connection...';
    try {
      const receipt = await client.request(operation, body, active.signal);
      if (current !== generation) return;
      if (receipt.status === 'connected') {
        session(receipt);
        const status = await client.request('status', {}, active.signal);
        if (current !== generation) return;
        connected = true;
        connect.textContent = 'Refresh source status';
        remember();
        describeSource(status);
        notice.textContent = `Connected read-only. ${status.count} entries in the authorized source.`;
      } else if (receipt.status === 'disconnected') {
        const storageError = dropSession();
        notice.textContent = 'Disconnected. Browser access revoked and displayed data cleared.' + storageError;
      } else {
        describeSource(receipt);
        if (receipt.status === 'ready') {
          notice.textContent = `Connected read-only. ${receipt.count} entries in the authorized source.`;
        } else {
          renderMatches(documentTarget, results, receipt);
          notice.textContent = receipt.status === 'no_match' ? 'No matching reference in the authorized source.' :
            `${receipt.matches.length} cited matches shown${receipt.truncated ? ' (result limit reached)' : ''}. Recorded context only.`;
        }
      }
    } catch (error) {
      if (current !== generation) return;
      clear();
      if (error instanceof HttpError && error.status === 401) {
        const storageError = dropSession();
        notice.textContent = 'Connection expired or revoked. Click Connect to Brain to reconnect.' + storageError;
      } else {
        notice.textContent = error instanceof BrowserSessionError ? error.message :
          error instanceof HttpError ? ({
            403: 'Source access denied or reader not synchronized. No current results are shown.',
            429: 'Local connection busy. Retry when the current request finishes.',
            503: 'Local connection unavailable. Check its external profile and source authority.',
            502: 'Authorized source read failed. No current results are shown.'
          }[error.status] ?? `Local request failed (HTTP ${error.status}).`) :
            active.signal.aborted ? 'Browser request canceled or timed out; a server-side read may still finish.' :
              'Local connection or response validation failed. No current results are shown.';
      }
    } finally {
      clearTimeout(timeout);
      if (current === generation) {
        if (operation === 'disconnect') {
          const storageError = dropSession();
          notice.textContent += ' Local access cleared; server revocation was not confirmed.' + storageError;
        } else controls();
      }
    }
  }

  const onConnect = () => run(connected ? 'status' : 'session');
  const onDisconnect = () => {
    connected = false;
    query.value = '';
    return run('disconnect');
  };
  const onSubmit = event => {
    event.preventDefault();
    if (connected && query.value.trim()) return run('synapse', {query: query.value.trim()});
  };
  connect.addEventListener('click', onConnect);
  disconnect.addEventListener('click', onDisconnect);
  form.addEventListener('submit', onSubmit);
  controls();
  try {
    if (client.hasSession()) void run('resume');
  } catch (error) {
    notice.textContent = error.message;
  }
  return () => {
    connect.removeEventListener('click', onConnect);
    disconnect.removeEventListener('click', onDisconnect);
    form.removeEventListener('submit', onSubmit);
    // Keep the origin-scoped CSRF state for a normal page refresh, not private results.
    forget();
  };
}
