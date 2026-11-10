# Cortex web foundation

This is a small browser foundation with an optional owner-only local read pilot,
not the complete Cortex application or accepted shared-service API.
It uses plain HTML, CSS and native
JavaScript modules, following the reference apps without introducing a framework,
package manager, build step or runtime dependency on either app.

## File ownership

```text
web/
  index.html                accessible foundation page
  app.mjs                   composition; no private configuration
  theme.mjs                 six themes and Cortex-only local preference
  api/
    activity.mjs            per-page request lifecycle and subscriptions
    client.mjs              injected JSON transport; no product endpoints
    synapses.mjs            explicit local read routes and receipt validation
  components/
    api-status.mjs          request status button and disclosure
    synapses.mjs            owner pairing, source status and cited Recall
  styles/
    themes.css              selected shared palette tokens
    base.css                layout, focus, activity and reduced-motion rules
tests/web/
  foundation.test.mjs       offline behavioral and local HTTP fixture tests
  synapses.test.mjs         local adapter, privacy and rendering behavior
cortex_server               source-checkout lifecycle launcher
brain_bridge/
  cortex_server.py          owned loopback preview and private CLI control
  cortex_synapses.py        expiring local sessions; delegates managed reads
tests/
  test_cortex_server.py     isolated real-process lifecycle behavior
  test_cortex_synapses.py   synthetic pairing, authority and HTTP boundaries
```

Keep transport and activity independent of DOM rendering. Future product
adapters belong under `web/api/`; they must implement reviewed browser contracts,
not call infrastructure telemetry or invent replacements for Brain Bridge.
Future screens consume those adapters, not `fetch` scattered through the UI.
The framework's `brain-bridge` CLI is unchanged. The preview launcher and web
assets are source-checkout tooling, not an installed application/server command.

## Run and test

For a local static preview, run from the repository root with Python 3.11+:

```sh
./cortex_server --start
./cortex_server --status --pretty
./cortex_server --stop
```

Use the URL in the start result (default `http://127.0.0.1:8080/`).
On Windows, use `python cortex_server` instead of `./cortex_server`, with the same
arguments. On POSIX, the launcher selects an available Python 3.11+ when the
default `python3` is older; `CORTEX_PYTHON` is a strict interpreter override.
No packages need installing for this preview.

`--start` waits for authenticated readiness before returning, and repeated
starts reuse the owned instance. `--stop` is idempotent and removes stopped
instance metadata; it never signals a PID. Stale metadata cannot cause an
unrelated process to be killed. A responsive foreign listener, mismatched
identity, invalid metadata or lock contention is an explicit error, not success.
Startup failure closes the controller pipe so an unregistered worker exits.
Stop verifies authenticated self-shutdown and listener closure.

Configuration is deliberately narrow:

| Setting | Meaning |
| --- | --- |
| `--port N` / `CORTEX_PORT` | Default 8080; 0 selects an available ephemeral port. A busy port fails without stopping its occupant. |
| `--runtime-dir PATH` / `CORTEX_RUNTIME_DIR` | Private directory outside the checkout; use the same selection for every command. |
| `CORTEX_HOST` | Only `127.0.0.1` and `localhost` accepted; always binds IPv4 loopback. |
| `CORTEX_PYTHON` | Explicit Python 3.11+ executable; an invalid override fails rather than falling back. |
| `--synapses-profile PATH` | Optional external consultation JSON profile, only with a fresh `--start`. No default private profile is selected implicitly. |

The default runtime is under `$XDG_STATE_HOME/brain-dump/` or
`~/.local/state/brain-dump/`, keyed by the resolved source checkout. `state.json`
contains a private instance token; never publish it. `server.log` retains
lifecycle diagnostics without request contents or tokens; the log and lock file
remain after stop. Use an owner-private directory, not shared storage. POSIX
directory/file modes are checked (700/600); Windows relies on the selected
directory's inherited user-private ACLs, not POSIX permission bits.

Results are JSON (`--json` is the default); `--pretty` only changes whitespace.
Exit 0 means the requested start/stop succeeded or status is running; status
stopped/stale and lifecycle errors return 1, and invalid arguments return 2.
`--help` and `--version` are supported. There is no restart, installation,
boot-service registration, remote binding or deployment operation.
`--pair BROWSER_ID` additionally approves a pending local browser tab as described
below; it does not change upstream grants or print session credentials.

Only `web/` is served; hidden paths, traversal, symlinks and directory listings
are rejected. An authenticated loopback `/_cortex/lifecycle` control is internal
process ownership/shutdown plumbing, not a browser data API or API-badge
activity source. Opening the page or its API details makes no backend
requests. Theme preferences use only `cortex.theme` in browser storage; denied
storage is visibly reported and does not prevent an in-page theme change.

