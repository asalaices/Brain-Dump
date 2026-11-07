# Bootstrap ownership

`bootstrap/entrypoints.json` classifies operator-facing roots and numbered phase
coverage. Runtime helpers must be reachable from the controller, a registered
phase or an explicitly classified compatibility/application entrypoint.

The root `bootstrap.py` remains temporarily classified only to prevent an
interruption during migration. It may not gain MCP, tunnel, service or client
installation logic. Those capabilities must be registered under `bootstrap/`.
