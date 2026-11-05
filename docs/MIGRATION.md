# Private migration rehearsal

Migration is an explicit operator workflow, not normal record publication and not production cutover. It does not grant a client access, change GitHub permissions, switch readers/writers, stage Git files or delete source data.

```sh
python3 -m brain_bridge migrate-plan --source-repo /authorized/legacy --destination-repo /authorized/private-data --source-id 123 --destination-id 456 --destination-ref reviewed-foundation --namespace Brain-Bridge --pretty > /private/reviewed-plan.json
python3 -m brain_bridge migrate-apply --source-repo /authorized/legacy --destination-repo /authorized/private-data --plan /private/reviewed-plan.json --pretty
```

The default apply command verifies the plan without writing. Adding `--execute --yes` prepares only byte-identical additions in the private destination working copy. Commit and review are separate steps. Neither command modifies a runtime or merges a branch.

The source/destination numeric IDs, selected published refs/commits, file paths, bytes/hashes and observed audiences are bound into a deterministic plan token. The source is read from immutable Git objects. The destination must be private, have actual read/write permission, match its published base, and contain a canonical records directory. Existing bytes/entry IDs are never overwritten. Changed plans/HEADs, unavailable audience inventory, known audience expansion, symlinks or unrelated owner work block application. A partial preparation can be resumed only when every existing planned file is still identical.

Dated envelopes map to records/; provenance sidecars map to metadata/. Both preserve exact bytes. Sidecars keep their original logical Brain-Bridge ledger references, record hashes, entry IDs and attribution sources. Legacy read-time provenance must not be written back into frozen envelopes. Current rehearsal input is bounded to128 MiB; larger migrations need an explicitly staged strategy.

Audience inventory compares owners, collaborators, teams and public deploy-key fingerprints. It does not claim to enumerate every third-party application grant or inherited enterprise identity rule. Those require owner review before cutover. A proposal into an explicitly selected owner-controlled private repository is not a declaration that all external application scopes were audited.

After preparation, compare all envelope/entry/sidecar counts, unique IDs, hashes, effective provenance and search/index behavior. Source main advancing invalidates the plan even if only code changed: review a fresh snapshot rather than silently accepting a stale plan. Production remains on the old source until a concrete routing change, rollback and writer inventory have been validated and approved. Rollback restores routing; it does not delete immutable records.
