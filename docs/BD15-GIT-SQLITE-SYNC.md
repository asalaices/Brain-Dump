# BD15 guarded Git-to-SQLite sync (development contract)

The Git JSON files remain canonical; SQLite is only a derived, per-agent cache. This phase supports an **already-cloned, clean, standalone** repository with an explicitly authorized `origin` URL. No background daemon, credential manager, unattended cloning, or direct-main publisher is included.

Example, using a **private** authorized data checkout:

```sh
python -m brain_bridge sync \
  --repo "$HOME/brain-data/Synapses" \
  --remote "git@github.com:asalaices/Brain-Bridge-Synapses.git" \
  --branch main \
  --records . \
  --db "$HOME/.local/state/brain-bridge/synapses.sqlite"
```

The command rejects a dirty checkout, wrong remote, wrong branch, in-repository SQLite path, and non-fast-forward history; successful sync reports the Git commit, indexed JSON record count, and freshness verification. No `reset --hard`, force update, rebase, or automatic push is used.

A Git pull or indexing failure is returned as an error, not a reported successful sync. The existing `search --backend auto` can independently read current local JSON when the SQLite cache is stale or unavailable. Source access is still controlled by Git credentials and filesystem permissions.

**Limitations for follow-up:** The current full hash comparison and full transactional index rebuild are not yet incremental. No structured record schema or signature verification, multi-source manifest, scheduling, cross-process locking, or post-pull audit log is provided. The caller must choose a directory containing only its authorized canonical JSON records; using `--records .` indexes all JSON under that checkout including examples. Do not use against production data until those contracts are reviewed.

Tests use temporary local Git repositories only. No GitHub Actions run is required for local test execution.
