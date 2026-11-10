// SPDX-License-Identifier: AGPL-3.0-only
export class HttpError extends Error {
  constructor(status) {
    super(`API request failed (HTTP ${status}).`);
    this.name = 'HttpError';
    this.status = status;
  }
}

export function createApiClient({baseUrl, activity, fetchImpl = globalThis.fetch}) {
  const base = new URL(baseUrl);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password ||
      base.search || base.hash || !base.pathname.endsWith('/')) {
    throw new TypeError('API base URL must be an HTTP(S) directory URL without credentials, query or fragment.');
  }
  if (typeof fetchImpl !== 'function') throw new TypeError('A fetch implementation is required.');
  activity.configure();

  return Object.freeze({
    async requestJson(path, options = {}) {
      if (typeof path !== 'string' || !path || path !== path.trim() ||
          path.startsWith('/') || path.includes('\\') || path.includes('#') ||
          /^[a-z][a-z0-9+.-]*:/i.test(path)) {
        throw new TypeError('API request path must be relative to the configured base.');
      }
      const target = new URL(path, base);
      if (target.origin !== base.origin || !target.pathname.startsWith(base.pathname) ||
          /%(?:2f|5c)/i.test(target.pathname)) {
        throw new TypeError('API request path cannot escape the configured base.');
      }
      const finish = activity.begin();
      try {
        const response = await fetchImpl(target.href, {...options, credentials: 'omit', redirect: 'error'});
        if (!response.ok) throw new HttpError(response.status);
        const result = response.status === 204 ? null : await response.json();
        finish('completed');
        return result;
      } catch (error) {
        finish(options.signal?.aborted || error?.name === 'AbortError' ? 'cancelled' : 'failed');
        throw error;
      }
    }
  });
}
