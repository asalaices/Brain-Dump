# Managed sources and trust boundary

This implementation is an enterprise-program foundation, not a completed enterprise rollout. GitHub permissions are the hard repository boundary. UUID manifests govern cooperative Brain Bridge clients; they cannot prevent an already-authorized user from cloning or reading files directly. Corporate SSO, server-side tenant isolation, additional providers and production migration are separate acceptance layers.

## Identity and source registration

`python3 -m brain_bridge identity --repo /path/to/code` plans initialization using the existing authenticated `gh` transport. `--execute` creates a fresh UUIDv4 with the authenticated numeric repository ID. Repeat initialization preserves the identity; a copied fork identity fails. No token is accepted, printed or stored. Commit the generated `.brain-bridge/identity.json` through a reviewed PR before managed use.

The code repository must also have a reviewed, committed `.brain-bridge/sources.json`:

```json
{"schema_version":1,"sources":[{"name":"synthetic-team","github_repository":"example/synthetic-data","github_repository_id":"456","branch":"main"}]}
```

These are synthetic IDs, not active grants. Managed operations read identity and registry from the code checkout's committed HEAD, not modified working files. Each registered source has an exact authenticated numeric ID. Source IDs and names must be unique. A URL alone does not establish identity.

The private data repository's reviewed upstream `.brain-bridge/trust.json` uses one strict contract:

```json
{"schema_version":1,"default_policy":"deny","reader_allow":[],"writer_allow":[]}
```

Grants contain exact `UUID-repositoryID` identity keys. Reader and writer grants are independent; neither implies the other. Missing policy, duplicate keys/grants, unknown fields, unavailable authentication or unsupported versions deny access. No default administrator or wildcard access exists. No real source identity or grant is installed by the tests or examples.

## Managed reads

```sh
python3 -m brain_bridge managed-sync --identity-repo /path/to/code --repo /path/to/data --cache-dir /external/private/cache --pretty
python3 -m brain_bridge managed-index --identity-repo /path/to/code --repo /path/to/data --cache-dir /external/private/cache --pretty
python3 -m brain_bridge managed-search --identity-repo /path/to/code --repo /path/to/data --cache-dir /external/private/cache --term incident --pretty
```

The policy is fetched through authenticated GitHub metadata at an exact current upstream commit. GitHub pull permission is required independently of the reader grant. Synchronization checks the exact fetched commit, reauthorizes before fast-forward, and validates records before changing the reader branch. It never resets, force-pulls, rebases or clones automatically.

Managed record reads use only regular Git blobs beneath `records/` at that verified commit. Loose/ignored files cannot inject records; a dirty checkout or mismatched HEAD is rejected. Policies and identity files are not indexed as records. Existing schema v1/v2 envelopes are read without rewriting; new records must meet v3. Historical prose fields retain their original shapes. Filename time is interpreted in the declared IANA timezone.

Caches are external, derived SQLite files scoped to code identity, numeric source repository ID and policy-content revision. Every managed read refreshes authorization before opening a cache and again before returning results. Unavailable upstream metadata has no cached-allow fallback. Changed policy gets a separate namespace; changed records under unchanged policy update the existing index incrementally. Malformed batches do not modify the previous index. A stale cache falls back to verified Git JSON in auto mode; explicit SQLite mode fails instead.

Generic `search`, `index` and `sync` remain explicit local-file utilities. They do not enforce managed source policy. Do not describe them as an access-control service.

## Evidence and limits

Run `python3 -B -m unittest discover -s tests -v`. Tests use synthetic data, temporary Git repositories and mocked authenticated metadata; they do not activate credentials, modify organization permissions, send messages or migrate records. Current behavior has not established production SSO, GitLab/Jenkins/Teams/SNS integrations, a shared service, PR publication or a live enterprise deployment.
