// SPDX-License-Identifier: AGPL-3.0-only
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {bindWorkspaceTabs} from '../../web/components/workspace-tabs.mjs';

class Element extends EventTarget {
  attributes = {};
  hidden = false;
  focused = false;
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
}

function fixture() {
  const tabs = [new Element(), new Element()];
  const panels = [new Element(), new Element()];
  return {tabs, panels, dispose: bindWorkspaceTabs({tabs, panels})};
}

function key(element, value) {
  const event = new Event('keydown', {cancelable: true});
  Object.defineProperty(event, 'key', {value});
  element.dispatchEvent(event);
  return event;
}

test('tabs select exactly one panel without modifying its private content or shared connection', () => {
  const {tabs, panels, dispose} = fixture();
  panels[0].textContent = 'synthetic cited content';
  assert.equal(tabs[0].attributes['aria-selected'], 'true');
  assert.equal(tabs[0].tabIndex, 0);
  assert.equal(tabs[1].tabIndex, -1);
  assert.equal(panels[1].hidden, true);
  tabs[1].dispatchEvent(new Event('click'));
  assert.equal(tabs[1].attributes['aria-selected'], 'true');
  assert.equal(tabs[1].tabIndex, 0);
  assert.equal(panels[0].hidden, true);
  assert.equal(panels[1].hidden, false);
  assert.equal(panels[0].textContent, 'synthetic cited content');
  dispose();
  tabs[0].dispatchEvent(new Event('click'));
  assert.equal(panels[0].hidden, true);
});

test('arrow keys wrap and Home/End move focus with selection; unrelated keys remain native', () => {
  const {tabs, panels, dispose} = fixture();
  assert.equal(key(tabs[0], 'ArrowLeft').defaultPrevented, true);
  assert.equal(tabs[1].focused, true);
  assert.equal(panels[1].hidden, false);
  key(tabs[1], 'ArrowRight');
  assert.equal(panels[0].hidden, false);
  key(tabs[0], 'End');
  assert.equal(panels[1].hidden, false);
  key(tabs[1], 'Home');
  assert.equal(panels[0].hidden, false);
  assert.equal(key(tabs[0], 'Tab').defaultPrevented, false);
  assert.equal(key(tabs[0], 'Enter').defaultPrevented, false);
  dispose();
});

test('mismatched tab/panel configuration fails explicitly', () => {
  assert.throws(() => bindWorkspaceTabs({tabs: [], panels: []}), TypeError);
  assert.throws(() => bindWorkspaceTabs({tabs: [new Element()], panels: []}), TypeError);
});

test('attached tab markup keeps connection controls outside hidden content and Administration non-operational', async () => {
  const html = await readFile(new URL('../../web/index.html', import.meta.url), 'utf8');
  assert.match(html, /class="workspace-tabs" role="tablist"/);
  for (const name of ['recall', 'administration']) {
    assert.match(html, new RegExp(`id="${name}-tab"[^>]*role="tab"[^>]*aria-controls="${name}-panel"`));
    assert.match(html, new RegExp(`id="${name}-panel"[^>]*role="tabpanel"[^>]*aria-labelledby="${name}-tab"`));
  }
  const connection = html.match(/<div class="workspace-connection"[\s\S]*?<\/div>\s*<p id="synapses-notice"[\s\S]*?<\/div>/)[0];
  for (const id of ['synapses-connect', 'synapses-disconnect', 'synapses-notice', 'synapses-source']) {
    assert.ok(connection.includes(`id="${id}"`));
  }
  const administration = html.match(/<div id="administration-panel"[\s\S]*?<\/div>/)[0];
  assert.match(administration, /not available in this local read-only pilot/);
  assert.doesNotMatch(administration, /<button|<form|<input/);
  assert.ok(html.indexOf('id="synapses-connect"') < html.indexOf('id="recall-panel"'));
  const css = await readFile(new URL('../../web/styles/base.css', import.meta.url), 'utf8');
  assert.match(css, /role="tab"\] \{[^}]*margin-bottom: -1px;[^}]*border-radius: \.6rem \.6rem 0 0/);
  assert.match(css, /aria-selected="true"\] \{[^}]*border-bottom-color: var\(--surface\)/);
});
