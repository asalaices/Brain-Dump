// SPDX-License-Identifier: AGPL-3.0-only
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {createApiActivity} from '../../web/api/activity.mjs';
import {createApiClient, HttpError} from '../../web/api/client.mjs';
import {bindApiStatus, describeActivity} from '../../web/components/api-status.mjs';
import {bindTheme, THEMES} from '../../web/theme.mjs';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

class Element extends EventTarget {
  dataset = {};
  attributes = {};
  hidden = false;
  value = '';
  textContent = '';
  focused = false;
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
}

function statusFixture(activity) {
  const parts = {
    activity, button: new Element(), panel: new Element(), status: new Element(),
    details: new Element(), documentTarget: new EventTarget()
  };
  return {...parts, dispose: bindApiStatus(parts)};
}

function themeFixture(getStorage) {
  const parts = {root: new Element(), select: new Element(), notice: new Element(), getStorage};
  parts.notice.hidden = true;
  return {...parts, dispose: bindTheme(parts)};
}

test('activity stays unconfigured until a transport is configured', () => {
  const activity = createApiActivity();
  assert.equal(describeActivity(activity.snapshot()).state, 'unconfigured');
  assert.throws(() => activity.begin(), /Configure/);
  assert.equal(activity.snapshot().started, 0);
  assert.ok(Object.isFrozen(activity.snapshot()));
});

test('concurrent requests stay active until both settle, including JSON parsing', async () => {
  const activity = createApiActivity();
  const bodies = [deferred(), deferred()];
  let next = 0;
  const client = createApiClient({
    baseUrl: 'https://example.test/fixture/', activity,
    fetchImpl: async () => ({ok: true, status: 200, json: () => bodies[next++].promise})
  });
  const first = client.requestJson('first');
  const second = client.requestJson('second');
  assert.equal(activity.snapshot().pending, 2);
  await Promise.resolve();
  bodies[1].resolve({second: true});
  assert.deepEqual(await second, {second: true});
  assert.equal(activity.snapshot().pending, 1);
  bodies[0].resolve({first: true});
  assert.deepEqual(await first, {first: true});
  assert.deepEqual(activity.snapshot(), {
    configured: true, pending: 0, started: 2, completed: 2,
    failed: 0, cancelled: 0, lastOutcome: 'completed'
  });
});

test('HTTP errors propagate without reading private response bodies', async () => {
  for (const status of [401, 403, 404, 429, 500]) {
    const activity = createApiActivity();
    const client = createApiClient({
      baseUrl: 'https://example.test/api/', activity,
      fetchImpl: async () => ({ok: false, status, json: () => assert.fail('must not read error body')})
    });
    await assert.rejects(client.requestJson('fixture'), error =>
      error instanceof HttpError && error.status === status);
    assert.equal(activity.snapshot().pending, 0);
    assert.equal(activity.snapshot().failed, 1);
    assert.equal(describeActivity(activity.snapshot()).state, 'error');
  }
});

test('network, synchronous transport, and malformed JSON failures are observable and rethrown', async () => {
  const failures = [
    () => { throw new TypeError('network failed'); },
    async () => { throw new TypeError('network failed'); },
    async () => ({ok: true, status: 200, json: async () => { throw new SyntaxError('invalid JSON'); }})
  ];
  for (const fetchImpl of failures) {
    const activity = createApiActivity();
    const client = createApiClient({baseUrl: 'https://example.test/api/', activity, fetchImpl});
    await assert.rejects(client.requestJson('fixture'));
    assert.equal(activity.snapshot().failed, 1);
    assert.equal(activity.snapshot().pending, 0);
  }
});

test('204 does not parse a body and requests omit credentials', async () => {
  const activity = createApiActivity();
  const controller = new AbortController();
  const headers = {'Content-Type': 'application/json'};
  const client = createApiClient({
    baseUrl: 'https://example.test/api/', activity,
    fetchImpl: async (url, options) => {
      assert.equal(url, 'https://example.test/api/items?limit=1');
      assert.deepEqual(options, {
        method: 'POST', headers, body: '{}', signal: controller.signal,
        credentials: 'omit', redirect: 'error'
      });
      return {ok: true, status: 204, json: () => assert.fail('204 must not parse JSON')};
    }
  });
  assert.equal(await client.requestJson('items?limit=1', {
    method: 'POST', headers, body: '{}', signal: controller.signal,
    credentials: 'include', redirect: 'follow'
  }), null);
  assert.equal(activity.snapshot().completed, 1);
});

