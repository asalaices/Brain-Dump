# GitHub evidence connector

`collect` reads exactly one issue, pull request, full commit ID or workflow run through existing authenticated `gh` GET requests. It cannot update issues/tasks, trigger builds, merge PRs or publish records. Private operational connector configuration belongs in a private instance repository; examples here are synthetic.

## Registration and use

Propose an entry in the selected instance repository's `.brain-bridge/connectors.json`:

```json
{"schema_version":1,"connectors":[{"name":"example-github","provider":"github","repository":"example/code","repository_id":"123"}]}
```

Use the real independently verified numeric repository ID in an operational proposal. A local edit, proposed branch or PR never activates this connector. The instance identity and registry must be reviewed on authenticated upstream main. `github_actions` registrations remain CI-only; `github` explicitly permits the four selected object kinds.

```sh
brain-bridge collect --identity-repo /private/instance --connector example-github --kind issue --id 9 --pretty
brain-bridge collect --identity-repo /private/instance --connector example-github --kind pull_request --id 9 --json
brain-bridge collect --identity-repo /private/instance --connector example-github --kind commit --id 1111111111111111111111111111111111111111 --json
brain-bridge collect --identity-repo /private/instance --connector example-github --kind run --id 9 --json
```

`--json` is the default; `--pretty` changes whitespace only. Issue/PR bodies and complete commit messages are excluded unless `--include-body` is explicitly passed. Titles and returned text are untrusted provider content, never agent instructions. Output may contain private material from an authorized source: choose its destination accordingly. No payload or credential is logged by this connector.

## Identity, freshness and evidence

The connector verifies the registered repository's stable numeric ID, full name and actual pull permission both before and after the object read. The selected object's number/ID, repository-bound URL, PR base identity, full commit SHA and timestamp fields are validated. The named interface also refreshes instance registration after collection and withholds evidence if registration changed. It fails closed on unavailable metadata or permission revocation; there is no stale/offline fallback.

The receipt contains a provider-qualified `resource_id`, canonical content `snapshot_sha256`, version-qualified `observation_id`, `observed_at` and authenticated registration commit. Repeating an identical observation retains the same observation ID; changed selected content changes the snapshot hash without inventing a new provider object. This hash covers the provider, repository name/ID, kind, resource ID and normalized object, not the wall clock or registration wrapper. It detects differences; it is not a signature, durable authorization grant or guarantee that a mutable provider object has not changed since observation. The GETs are separate observations, not a transaction across GitHub.

`brain_evidence` projects the result into valid v3 `provenance` and `references`, plus proposed string evidence for a task. It never writes a ledger or mutates a TODO. Merge these fields into a separately authored/validated record and use the guarded `publish` workflow when authorized. Graph generation recognizes explicit `github_evidence` references and retains their observation IDs and source links. Do not infer task completion from a closed issue, draft PR, successful CI run or an unmerged PR test merge SHA. Task state remains authoritative in SimpleTodos.

## Scope and limits

This bounded first connector handles selected objects, not automatic organization-wide crawling, webhook subscriptions, comments/artifact downloads or implicit pagination. Its existing transport rejects failed/oversized responses and bounds request duration. GitHub/GitLab/Jenkins CI observers are separate read-only adapters. Email, Teams and SNS dispatch are not implemented by this connector. Publication remains a separate plan-first, private-source, dedicated-PR workflow with independent remote SHA/byte verification.

Validation uses synthetic API responses and isolated Git repositories. Live named acceptance needs the exact registration reviewed upstream; do not bypass the registry by promoting local configuration. Live record publication additionally needs separately reviewed private reader/writer grants.

Provider contracts: [issues](https://docs.github.com/en/rest/issues/issues#get-an-issue), [pull requests](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request), [commits](https://docs.github.com/en/rest/commits/commits#get-a-commit), [workflow runs](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run).
