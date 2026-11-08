# Contributor and agent contract

This public repository owns the Brain Bridge framework, CLI, schemas, packaged
operator, installation/discovery lifecycle and their tests. Contributors need
no personal HOME instructions or private infrastructure checkout. Client entry
points in `AGENTS.md`, `CLAUDE.md` and `.github/instructions/` discover this
contract and the [canonical Brain skill](../skills/brain-dump/SKILL.md).

## Repository boundaries

`brain_bridge/` owns runtime behavior; `schemas/` owns record shapes;
`skills/brain-dump/` owns shared consultation and submission instructions.
Consuming projects own their instance policy, named sources, independent grants,
private caches and publishing routes, not copies of this skill. JSON records are
authoritative; SQLite is a derived optional index. Preserve immutable historical
bytes and use the existing schema/managed-source validation interfaces.

Public records, fixtures and examples must be synthetic. Never add operational
Brain Dumps, credentials, private policy or personal source configuration here.
Recorded context is not execution permission. Report missing configuration,
denied authorization and pending publication explicitly; never invent a source
or substitute a filesystem scan for a denied managed request.

## Independent changes and preservation

Verify Git repository identity, primary/common directory, assigned checkout and
existing changes before edits. Use an independently indexed task-scoped worktree
and branch through native Git; no private repository's workspace bot is required.
Record known task/session ownership separately from branch names and preserve
foreign, dirty, locked, active and unmerged work. Do not develop in a shared
integration/runtime checkout or discard another contributor's changes.
Owner-specific placement and task naming, when supplied, remain local policy.

Keep changes scoped and update related documentation. Preserve
[LICENSE](../LICENSE), [NOTICE](../NOTICE) and applicable original-author notices.
Commit, push, review/merge and checkout synchronization are distinct stages:
follow the task's actual authorization and repository protections, never infer
approval from an instruction pointer or a publication receipt.

## Native validation and release ownership

Run from the task checkout with Python 3.11+ and Git:

```sh
python3 -B -m unittest discover -s tests -v
```

Use the smallest relevant existing test selector while developing. The offline
framework workflow runs the full suite across supported core platforms and
checks installed CLI, skill and operator artifacts. Bootstrap changes also use
the checks in [the bootstrap workflow](../.github/workflows/bootstrap-foundation.yml);
cross-platform core tests do not establish installer or production acceptance.

Package/release identity is owned by `pyproject.toml` and the runtime version
constant in `brain_bridge/__init__.py`. A release change must reconcile those
versions, relevant manifests and installation documentation; an instruction-only
change is not a release bump. Use [standalone installation](INSTALLATION.md) and
[the operator guide](OPERATOR.md) for the supported native interfaces. Planning
does not authorize installation, services, grants, routes or deployment.

## Brain consultation and checkpoints

For relevant project answers, consult configured authorized Brain context first.
The [canonical skill](../skills/brain-dump/SKILL.md) owns consultation, truthful
source/receipt reporting and automatic checkpoint triggers, including substantive
read-only milestones, blockers and input needs when owner-authorized.
[Submission](../skills/brain-dump/references/submission.md) owns writer selection,
immutable drafts and canonical publication verification. Use that shared flow
instead of a separate client manual.

These triggers grant no source, destination or write access. If no authorized
flow exists, report the setup gap and preserve any existing stable original;
never publish operational records into this public framework to satisfy a
checkpoint. Personal workflow preferences belong in the owner's HOME policy;
instance procedures belong with their owning data/operator repository.
