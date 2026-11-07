# Executable mode policy

Controllers, phase wrappers, executable assets and test entrypoints use Git mode
`100755`. Sourced `.inc` files, JSON configuration, manifests and documentation
use `100644`. Credentials and private instance state are never repository
payloads and retain owner-only modes through their owning phases.
