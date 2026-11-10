// SPDX-License-Identifier: AGPL-3.0-only
import {HttpError} from '../api/client.mjs';
import {citationUrl, createSynapsesClient} from '../api/synapses.mjs';
import {receiveLaunch} from '../api/bootstrap.mjs';

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
  windowTarget = globalThis.window, getStorage = () => windowTarget.localStorage
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
  const brain = select('synapses-brain');
  const preference = select('synapses-preference');
  let client;
  let controller;
  let expires;
  let generation = 0;
  let paired = false;
  let trusted = false;

  function remember() {
    try {
      getStorage().setItem('cortex.source', brain.value);
      preference.textContent = '';
    } catch {
      preference.textContent = 'Source preference storage is unavailable. Selection lasts only for this page.';
    }
  }

  function trust(receipt) {
    trusted = true;
    brain.replaceChildren();
    for (const alias of receipt.sources) {
      const option = documentTarget.createElement('option');
      option.value = alias;
      option.textContent = alias;
      brain.append(option);
    }
    brain.value = receipt.sources[0];
    try {
      const saved = getStorage().getItem('cortex.source');
      if (receipt.sources.includes(saved)) brain.value = saved;
      else if (saved !== null) preference.textContent = 'Previously selected Brain is not configured in this launcher.';
    } catch {
      preference.textContent = 'Source preference storage is unavailable. Selection lasts only for this page.';
    }
    clearTimeout(expires);
    expires = setTimeout(() => {
      trusted = false;
      forget();
      notice.textContent = 'Local session expired. Reopen Cortex through its launcher; displayed private data was cleared.';
    }, receipt.expires_in_seconds * 1000);
    notice.textContent = 'Trusted local tab ready. Select the configured Brain and Connect. Upstream access is checked on every read.';
    controls();
  }

  function clear() {
    source.textContent = '';
    results.replaceChildren();
    pairing.textContent = '';
  }

  function controls(busy = false) {
    connect.disabled = busy || !trusted;
    brain.disabled = busy || !trusted || paired;
    submit.disabled = busy || !paired;
    form.hidden = !paired;
    disconnect.hidden = !client;
  }

  function forget() {
    generation += 1;
    controller?.abort();
    paired = false;
    clear();
    query.value = '';
    connect.textContent = 'Connect';
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
        trusted = false;
        notice.textContent = 'Reopen Cortex through its launcher to establish a trusted tab. Git access remains required upstream.';
      } else if (receipt.status === 'paired') {
        trust(receipt);
        controls(true);
        const status = await client.request('status', {}, signal);
        if (current !== generation) return;
        paired = true;
        connect.textContent = 'Refresh source status';
        remember();
        describeSource(status);
        notice.textContent = `Connected read-only. ${status.count} entries in the authorized source.`;
      } else if (receipt.status === 'disconnected') {
        forget();
        notice.textContent = 'Disconnected. Local browser access revoked and displayed results cleared.';
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
        trusted = false;
        forget();
        notice.textContent = 'Local session expired or revoked. Reopen Cortex through its launcher.';
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

  const onConnect = () => trusted ? run(paired ? 'status' : 'session', paired ? {} : {source: brain.value}) : undefined;
  const onDisconnect = () => {
    // Disconnect read access, not the fixed-lifetime trust established by native launch.
    generation += 1;
    controller?.abort();
    paired = false;
    clear();
    query.value = '';
    connect.textContent = 'Connect';
    return run('disconnect');
  };
  const onSubmit = event => {
    event.preventDefault();
    if (paired && query.value.trim()) return run('synapse', {query: query.value.trim()});
  };
  connect.addEventListener('click', onConnect);
  disconnect.addEventListener('click', onDisconnect);
  form.addEventListener('submit', onSubmit);
  brain.addEventListener('change', remember);
  let disposeLaunch = () => {};
  if (windowTarget?.opener) {
    client = createSynapsesClient({origin: getOrigin(), activity, fetchImpl});
    disposeLaunch = receiveLaunch({
      windowTarget, client, onReady: trust,
      onError: () => {
        notice.textContent = 'Trusted launch expired or failed. Reopen Cortex through its launcher. No access grant was changed.';
        controls();
      }
    });
  }
  controls();
  return () => {
    disposeLaunch();
    clearTimeout(expires);
    connect.removeEventListener('click', onConnect);
    disconnect.removeEventListener('click', onDisconnect);
    form.removeEventListener('submit', onSubmit);
    brain.removeEventListener('change', remember);
    forget();
    connect.disabled = true;
    disconnect.disabled = true;
  };
}
