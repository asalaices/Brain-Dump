// SPDX-License-Identifier: AGPL-3.0-only
import assert from 'node:assert/strict';
import test from 'node:test';
import {createApiActivity} from '../../web/api/activity.mjs';
import {createApiClient} from '../../web/api/client.mjs';
import {createSynapsesClient, validateReceipt} from '../../web/api/synapses.mjs';
import {bindSynapses, renderMatches} from '../../web/components/synapses.mjs';

const origin = 'http://127.0.0.1:8080';
const source = {name: 'example', repository: 'example/synthetic', commit: 'a'.repeat(40)};
const status = {
  schema_version: 1, status: 'ready', read_only: true, source, request_id: 'status-request',
  source_verified: true, synchronized: true, cache_fresh: false, count: 2
};
const match = {
  excerpt: {text: '<img src=x onerror=alert(1)>'}, json_pointer: '/entry/summary',
  source_url: `https://github.com/example/synthetic/blob/${source.commit}/records/example.json`,
  sha256: 'b'.repeat(64), entry_id: 'example-entry', record_timestamp: '2026-01-01T00:00:00Z',
  superseded_by: ['newer-example']
};
const found = {
  schema_version: 1, status: 'found', read_only: true, source, request_id: 'synapse-request',
  freshness: {source_verified: true, cache_fresh: false}, matches: [match], truncated: true
};
const pending = {schema_version: 1, status: 'pairing_required', pairing_id: 'c'.repeat(32), expires_in_seconds: 300};
const paired = {...pending, status: 'paired', expires_in_seconds: 1800};
const response = value => ({ok: true, status: 200, json: async () => value});

class Element {
  hidden = false;
  disabled = false;
  value = '';
  textContent = '';
  children = [];
  handlers = new Map();
  addEventListener(name, callback) { this.handlers.set(name, callback); }
  removeEventListener(name) { this.handlers.delete(name); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  fire(name) { return this.handlers.get(name)?.(new Event(name, {cancelable: true})); }
}

function fixture(t) {
  const ids = ['connect', 'disconnect', 'form', 'query', 'search', 'notice', 'pairing', 'source', 'results'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements.form.hidden = true;
  const documentTarget = {
    querySelector: selector => elements[selector.replace('#synapses-', '')],
    createElement: tag => Object.assign(new Element(), {tag})
  };
  const activity = createApiActivity();
  const calls = [];
  const queue = [];
  const dispose = bindSynapses({
    activity, documentTarget, getOrigin: () => origin,
    fetchImpl: async (url, options) => {
      calls.push({url, options});
      assert.ok(queue.length, 'unexpected request');
      const next = queue.shift();
      return typeof next === 'function' ? next(options) : next;
    }
  });
  t.after(dispose);
  return {...elements, documentTarget, activity, calls, queue};
}

test('cookies require explicit same-origin transport and cannot be widened per request', async () => {
  const activity = createApiActivity();
  assert.throws(() => createApiClient({
    baseUrl: 'https://other.example/api/', pageOrigin: origin, credentials: 'same-origin', activity
  }), /same-origin/);
  assert.throws(() => createApiClient({baseUrl: `${origin}/api/`, credentials: 'include', activity}), /same-origin/);
  const client = createApiClient({
    baseUrl: `${origin}/api/`, credentials: 'same-origin', pageOrigin: origin, activity,
    fetchImpl: async (_url, options) => {
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.redirect, 'error');
      return response({});
    }
  });
  await client.requestJson('fixture', {credentials: 'include', redirect: 'follow'});
});

test('local adapter pins origin, read routes, JSON schema and a per-tab key', async () => {
  const activity = createApiActivity();
  let browserKey;
  const client = createSynapsesClient({
    origin, activity, fetchImpl: async (url, options) => {
      assert.equal(url, `${origin}/api/local/status`);
      assert.equal(options.method, 'POST');
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.redirect, 'error');
      assert.equal(options.headers['Content-Type'], 'application/json');
      assert.equal(options.headers['X-Cortex-Read-Only'], '1');
      assert.match(options.headers['X-Cortex-Browser'], /^[a-f0-9]{64}$/);
      browserKey ??= options.headers['X-Cortex-Browser'];
      assert.equal(options.headers['X-Cortex-Browser'], browserKey);
      return response(status);
    }
  });
  await client.request('status');
  await client.request('status');
  assert.throws(() => client.request('export'), /Unsupported/);
  assert.equal(activity.snapshot().started, 2);
  for (const invalid of ['https://127.0.0.1', 'http://localhost:8080', 'http://example.test', `${origin}/path`]) {
    assert.throws(() => createSynapsesClient({origin: invalid, activity}), /loopback/);
  }
});

