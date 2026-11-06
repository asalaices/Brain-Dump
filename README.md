# Brain-Dump

Portable Git-backed Brain Bridge framework for Claude, Copilot and ChatGPT.

**Development foundation, not an enterprise-ready release.** Public source includes only synthetic examples and schema stubs; real Brain Dump data remains in separately permissioned private repositories such as `asalaices/Brain-Dump-Synapses`.

Track implementation in [BD program #272](https://github.com/asalaices/master-01/issues/272) and [BD15 #276](https://github.com/asalaices/master-01/issues/276).

Software is licensed under **AGPL-3.0-only**. Copyright (C) 2026 **Creative Software Development**. Preserve the applicable original-author, copyright and license notices; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Private operational records and credentials are separate from the software license.

## Current implementation

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


[Observability documentation](docs/OBSERVABILITY.md) covers named read-only CI
adapters and deterministic JSON/DOT/Mermaid evidence graphs. The managed-source
reference also documents plan-by-default append-only record PRs. No live provider
or production source is activated by installing the package. The public runtime
uses the Python standard library, declared Windows timezone data and existing external credential transports.

[Migration rehearsal](docs/MIGRATION.md) prepares reviewed byte-identical additions into a private destination. It does not activate grants, migrate credentials or switch production routing.

[Cited synapse consultation](docs/SYNAPSE-CONSULT.md) provides `brain-bridge synapse` for an explicitly registered source, with request IDs, immutable record/entry/pointer citations, bounded excerpts and truthful found/no-match/denied/unavailable/error outcomes. The [shared skill](skills/brain-bridge/SKILL.md) and agent discovery pointers use this authorized interface; `brain-bridge skill --json` locates the bundled artifact without installing it globally. Historical records must be separately reviewed upstream before normal clients can consult them.

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
