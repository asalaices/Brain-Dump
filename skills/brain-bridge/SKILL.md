---
name: brain-bridge
description: Authorized JSON Brain Bridge searches and local derived SQLite indexing for Claude, Copilot and ChatGPT.
---
# Brain Bridge
Use `python3 -m brain_bridge search --root AUTHORIZED_RECORDS --term KEYWORD`. Use `--backend sqlite --db LOCAL_PATH` only for local authorized data. All nested JSON object keys, scalar values and arrays are searched. JSON is canonical; a SQLite index is rebuildable. The current CLI is a local development foundation; remote publication and corporate SSO are not implemented. Never copy real data into the public code repo.
