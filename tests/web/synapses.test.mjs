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
const connected = {schema_version: 1, status: 'connected', expires_in_seconds: 1800, sources: ['example']};
const response = value => ({ok: true, status: 200, json: async () => value});
const storage = map => ({
  getItem: key => map.get(key) ?? null,
  setItem: (key, value) => map.set(key, value),
  removeItem: key => map.delete(key)
});

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

function fixture(t, options = {}) {
  const ids = ['connect', 'disconnect', 'form', 'query', 'search', 'notice', 'source', 'results', 'brain', 'brain-control', 'preference'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements.form.hidden = true;
  const documentTarget = {
    querySelector: selector => elements[selector.replace('#synapses-', '')],
    createElement: tag => Object.assign(new Element(), {tag})
  };
  const activity = createApiActivity();
  const calls = [];
  const queue = [...(options.responses ?? [])];
  const saved = new Map(options.saved ? [['cortex.source', options.saved]] : []);
  const sessionMap = options.sessionMap ?? new Map();
  const dispose = bindSynapses({
    activity, documentTarget, getOrigin: () => origin,
    windowTarget: {open() { assert.fail('Connect must not open another page'); }},
    getStorage: () => {
      if (options.storageDenied) throw new Error('fixture preference storage denied');
      return storage(saved);
    },
    getSessionStorage: () => {
      if (options.sessionDenied) throw new Error('fixture session storage denied');
      return {
        ...storage(sessionMap),
        removeItem: key => {
          if (options.removeDenied) throw new Error('fixture removal denied');
          sessionMap.delete(key);
        }
      };
    },
    fetchImpl: async (url, options) => {
      calls.push({url, options});
      assert.ok(queue.length, 'unexpected request');
      const next = queue.shift();
      return typeof next === 'function' ? next(options) : next;
    }
  });
  t.after(dispose);
  const connect = async (upstream = response(status), receipt = connected) => {
    queue.push(response(receipt), upstream);
    await elements.connect.fire('click');
  };
  return {...elements, documentTarget, activity, calls, queue, connectNow: connect, saved, sessionMap, dispose};
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

test('adapter pins origin, JSON, custom headers and origin-scoped session state', async () => {
  const activity = createApiActivity();
  const saved = new Map([['cortex.csrf', 'c'.repeat(64)]]);
  const client = createSynapsesClient({
    origin, activity, getSessionStorage: () => storage(saved),
    fetchImpl: async (url, options) => {
      assert.equal(url, `${origin}/api/local/status`);
      assert.equal(options.method, 'POST');
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.redirect, 'error');
      assert.equal(options.headers['Content-Type'], 'application/json');
      assert.equal(options.headers['X-Cortex-Read-Only'], '1');
      assert.equal(options.headers['X-Cortex-Browser'], 'c'.repeat(64));
      return response(status);
    }
  });
  await client.request('status');
  await client.request('status');
  for (const operation of ['export', 'launch', 'bootstrap']) {
    assert.throws(() => client.request(operation), /Unsupported/);
  }
  assert.equal(activity.snapshot().started, 2);
  for (const invalid of ['https://127.0.0.1', 'http://localhost:8080', 'http://example.test', `${origin}/path`]) {
    assert.throws(() => createSynapsesClient({origin: invalid, activity}), /loopback/);
  }
});

test('Connect rotates CSRF state, refresh restores it and Disconnect removes it', async () => {
  const saved = new Map();
  const requests = [];
  const adapter = () => createSynapsesClient({
    origin, activity: createApiActivity(), getSessionStorage: () => storage(saved),
    fetchImpl: async (_url, options) => {
      requests.push(options);
      return response(connected);
    }
  });
  const first = adapter();
  assert.equal(first.hasSession(), false);
  assert.throws(() => first.request('resume'), /No local session/);
  await first.request('session');
  const firstKey = requests.at(-1).headers['X-Cortex-Browser'];
  assert.match(firstKey, /^[a-f0-9]{64}$/);
  assert.deepEqual([...saved.keys()], ['cortex.csrf']);
  const refreshed = adapter();
  assert.equal(refreshed.hasSession(), true);
  await refreshed.request('resume');
  assert.equal(requests.at(-1).headers['X-Cortex-Browser'], firstKey);
  await refreshed.request('session');
  assert.notEqual(requests.at(-1).headers['X-Cortex-Browser'], firstKey);
  refreshed.clearSession();
  assert.equal(refreshed.hasSession(), false);
  assert.equal(saved.size, 0);
  assert.throws(() => refreshed.request('status'), /No local session/);
});

test('invalid successful responses count as failures, not completed backend reads', async () => {
  const activity = createApiActivity();
  const client = createSynapsesClient({
    origin, activity, getSessionStorage: () => storage(new Map([['cortex.csrf', 'c'.repeat(64)]])),
    fetchImpl: async () => response({...status, synchronized: false})
  });
  await assert.rejects(client.request('status'), /Unverified/);
  assert.equal(activity.snapshot().failed, 1);
  assert.equal(activity.snapshot().completed, 0);
  for (const bad of [
    {...connected, expires_in_seconds: 1801}, {...connected, expires_in_seconds: -1},
    {...connected, sources: ['example', 'other']}, {...connected, sources: ['/'.repeat(129)]},
    {...connected, status: 'trusted'}
  ]) assert.throws(() => validateReceipt(bad), TypeError);
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
    {...found, freshness: {source_verified: false}}, {...found, status: 'no_match'}
  ]) assert.throws(() => validateReceipt(bad), TypeError);
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

test('ordinary entry Connect establishes and authorizes on the same page with actual request activity', async t => {
  const f = fixture(t);
  assert.equal(f.calls.length, 0);
  assert.equal(f.connect.disabled, false);
  await f.connectNow();
  assert.deepEqual(f.calls.map(call => call.url), [`${origin}/api/local/session`, `${origin}/api/local/status`]);
  assert.deepEqual(JSON.parse(f.calls[0].options.body), {});
  assert.equal(f.brain.value, 'example');
  assert.equal(f.form.hidden, false);
  assert.equal(f.disconnect.hidden, false);
  assert.match(f.source.textContent, /Source verified and synchronized/);
  assert.match(f.source.textContent, /cache: stale or absent/);
  assert.equal(f.activity.snapshot().completed, 2);
  f.query.value = 'synthetic context';
  f.queue.push(response(found));
  await f.form.fire('submit');
  assert.equal(f.results.children.length, 1);
  assert.match(f.notice.textContent, /result limit reached/);
  assert.deepEqual(JSON.parse(f.calls.at(-1).options.body), {query: 'synthetic context'});
});

test('refresh resumes without a new session and Disconnect survives another refresh', async t => {
  const first = fixture(t);
  await first.connectNow();
  first.dispose();
  const refreshed = fixture(t, {sessionMap: first.sessionMap, responses: [response(connected), response(status)]});
  await new Promise(setImmediate);
  assert.deepEqual(refreshed.calls.map(call => call.url.split('/').at(-1)), ['resume', 'status']);
  assert.equal(refreshed.form.hidden, false);
  refreshed.queue.push(response({schema_version: 1, status: 'disconnected'}));
  await refreshed.disconnect.fire('click');
  assert.equal(refreshed.sessionMap.size, 0);
  assert.equal(refreshed.form.hidden, true);
  assert.match(refreshed.notice.textContent, /Disconnected/);
  const after = fixture(t, {sessionMap: first.sessionMap});
  assert.equal(after.calls.length, 0);
  assert.equal(after.form.hidden, true);
});

test('denial, unavailable, malformed and expired responses clear previously displayed results', async t => {
  for (const code of [403, 503, 502, 429, 401, 200]) {
    await t.test(String(code), async t => {
      const f = fixture(t);
      await f.connectNow();
      f.queue.push(response(found));
      f.query.value = 'first';
      await f.form.fire('submit');
      assert.equal(f.results.children.length, 1);
      f.queue.push({ok: code === 200, status: code, json: async () => ({bad: 'schema'})});
      await f.form.fire('submit');
      assert.equal(f.results.children.length, 0);
      assert.equal(f.source.textContent, '');
      assert.equal(f.activity.snapshot().failed, 1);
      if (code === 401) {
        assert.equal(f.form.hidden, true);
        assert.equal(f.sessionMap.size, 0);
      }
    });
  }
});

test('disconnect cancels in-flight reads, clears data and ignores late replies', async t => {
  const f = fixture(t);
  await f.connectNow();
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
  assert.equal(f.sessionMap.size, 0);
  assert.match(f.notice.textContent, /Disconnected/);
  await f.connectNow();
  assert.equal(f.form.hidden, false);
});

test('failed disconnect clears local access but explicitly reports unconfirmed server revocation', async t => {
  const f = fixture(t);
  await f.connectNow();
  f.queue.push(() => { throw new Error('fixture network failure'); });
  await f.disconnect.fire('click');
  assert.match(f.notice.textContent, /server revocation was not confirmed/);
  assert.equal(f.sessionMap.size, 0);
  assert.equal(f.form.hidden, true);
});

test('blocked session storage is explicit and never silently falls back to memory or a popup', async t => {
  const f = fixture(t, {sessionDenied: true});
  assert.match(f.notice.textContent, /session storage is unavailable/);
  await f.connect.fire('click');
  assert.equal(f.calls.length, 0);
  assert.equal(f.form.hidden, true);
  assert.match(f.notice.textContent, /session storage is unavailable/);
  assert.equal(f.connect.disabled, false);
});

test('Disconnect reports a local storage removal failure even when server revocation succeeds', async t => {
  const f = fixture(t, {removeDenied: true});
  await f.connectNow();
  f.queue.push(response({schema_version: 1, status: 'disconnected'}));
  await f.disconnect.fire('click');
  assert.match(f.notice.textContent, /session storage could not be cleared/);
  assert.equal(f.form.hidden, true);
  assert.equal(f.results.children.length, 0);
  assert.doesNotMatch(f.notice.textContent, /fixture removal denied/);
});

test('invalid saved local state is visible and can be replaced by explicit Connect', async t => {
  const f = fixture(t, {sessionMap: new Map([['cortex.csrf', 'invalid']])});
  assert.match(f.notice.textContent, /Saved local session is invalid/);
  assert.equal(f.calls.length, 0);
  await f.connectNow();
  assert.equal(f.form.hidden, false);
});

test('only source alias and CSRF state persist, not results, query text or upstream credentials', async t => {
  for (const options of [{}, {saved: 'removed'}, {storageDenied: true}]) {
    await t.test(JSON.stringify(options), async t => {
      const f = fixture(t, options);
      await f.connectNow();
      if (options.saved) assert.match(f.preference.textContent, /not configured/);
      if (options.storageDenied) assert.match(f.preference.textContent, /unavailable/);
      assert.equal(f.form.hidden, false);
      if (!options.storageDenied) assert.deepEqual([...f.saved], [['cortex.source', 'example']]);
      assert.deepEqual([...f.sessionMap.keys()], ['cortex.csrf']);
    });
  }
});

test('upstream denial during Connect does not expose Recall or fabricate connected state', async t => {
  const f = fixture(t);
  await f.connectNow({ok: false, status: 403});
  assert.match(f.notice.textContent, /denied/);
  assert.equal(f.form.hidden, true);
  assert.equal(f.results.children.length, 0);
});

test('expired refresh clears saved state instead of silently creating another session', async t => {
  const f = fixture(t, {
    sessionMap: new Map([['cortex.csrf', 'c'.repeat(64)]]),
    responses: [{ok: false, status: 401}]
  });
  await new Promise(setImmediate);
  assert.deepEqual(f.calls.map(call => call.url.split('/').at(-1)), ['resume']);
  assert.equal(f.sessionMap.size, 0);
  assert.equal(f.form.hidden, true);
  assert.match(f.notice.textContent, /expired or revoked/);
});

test('local expiry clears displayed data and session state at the returned fixed lifetime', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const f = fixture(t);
  await f.connectNow(response(status), {...connected, expires_in_seconds: 2});
  assert.equal(f.form.hidden, false);
  t.mock.timers.tick(2000);
  assert.equal(f.form.hidden, true);
  assert.equal(f.sessionMap.size, 0);
  assert.equal(f.source.textContent, '');
  assert.match(f.notice.textContent, /Connection expired/);
});
