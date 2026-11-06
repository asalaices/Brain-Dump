# Reviewed historical catch-up

`import-plan` proposes an exact, bounded historical batch. It does not copy data,
write an authorization, enroll a grant, push a branch, install anything or switch
production. The existing `migrate-plan`/`migrate-apply` rehearsal remains separate.
A plan token proves content integrity; only separate destination review makes its
manifest available as a BASE authorization for a later payload PR.

## Narrow historical read pins

The committed `.brain-bridge/history-compatibility.json` supports two independent
kinds, each bound to one logical `Brain-Bridge/...json` path and exact raw SHA256:

- `legacy_github_issue_shape`: adapt numeric GitHub issue numbers and missing
  relationships in a validation-only deep copy.
- `legacy_analysis_object`: wrap an existing schema3 analysis object as an array
  in a validation-only deep copy.

Returned history and stored bytes remain unchanged. Neither kind enables the
other adaptation. Missing, mismatched, duplicate or unknown pins fail closed.
New `create`, `publish` and ordinary destination additions still use strict v3;
a candidate-added pin does not excuse an invalid new record.

## Stage 1: authenticated proposal and separate review

Use explicitly selected repositories and their verified numeric IDs:

```sh
brain-bridge import-plan --source-repo /private/source \
  --destination-repo /private/destination \
  --source-id SOURCE_REPOSITORY_ID --destination-id DESTINATION_REPOSITORY_ID \
  --source-ref main --destination-ref main --namespace Brain-Bridge --pretty
```

This reuses authenticated migration identity, published snapshot, permission,
private-destination and audience checks. It validates immutable history and
provenance, refuses destination byte/ID collisions and audience expansion, and
rechecks source/destination snapshots and observable audiences before returning.
The destination must already have its reviewed `.brain-bridge/identity.json`.
No credential value is accepted or returned. Application grants are still a
separate owner-review concern, not an inferred approval.

The receipt contains `manifest_path` and the proposed `manifest` object. Only
that object belongs at the exact `.brain-bridge/imports/<manifest_token>.json`
path in a separately reviewed destination authorization PR. The token is SHA256
of the canonical manifest body excluding the token itself. The manifest binds:

- Source/destination repository names, numeric IDs, refs and full snapshot SHAs.
- Every new source/target path, raw SHA256, byte count, Git mode, schema version,
  ordered entry IDs and timestamps; provenance declarations identify their target.
- Exact required historical pins and point-in-time observable audience evidence.

Any necessary compatibility descriptor changes are reviewed before payloads.
Stage 1 may change only authorization controls and exact history pins, not trust
or workflow settings, and must not contain the payload. Neither a loose file nor a manifest first
introduced alongside payload additions can authorize that candidate.

This release targets destination `main`, at most1000 files and128MiB per batch.
Reviewed authorization bytes/modes are immutable and cannot be deleted; expired
ledger snapshots do not authorize a new batch. Source history is a point-in-time snapshot; a later source record needs its own
catch-up plan. The plan does not claim continuous ingestion.

## Stage 2: exact offline payload verification

After the authorization is reviewed into destination BASE, an independently
authorized operator may prepare the exact private payload PR. Destination CI
runs the existing `validate-source` command with immutable BASE/HEAD refs. It
reads reviewed authorization and identity only from BASE, and requires:

1. The complete exact approved additions, without partial batches or extra files.
2. The BASE destination identity/origin match, ancestor-bound preauthorization
   commit, and unchanged records/metadata snapshot since that planned base.
3. Exact path/hash/size/mode/schema/entry identities for every file; all existing
   ledger modes and Git objects remain unchanged.
4. A payload-only diff: no trust, workflow, authorization, pin or unrelated edits.
5. Whole-history validation, unique entry IDs, and hash-bound valid provenance
   overlays. Necessary compatibility pins already exist in BASE.

Only this exact batch may use historical v1/v2/v3 validation and retain its
original source coverage anchors without a destination-ancestor check. Other
new additions remain strict v3 with a published destination baseline. Reuse of
an authorization cannot replace history or authorize another path.

CI needs no cross-repository secret or access to the private source. Its receipt
truthfully reports verification against reviewed manifest bytes. Authentication
of the source-to-manifest relationship happened in the operator planner before
review; CI does not claim to have repeated live source/audience authorization.
If the destination ledger advances after planning, make and review a fresh
manifest. Do not overwrite the original batch or loosen validation to proceed.

Publication acceptance still requires separately authorized integration,
independent canonical byte/ID verification and cited reader/cache checks. An
import authorization does not change reader/writer grants or production routing.
