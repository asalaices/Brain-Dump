# Bootstrap configuration

Committed configuration contains schemas, public defaults and external-resource
references only. Private instance profiles, source identities, credential bytes,
tunnel IDs and connector IDs remain outside Git.

The initial `brain-runtime` stack accepts the existing reviewed schema-2 profile
through `--config`. Later MCP and tunnel phases must extend the public bootstrap
without changing or taking ownership of an installed runtime until their own
parallel acceptance succeeds.