test('cancellation is distinct from failure, including a custom abort reason', async () => {
  for (const reason of [undefined, new Error('cancelled by caller')]) {
    const activity = createApiActivity();
    const controller = new AbortController();
    const client = createApiClient({
      baseUrl: 'https://example.test/api/', activity,
      fetchImpl: async (_url, {signal}) => { signal.throwIfAborted(); }
    });
    controller.abort(reason);
    await assert.rejects(client.requestJson('fixture', {signal: controller.signal}));
    assert.equal(activity.snapshot().cancelled, 1);
    assert.equal(activity.snapshot().failed, 0);
    assert.equal(activity.snapshot().pending, 0);
    assert.equal(describeActivity(activity.snapshot()).state, 'cancelled');
  }
});

test('invalid configuration and escaping paths fail before any request starts', async () => {
  for (const baseUrl of [
    'file:///tmp/', 'https://user:password@example.test/api/', 'https://example.test/api',
    'https://example.test/api/?token=value', 'https://example.test/api/#fragment'
  ]) {
    const activity = createApiActivity();
    assert.throws(() => createApiClient({baseUrl, activity}), TypeError);
    assert.equal(activity.snapshot().configured, false);
  }
  const activity = createApiActivity();
  const client = createApiClient({
    baseUrl: 'https://example.test/api/', activity,
    fetchImpl: () => assert.fail('invalid path must not fetch')
  });
  for (const path of [
    '', '/outside', '//other.test/api/', 'https://other.test/api/', '../outside',
    '%2e%2e/outside', 'items/%2e%2e/%2e%2e/outside', 'items%2foutside',
    'items%5coutside', 'items\\outside', 'items#fragment', ' items', null
  ]) {
    await assert.rejects(client.requestJson(path), TypeError);
  }
  assert.equal(activity.snapshot().started, 0);
});

test('finishing is idempotent and subscriptions can be removed', () => {
  const activity = createApiActivity();
  let calls = 0;
  const unsubscribe = activity.subscribe(() => { calls += 1; });
  activity.configure();
  const finish = activity.begin();
  assert.throws(() => finish('unknown'), TypeError);
  assert.equal(activity.snapshot().pending, 1);
  finish('failed');
  finish('completed');
  assert.equal(activity.snapshot().failed, 1);
  assert.equal(activity.snapshot().completed, 0);
  assert.equal(calls, 4);
  unsubscribe();
  activity.begin()('completed');
  assert.equal(calls, 4);
});

test('the button reflects overlapping requests and retains cumulative errors', () => {
  const activity = createApiActivity();
  const parts = statusFixture(activity);
  assert.equal(parts.button.dataset.state, 'unconfigured');
  assert.equal(parts.panel.hidden, true);
  assert.equal(parts.button.attributes['aria-expanded'], 'false');
  activity.configure();
  const first = activity.begin();
  const second = activity.begin();
  assert.equal(parts.button.dataset.active, 'true');
  assert.equal(parts.button.attributes['aria-busy'], 'true');
  first('failed');
  assert.equal(parts.button.dataset.active, 'true');
  assert.match(parts.button.attributes['aria-label'], /1 failed/);
  second('completed');
  assert.equal(parts.button.dataset.active, 'false');
  assert.equal(parts.button.attributes['aria-busy'], 'false');
  assert.match(parts.details.textContent, /1 failed/);
  assert.match(parts.details.textContent, /not backend readiness/);
  parts.dispose();
});

test('details toggle without network activity; Escape closes and restores focus', () => {
  const activity = createApiActivity();
  const parts = statusFixture(activity);
  parts.button.dispatchEvent(new Event('click'));
  assert.equal(parts.panel.hidden, false);
  assert.equal(parts.button.attributes['aria-expanded'], 'true');
  const escape = new Event('keydown');
  Object.defineProperty(escape, 'key', {value: 'Escape'});
  parts.documentTarget.dispatchEvent(escape);
  assert.equal(parts.panel.hidden, true);
  assert.equal(parts.button.focused, true);
  assert.equal(activity.snapshot().started, 0);
  parts.dispose();
  parts.button.dispatchEvent(new Event('click'));
  assert.equal(parts.panel.hidden, true);
  activity.configure();
  assert.equal(parts.button.dataset.state, 'unconfigured');
});

test('all six inherited palettes can be selected and persisted independently', () => {
  const saved = new Map([['cortex.theme', 'sand']]);
  const fixture = themeFixture(() => ({
    getItem: key => saved.get(key),
    setItem: (key, value) => saved.set(key, value)
  }));
  assert.equal(fixture.root.dataset.theme, 'sand');
  for (const theme of THEMES) {
    fixture.select.value = theme;
    fixture.select.dispatchEvent(new Event('change'));
    assert.equal(fixture.root.dataset.theme, theme);
    assert.equal(saved.get('cortex.theme'), theme);
  }
  assert.equal(fixture.notice.hidden, true);
  fixture.dispose();
  fixture.select.value = 'light';
  fixture.select.dispatchEvent(new Event('change'));
  assert.equal(fixture.root.dataset.theme, 'sand');
});

