# Managed authoring and history adapters

These commands operate on one explicitly named authorized source. They do not
change installed skills, grants, historical records or production routing.
Every command accepts `--json` (the default) and `--pretty` for the same document.

```sh
brain-bridge export --identity-repo /private/instance --repo /private/reader --source primary --pretty
brain-bridge latest --identity-repo /private/instance --repo /private/reader --source primary --pretty
brain-bridge status --identity-repo /private/instance --repo /private/reader --source primary --cache-dir /private/cache --pretty
brain-bridge create --identity-repo /private/instance --repo /private/reader --source primary --entry /private/authored-entry.json --output /private/draft-envelope.json --pretty
```

Paths and `primary` above are placeholders; use the registered name. A mismatch
fails closed. Reads require current upstream read authorization, a clean reader
at that exact commit, whole-history validation, and unchanged authorization
before returning. They read immutable Git objects, never loose draft files.
They do not pull implicitly; use `managed-sync` for an explicit safe fast-forward.

## Effective export, latest and status

`export` returns a versioned object with `entries`, `count`, `records`, `overlays`,
`source`, `read_only` and the common `info` metadata. Entries retain their fields
and historical prose types. Validated hash-bound provenance overlays appear only
in the exported view when native provenance is absent; original blobs stay exact.
Entries sort by UTC instant, then entry ID, including repeated DST local times.
`latest` returns that same last effective entry as `entry`, or null for an empty
committed corpus, with the total `count` and source receipt. An empty source still
requires a committed records directory and valid policy; missing data is not
silently treated as empty.

`status` reports authorized source identity/commit/branch, counts,
`source_verified`, `synchronized`, `cache_fresh`, `indexed_commit` and `indexed_at`.
The source is synchronized only after verifying reader HEAD against refreshed
upstream. Cache freshness describes the derived inventory binding, not permission
or proof of a recent pull. An unchanged content cache can be fresh with an older
indexing commit. Actual SQLite queries independently compare returned text against
canonical JSON. Status creates no cache and serves no stale records on denial.

## Draft creation and stable retry

Supply a complete authored entry (the object inside an envelope), including a
canonical UUIDv4 `id` and offset-bearing `timestamp`. Creation never generates or
changes these fields. This intentional requirement prevents new identities on
retry. New entries must satisfy the existing strict v3 contract; the Chicago date
and dated destination path derive from the authored timestamp. No thought content
is invented by the adapter. Duplicate fields, nonfinite numbers and potential
credential markers are rejected.

The entry's `context.coverage_since` must identify an existing record in this
**destination** history: ID, timestamp, logical `Brain-Bridge/...` path and a full
ancestor commit containing it. A plausible source-code SHA or merely replacing an
old SHA is insufficient. Exact historical compatibility pins may validate that
baseline; they never relax validation of the newly authored entry.

The default plans without writing. Add `--execute --yes` to write a private draft
with mode0600 using an exclusive, atomic operation. Its parent directory must
already exist; output must be outside both identity and source checkouts, without
symlink components. The receipt identifies the stable ID, exact SHA256, destination
path and authorized source commit. An identical retry returns `existing`; different
bytes, a conflicting canonical ID or unsafe output fail without overwrite. Keep
the original authored entry and draft unchanged even if upstream advances.

Creation requires independent read and write grants plus actual GitHub permissions;
it does not publish. Pass the resulting envelope to existing `publish` (plan by
default, `--push --yes` for a review branch). Pending review is not canonical
publication. After separately authorized integration and managed synchronization,
retry `publish` with the same draft to verify `published` and `canonical_verified`.
If that ID is already canonical, retry publication rather than creating a new ID.
No automatic merge, cutover, catch-up import or installer action is included.
