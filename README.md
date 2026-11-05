# Brain-Dump

Portable Git-backed Brain Bridge framework for Claude, Copilot and ChatGPT.

**Development foundation, not an enterprise-ready release.** Public source includes only synthetic examples and schema stubs; real Brain Dump data remains in separately permissioned private repositories such as `asalaices/Brain-Dump-Synapses`.

Track implementation in [BD program #272](https://github.com/asalaices/master-01/issues/272) and [BD15 #276](https://github.com/asalaices/master-01/issues/276).

MPL-2.0 is under consideration pending a rights/license audit. No license is granted by this preliminary README alone.

## Current implementation

The full enterprise roadmap remains the target; this is a development foundation.
[Managed source documentation](docs/MANAGED-SOURCES.md) describes the implemented
identity, separate default-deny grants, authenticated policy refresh, source-ID
binding, immutable Git reads, incremental external caches and guarded sync.
No real grant is installed by these changes. Generic local utilities are separate
from managed access. GitHub permissions remain the hard repository boundary.

Use `python3 -m brain_bridge --help`; all results carry an `info.script_version`
field. `--json` is the default and `--pretty` changes only whitespace. Tests run
with `python3 -B -m unittest discover -s tests -v` and require no credentials.
Current new records use schema v3; explicit history reads preserve v1/v2 bytes.
