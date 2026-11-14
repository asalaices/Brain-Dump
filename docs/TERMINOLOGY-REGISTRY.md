# Terminology registry (CORTEX1)

**Status: approved by the owner on 2026-11-07 as CORTEX1 acceptance (PR #30).** This registry consolidates the hybrid vocabulary in
[Brain-Evolution §3](../Brain-Evolution.md) into one reviewable record. Approval covers this registry only; the *Maturity* column still marks which names are shipped. Nothing here changes shipped behavior, grants, routing or data. Names are product metaphors, not
authority or security principals. The *API term* is the stable machine identifier; display names may change.

**Scoped owner revision, 2026-11-10:** Cortex is one application with Recall and
Administration folder tabs in the same main panel and always-visible connection
controls. This supersedes the original "separate admin surface, never under
Cortex" placement for Brain Gate, not the remaining taxonomy or operations
acceptance. Historical approval remains scoped to its original record.

Maturity values: **Existing** (shipped, contract preserved), **Proposed** (named, not shipped),
**Planned** (scheduled), **Future** (unscheduled).

| Canonical name | Aliases | Plain-language purpose | Owner | Repository | Dashboard placement | API term | Maturity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Brain-Dump | — | The whole independent software product | Brain-Dump | `asalaices/Brain-Dump` | Product name; not a menu item | `brain-dump` | Existing |
| Cortex | Brain-Cotletex (candidate label only) | Everyday human-facing portal and navigation shell | Brain-Dump product UI (BDT30; CORTEX track) | `asalaices/Brain-Dump` | Top-level application shell | `cortex` | Proposed |
| Memory | — | Searchable explorer of recorded history | Brain-Dump product UI | `asalaices/Brain-Dump` | Cortex → Memory | `memory` | Proposed |
| Recall | — | Cited, authorized retrieval action over a registered source | Brain-Dump product UI over Brain Bridge | `asalaices/Brain-Dump` | Cortex → Recall pilot tab; broader Memory explorer remains proposed | `recall` | Proposed; local pilot implemented, acceptance pending |
| Synapses | Neural Pathways (relationship view only) | Canonical permissioned memory repository and its recorded link vocabulary | Synapses repositories (canonical data) | private Synapses repositories, e.g. `asalaices/Brain-Dump-Synapses` | Cortex → Synapses (relationship explorer) | `synapses` (explorer: `pathways`) | Existing (storage); Proposed (UI) |
| Neural Map | word globe | Cited prevalence of recorded terms in authorized content | Brain-Dump product UI (BDT31) | `asalaices/Brain-Dump` | Cortex → Neural Map | `neural-map` | Proposed |
| Pulse | — | Freshness, sync, submission and publication status | Brain-Dump product UI (BDT32/35) | `asalaices/Brain-Dump` | Cortex → Pulse | `pulse` | Proposed |
| Brain Gate | Administration (Cortex display label) | Restricted operations/maintenance capabilities with independent server-side permissions | Brain Gate operations (BDT48) | `asalaices/Brain-Dump` | Cortex → Administration; unavailable-capability notice in the pilot | `brain-gate` | Planned (operations) |
| Brain Bridge | `brain-bridge` CLI | CLI/integration contract for consultation, evidence and publication | Brain Bridge integration | `asalaices/Brain-Dump` | Not a UI surface | `brain-bridge` | Existing; preserve |

## Reserved terms

`Encode`, `Attention` and `Reflex` are reserved as **actions or future workflows**, not products or
sections: Encode (`encode`, proposed workflow label), Attention (`attention`, future), Reflex
(`reflex`, future). They must not be implemented or shown as shipped features until separately approved.

## Rules

- Proposed names are never described as shipped; only Brain Bridge and Synapses storage are Existing.
- `brain-bridge synapse` and `brain-bridge graph` keep their existing contracts; UI labels must not redefine them.
- One Cortex UI may present Recall and Administration; user-facing search and tab selection never imply administrative authority. Privilege separation is enforced server-side, not by a separate browser application or port.
- Unapproved inference is not "memory"; proposals are not "trusted" or "Done".
- Dashboard placement follows [Brain-Evolution §4](../Brain-Evolution.md); Widgy and master-01 infrastructure remain separate lanes.
