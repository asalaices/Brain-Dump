# Brain-Dump bootstrap stacks

`bootstrap/bootstrap.sh` is the only orchestration entrypoint. Stack manifests
select registered numbered phases; phases retain lifecycle ownership.

```bash
bash bootstrap/bootstrap.sh --list-stacks --pretty
bash bootstrap/bootstrap.sh --stack brain-runtime --host local --config PROFILE --plan --pretty
bash bootstrap/bootstrap.sh --stack brain-runtime --host local --config PROFILE --verify --pretty
bash bootstrap/bootstrap.sh --stack brain-runtime --host local --config PROFILE --install --execute --pretty
```

The initial stack wraps the existing runtime owner without changing services,
sources, grants, publishing routes, MCP connectors or tunnels.
