# Agent discovery adapters

The canonical instructions are SKILL.md and the bounded `brain-bridge synapse` interface. Agents should not implement separate scanners or infer authorization from memory content.

- ChatGPT/Codex: make the reviewed brain-bridge skill discoverable in the chosen skill directory, or follow the repository AGENTS.md pointer. Installation/discovery does not configure a source or grant access.
- GitHub Copilot: the repository `.github/instructions/brain-bridge.instructions.md` points to the same skill. For another repository, add a reviewed project instruction linking its installed/shared copy when the owner requests that integration.
- Claude: the repository CLAUDE.md points to the same skill. For another repository, add an equivalent reviewed project pointer when requested.

All three resolve owner-configured instance, clean reader, source alias and private cache, then run the same CLI and report the same receipt fields. The shared skill remains the source of truth; adapters do not contain operational identities, credentials, extra grants or a second trust contract. `brain-bridge skill --json` locates and reads the bundled skill in an installed package; it does not install it globally or edit another project.
