// SPDX-License-Identifier: AGPL-3.0-only
import {createApiActivity} from './api/activity.mjs';
import {bindApiStatus} from './components/api-status.mjs';
import {bindTheme} from './theme.mjs';

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
  status: document.querySelector('#api-label'),
  details: document.querySelector('#api-counts'),
  documentTarget: document
});

// Endpoint selection and authenticated product adapters belong to the API contract work.
// No transport is created here, so opening the foundation makes no backend requests.
