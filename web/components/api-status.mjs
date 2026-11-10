// SPDX-License-Identifier: AGPL-3.0-only
export function describeActivity(value) {
  let state;
  let label;
  if (!value.configured) {
    state = 'unconfigured';
    label = 'API not configured';
  } else if (value.pending) {
    state = 'active';
    label = `${value.pending} API request${value.pending === 1 ? '' : 's'} in progress`;
  } else if (value.lastOutcome === 'failed') {
    state = 'error';
    label = 'Last API request failed';
  } else if (value.lastOutcome === 'cancelled') {
    state = 'cancelled';
    label = 'Last API request cancelled';
  } else if (value.lastOutcome === 'completed') {
    state = 'idle';
    label = 'Last API request completed';
  } else {
    state = 'idle';
    label = 'API configured; not checked';
  }
  const details = `This page only: ${value.started} started, ${value.pending} in progress, ` +
    `${value.completed} completed, ${value.failed} failed, ${value.cancelled} cancelled. ` +
    'Activity is not backend readiness, server-wide history or authorization.';
  return {state, label, details};
}

export function bindApiStatus({activity, button, panel, status, details, documentTarget}) {
  function setOpen(open) {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
  }
  const unsubscribe = activity.subscribe(value => {
    const description = describeActivity(value);
    button.dataset.state = description.state;
    button.dataset.active = String(value.pending > 0);
    button.setAttribute('aria-busy', String(value.pending > 0));
    button.setAttribute('aria-label', `${description.label}. ${description.details} Show API activity details.`);
    status.textContent = description.label;
    details.textContent = description.details;
  });
  const toggle = () => setOpen(panel.hidden);
  const keydown = event => {
    if (event.key === 'Escape' && !panel.hidden) {
      setOpen(false);
      button.focus();
    }
  };
  setOpen(false);
  button.addEventListener('click', toggle);
  documentTarget.addEventListener('keydown', keydown);
  return () => {
    unsubscribe();
    button.removeEventListener('click', toggle);
    documentTarget.removeEventListener('keydown', keydown);
  };
}
