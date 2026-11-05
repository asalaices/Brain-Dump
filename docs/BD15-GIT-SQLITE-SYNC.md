# Guarded Git-to-SQLite synchronization

Git JSON is canonical; SQLite is an external derived cache. Use [managed source operations](MANAGED-SOURCES.md) when identity/policy enforcement is required. Generic local utilities do not enforce managed grants.

```sh
python3 -m brain_bridge sync --repo /authorized/checkout --remote git@github.com:example/synthetic-data.git --branch main --records records --db /external/cache/index.sqlite --contract history --pretty
```

Sync requires an existing clean standalone checkout, exact expected origin, checked-out branch and fast-forward ancestry. Resolved SQLite paths must be outside the checkout, including filesystem aliases. With a contract selected, fetched records are validated before the reader advances. `--contract v3` requires current envelopes; `--contract history` additionally reads frozen v1/v2 without rewriting them.

Indexing validates the whole batch first and transactionally changes only changed/deleted records. Index metadata binds the resolved source root. JSON duplicate keys and non-finite numbers are rejected. Missing/stale caches fall back only in auto mode; explicit SQLite mode fails. These utilities do not activate a background scheduler, production credentials, shared database, server-side ACLs or publication.
