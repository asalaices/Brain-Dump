# Brain Bridge consultation and submission skill

The public Brain-Dump package owns runtime installation and Git-owned skill
discovery. No private integration checkout or external installer is needed.
See [standalone installation](../../docs/INSTALLATION.md) for a complete setup.

The native Python interface works before Bash is installed:

```sh
python3 -m brain_bridge skill-link status --source /absolute/Brain-Dump/skills/brain-bridge --skill-home /absolute/user/.codex/skills --pretty
python3 -m brain_bridge skill-link install --source /absolute/Brain-Dump/skills/brain-bridge --skill-home /absolute/user/.codex/skills --execute --yes --pretty
```

Use `uninstall` with the same explicit source and target to plan removal; add
`--execute --yes` to remove only the exact owned link. Existing directories,
files and links to another source are preserved as conflicts. Skill contents
must be tracked and match their committed Git version. Installed wheel copies
are inspection artifacts (`brain-bridge skill`), not Git-owned discovery sources.

For existing POSIX callers, `install.sh status|install|uninstall` forwards to this
same package, with optional `--skill-home`; its historical
`COPILOT_SKILLS_HOME` override selects the target. `--installer-root` is retired.
Set `BRAIN_BRIDGE_PYTHON` when selecting an interpreter explicitly.

[SKILL.md](SKILL.md) owns consultation; [submission](references/submission.md)
owns authoring and publication. Discovery never configures a source, grants
access, installs services or changes publishing policy. The install profile
selects local resources; committed registration and grants remain independent.

License: AGPL-3.0-only. Original author: Creative Software Development.
