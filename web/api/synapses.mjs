// SPDX-License-Identifier: AGPL-3.0-only
import {createApiClient} from './client.mjs';

export function citationUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.port || url.username || url.password) {
    throw new TypeError('Unsupported citation URL.');
  }
  return url.href;
}

export function validateReceipt(value) {
  if (!value || value.schema_version !== 1) throw new TypeError('Unsupported local API response.');
  if (['pairing_required', 'paired', 'trusted'].includes(value.status)) {
    if (!/^[a-f0-9]{32}$/.test(value.pairing_id) || !Number.isInteger(value.expires_in_seconds) ||
        value.expires_in_seconds < 0 || value.expires_in_seconds > 1800) {
      throw new TypeError('Invalid browser pairing response.');
    }
    if (value.status === 'trusted' || value.sources !== undefined) {
      if (!Array.isArray(value.sources) || value.sources.length !== 1 ||
          typeof value.sources[0] !== 'string' || !value.sources[0].trim() || value.sources[0].length > 128) {
        throw new TypeError('Invalid configured Brain selection.');
      }
    }
  } else if (['ready', 'found', 'no_match'].includes(value.status)) {
    if (value.read_only !== true || !value.request_id || !value.source?.name ||
        !/^[a-f0-9]{40}$/.test(value.source.commit)) {
      throw new TypeError('Invalid named-source receipt.');
    }
    if (value.status === 'ready') {
      if (value.source_verified !== true || value.synchronized !== true ||
          typeof value.cache_fresh !== 'boolean' || !Number.isInteger(value.count) || value.count < 0) {
        throw new TypeError('Unverified source status.');
      }
    } else {
      if (value.freshness?.source_verified !== true || typeof value.freshness.cache_fresh !== 'boolean' ||
          !Array.isArray(value.matches) || value.matches.length > 5 ||
          (value.status === 'found') !== (value.matches.length > 0)) {
        throw new TypeError('Invalid cited result.');
      }
      for (const match of value.matches) {
        if (typeof match.excerpt?.text !== 'string' || [...match.excerpt.text].length > 240 ||
            typeof match.json_pointer !== 'string' || !/^[a-f0-9]{64}$/.test(match.sha256)) {
          throw new TypeError('Invalid citation.');
        }
        if (!citationUrl(match.source_url).startsWith(`https://github.com/${value.source.repository}/blob/${value.source.commit}/`)) {
          throw new TypeError('Citation does not belong to the authorized source snapshot.');
        }
      }
    }
  } else if (value.status !== 'disconnected') {
    throw new TypeError('Unexpected local API outcome.');
  }
  return value;
}

export function createSynapsesClient({origin, activity, fetchImpl}) {
  const base = new URL(origin);
  if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || base.origin !== origin) {
    throw new TypeError('The local pilot requires its exact IPv4 loopback origin.');
  }
  const client = createApiClient({
    baseUrl: `${origin}/api/local/`, pageOrigin: origin, credentials: 'same-origin',
    activity, fetchImpl, validateJson: validateReceipt
  });
  // Loopback cookies are shared across ports. Bind reads to this tab's in-memory key too.
  const browserKey = [...crypto.getRandomValues(new Uint8Array(32))].map(byte => byte.toString(16).padStart(2, '0')).join('');
  return Object.freeze({
    request(operation, body = {}, signal) {
      if (!['bootstrap', 'session', 'disconnect', 'status', 'synapse'].includes(operation)) {
        throw new TypeError('Unsupported local read operation.');
      }
      return client.requestJson(operation, {
        method: 'POST', headers: {
          'Content-Type': 'application/json', 'X-Cortex-Read-Only': '1', 'X-Cortex-Browser': browserKey
        },
        body: JSON.stringify(body), signal
      });
    }
  });
}
