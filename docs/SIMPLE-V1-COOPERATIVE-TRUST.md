# Simple V1: GitHub-native cooperative trust

Status: implementation plan, not an enforced authorization feature. Related: [public starter TODO #5](https://github.com/asalaices/Brain-Dump/issues/5).

## Reviewed foundation

Brain-Dump main at f07fa8aa0eba18fbd974bbd3c2f0c88f50266f03 has Python CLI dispatch in brain_bridge/__main__.py, local JSON/SQLite access in store.py, guarded fetch/fast-forward in sync.py, contract validation in contract.py, and local tests. It has no persistent instance identity, reader/writer policy evaluator, or publisher. PR #4 adds v3 validation before indexing/sync and must be reconciled before touching those paths.

The separately permissioned Synapses repository has starter documentation, synthetic examples and schema stubs; its reviewed tree has no identity/trust manifest or canonical records directory. Do not infer production readiness from that scaffold. No private content belongs in this public repository.

## Trust boundary

GitHub credentials and repository/team permissions enforce actual repository access. A UUID plus GitHub numeric repository ID identifies a cooperative Brain-Dump instance; neither is a secret or proof of control. Git itself has no built-in repository ID: use GitHub's repository ID, obtained through the authenticated GitHub API. No signing keys, gateway, new service or Actions dependency.

A developer with GitHub read permission can clone directly regardless of these manifests. Team isolation therefore depends on GitHub permissions. These checks govern Brain Bridge behavior only, including local cache access.

## Proposed files and contract

Keep identity, policy and records separate. Proposed paths (not yet consumed by the CLI):

- Brain-Dump: .brain-bridge/identity.json.
- Each Synapses repository: .brain-bridge/trust.json.
- Canonical data: records/; derived SQLite stays outside the checkout. Never index the repository root, identity or trust files as records.

Identity example below is synthetic and must never be installed as a shared default:

```json
{
  "schema_version": 1,
  "instance_uuid": "11111111-1111-4111-8111-111111111111",
  "github_repository_id": "123456789"
}
```

Persist a generated UUID v4 through an explicit initialization PR. Read the numeric repository ID from the authenticated API for the explicitly selected Brain-Dump origin; store as a canonical positive decimal string. Canonical policy key is lowercase UUID + "-" + repository ID. Compare the structured fields/derived key exactly; do not split a UUID-containing key on every hyphen. Owner/name/URL may aid display, but are not the identity.

Existing clones of the same registered repository share its identity. A fork has a different repository ID and must explicitly generate a fresh UUID and request registration. Never silently regenerate identity, accept a copied fork identity, or trust an ID supplied only on the command line. Verify the selected origin's current API ID against the persisted identity; fail closed on mismatch or unverifiable identity. Renames retain the ID; a new repository at the old name does not.

Proposed Synapses policy shape:

```json
{
  "schema_version": 1,
  "default_policy": "deny",
  "reader_allow": [],
  "writer_allow": []
}
```

Separate reader_allow and writer_allow lists carry exact canonical identity keys. Reading requires membership in reader_allow; writing requires membership in writer_allow. Neither implies the other. Operations that read and write require both. No wildcards, implicit owner/admin grants, inherited template grants or permissive legacy fallback. Missing/malformed files, unsupported versions, malformed keys, duplicate JSON keys and unknown policy fields deny access. Empty lists deny everyone. Maintainers approve identity registration and policy changes through reviewed PRs.

## Implementation sequence and acceptance gates

1. Add identity parsing/validation and explicit initialization in a small Brain-Dump PR. Use the existing GitHub login, verify the named origin/repository ID, preserve identity on repeat initialization, and fail on mismatches. Do not log credentials or add a credential store.
2. Add strict policy parsing and separate read/write evaluation as pure functions with synthetic fixtures. Tests must cover reader-only, writer-only, both, neither, malformed/missing policy, unsupported version, fork-ID mismatch and invalid identity.
3. Integrate checks into managed Synapses search, index and sync before reading records or SQLite, producing results, fetching records or changing the checkout/cache. Fetch the policy at an explicit trusted upstream ref through existing GitHub authentication; do not authorize from a caller-edited working tree or proposed PR policy. Re-check policy at the target commit after fetch and before merge/index, and deny if the trusted policy cannot be refreshed. Policy discovery necessarily reads policy metadata before record authorization. Specify commit binding and revocation behavior in the integration PR.
4. Scope each cache to source repository ID plus identity and policy revision. Reauthorize every managed read; a stale cache must not bypass denial. Keep generic local-file utilities clearly separate from managed Synapses access; they provide no security boundary.
5. Introduce a PR-only writer after the read flow passes: check GitHub access and writer_allow, preserve immutable canonical-record rules and validate records, then propose an append-only change. Forbid replacement/deletion of canonical records and self-granting policy edits in record publication. No direct-main publisher.
6. Propose the first real Synapses trust manifest in a separate private-repository PR only after identity initialization and evaluator tests pass. Empty default-deny policy is not a production rollout. Do not register a fabricated UUID or migrate records to demonstrate the flow.
7. Complete the future public forkable model tracked in #5 after onboarding is validated. Include minimal synthetic/empty base data and an empty schema placeholder {}; that placeholder does not validate records and is distinct from the strict identity/trust contract.

Use temporary local repositories and synthetic data for tests. Run the existing unittest suite plus the new authorization/integration tests locally; Actions availability is not a merge prerequisite substitute for existing required checks. Preserve existing clean-checkout, explicit-origin, fast-forward-only and external-cache safeguards, including PR #4's record validation.

## Review and rollout constraints

All changes go through GitHub PRs. Do not merge automatically, weaken checks, bypass protections, alter visibility/team permissions, change servers, or migrate production data.

During this review, the public Brain-Dump ruleset listing returned empty; branch-protection reads were denied to the integration (403). The private Synapses ruleset listing was unavailable under the current plan (403). These observations do not establish that branches are unprotected. Preserve settings as-is; confirm effective required reviews/checks through an authorized settings view before eventual merge.
