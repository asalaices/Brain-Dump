# Cortex web foundation

This is a small, unconnected browser foundation, not the complete Cortex
application or an accepted browser API. It uses plain HTML, CSS and native
JavaScript modules, following the reference apps without introducing a framework,
package manager, build step or runtime dependency on either app.

## File ownership

```text
web/
  index.html                accessible foundation page
  app.mjs                   composition only; no backend configuration
  theme.mjs                 six themes and Cortex-only local preference
  api/
    activity.mjs            per-page request lifecycle and subscriptions
    client.mjs              injected JSON transport; no product endpoints
  components/
    api-status.mjs          request status button and disclosure
  styles/
    themes.css              selected shared palette tokens
    base.css                layout, focus, activity and reduced-motion rules
tests/web/
  foundation.test.mjs       offline behavioral and local HTTP fixture tests
```

Keep transport and activity independent of DOM rendering. Future product
adapters belong under `web/api/`; they must implement reviewed browser contracts,
not call infrastructure telemetry or invent replacements for Brain Bridge.
Future screens consume those adapters, not `fetch` scattered through the UI.
The framework's Python CLI and installed package are unchanged; these source
assets are not yet a packaged application/server.

## Run and test

For a local, static preview from the repository root, with Python 3.11+:

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory web
```

Open `http://127.0.0.1:8080/` and stop the process when finished. If that port is
occupied, select an unused port; do not stop the other process. The static server
does not provide an API. Opening the page or its API details makes no backend
requests. Theme preferences use only `cortex.theme` in browser storage; denied
storage is visibly reported and does not prevent an in-page theme change.

Run behavioral coverage with Node.js 22+ (no npm packages):

```sh
node --test tests/web/*.test.mjs
```

The existing offline CI workflow runs these tests separately from the Python
suite. Tests cover overlap, out-of-order settlement, body parsing, HTTP errors,
network errors, cancellation, path/configuration rejection, state subscriptions,
button disclosure, theme storage failures and a temporary loopback HTTP fixture.
No reference app or private backend is needed.

## API adapter boundary

There are deliberately no default routes, credentials, readiness probes or
automatic polling. A future adapter can compose the existing pieces:

```js
import {createApiActivity} from './api/activity.mjs';
import {createApiClient} from './api/client.mjs';

const activity = createApiActivity();
// Supply an explicitly selected HTTP(S) base directory URL ending in "/".
const client = createApiClient({baseUrl: approvedBaseUrl, activity});
// Pass this same activity to bindApiStatus; use client.requestJson only with
// paths and request/response shapes approved by the product API contract.
```

`requestJson(relativePath, fetchOptions)` rejects paths escaping its base,
omits browser credentials, rejects redirects, propagates HTTP/network/JSON errors, and accepts an
`AbortSignal`. It returns parsed JSON, or `null` for HTTP 204. Completion includes
body parsing, not just receipt of response headers. Authentication, schema
validation, pagination, capability negotiation and timeouts remain adapter/API
contract decisions; do not use this transport as an authenticated product API.
Error responses are not parsed or copied into UI text.

The activity button counts **this page's adapter requests only**. Pending count
keeps the throb active until every overlapping request finishes or is cancelled.
Failures and cancellations are distinct and remain in cumulative page counters;
the most recently settled request supplies the last-outcome label. A later
success does not erase the failure count. Configured-but-unchecked and
unconfigured are explicit states. Neither a green idle dot nor a completed
request establishes backend readiness, a grant, server-wide activity or task
acceptance. Disclosure clicks, theme changes and local interaction never pulse.

## Reference implementation and adaptation

The owner authorized selected software-only reuse under this repository's
AGPL-3.0-only license. Only neutral software palette tokens and UI patterns are
adapted; no private data, host settings, credentials or runtime configuration
are included.

Reference source paths below are repository-relative to their named owner:

| Reference | Source evidence | Cortex adaptation |
| --- | --- | --- |
| master-01, `d86b5b34207351c6ed3d7456f698486db6de224b` | `payload_files/dashboard/usr/share/nginx/html/media-host-status/theme-dark.css:1-124`; `theme-light.css:1-30,108-143` in the same directory | Dark, Light, Ocean, Midnight, Plum and Sand retain selected original semantic token names and color values; host-specific selectors are excluded. |
| master-01, same revision | `payload_files/dashboard/usr/share/nginx/html/media-host-status/prompt-activity.js:29-49` | Reference pulses on changed backend sequence, not a timer that invents activity. Cortex has no such backend contract: an explicitly different per-page lifecycle drives activity, with no telemetry polling. |
| master-01, same revision | `payload_files/dashboard/usr/share/nginx/html/media-host-status/styles.css:2749-2753,2796-2836` | Circular activity mark, active scale/color and tokenized container styling; reduced-motion support is preserved. Idle breathing is intentionally omitted so idle is not mistaken for request activity. No infrastructure drawer or LLM/auth controls are copied. |
| Simple-Todos, `297d52658c9c7fa26b02cd6866d8272b4f59cf00` | `web/executions.js:12-34,86-117`; `web/app.js:595-660` | Availability, history and activity are separate concepts. Cortex exposes only locally known request activity; it does not fabricate readiness/history or copy local-click/monitor completion pulses. |
| Simple-Todos, same revision | `web/themes.js:9-34`; `web/themes.css:1-11` | Validated theme allowlist and per-app preference; Cortex uses the requested master-01 palettes, not similarly named Simple-Todos palettes. Storage errors are visible rather than silent. |

These are historical source references, not runtime dependencies or evidence
that either app is currently deployed. The API control uses a native button,
`aria-expanded`/`aria-controls`, `aria-busy`, descriptive text, keyboard activation
and Escape-to-close with focus return. It is an inline, non-modal disclosure;
there is no hover timer or focus trap.

## Remaining product gates

This foundation does not complete or approve the product taxonomy, journeys,
standalone application/server or versioned API contracts. Those retain their
existing CORTEX2-5 and CORTEX8 ownership and acceptance boundaries. No proposed
navigation is presented as working. Endpoint selection and authenticated
integration must wait for the applicable contract; installation, configuration
validation/port management and release acceptance remain separate work.