Run behavioral coverage with Node.js 22+ (no npm packages):

```sh
node --test tests/web/*.test.mjs
python3 -B -m unittest discover -s tests -p test_cortex_server.py -v
python3 -B -m unittest discover -s tests -p test_cortex_synapses.py -v
```

The existing offline CI workflow runs the Node tests in its separate web job.
Browser tests cover overlap, out-of-order settlement, body parsing, HTTP errors,
network errors, cancellation, path/configuration rejection, state subscriptions,
button disclosure, theme storage failures and a temporary loopback HTTP fixture.
No reference app or private backend is needed.
The Python CI matrix explicitly runs lifecycle and local Synapses coverage on Linux, macOS and
Windows with Python 3.11/3.14 before the full suite, which also discovers it.
The full-suite runner explicitly imports checkout source; subsequent installed
artifact checks remain separate. JavaScript/CSS MIME types are explicit rather
than inherited from OS registry guesses, and connection-refusal checks allow
Windows TCP retry timing without treating timeouts as a successful shutdown.
Binding the loopback preview does not require reverse DNS. An unregistered
worker also has a ten-second self-exit deadline, bounding startup cleanup even
if a platform call cannot finish; successful registration cancels that deadline.
Lifecycle fixtures cover real start/readiness/stop/restart, concurrency,
idempotency, stale live PIDs, foreign listeners, redirects, invalid/oversized
state or identity, busy ports, startup failure/timeout, private paths, static
file boundaries and cleanup. All test workers are bounded and stopped.

## API adapter boundary

The generic client has no default routes, credentials, readiness probes or
automatic polling. An adapter composes the existing pieces:

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
omits browser credentials by default, rejects redirects, propagates HTTP/network/JSON errors, and accepts an
`AbortSignal`. It returns parsed JSON, or `null` for HTTP 204. Completion includes
body parsing and an optional `validateJson` callback, not just response headers.
Only explicit `credentials: 'same-origin'` with a matching `pageOrigin` can enable
cookies; per-request options cannot widen this to cross-origin credentials.
The local adapter pins the exact IPv4 loopback origin, read routes and version-1
receipt validation. Broader pagination, capabilities and shared-service
authentication remain pending; this generic transport alone grants no access.
Error responses are not parsed or copied into UI text.

The activity button counts **this page's adapter requests only**. Pending count
keeps the throb active until every overlapping request finishes or is cancelled.
Failures and cancellations are distinct and remain in cumulative page counters;
the most recently settled request supplies the last-outcome label. A later
success does not erase the failure count. Configured-but-unchecked and
unconfigured are explicit states. Neither a green idle dot nor a completed
request establishes backend readiness, a grant, server-wide activity or task
acceptance. Disclosure clicks, theme changes and local interaction never pulse.

## Owner-only local Synapses pilot

The local pilot reuses `managed_status` and `synapse_request` directly; it does
not add another search engine, read raw private records itself or invoke the
profile's `cli` string. Select an existing consultation profile explicitly:

```sh
# Stop only an owned preview when applying new server code or configuration.
./cortex_server --stop
./cortex_server --start --synapses-profile /absolute/private/consult.json
```

The existing profile supplies `identity_repo`, `source_repo`, `source` (registered
alias) and `cache_dir`. All paths must be absolute, outside this checkout and
free of symlinks. The profile must be an external regular JSON file up to 8 KiB;
on POSIX it must be owner-owned and not writable by others. Other profile keys
do not confer authority and are not passed to the adapter. Private paths are
never browser inputs or responses. No application port/configuration manifest
has been copied; this is the existing external **consultation routing profile**,
not a writer route or replacement for CLI/environment settings.

An already running preview is not silently reconfigured: `--start` with an
explicit profile rejects that case. Stop/start the owned instance deliberately.
Starting without a profile still serves the foundation, but local reads return
`not_configured`; no ambient source is inferred.

1. Open the reported `http://127.0.0.1:PORT/` URL and click **Connect to Synapses**.
2. Run the displayed `./cortex_server --pair BROWSER_ID` in this task checkout
   (with the same `--runtime-dir`, if overridden). The ID identifies the pending
   tab; it is not a credential and cannot approve itself.
3. Click **Check pairing**. Cortex verifies source status through the existing
   upstream authority, then enables bounded **Recall**. **Disconnect** revokes
   this tab's local session and clears its displayed data.

