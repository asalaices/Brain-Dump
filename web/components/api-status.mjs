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

const DRAWER_STORAGE_KEY = 'cortex.api-drawer.collapsed';

export function bindApiStatus({
  activity, button, panel, closeButton, status, details, documentTarget,
  drawer, contents, hideButton, notice, getStorage
}) {
  function warn(message) {
    notice.hidden = false;
    notice.textContent = message;
  }
  function setOpen(open, restoreFocus = false) {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    if (open) closeButton.focus();
    else if (restoreFocus) button.focus();
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
  function setCollapsed(collapsed, save = true) {
    if (collapsed) setOpen(false);
    drawer.dataset.collapsed = String(collapsed);
    contents.inert = collapsed;
    contents.setAttribute('aria-hidden', String(collapsed));
    hideButton.setAttribute('aria-expanded', String(!collapsed));
    const label = collapsed ? 'Show API activity control' : 'Hide API activity control';
    hideButton.setAttribute('aria-label', label);
    hideButton.setAttribute('title', label);
    hideButton.querySelector('span').textContent = collapsed ? '›' : '‹';
    if (save) {
      try {
        getStorage().setItem(DRAWER_STORAGE_KEY, String(collapsed));
        notice.hidden = true;
        notice.textContent = '';
      } catch {
        warn('API drawer storage is unavailable. The hide setting applies only to this page.');
      }
    }
  }
  let saved;
  try {
    saved = getStorage().getItem(DRAWER_STORAGE_KEY);
  } catch {
    warn('API drawer storage is unavailable. The hide setting applies only to this page.');
  }
  if (saved && !['true', 'false'].includes(saved)) {
    warn('The saved API drawer setting is not supported. Showing the control.');
  }
  setCollapsed(saved === 'true', false);
  const toggleSurface = () => {
    setCollapsed(drawer.dataset.collapsed !== 'true');
    hideButton.focus();
  };
  const collapseFromBackground = event => {
    if (!button.contains(event.target) && !hideButton.contains(event.target)) {
      setCollapsed(true);
      hideButton.focus();
    }
  };
  const toggle = () => setOpen(panel.hidden, !panel.hidden);
  const close = () => setOpen(false, true);
  const showTooltip = () => { button.dataset.tooltipDismissed = 'false'; };
  const keydown = event => {
    if (event.key === 'Escape') {
      if (!panel.hidden) close();
      else if (drawer.contains(event.target) && drawer.dataset.collapsed !== 'true') {
        event.preventDefault();
        setCollapsed(true);
        hideButton.focus();
      }
      button.dataset.tooltipDismissed = 'true';
    }
  };
  const outside = event => {
    if (!panel.hidden && !panel.contains(event.target) && !button.contains(event.target)) setOpen(false);
  };
  setOpen(false);
  button.addEventListener('click', toggle);
  button.addEventListener('pointerenter', showTooltip);
  button.addEventListener('focus', showTooltip);
  closeButton.addEventListener('click', close);
  hideButton.addEventListener('click', toggleSurface);
  drawer.addEventListener('click', collapseFromBackground);
  documentTarget.addEventListener('keydown', keydown);
  documentTarget.addEventListener('pointerdown', outside);
  return () => {
    unsubscribe();
    button.removeEventListener('click', toggle);
    button.removeEventListener('pointerenter', showTooltip);
    button.removeEventListener('focus', showTooltip);
    closeButton.removeEventListener('click', close);
    hideButton.removeEventListener('click', toggleSurface);
    drawer.removeEventListener('click', collapseFromBackground);
    documentTarget.removeEventListener('keydown', keydown);
    documentTarget.removeEventListener('pointerdown', outside);
  };
}
