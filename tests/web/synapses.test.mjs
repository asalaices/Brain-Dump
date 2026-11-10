// SPDX-License-Identifier: AGPL-3.0-only
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';
import {createApiActivity} from '../../web/api/activity.mjs';
import {createApiClient} from '../../web/api/client.mjs';
import {createSynapsesClient, validateReceipt} from '../../web/api/synapses.mjs';
import {bindSynapses, renderMatches} from '../../web/components/synapses.mjs';
import {receiveLaunch} from '../../web/api/bootstrap.mjs';

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
const paired = {...pending, status: 'paired', expires_in_seconds: 1800, sources: ['example']};
const trusted = {...paired, status: 'trusted'};
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

function fixture(t, options = {}) {
  const ids = ['connect', 'disconnect', 'form', 'query', 'search', 'notice', 'pairing', 'source', 'results', 'brain', 'brain-control', 'preference'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements.form.hidden = true;
  const documentTarget = {
    querySelector: selector => elements[selector.replace('#synapses-', '')],
    createElement: tag => Object.assign(new Element(), {tag})
  };
  const activity = createApiActivity();
  const calls = [];
  const queue = [];
  const saved = new Map(options.saved ? [['cortex.source', options.saved]] : []);
  const opener = {postMessage() {}};
  const windowTarget = Object.assign(new Element(), {opener: options.fresh ? null : opener});
  const dispose = bindSynapses({
    activity, documentTarget, getOrigin: () => origin, windowTarget,
    getStorage: () => {
      if (options.storageDenied) throw new Error('fixture storage denied');
      return {getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value)};
    },
    fetchImpl: async (url, options) => {
      calls.push({url, options});
      assert.ok(queue.length, 'unexpected request');
      const next = queue.shift();
      return typeof next === 'function' ? next(options) : next;
    }
  });
  t.after(dispose);
  const launch = async (upstream = response(status)) => {
    queue.push(response(trusted), response(paired), upstream);
    await windowTarget.handlers.get('message')({
      source: opener, origin: 'null', data: {type: 'cortex-bootstrap', credential: 'd'.repeat(64)}
    });
  };
  return {...elements, documentTarget, activity, calls, queue, launch, saved};
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

test('ordinary Cortex entry has enabled Connect and requests independent approval, never self-authorization', async t => {
  const f = fixture(t, {fresh: true});
  assert.equal(f.calls.length, 0);
  assert.equal(f.connect.disabled, false);
  assert.equal(f['brain-control'].hidden, true);
  f.queue.push(response({schema_version: 1, status: 'launch_requested'}));
  await f.connect.fire('click');
  assert.equal(f.calls[0].url, `${origin}/api/local/launch`);
  assert.deepEqual(JSON.parse(f.calls[0].options.body), {});
  assert.match(f.notice.textContent, /Approve connection/);
  assert.match(f.notice.textContent, /original tab remains disconnected/);
  assert.equal(f.form.hidden, true);
  assert.equal(f.disconnect.hidden, true);
  assert.equal(f.source.textContent, '');
  assert.equal(f.saved.size, 0);
  assert.equal(f.activity.snapshot().completed, 1);
});

test('native approval failure and already-pending approval offer an explicit retry, not a dead control', async t => {
  for (const code of [503, 429]) {
    const f = fixture(t, {fresh: true});
    f.queue.push({ok: false, status: code});
    await f.connect.fire('click');
    assert.match(f.notice.textContent, code === 429 ? /already waiting/ : /could not open/);
    assert.equal(f.form.hidden, true);
    assert.equal(f.connect.disabled, false);
  }
});

test('approved tab automatically connects configured Brain without another click through real activity', async t => {
  const f = fixture(t);
  assert.equal(f.calls.length, 0);
  await f.launch();
  assert.equal(f.brain.value, 'example');
  assert.equal(f.connect.disabled, false);
  assert.doesNotMatch(f.notice.textContent + f.pairing.textContent, /--pair/);
  assert.deepEqual(JSON.parse(f.calls[1].options.body), {source: 'example'});
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
      await f.launch();
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
  await f.launch();
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
  assert.equal(f.connect.disabled, false);
  f.queue.push(response(paired), response(status));
  await f.connect.fire('click');
  assert.equal(f.form.hidden, false);
  assert.equal(f.calls.filter(call => call.url.endsWith('/bootstrap')).length, 1);
});

test('only the source alias is remembered; unavailable storage and removed sources are visible', async t => {
  for (const options of [{}, {saved: 'removed'}, {storageDenied: true}]) {
    await t.test(JSON.stringify(options), async t => {
      const f = fixture(t, options);
      await f.launch();
      if (options.saved) assert.match(f.preference.textContent, /not configured/);
      if (options.storageDenied) assert.match(f.preference.textContent, /unavailable/);
      assert.equal(f.form.hidden, false);
      if (!options.storageDenied) assert.deepEqual([...f.saved], [['cortex.source', 'example']]);
    });
  }
});

test('upstream denial during Connect does not expose Recall or fabricate connected state', async t => {
  const f = fixture(t);
  await f.launch({ok: false, status: 403});
  assert.match(f.notice.textContent, /denied/);
  assert.equal(f.form.hidden, true);
  assert.equal(f.results.children.length, 0);
});

test('bootstrap receiver requires exact opener, opaque file origin and one well-formed transfer', async t => {
  const windowTarget = new Element();
  const messages = [];
  const opener = {postMessage: (body, target) => messages.push({body, target})};
  windowTarget.opener = opener;
  const requests = [];
  let result;
  let tick;
  let cancelled = 0;
  const dispose = receiveLaunch({
    windowTarget, client: {request: async (operation, body) => {
      requests.push({operation, credential: body.credential});
      return trusted;
    }},
    onReady: receipt => { result = receipt; },
    onError: () => assert.fail('unexpected bootstrap failure'),
    schedule: fn => { tick = fn; return 42; }, cancel: id => { assert.equal(id, 42); cancelled++; }
  });
  t.after(dispose);
  const handler = windowTarget.handlers.get('message');
  const valid = {source: opener, origin: 'null', data: {type: 'cortex-bootstrap', credential: 'a'.repeat(64)}};
  for (const wrong of [
    {...valid, source: {}}, {...valid, origin}, {...valid, origin: 'http://127.0.0.1:9999'},
    {...valid, data: {type: 'cortex-bootstrap', credential: 'bad'}},
    {...valid, data: {type: 'other', credential: 'a'.repeat(64)}}
  ]) await handler(wrong);
  assert.equal(requests.length, 0);
  tick();
  assert.ok(messages.every(({body}) => !JSON.stringify(body).includes('a'.repeat(64))));
  await handler(valid);
  await handler(valid);
  assert.deepEqual(requests, [{operation: 'bootstrap', credential: 'a'.repeat(64)}]);
  assert.equal(result, trusted);
  assert.equal(windowTarget.opener, null);
  assert.ok(cancelled > 0);
});

test('bootstrap handshake timeout or failed redemption surfaces errors with no retry', async () => {
  for (const fail of [false, true]) {
    const windowTarget = Object.assign(new Element(), {opener: {postMessage() {}}});
    let tick;
    let errors = 0;
    const dispose = receiveLaunch({
      windowTarget, client: {request: async () => { throw new Error('synthetic denial'); }},
      onReady: () => assert.fail('must not succeed'), onError: () => { errors++; },
      schedule: fn => { tick = fn; return 1; }, cancel() {}
    });
    if (fail) {
      await windowTarget.handlers.get('message')({
        source: windowTarget.opener, origin: 'null', data: {type: 'cortex-bootstrap', credential: 'a'.repeat(64)}
      });
    } else for (let i = 0; i < 600; i++) tick();
    assert.equal(errors, 1);
    assert.equal(windowTarget.handlers.has('message'), false);
    dispose();
  }
});

test('disposed bootstrap receiver ignores late redemption responses', async () => {
  const windowTarget = Object.assign(new Element(), {opener: {postMessage() {}}});
  let finish;
  const dispose = receiveLaunch({
    windowTarget, client: {request: () => new Promise(resolve => { finish = resolve; })},
    onReady: () => assert.fail('disposed view must not become trusted'),
    onError: () => assert.fail('disposed view must not report late errors'),
    schedule: () => 1, cancel() {}
  });
  const reading = windowTarget.handlers.get('message')({
    source: windowTarget.opener, origin: 'null', data: {type: 'cortex-bootstrap', credential: 'a'.repeat(64)}
  });
  dispose();
  finish(trusted);
  await reading;
  assert.equal(windowTarget.opener, null);
});

test('actual private-launch script sends its credential once only to the exact child origin', async () => {
  const python = await readFile(new URL('../../brain_bridge/cortex_launch.py', import.meta.url), 'utf8');
  const source = python.match(/script = """([\s\S]*?)"""/)[1];
  const credential = 'd'.repeat(64);
  const script = source.replace('ORIGIN', JSON.stringify(origin)).replace('CREDENTIAL', JSON.stringify(credential));
  function fixture(blocked = false) {
    const button = new Element();
    const notice = new Element();
    const messages = [];
    const child = {postMessage: (body, target) => messages.push({body, target})};
    const windowTarget = Object.assign(new Element(), {open: target => {
      assert.equal(target, origin + '/');
      assert.ok(!target.includes(credential));
      return blocked ? null : child;
    }});
    let expire;
    runInNewContext(script, {
      document: {querySelector: selector => selector === 'button' ? button : notice},
      window: windowTarget, setTimeout: fn => { expire = fn; return 1; }, clearTimeout() {}
    });
    return {button, notice, child, windowTarget, messages, expire};
  }
  const f = fixture();
  f.button.fire('click');
  const receive = f.windowTarget.handlers.get('message');
  const valid = {source: f.child, origin, data: {type: 'cortex-ready'}};
  receive({...valid, origin: 'http://127.0.0.1:9999'});
  receive({...valid, source: {}});
  assert.equal(f.messages.length, 0);
  receive(valid);
  receive(valid);
  assert.equal(f.messages.length, 1);
  assert.equal(f.messages[0].target, origin);
  assert.equal(f.messages[0].body.credential, credential);
  receive({...valid, data: {type: 'cortex-bootstrap-complete'}});
  assert.match(f.notice.textContent, /connecting in the new tab/);
  const expired = fixture();
  expired.button.fire('click');
  expired.expire();
  expired.windowTarget.handlers.get('message')({source: expired.child, origin, data: {type: 'cortex-ready'}});
  assert.equal(expired.messages.length, 0);
  assert.match(expired.notice.textContent, /expired/);
  const blocked = fixture(true);
  blocked.button.fire('click');
  assert.match(blocked.notice.textContent, /blocked/);
  assert.equal(blocked.button.disabled, false);
});
