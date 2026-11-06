# Historical reconciliation foundation

`reconcile` observes a selected published source and canonical destination. It
compares complete paths, raw hashes, Git modes, entry IDs and provenance overlays.
Destination-native records remain intact. It never copies records, creates an
authorization, opens/merges a PR, changes grants, installs a runtime or scheduler,
or switches production. Existing [`import-plan`](HISTORICAL-IMPORTS.md) produces
proposed batch metadata only; approval and transplantation stay separate.

## One-shot observation is the default

```sh
brain-bridge reconcile --source-repo /private/source \
  --destination-repo /private/destination \
  --source-id SOURCE_REPOSITORY_ID --destination-id DESTINATION_REPOSITORY_ID \
  --source-ref main --destination-ref main --namespace Brain-Bridge --pretty
```

Like the authenticated migration planner, this uses the explicitly selected
repository IDs, current published commits, existing operator permissions,
private destination and observable audience checks. It never treats a saved
allow as current authorization. Upstream snapshots and audiences are rechecked
before returning or checkpointing a cycle. Source/destination drift withholds
that cycle's result. Unknown permissions or audience expansion fail closed.

By default, prepare clean synchronized readers and locally available published
Git objects through their existing owners; observation alone does not fetch.
Only published canonical source commits are captured, never uncommitted drafts
or pending-review branches. Explicit reader refresh below closes the gap when
new published commits are not yet available locally. There is no loose-record
fallback, reset or rebase.
This release requires both refs to be `main`; selecting a review branch cannot
turn its complete payload into a canonical watermark. Timestamp ordering is not
a filter: a backdated entry published later is still captured by its ID/hash.

The result separates:

- `observed`: the current complete source inventory counts and source commit.
- `pending`/`outbox`: missing canonical files, including IDs/hashes and provenance.
- `verified_watermark`: the latest captured source snapshot whose entire record
  and overlay set is present at the canonical destination with exact identity.
- `destination_only`: preserved native destination counts.
- `proposal`: a fresh proposed import manifest against the observed destination
  base, when work remains. A destination append regenerates the plan.
- `lag_seconds`: age since the earliest still-pending captured observation, not a
  promise that every source event has been observed since repository creation.

A pending PR or successful push receipt cannot acknowledge an observation.
If source snapshotA is pending and snapshotB arrives, both captures survive.
When all ofA becomes canonical butB is still pending, the watermark can advance
toA without forgettingB. A record is not acknowledged until its required
provenance overlay is canonical too.

## Explicit private checkpoint persistence

Without execution, the observer creates no state. Optional bounded polling keeps
observations in memory; crash/restart continuity needs explicitly persisted state:

```sh
brain-bridge reconcile --source-repo /private/source \
  --destination-repo /private/destination \
  --source-id SOURCE_REPOSITORY_ID --destination-id DESTINATION_REPOSITORY_ID \
  --state-dir /external/private/reconciliation --execute --yes --pretty
```

These flags authorize only private metadata checkpointing. The directory must
be outside source, destination and every other Git checkout, including identity
checkouts, and contain no symlinks. POSIX ownership and0700/0600 modes are
verified; Windows deployments must provision an owner-private parent ACL through
the platform's installer. No record bodies or prose are stored. The checkpoint
contains immutable inventory hashes/IDs/modes, first-seen capture sequences,
pending paths and the separately verified watermark.

One shared advisory lock covers checkpoint read, comparison and atomic write per
cycle. Another worker using that state is refused; no stale lock bypass is
provided. The lock is released before output or waiting, including when polling.
Writes use a private temporary file, fsync and atomic replacement; a crash before
replacement retains the prior checkpoint. Restart rechecks every canonical fact
before acknowledging any pending observation. Corrupt or source-mismatched state
is rejected rather than silently reset.

Both source and destination inventories are append-only once observed. The
canonical first-parent chain is audited across polling gaps, so a rewrite or
deletion followed by restoration cannot hide an intervening violation. Changed
ancestry, bytes, IDs, modes, deleted provenance or destination-native history
fail closed. This is not an automatic forensic recovery tool.

Storage is bounded to20000 inventory files,1024 unacknowledged source captures
and8MiB per checkpoint. Already verified older captures may be compacted; the
complete observed inventory and still-pending captures are retained. Reaching a
bound requires draining or reviewing the worker, never silently dropping entries.

## Explicit refresh of dedicated readers

For continuous use, explicitly designate two existing dedicated, standalone,
clean `main` readers and enable refresh:

```sh
brain-bridge reconcile --source-repo /private/source-reader \
  --destination-repo /private/destination-reader \
  --source-id SOURCE_REPOSITORY_ID --destination-id DESTINATION_REPOSITORY_ID \
  --state-dir /external/private/reconciliation --refresh --execute --yes \
  --cycles 10 --interval 60 --json
```

`--refresh` requires all three checkpoint execution arguments. It is not enabled
by a default plan. Both readers must already exist: no clone, linked worktree,
branch switch or source-location discovery is performed. Do not designate active
authoring checkouts as these readers. Both are preflighted before either can
fast-forward; dirty, detached, divergent or mismatched-origin readers are refused.

The cycle first authenticates repository IDs, GitHub origins, permissions,
published `main` SHAs and audiences without assuming the new objects are local.
Inside the shared cycle lock, the existing sync owner fetches and checks the
exact authenticated target, validates complete immutable history/pins/provenance
for `Brain-Bridge` or `records`, and rechecks targets/audiences before each FF.
Observed history rewrites/deletes are rejected before FF. Both published targets
are rechecked afterward and before the checkpoint can change. There is no SQLite
rebuild or remote record, branch, PR or authorization write.

If a target drifts, the cycle reports failure with the checkpoint/watermark
unchanged. A reader already fast-forwarded to a separately verified target can
remain there; the worker never resets it to simulate atomic rollback. Retry
against fresh authenticated targets. A valid later destination-native append is
preserved and produces a new proposal rather than losing the pending outbox.
The receipt reports `readers_refreshed` and both verified local reader commits.

## Bounded foreground polling and JSONL

```sh
brain-bridge reconcile --source-repo /private/source \
  --destination-repo /private/destination \
  --source-id SOURCE_REPOSITORY_ID --destination-id DESTINATION_REPOSITORY_ID \
  --state-dir /external/private/reconciliation --execute --yes \
  --cycles 10 --interval 60 --json
```

The default is one cycle. More than one cycle explicitly emits JSONL: one compact
versioned receipt per completed cycle, flushed immediately. `--pretty` is only
supported for one-shot JSON. Polling is bounded to1–1000 cycles; the default
interval is60seconds because authenticated full planning is expensive. The lock
is not held during the interval. Tests inject waiting instead of sleeping.

A failed cycle ends the bounded run with a nonzero exit and an error JSON line;
prior successful receipts/checkpoints remain point-in-time evidence. A separate
reviewed controller may restart observation. No background service, automatic
retry policy, launch agent or scheduled task is installed by this foundation.
