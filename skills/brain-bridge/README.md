# Brain Bridge consultation and submission skill

This package teaches authorized, cited consultation through `brain-bridge synapse`
and immutable contribution through the owner's selected publishing flow.
[SKILL.md](SKILL.md) owns consultation, [submission](references/submission.md)
owns authoring/publication, and [agent adapters](references/agent-adapters.md)
describe discovery. Skill discovery
does not configure a source, grant access, install the runtime or change publishing.

## Git-owned discovery

Use this package from a reviewed Git checkout. The installed framework also
bundles these documents for inspection with `brain-bridge skill --json`; a wheel's
copied artifact is not a Git-owned discovery source.

The thin installer delegates every link decision to an explicitly selected
existing master installer checkout. It never implements its own link replacement,
copying, backup or conflict-resolution logic. There is no implicit private path
or automatic installer download.

```sh
# Inspect this package's discovery target.
skills/brain-bridge/install.sh --installer-root /path/to/master-installer status

# Review the install plan, then explicitly install if the target is unowned.
skills/brain-bridge/install.sh --installer-root /path/to/master-installer install
skills/brain-bridge/install.sh --installer-root /path/to/master-installer install --execute --yes

# Select a Codex discovery directory through the existing owner's override.
COPILOT_SKILLS_HOME=/chosen/codex/skills \
  skills/brain-bridge/install.sh --installer-root /path/to/master-installer status
```

The selected checkout must contain Git-tracked
`intelli_bots/bot_local_skill_link.sh`, `bot_general.inc` and `bot_general.py`.
Its existing installer owns stdout, diagnostics, action semantics and exit status.
`status` is read-only. Install and uninstall plan by default; mutation requires
`--execute`, and `--yes` supplies explicit noninteractive confirmation. The same
`--debug` and `--log-file` options remain available.

The default discovery directory belongs to that installer. Set
`COPILOT_SKILLS_HOME` deliberately when selecting another agent. Existing regular
files, directories and links to another source are conflicts and remain untouched.
Preserve and reconcile their ownership separately; this wrapper has no force mode.
Uninstall removes only a link pointing to this exact source package:

```sh
skills/brain-bridge/install.sh --installer-root /path/to/master-installer uninstall
skills/brain-bridge/install.sh --installer-root /path/to/master-installer uninstall --execute --yes
```

Installing this package does not replace committed project publishing policy.
The submission instructions distinguish legacy, paused and managed writers;
a production writer cutover requires its own review. A consultation profile
alone never authorizes direct publication.
No operational identity, profile, repository registration or credential is
included in the public package. License: AGPL-3.0-only; original author and
copyright holder: Creative Software Development.
