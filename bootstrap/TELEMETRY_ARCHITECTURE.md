# Bootstrap telemetry architecture

Brain-Dump follows the master-01 bootstrap telemetry contract: each captured run
has a private raw log, redacted publication log and machine-readable manifest;
the original child status is preserved and publication failure cannot change the
bootstrap result.

Because this repository is public, telemetry publication is disabled until an
explicit private destination is configured. Private Brain paths, source
identities, excerpts, credentials, grants and publication records must never be
published to this repository.
