# Packaged integration operator

Version **0.8.2** includes `brain_bridge/operator/` in the normal framework
distribution. Its command is `brain-bridge operator`. No private project checkout,
private helper import or owner-specific path is required to install this code.
Tests use synthetic independent Git roots and mocked provider operations.

The existing `brain-bridge publish` command remains **PR-only**. The separate
operator is an explicit opt-in workflow for an installation whose owner has
selected normal exact-head promotion. It never grants access, changes routes,
installs services, force-pushes or bypasses repository merge policy. Installing
the package does not authorize a merge.

## Select your own instance

Use an owner-controlled integration Git checkout with a verified origin and
reviewed committed configuration on `origin/main`. This can be the private
instance/data repository itself; there is no requirement for a repository
called master-01 or an additional repository just for the wrapper. Identity,
source registration, independent reader/writer grants and real GitHub access
remain prerequisites; see [managed sources](MANAGED-SOURCES.md).

Committed `.brain-bridge/publisher-route.json`:

```json
{"schema_version":2,"mode":"managed","reader":"managed","generation":1}
```

This is an illustrative new installation policy, **not** instructions to reset
an existing installation's generation. Existing transitions require their
reviewed pause/generation workflow. Missing policy fails closed; the packaged
operator has no implicit legacy fallback.

Committed `.brain-bridge/managed-runtime.json` uses the following shape. Replace
all illustrative absolute paths and source alias with your reviewed installation
values; do not copy another person's paths or credentials.

```json
{
  "schema_version": 1,
  "cli": "/absolute/installed/environment/bin/brain-bridge",
  "identity_repo": "/absolute/private/instance",
  "source_repo": "/absolute/private/reader",
  "source": "selected-source",
  "cache_dir": "/absolute/private/cache",
  "minimum_version": "0.8.2"
}
```

Profile hints do not establish authorization. The installed named-source
framework independently refreshes registration, numeric source identity and
grants. Version family compatibility is explicit; an arbitrary newer binary is
not presumed compatible. Policy/profile reads use committed regular Git blobs,
not loose working files.

## Commands

Inspect selected routing and profile:

```sh
brain-bridge operator --project-repo /absolute/private/instance publisher-route --pretty
brain-bridge operator --project-repo /absolute/private/instance profile --pretty
brain-bridge operator --project-repo /absolute/private/instance status --pretty
```

Consult using the existing cited `synapse` command and author a complete entry
with its actual destination coverage anchor. Then plan creation, explicitly
create one external immutable envelope, and plan promotion:

```sh
brain-bridge operator --project-repo /absolute/private/instance create \
  --entry /absolute/private/entry.json --output /absolute/private/envelope.json --pretty
brain-bridge operator --project-repo /absolute/private/instance create \
  --entry /absolute/private/entry.json --output /absolute/private/envelope.json --execute --yes --pretty
brain-bridge operator --project-repo /absolute/private/instance dump \
  --record /absolute/private/envelope.json --pretty
```

Only when the owner authorizes this normal promotion workflow:

```sh
brain-bridge operator --project-repo /absolute/private/instance dump \
  --record /absolute/private/envelope.json --execute --yes --pretty
```

The operator plans against the exact original ID/path/hash, synchronizes the
authorized reader, proposes the framework's record PR, checks its exact head,
branch, base and one added record, refreshes committed route/profile immediately
before normal merge, then synchronizes/retries the unchanged envelope and checks
canonical unique-ID count at that same commit. Server refusal stops the merge.
No `--admin`, protection bypass or direct main push is used.

Version 0.8.3 additionally supports paired `--expected-generation` and
`--expected-policy-commit` on `operator ... dump`. A compatibility bridge can
bind its caller-selected snapshot before delegation; a changed generation or
profile is rejected before planning or promotion. The policy commit may advance
through unrelated changes only when its bound profile and generation agree.

A paused writer returns a nonzero pending receipt and retains the original,
without consulting the runtime for a dump. Changed routes/profiles, denied
access or failed canonical verification withhold completion. Retry the same
original after reconciliation; never regenerate its ID to escape a failure.

Other operations are `latest`, `export`, `validate`, explicit plan/execute `pull`
and `check-record`. JSON is default; `--json` and `--pretty` select equivalent
documents. `profile` reports routing settings, not a successful source grant.
Read-only operations reject execution flags. This package deliberately does not
implement legacy authoring, retirement, backup custody or route-edit proposals;
those belong to the owning installation's administration/history policy.

## Portability limit and migration

The current v3 record profile still requires America/Chicago and publishing
agents `copilot` or `chatgpt`. Packaging the operator does not silently relax
that format. Configurable reviewed record profiles are separate BDT follow-up
work; unsupported identities must not be mislabeled to pass validation.

An existing installation should first build/test the package, upgrade through
its registered runtime owner with rollback, and only then replace its old
managed implementation with a thin command adapter. Preserve pending originals,
instance policy, source identity/grants and cache. Historical validators and
private retirement manifests are not product dependencies and should not be
copied into public examples.
