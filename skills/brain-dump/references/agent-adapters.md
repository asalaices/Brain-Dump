# Agent discovery adapters

The canonical instructions are [SKILL.md](../SKILL.md), the bounded `brain-bridge synapse`
interface and [submission](submission.md). Agents should not implement separate
scanners or infer authorization from memory content. For an authorized new dump,
all three agents follow the same committed writer-route decision and publication
receipt rules; discovery alone never changes the producer destination.

- ChatGPT/Codex: the repository `AGENTS.md` points to the contributor contract and canonical skill. Reviewed skill discovery in a chosen directory is optional and grants no access.
- GitHub Copilot: `.github/instructions/brain-dump.instructions.md` uses `applyTo: "**"` and document-relative links to those same owners; it does not depend on personal HOME instructions.
- Claude: `CLAUDE.md` points to those same owners without a private infrastructure dependency.

The [contributor contract](../../../docs/CONTRIBUTING.md) owns portable repository
correctness; the skill owns consultation/checkpoint triggers and submission owns
the publishing procedure. Keep client entry points short. For another repository,
add a reviewed local discovery pointer only when that integration is requested;
retain that repository's own contract and instance policy rather than copying
this package's manuals. Verify actual client discovery and relative links; an
installed skill or HOME file is not automatically visible to every runtime.

All three resolve owner-configured instance, clean reader, source alias and private cache, then run the same CLI and report the same receipt fields. The shared skill remains the source of truth; adapters do not contain operational identities, credentials, extra grants or a second trust contract. `brain-bridge skill --json` locates and reads the bundled skill in an installed package; it does not install it globally or edit another project.

For Git-owned discovery, follow [the package installer](../README.md). Its thin
wrapper requires an explicit existing installer checkout and preserves all
conflicting discovery paths. The bundled wheel artifact remains readable through
`brain-bridge skill --json`; it does not become a discovery source automatically.
