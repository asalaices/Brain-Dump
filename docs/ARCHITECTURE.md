# Local-first architecture

```mermaid
flowchart TD
 A[Claude / Copilot / ChatGPT] --> B[Named source]
 B --> C[Private Git JSON]
 C --> D[Verified pull]
 D --> E[(User SQLite index)]
 D --> F[JSON fallback]
 E --> G[Scoped search and graphs]
 F --> G
```

Git JSON in separately permissioned repositories is canonical. Local SQLite is a rebuildable query index. Repository permissions control access. PR publication is default; an append-only direct default-branch publisher is future work and requires explicit named data-repository authorization. No production remote database required.
