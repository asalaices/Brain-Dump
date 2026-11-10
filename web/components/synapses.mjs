// SPDX-License-Identifier: AGPL-3.0-only
import {HttpError} from '../api/client.mjs';
import {citationUrl, createSynapsesClient} from '../api/synapses.mjs';

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
  fetchImpl = (...args) => globalThis.fetch(...args)
}) {
  const select = id => documentTarget.querySelector(`#${id}`);
  const connect = select('synapses-connect');
  const disconnect = select('synapses-disconnect');
  const form = select('synapses-form');
  const query = select('synapses-query');
  const submit = select('synapses-search');
  const notice = select('synapses-notice');
  const pairing = select('synapses-pairing');
  const source = select('synapses-source');
  const results = select('synapses-results');
  let client;
  let controller;
  let expires;
  let generation = 0;
  let paired = false;

  function clear() {
    source.textContent = '';
    results.replaceChildren();
    pairing.textContent = '';
  }

  function controls(busy = false) {
    connect.disabled = busy;
    submit.disabled = busy || !paired;
    form.hidden = !paired;
    disconnect.hidden = !client;
  }

  function forget() {
    generation += 1;
    controller?.abort();
    clearTimeout(expires);
    paired = false;
    clear();
    query.value = '';
    connect.textContent = 'Connect to Synapses';
    controls();
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
    const signal = active.signal;
    const current = ++generation;
    const timeout = setTimeout(() => active.abort(), 90000);
    clear();
    controls(true);
    notice.textContent = 'Waiting for the local read-only connection...';
    try {
      client ??= createSynapsesClient({origin: getOrigin(), activity, fetchImpl});
      const receipt = await client.request(operation, body, signal);
      if (current !== generation) return;
      if (receipt.status === 'pairing_required') {
        paired = false;
        connect.textContent = 'Check pairing';
        pairing.textContent = `Approve this browser in your task checkout: ./cortex_server --pair ${receipt.pairing_id}`;
        notice.textContent = `Owner approval required. This tab has no source access yet. Pairing expires in ${receipt.expires_in_seconds} seconds.`;
      } else if (receipt.status === 'paired') {
        paired = true;
        connect.textContent = 'Refresh source status';
        clearTimeout(expires);
        expires = setTimeout(() => {
          forget();
          notice.textContent = 'Local session expired. Pair again; no private results are retained on this page.';
        }, receipt.expires_in_seconds * 1000);
        controls(true);
        const status = await client.request('status', {}, signal);
        if (current !== generation) return;
        describeSource(status);
        notice.textContent = `Owner-paired read-only connection. ${status.count} entries in the authorized source.`;
      } else if (receipt.status === 'disconnected') {
        forget();
        notice.textContent = 'Disconnected. Local browser access revoked and displayed results cleared.';
      } else {
        describeSource(receipt);
        if (receipt.status === 'ready') {
          notice.textContent = `Owner-paired read-only connection. ${receipt.count} entries in the authorized source.`;
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
        forget();
        notice.textContent = 'Local session expired or revoked. Pair again before reading.';
      } else {
        const message = error instanceof HttpError ? ({
          403: 'Source access denied or reader not synchronized. No current results are shown.',
          429: 'Local connection busy. Retry when the current request finishes.',
          503: 'Local connection unavailable. Check its external profile and source authority.',
          502: 'Authorized source read failed. No current results are shown.'
        }[error.status] ?? `Local request failed (HTTP ${error.status}).`) :
          signal.aborted ? 'Browser request canceled or timed out; a server-side read may still finish.' :
            'Local connection or response validation failed. No current results are shown.';
        notice.textContent = message;
      }
    } finally {
      clearTimeout(timeout);
      if (current === generation) controls();
    }
  }

  const onConnect = () => run(paired ? 'status' : 'session');
  const onDisconnect = () => {
    forget();
    return run('disconnect');
  };
  const onSubmit = event => {
    event.preventDefault();
    if (paired && query.value.trim()) return run('synapse', {query: query.value.trim()});
  };
  connect.addEventListener('click', onConnect);
  disconnect.addEventListener('click', onDisconnect);
  form.addEventListener('submit', onSubmit);
  return () => {
    connect.removeEventListener('click', onConnect);
    disconnect.removeEventListener('click', onDisconnect);
    form.removeEventListener('submit', onSubmit);
    forget();
    connect.disabled = true;
    disconnect.disabled = true;
  };
}
