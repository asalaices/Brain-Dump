# Numbered Brain-Dump phases

Stable phase IDs and hard dependencies are registered in `phases.conf`.
Installation logic belongs in phase-owned assets or reusable `brain_bridge`
libraries, never in the controller. Every phase is independently plan-first,
idempotent, verifiable and reachable from a registered stack.