test('unavailable storage and invalid saved themes are explicitly reported', () => {
  const unavailable = themeFixture(() => { throw new Error('storage denied'); });
  assert.equal(unavailable.root.dataset.theme, 'dark');
  assert.match(unavailable.notice.textContent, /storage is unavailable/);
  unavailable.select.value = 'light';
  unavailable.select.dispatchEvent(new Event('change'));
  assert.equal(unavailable.root.dataset.theme, 'light');
  unavailable.dispose();
  const invalid = themeFixture(() => ({getItem: () => 'unknown', setItem() {}}));
  assert.equal(invalid.root.dataset.theme, 'dark');
  assert.match(invalid.notice.textContent, /not supported/);
  invalid.select.value = 'ocean';
  invalid.select.dispatchEvent(new Event('change'));
  assert.equal(invalid.root.dataset.theme, 'ocean');
  assert.equal(invalid.notice.hidden, true);
  invalid.dispose();
});

test('browser entry wires real selectors and never probes an invented API', async t => {
  const html = await readFile(new URL('../../web/index.html', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(ids.length, new Set(ids).size);
  const elements = new Map(ids.map(id => [`#${id}`, new Element()]));
  const documentTarget = new EventTarget();
  documentTarget.documentElement = new Element();
  documentTarget.querySelector = selector => {
    assert.ok(elements.has(selector), `missing HTML selector: ${selector}`);
    return elements.get(selector);
  };
  const previous = {document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch};
  t.after(() => Object.assign(globalThis, previous));
  globalThis.document = documentTarget;
  globalThis.window = {
    location: {origin: 'http://127.0.0.1:8080'},
    localStorage: {getItem: () => null, setItem() {}},
    sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}}
  };
  globalThis.fetch = () => assert.fail('foundation must not make backend requests');
  await import('../../web/app.mjs');
  assert.equal(elements.get('#api-status').dataset.state, 'idle');
  assert.equal(documentTarget.documentElement.dataset.theme, 'dark');
  elements.get('#api-status').dispatchEvent(new Event('click'));
  assert.equal(elements.get('#api-details').hidden, false);
});

test('real fetch follows a bounded local HTTP fixture, including abort and bad JSON', async t => {
  const server = createServer((request, response) => {
    if (request.url === '/fixture/redirect') {
      response.writeHead(302, {Location: '/outside'});
      response.end();
    } else if (request.url === '/outside') {
      assert.fail('transport must not follow redirects outside its configured base');
    } else if (request.url === '/fixture/invalid') {
      response.writeHead(200, {'Content-Type': 'application/json'});
      response.end('not JSON');
    } else if (request.url === '/fixture/wait') {
      response.writeHead(200, {'Content-Type': 'application/json'});
      response.flushHeaders();
    } else {
      response.writeHead(200, {'Content-Type': 'application/json'});
      response.end('{"fixture":true}');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
  const activity = createApiActivity();
  const client = createApiClient({
    baseUrl: `http://127.0.0.1:${server.address().port}/fixture/`, activity
  });
  assert.deepEqual(await client.requestJson('ok'), {fixture: true});
  await assert.rejects(client.requestJson('invalid'), SyntaxError);
  await assert.rejects(client.requestJson('redirect'), TypeError);
  const controller = new AbortController();
  const pending = client.requestJson('wait', {signal: controller.signal});
  assert.equal(activity.snapshot().pending, 1);
  controller.abort();
  await assert.rejects(pending);
  assert.equal(activity.snapshot().pending, 0);
  assert.equal(activity.snapshot().completed, 1);
  assert.equal(activity.snapshot().failed, 2);
  assert.equal(activity.snapshot().cancelled, 1);
});

test('styles define all palette tokens, bounded activity motion, and reduced-motion behavior', async () => {
  const palettes = await readFile(new URL('../../web/styles/themes.css', import.meta.url), 'utf8');
  for (const theme of THEMES) {
    const body = palettes.match(new RegExp(`:root\\[data-theme="${theme}"\\]\\s*\\{([^}]+)\\}`))[1];
    for (const token of ['background', 'surface', 'surface-raised', 'border', 'text', 'muted', 'accent', 'healthy', 'warning', 'danger']) {
      assert.match(body, new RegExp(`--${token}: #[a-f0-9]{6};`));
    }
  }
  const css = await readFile(new URL('../../web/styles/base.css', import.meta.url), 'utf8');
  assert.match(css, /\[data-active="true"\] \.activity-dot \{[^}]*animation: request-throb/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*#api-status\[data-active="true"\] \.activity-dot \{ animation: none;/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /min-height: 2\.75rem/);
  assert.match(css, /\[hidden\] \{ display: none !important;/);
});