Pairing approval uses the existing owner-private lifecycle credential only on
the separate internal `/_cortex/pair` route. It is never given to the browser or
used as a data token. An older worker rejects this new route rather than
misinterpreting a pairing request as shutdown.

There is one approved **tab** per server process, with five-minute pending
requests, a fixed 30-minute approved lifetime and at most eight pending sessions.
Approval replaces other sessions. Restart, expiry and disconnect revoke access;
the server rechecks the session after each managed read before returning data.
The browser clears displayed results on read errors, logout and local expiry,
never persists queries/results, and ignores late replies after cancellation.
Reloading or using a different tab requires new pairing; concurrent-tab/shared
session behavior is not claimed.

An HttpOnly, SameSite=Strict cookie is combined with a cryptographically random
tab key held only in JavaScript memory and sent in a custom header. **Loopback
cookies are shared across ports**, so the cookie alone cannot authorize reads;
the extra key prevents another local service from using a cookie it received.
Requests require the exact Host and Origin plus custom read-only headers, use
same-origin cookies, reject redirects and have no cross-origin allowance.
This is HTTP on IPv4 loopback only, not remote authentication or protection
against malicious code already running as the same OS user. Windows still
requires the private runtime directory ACL described above.

Version-1 HTTP contract (all routes are POST, JSON, under `/api/local/`):

| Route | Request | Result |
| --- | --- | --- |
| `session` | `{}` | `pairing_required` or `paired`, public pending ID and remaining lifetime; HttpOnly cookie. No source read. |
| `disconnect` | `{}` | `disconnected`; local session revoked, cookie cleared. No source mutation. |
| `status` | `{}` | Authorized named-source receipt, `ready`, source verification/synchronization and separate cache freshness/counts. |
| `synapse` | `{"query":"synthetic term"}` | Existing `found`/`no_match` receipt, at most five cited matches with excerpts up to 240 Unicode code points. |

Requests accept no extra fields, source overrides, filesystem paths or command
inputs. Bodies are limited to 4 KiB, query strings to 1-512 characters, responses
to 256 KiB and one managed read may run at a time (otherwise HTTP 429). The
managed functions retain their existing bounded upstream command timeouts;
the browser stops waiting after 90 seconds. Browser cancellation does **not**
claim to cancel an already executing server-side read; a subsequent read may
remain busy until it finishes. There is no automatic retry or polling.

HTTP 401 means local pairing expired/missing, 403 denies a caller or source,
503 means not configured/upstream authority unavailable, and 502 means a failed
managed read. Unexpected fields or malformed bodies return 400. Raw private
diagnostic messages, paths, credentials, query strings and excerpts are omitted
from logs/error responses; failures never return cached authorized results.
The managed reader's unsynchronized/denied states remain denied, not healthy.
A stale derived cache is reported separately from an authorized synchronized
source; the existing query engine may use its verified JSON fallback.

Successful Recall preserves the engine's request ID, commit/policy/cache
receipt, record URL, entry/timestamp, JSON Pointer, hashes, overlay provenance
and supersession metadata. The UI renders excerpts as text, validates immutable
GitHub citations against the source snapshot and shows supersession rather than
treating old context as authority. Private examples/configuration are not part
of this public source tree. Offline tests mock only the managed source boundary,
exercise real local HTTP and CLI pairing, and require no private grant or data.

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

The lifecycle interface follows separately reviewed Simple-Todos conventions
at `4fec68ce252c711d99d6a0421c4c4fc337e86b95`:
`web-server.sh:11-27` (1.1.2) interpreter selection and strict override, and
`src/simple_todos/server_lifecycle.py:30-94` (1.0.0) start/stop/status, serialized
operations, private state/logs and readiness. The Cortex implementation is
independently written and reuses Brain Bridge's own path validation, locking and
atomic state helpers. Unlike the reference PID-signalling stop, Cortex asks its
authenticated server to shut itself down. No private runtime code, configuration,
data, fixed infrastructure endpoint or service dependency is copied.

## Remaining product gates

This foundation does not complete or approve the product taxonomy, journeys,
full standalone application/server or versioned API contracts. Those retain their
existing CORTEX2-5 and CORTEX8 ownership and acceptance boundaries. No proposed
navigation is presented as working. The owner-selected local read pilot defines
only the limited pairing/status/Recall contract above; it does not accept or
close CORTEX6-9 or BDT5/6/16/17/20 shared-service/authentication prerequisites.
Other authenticated integrations still require their applicable contracts.
The source preview's limited
loopback/port validation does not complete application configuration, base-path
routing, capability navigation, installation or release acceptance.
