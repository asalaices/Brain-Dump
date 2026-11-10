# Brain-Dump

Portable Git-backed Brain Bridge framework for Claude, Copilot and ChatGPT.

Contributors and agents start with the [portable repository contract](docs/CONTRIBUTING.md).
It requires neither personal HOME instructions nor a private infrastructure checkout.

**Development foundation, not an enterprise-ready release.** Public source includes only synthetic examples and schema stubs; real Brain Dump data remains in separately permissioned private repositories such as `asalaices/Brain-Dump-Synapses`.

Track implementation in [BD program #272](https://github.com/asalaices/master-01/issues/272) and [BD15 #276](https://github.com/asalaices/master-01/issues/276).

Software is licensed under **AGPL-3.0-only**. Copyright (C) 2026 **Creative Software Development**. Preserve the applicable original-author, copyright and license notices; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Private operational records and credentials are separate from the software license.

## Vision: Brain Evolution

[Brain Evolution](Brain-Evolution.md) documents our hybrid neural vocabulary, the proposed Cortex / Brain-Cotletex experience, Brain Gate operations, deep metadata provenance, repository swim lanes, and a long-term opt-in inter-group Synapses collaboration roadmap. It is a living vision, not a claim that the planned UI or federation is shipped.

## Production delivery roadmap

The [BDT roadmap](docs/roadmap/README.md) covers direct Git bots, continuous local
cache sync, shared query service, local/remote MCP, end-to-end bootstrap (binaries,
services, optional tunnels and client settings), web UI and production acceptance.
These are planned deliverables; current capabilities are described below.

## Packaged integration operator

Version 0.8.2 packages optional managed promotion under `brain_bridge/operator/`.
Start with [standalone installation](docs/INSTALLATION.md) for the public runtime and Git-owned skill discovery.

The [operator guide](docs/OPERATOR.md) explains standalone installation, committed
instance policy and explicit normal PR promotion. Ordinary `publish` remains
PR-only; no private master-01 checkout is required for the packaged operator.

## Current implementation

An initial [Cortex web foundation](docs/CORTEX-WEB.md) provides a common `web/`
structure, six shared themes and reusable request-driven API activity components.
An optional trusted-launch local pilot connects source status and bounded cited
Recall to the existing authorized Brain Bridge functions. It is not a shared
service, new source grant or complete Cortex application.

From a source checkout, `./cortex_server --start`, `--status` and `--stop`
manage a loopback-only static preview with verified ownership and readiness.
Python 3.11+ is required; Windows uses `python cortex_server`.
See [Cortex setup and lifecycle](docs/CORTEX-WEB.md#run-and-test) for configuration
and limits, including explicit external-profile selection. Open the Cortex URL
and click **Connect to Brain**; approve the private page opened by the existing
native browser launcher, and Cortex connects automatically in a trusted tab.
Routine use requires no terminal or pairing command; `--open` is an optional
operator shortcut.
This does not install a service or complete the planned product API.

The full enterprise roadmap remains the target; this is a development foundation.
[Managed source documentation](docs/MANAGED-SOURCES.md) describes the implemented
identity, separate default-deny grants, authenticated policy refresh, source-ID
binding, immutable Git reads, incremental external caches and guarded sync.
No real grant is installed by these changes. Generic local utilities are separate
from managed access. GitHub permissions remain the hard repository boundary.

Use `python3 -m brain_bridge --help` or `--license`; all results carry an `info.script_version`
field. `--json` is the default and `--pretty` changes only whitespace. Tests run
with `python3 -B -m unittest discover -s tests -v` and require no credentials.
Current new records use schema v3; explicit history reads preserve v1/v2 bytes.

The [tests and GitHub Actions audit](docs/TEST-COVERAGE-AUDIT.md) preserves the
2026-11-08 coverage matrix, observed CI results, limitations and prioritized gaps.
It is a historical audit, not a claim that the recommendations are implemented.

[Observability documentation](docs/OBSERVABILITY.md) covers named read-only CI
adapters and deterministic JSON/DOT/Mermaid evidence graphs. The managed-source
reference also documents plan-by-default append-only record PRs. No live provider
or production source is activated by installing the package. The public runtime
uses the Python standard library, declared Windows timezone data and existing external credential transports.

[Migration rehearsal](docs/MIGRATION.md) prepares reviewed byte-identical additions into a private destination. It does not activate grants, migrate credentials or switch production routing.

[Cited synapse consultation](docs/SYNAPSE-CONSULT.md) provides `brain-bridge synapse` for an explicitly registered source, with request IDs, immutable record/entry/pointer citations, bounded excerpts and truthful found/no-match/denied/unavailable/error outcomes. The [shared skill](skills/brain-dump/SKILL.md) and agent discovery pointers use this authorized interface; `brain-bridge skill --json` locates the bundled artifact without installing it globally. Historical records must be separately reviewed upstream before normal clients can consult them.

### Rollback evidence and immutable history

`brain-bridge rollback-audit` accepts explicit `--source-repo`,
`--destination-repo`, `--source-id`, `--destination-id`, `--source-ref`, and
`--destination-ref`. It authenticates the published repository identities,
permissions and audiences, compares legacy `Brain-Bridge/` with destination
`records/` and provenance metadata, then rechecks those observations. Its JSON
report identifies destination-only IDs, divergent content and metadata changes.
It never changes routing, grants, files, branches or production state; even
identical snapshots require writer quiescence, routing review and operator
acceptance. Keep operational reports within the repositories' authorized audience.

Managed historical reads can use a separately reviewed, committed
`.brain-bridge/history-compatibility.json` descriptor. Schema version 1 contains
`records`, each with a logical dated `Brain-Bridge/...json` path, exact raw
`sha256`, and kind `legacy_github_issue_shape`. This narrowly permits positive
numeric GitHub issue numbers and missing relationship fields during validation
of those exact historical bytes. Returned records retain their original fields;
new publication remains strict. Loose configuration files, mismatched hashes,
symlinks, duplicate keys and unknown descriptor fields are rejected or ignored
as appropriate to committed snapshot reads. Migration does not automatically
copy this policy: destination compatibility requires its own review before
historical data is accepted. Local loose-file index utilities remain strict.

### Everyday managed commands

Version 0.6 adds named-source `create`, `latest`, `export` and `status` adapters.
They preserve the private-source authorization boundary and never switch
production routing. `create` plans an external draft from a complete authored
entry; `--execute --yes` writes it without overwriting another file. Publishing
that draft remains a separate PR-only command. See
[managed adapter contracts](docs/MANAGED-ADAPTERS.md) for exact outputs and retries.

### Publication receipts

`publish` plans by default. `publish --push --yes` (also spelled
`--execute --yes`) pushes one immutable record branch and proposes a PR after
independent grants, remote SHA and raw-byte verification. It never merges.
A `pending_review` receipt has `published: false`, `canonical_verified: false`,
and `remote_verified: true`: verified branch bytes are still awaiting review.
After separately authorized integration and managed synchronization, retrying
the same record returns `published: true` and `canonical_verified: true` only
when its exact path and hash exist at the authenticated canonical commit.
The receipt includes entry ID and source identity. It does not infer a specific
PR merge from canonical bytes. Keep the original record and ID for every retry.
Live writer acceptance requires its own reviewed grant; a reader grant alone
is insufficient.

### Destination CI

`brain-bridge validate-source --repo CHECKOUT --base-ref REVIEWED_BASE_SHA`
checks committed Git objects only. Existing files in `records/` and `metadata/`
keep their exact paths, modes and bytes; new records require strict v3, unique
IDs, a published ancestor coverage anchor, and credential-marker screening.
Whole-history validation binds provenance overlays and explicit historical
compatibility pins. A pin cannot exempt a newly added record from strict v3.
This is a local CI utility, not managed access authorization. It never writes
files, grants access, pushes or merges. Initial historical imports and catch-up
migrations need their own separately reviewed acceptance process.

### Reviewed historical catch-up

The read-only [`import-plan` workflow](docs/HISTORICAL-IMPORTS.md) proposes an
authenticated exact-byte historical batch for separate destination review.
`validate-source` accepts only the complete batch authorized in immutable BASE;
normal new writes remain strict. Planning does not copy, grant, push or cut over.

### Continuous catch-up observation

The [`reconcile` foundation](docs/RECONCILIATION.md) keeps observed/pending
captures separate from canonically verified watermarks. One-shot planning is
read-only by default; bounded JSONL polling and explicitly confirmed external
metadata checkpoints support restart continuity. Optional confirmed `--refresh`
fetches and validates only the two selected clean readers without remote-record writes.
The worker never copies records,
authorizing imports, changing grants or installing a service.
