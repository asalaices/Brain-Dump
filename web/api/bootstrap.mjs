// SPDX-License-Identifier: AGPL-3.0-only
export function receiveLaunch({
  windowTarget, client, onReady, onError, schedule = setInterval, cancel = clearInterval
}) {
  const opener = windowTarget.opener;
  if (!opener) return () => {};
  let accepting = true;
  let disposed = false;
  let attempts = 0;
  let timer;
  const ready = () => {
    if (++attempts > 600) {
      accepting = false;
      cancel(timer);
      windowTarget.removeEventListener('message', receive);
      windowTarget.opener = null;
      onError();
      return;
    }
    // The local file has an opaque origin. This contains no credential or source data.
    opener.postMessage({type: 'cortex-ready'}, '*');
  };
  const receive = async event => {
    if (!accepting || event.source !== opener || event.origin !== 'null' ||
        event.data?.type !== 'cortex-bootstrap' ||
        typeof event.data.credential !== 'string' || !/^[a-f0-9]{64}$/.test(event.data.credential)) return;
    accepting = false;
    cancel(timer);
    windowTarget.removeEventListener('message', receive);
    const body = {credential: event.data.credential};
    try {
      const receipt = await client.request('bootstrap', body);
      if (disposed) return;
      onReady(receipt);
      opener.postMessage({type: 'cortex-bootstrap-complete'}, '*');
    } catch {
      if (!disposed) onError();
    } finally {
      body.credential = '';
      windowTarget.opener = null;
    }
  };
  windowTarget.addEventListener('message', receive);
  timer = schedule(ready, 100);
  ready();
  return () => {
    accepting = false;
    disposed = true;
    cancel(timer);
    windowTarget.removeEventListener('message', receive);
  };
}