test('invalid successful responses count as failures, not completed backend reads', async () => {
  const activity = createApiActivity();
  const client = createSynapsesClient({origin, activity, fetchImpl: async () => response({...status, synchronized: false})});
  await assert.rejects(client.request('status'), /Unverified/);
  assert.equal(activity.snapshot().failed, 1);
  assert.equal(activity.snapshot().completed, 0);
});

test('bounded citations remain bound to the source snapshot and allow Unicode code points', () => {
  assert.equal(validateReceipt(found), found);
  validateReceipt({...found, matches: [{...match, excerpt: {text: '🧠'.repeat(240)}}]});
  for (const bad of [
    {...found, schema_version: 2}, {...found, read_only: false},
    {...found, matches: Array(6).fill(match)},
    {...found, matches: [{...match, excerpt: {text: 'x'.repeat(241)}}]},
    {...found, matches: [{...match, source_url: 'javascript:alert(1)'}]},
    {...found, matches: [{...match, source_url: 'https://github.com/other/repo/blob/other/file'}]},
    {...found, freshness: {source_verified: false}},
    {...found, status: 'no_match'}
  ]) {
    assert.throws(() => validateReceipt(bad), TypeError);
  }
});

test('private excerpts render as text with safe immutable citations and supersession', () => {
  const target = new Element();
  renderMatches({createElement: tag => Object.assign(new Element(), {tag})}, target, found);
  const [quote, link, provenance] = target.children[0].children;
  assert.equal(quote.textContent, match.excerpt.text);
  assert.equal(link.href, match.source_url);
  assert.equal(link.rel, 'noopener noreferrer');
  assert.match(provenance.textContent, /superseded by newer-example/);
  assert.equal('innerHTML' in quote, false);
});

test('pairing is explicit, actual requests drive activity, and source/cache freshness stay distinct', async t => {
  const f = fixture(t);
  assert.equal(f.calls.length, 0);
  assert.equal(f.activity.snapshot().configured, false);
  f.queue.push(response(pending));
  await f.connect.fire('click');
  assert.match(f.pairing.textContent, new RegExp(`--pair ${pending.pairing_id}`));
  assert.equal(f.form.hidden, true);
  f.queue.push(response(paired), response(status));
  await f.connect.fire('click');
  assert.equal(f.form.hidden, false);
  assert.match(f.source.textContent, /Source verified and synchronized/);
  assert.match(f.source.textContent, /cache: stale or absent/);
  assert.equal(f.activity.snapshot().completed, 3);
  f.query.value = 'synthetic context';
  f.queue.push(response(found));
  await f.form.fire('submit');
  assert.equal(f.results.children.length, 1);
  assert.match(f.notice.textContent, /result limit reached/);
  assert.deepEqual(JSON.parse(f.calls.at(-1).options.body), {query: 'synthetic context'});
});

test('denial, unavailable, malformed and expired responses clear previously displayed results', async t => {
  for (const code of [403, 503, 502, 429, 401, 200]) {
    await t.test(String(code), async t => {
      const f = fixture(t);
      f.queue.push(response(paired), response(status));
      await f.connect.fire('click');
      f.queue.push(response(found));
      f.query.value = 'first';
      await f.form.fire('submit');
      assert.equal(f.results.children.length, 1);
      f.queue.push({ok: code === 200, status: code, json: async () => ({bad: 'schema'})});
      await f.form.fire('submit');
      assert.equal(f.results.children.length, 0);
      assert.equal(f.source.textContent, '');
      assert.equal(f.activity.snapshot().failed, 1);
      if (code === 401) assert.equal(f.form.hidden, true);
    });
  }
});

test('disconnect cancels in-flight browser reads, clears data and ignores late replies', async t => {
  const f = fixture(t);
  f.queue.push(response(paired), response(status));
  await f.connect.fire('click');
  let finish;
  f.queue.push(() => new Promise(resolve => { finish = resolve; }));
  f.query.value = 'private query';
  const reading = f.form.fire('submit');
  assert.equal(f.activity.snapshot().pending, 1);
  f.queue.push(response({schema_version: 1, status: 'disconnected'}));
  await f.disconnect.fire('click');
  assert.equal(f.form.hidden, true);
  assert.equal(f.query.value, '');
  finish(response(found));
  await reading;
  assert.equal(f.results.children.length, 0);
  assert.match(f.notice.textContent, /Disconnected/);
});
