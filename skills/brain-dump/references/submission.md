# Author and submit an immutable Brain Dump

Use this procedure for an owner-requested contribution or an existing project
rule authorizing automatic checkpoints. A consultation request does not authorize
a new record. Operational records belong in the explicitly registered private
data source, never in the public framework repository.

## Select the owner's publishing flow before authoring

Read the owner's project instructions and inspect its freshly committed writer
policy through its registered operator. Do not infer a publishing destination
from a repository title, a past record or `consult.json`. That profile supplies
consultation routing hints, not a writer binding or an access grant.

- **Legacy:** use that project's guarded legacy authoring/publishing recipe.
  Do not silently submit to the new data repository while its cutover is held.
- **Paused:** preserve the original external draft and any pending PR. Do not
  regenerate its identity or fall back to another writer.
- **Managed:** use the reviewed project operator when it owns submission and
  canonical promotion. Its managed flow must delegate authorization and record
  validation to this framework and verify canonical results before completion.

For a project using the registered Brain operator, inspect
`bot_github_brain_bridge.sh publisher-route --json`. Its managed recipe is
`create ENTRY --output DRAFT --execute --yes --json`, followed by
`dump --record DRAFT --execute --yes --json`. Resolve the operator from the
owner's project; this public skill does not discover or download a private one.
Never switch its route, install a profile or grant access merely to make a
submission succeed. Missing publishing policy/binding is a setup gap: request
the owner-selected identifiers or workflow, not credentials.

## Optional packaged operator

Version 0.8.2 also supplies `brain-bridge operator` for an owner-selected
managed integration. See [the operator guide](../../../docs/OPERATOR.md). It
uses the owner's own committed instance policy and can normally promote an
exact record PR only when that workflow is explicitly authorized. No private
project checkout is a public installation dependency. Keep ordinary `publish`
PR-only; installing this command does not itself authorize merging.

## Framework recipe for an explicitly selected managed workflow

Use these commands only when the owner's workflow explicitly selects the
framework's PR-only interface. The identity checkout, clean reader and source
alias must be supplied by that reviewed workflow. A project operator may run
these steps internally; do not bypass that operator's routing or promotion gate.
Values below are placeholders, not implicit source discovery.

```sh
brain-bridge status --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --source "$SOURCE" --cache-dir "$CACHE_DIR" --json
brain-bridge latest --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --source "$SOURCE" --json
brain-bridge synapse --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --source "$SOURCE" --cache-dir "$CACHE_DIR" --term "$BASELINE_ID" --backend json --json
```

Check the returned source alias, numeric repository identity, repository and
published commit against the selected workflow. Synchronize a stale reader
through the existing explicit managed-sync operation before proceeding. Author
a complete entry with a stable UUIDv4, offset-bearing timestamp, all required
collections and provenance. Set `BASELINE_ID` to the entry returned by `latest`,
and use its matching synapse citation to bind `context.coverage_since`:

- `entry_id` and `timestamp`: the cited entry ID and `record_timestamp`.
- `commit`: that receipt's **destination** `source.commit`.
- `ledger`: that receipt's `ledger_path`, replacing its leading `records/` with
  `Brain-Bridge/`. This is the v3 contract's logical path; the physical record
  remains in `records/` in the selected private data repository.

Never transplant an old source commit into a new entry's coverage anchor. An
empty source or absent exact baseline citation is a setup gap, not permission
to invent an anchor. Use the [synthetic v3 envelope](../../../schemas/record.v3.synthetic.json)
as a shape reference, replace its example identity, time, context and provenance
with evidence, and supply **only its `entry` object** as `ENTRY`. The framework
creates the envelope. Do not copy operational content into a public example.

`ENTRY` is the authored entry JSON. `DRAFT` is a new envelope path outside both
identity and reader checkouts. Creation preserves the authored identity and
time; it never rewrites a draft with different bytes.

```sh
brain-bridge create --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --source "$SOURCE" --entry "$ENTRY" --output "$DRAFT" --json
brain-bridge create --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --source "$SOURCE" --entry "$ENTRY" --output "$DRAFT" --execute --yes --json
brain-bridge publish --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --record "$DRAFT" --json
brain-bridge publish --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --record "$DRAFT" --push --yes --json
```

Before the push, verify the plan's `source`, `source_id`, `entry_id`, `path` and
`sha256` match the selected destination and original draft. Publication refreshes
independent read and write authorization; a successful read does not grant a
write. Plan mode makes no remote mutation. The public framework pushes only an
isolated immutable-record branch and proposes a PR; **it never merges or pushes
main**. Follow the owner's separately authorized normal review/promotion flow.
Do not issue raw Git pushes or bypass server merge policy to finish a dump.

## Completion, retries and source freshness

`status: pending_review`, a branch push or an open PR is still pending. Keep the
exact original draft/path/ID and receipt. After authorized canonical promotion,
synchronize through the same managed source and retry the same envelope:

```sh
brain-bridge managed-sync --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --cache-dir "$CACHE_DIR" --json
brain-bridge publish --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --record "$DRAFT" --push --yes --json
brain-bridge export --identity-repo "$IDENTITY_REPO" --repo "$READER_REPO" --source "$SOURCE" --json
```

Completion requires `published: true`, `canonical_verified: true`, unchanged
original ID/path/hash, and exactly one original entry ID in export at that same
verified canonical commit. Inspect the canonical citation/bytes when reporting
the record. A failed, denied, paused or changed-route operation stays pending;
never invent publication or silently choose another source. Clean up only an
owned identical loose draft after canonical verification and the applicable
owner cleanup rule. Preserve externally authored drafts unless their owner
authorized cleanup.

Use `--pretty` instead of `--json` for indented versions of the same receipts.
New authoring, publication, review and consultation remain distinct operations;
none authorizes trust enrollment, TODO changes, deployment or producer cutover.


## Mandatory Brain Dump after every implementation commit

For owner-authorized work in a repository, every source, documentation, skill, configuration, generated-view or tracker-data commit must trigger a Brain Dump. Do not wait for a reminder or treat a local commit, branch push or merge as the end of the workflow. Record each exact repository/branch/commit, purpose, changed behavior, validation, push/merge state, important context, failures and next steps through the selected guarded Brain flow. Never include secrets or private internal reasoning. A normal main merge is also a checkpoint event; a submission may cover a bounded commit/merge batch only if it explicitly accounts for every commit and no completed handoff omits an unpublished implementation commit.

Publication must be verified canonically before calling the checkpoint flushed. If a real queue, paused route, authorization failure or external error prevents submission, preserve one stable external original, identify the uncovered commits and report its exact ID/path/hash and blocker. Resume the same original through the approved flow when allowed; never silently skip, rewrite its identity or fall back to a retired writer. This authorizes the checkpoint flow only where the owner already authorized it; it grants no new destination, credential, grant, route, runtime or unrelated action permission.

**No recursive checkpoint loop:** a commit/PR containing only the Brain Dump record, its publication manifest/receipt or mechanical checkpoint metadata completes that dump and does not trigger another dump. A read-only recheck or acknowledgment of an unchanged published checkpoint is also not a new commit event. If substantive implementation is mixed into that commit, it still requires coverage. Do not create task edits merely to announce a dump or create another dump merely to announce its publication.
