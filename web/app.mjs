// SPDX-License-Identifier: AGPL-3.0-only
import {createApiActivity} from './api/activity.mjs';
import {bindApiStatus} from './components/api-status.mjs';
import {bindTheme} from './theme.mjs';
import {bindSynapses} from './components/synapses.mjs';

bindTheme({
  root: document.documentElement,
  select: document.querySelector('#theme'),
  notice: document.querySelector('#theme-notice'),
  getStorage: () => window.localStorage
});

const activity = createApiActivity();
bindApiStatus({
  activity,
  button: document.querySelector('#api-status'),
  panel: document.querySelector('#api-details'),
  closeButton: document.querySelector('#api-close'),
  drawer: document.querySelector('#api-drawer'),
  contents: document.querySelector('#api-drawer-content'),
  hideButton: document.querySelector('#api-drawer-toggle'),
  notice: document.querySelector('#api-drawer-notice'),
  getStorage: () => window.localStorage,
  status: document.querySelector('#api-label'),
  details: document.querySelector('#api-counts'),
  documentTarget: document
});

bindSynapses({activity, documentTarget: document});
