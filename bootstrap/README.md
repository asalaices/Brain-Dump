# Shared numbered Brain-Dump bootstrap

The root `bootstrap/` directory is the single owner of runtime, service, MCP,
tunnel, client-integration and acceptance provisioning. The current foundation
registers the existing runtime installer without changing its live behavior.

## Zero-interruption migration

- Existing `bootstrap.py` and `brain-bridge bootstrap` remain operational.
- The new controller initially wraps the same `brain_bridge.installation`
  implementation.
- No existing runtime, reader, cache, grant, publishing route, tunnel, connector
  or service is removed or restarted.
- Future MCP/OpenAI phases are additive and use separate state, credentials,
  tunnel identities and process labels.
- Removal of the temporary master-01 Brain tools is prohibited until the new
  Brain-owned path passes parallel browser and publication acceptance.

## Registered commands

```bash
bash bootstrap/bootstrap.sh --list-phases --pretty
bash bootstrap/bootstrap.sh --list-stacks --pretty
bash bootstrap/bootstrap.sh --stack brain-runtime --host local --config PROFILE --plan --pretty
```

Plans are read-only. Installation requires `--install --execute`.
The controller uses `python3` by default; set `BRAIN_BOOTSTRAP_PYTHON` to an
absolute Python 3.11+ interpreter when the shell default is older or shimmed.
