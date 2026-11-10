// SPDX-License-Identifier: AGPL-3.0-only
export function createApiActivity() {
  const listeners = new Set();
  const pending = new Set();
  let configured = false;
  let started = 0;
  let completed = 0;
  let failed = 0;
  let cancelled = 0;
  let lastOutcome = null;

  function snapshot() {
    return Object.freeze({
      configured, pending: pending.size, started, completed, failed, cancelled, lastOutcome
    });
  }

  function notify() {
    const value = snapshot();
    for (const listener of listeners) listener(value);
  }

  return Object.freeze({
    snapshot,
    subscribe(listener) {
      listeners.add(listener);
      listener(snapshot());
      return () => listeners.delete(listener);
    },
    configure() {
      configured = true;
      notify();
    },
    begin() {
      if (!configured) throw new Error('Configure the API transport before starting a request.');
      const token = Symbol('request');
      pending.add(token);
      started += 1;
      notify();
      return outcome => {
        if (!['completed', 'failed', 'cancelled'].includes(outcome)) {
          throw new TypeError('Unknown API request outcome.');
        }
        if (!pending.delete(token)) return;
        if (outcome === 'completed') completed += 1;
        if (outcome === 'failed') failed += 1;
        if (outcome === 'cancelled') cancelled += 1;
        lastOutcome = outcome;
        notify();
      };
    }
  });
}
