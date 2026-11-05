# Consolidated cooperative trust contract

The implementation in framework PR #8 and private instance PR #4 uses exactly one configuration contract: `.brain-bridge/identity.json`, `.brain-bridge/sources.json` and source `.brain-bridge/trust.json`. Trust has schema version 1, default_policy deny, reader_allow and writer_allow. Grants contain exact UUIDv4 plus authenticated numeric repository ID keys. Unknown fields, duplicate grants/JSON keys, malformed IDs and unsupported versions deny access. Neither reader nor writer implies the other.

Identity and source registration are read from authenticated upstream main; policy is pinned to the authenticated source branch commit. GitHub pull permission is independently required for reads; publication also requires push permission and a private destination. Proposed local files and unmerged PRs cannot authorize runtime access. Empty grants activate no client. Cache metadata never grants permission, and unavailable upstream authorization has no cached-allow fallback.

## Superseded proposals

- Brain-Dump-Synapses PR #1 (`policies/brain-bridge-trust.json`) proposed a different manifest. Do not install or merge it alongside this contract.
- Brain-Dump-Synapses PR #2 (`trust/evaluator.py` and its schema) proposed a separate evaluator with caller-supplied verification assertions, key fingerprints and a gateway/signature dependency. It is superseded; no required Ed25519 key, unimplemented signature verification or gateway is part of this cooperative V1 contract.
- Brain-Dump PR #6 proposed standalone V1 design documentation. The implemented contract and `MANAGED-SOURCES.md` supersede that draft; do not merge competing instructions independently.
- Brain-Dump PR #4 supplied unfinished pre-index validation. Its intent is integrated and extended in #8 with compatibility and transactional regression coverage; do not merge both implementations independently.

GitHub repository permissions remain the hard boundary. This cooperative policy cannot prevent an otherwise authorized person from cloning the repository. It does not implement organizational SSO, server-side tenant enforcement or deployment approval. Future authentication mechanisms need a separately versioned/reviewed design rather than silently changing schema 1.

Private instance PR #4 remains the review location for generated identity and empty grants. Retiring alternative drafts does not approve that PR, activate a client, grant access, merge framework code or switch production.
