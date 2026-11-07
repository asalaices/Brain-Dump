# Standalone runtime installation

Brain-Dump 0.8.6 owns its runtime lifecycle, CLI, integration operator, skill
discovery and product tests. A new developer needs this public source and an
owner-controlled private data/identity repository; no private infrastructure
repository or shell runtime from another project is required.

## Prerequisites and supported platforms

Runtime activation supports macOS and Linux with an existing Python 3.11+ and
Git. Start with native Python; Bash is optional. This release does not acquire
Python/Git binaries, configure MCP/tunnels, create grants or launch services.
The full guided configurator and Windows toolchain/activation are subsequent
roadmap work. Windows activation fails explicitly before building or activation;
do not interpret the cross-platform core test matrix as Windows installer acceptance.

Review a Git release commit, its license/notices and source. Choose absolute
paths under your user home for managed resources. Never run this as root or
point it at another user's installation. Create a private JSON profile, for
example by running the following from the reviewed checkout and replacing the
source path and immutable 40-character release commit:

```python
import json, pathlib, platform, sys
home = pathlib.Path.home().resolve()
profile = {
    "schema_version": 2,
    "host": "my-laptop",
    "home": str(home),
    "runtime_dir": str(home / ".local/share/brain-bridge"),
    "source_repo": "/absolute/Brain-Dump",
    "framework_commit": "REPLACE_WITH_REVIEWED_40_CHARACTER_COMMIT",
    "framework_version": "0.8.6",
    "python": str(pathlib.Path(sys.executable).resolve()),
    "python_version": platform.python_version(),
    "setuptools_version": "84.2.1",
    "launcher": str(home / ".local/bin/brain-bridge"),
    "skill_home": str(home / ".codex/skills"),
    "skill": "skills/brain-dump"
}
path = home / "brain-installation.json"
path.write_text(json.dumps(profile, indent=2) + "\n")
path.chmod(0o600)
```

The source must be clean, contain the immutable release in its ancestry and
have the exact reviewed skill tree. Builds use `git archive RELEASE`, never a
later development HEAD. Unrelated committed development changes are allowed;
changed live skill content requires an explicitly reviewed release/profile.

## Plan, install and verify

From that public checkout:

```sh
python3 bootstrap.py --config /absolute/user/brain-installation.json --pretty
python3 bootstrap.py --config /absolute/user/brain-installation.json --operation preflight --pretty
python3 bootstrap.py --config /absolute/user/brain-installation.json --operation install --execute --yes --pretty
python3 bootstrap.py --config /absolute/user/brain-installation.json --operation verify --pretty
```

The installed equivalent is `brain-bridge bootstrap` with the same arguments.
Plan is the default, is read-only and lists activation effects. Install requires
both execution flags, takes a bounded local lock, builds a versioned venv,
verifies package version/CLI/skill, activates the stable environment and launcher,
reconciles discovery, then saves a private ownership receipt. A repeated install
reuses the verified environment. Failure restores prior owned activation and
preserves foreign files. Existing unknown environments or copied skills are
conflicts, never overwritten. Private legacy migrations may supply exact reviewed
`legacy_version` and `legacy_skill_sha256`; new installations omit both.

For an offline POSIX install, add `wheel` (absolute regular wheel path) and
`wheel_sha256` (reviewed SHA256) to the profile. The installer verifies the digest
and uses `pip --no-index --no-deps`; current POSIX runtime has no external runtime
dependencies. The supplied wheel must match the reviewed release/version. Normal
source builds acquire the exact setuptools version from your configured package
index; review/configure that index separately. Neither mode installs arbitrary
system binaries. Receipts retain source pin, Python/package versions and wheel hash.

JSON is default; `--json` and `--pretty` return equivalent structured receipts
with framework version metadata. A failed operation exits nonzero. Bootstrap
plans and verification do not activate a writer. Retained versioned environments
and exact prior activation are recorded for recovery; this bounded flow does not
yet implement the full transactional uninstall/repair roadmap.

## Integrate with your own Brain

Follow [managed sources](MANAGED-SOURCES.md) to select a real identity, named
source and independent grants. Follow [the operator guide](OPERATOR.md) for
committed routing/runtime profiles, cited consultation, authoring a stable external
envelope and normal guarded promotion. The instance/data repository can itself
hold those profiles. All commands are public `brain-bridge` commands; there is
no private helper to discover or reconstruct. Ordinary `publish` remains PR-only.

## Acceptance and ownership

Public CI owns lifecycle, migration/rollback, discovery conflicts, profile and
installed-wheel tests. `tests/acceptance_standalone.py --wheel ABSOLUTE` performs
actual offline installation, verify, idempotent rerun and installed-package
managed authoring/publication tests in a fresh home with independent Git fixtures
and synthetic provider transport. It exposes no private integration source.
Production provider credentials/grants are deliberately not provisioned by a test.
Private installations retain their host policy adapter and private history guards;
product implementation and lifecycle tests are owned here.

## Existing brain-bridge discovery

The canonical skill is now named `brain-dump`. The CLI remains `brain-bridge`.
A consuming repository keeps instance configuration/policy, not another skill.
To migrate an existing exact owned link, plan then explicitly execute:

```sh
brain-bridge skill-link migrate --source /absolute/Brain-Dump/skills/brain-dump --skill-home /absolute/user/.codex/skills --previous-source /absolute/old-repository/skills/brain-bridge --pretty
brain-bridge skill-link migrate --source /absolute/Brain-Dump/skills/brain-dump --skill-home /absolute/user/.codex/skills --previous-source /absolute/old-repository/skills/brain-bridge --execute --yes --pretty
```

The old link must point to precisely that declared source (or already be absent).
The new target must be unowned or already point to the canonical public source.
Foreign links, regular directories and copied skills remain conflicts. A failed
migration restores the prior owned link and removes only its newly created link.
This does not change an identity, source registration, grant or publishing route.
