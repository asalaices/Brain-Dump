# Record profiles

Schema 3 records are validated against a *record profile* that lists the allowed
IANA timezones and publishing agent identifiers. Without configuration the
strict `master-01-v3` profile applies (`America/Chicago`; `copilot`, `chatgpt`),
so existing history and installations validate exactly as before.

An installation opts in to another reviewed profile by setting
`BRAIN_BRIDGE_RECORD_PROFILE` to a regular JSON file (up to 64 KiB):

```json
{"schema_version": 1, "name": "example-utc", "timezones": ["UTC"],
 "agents": ["claude", "copilot"], "default_timezone": "UTC"}
```

All fields are required; unknown fields, unknown timezones, duplicate or
non-lowercase agent identifiers, or a `default_timezone` outside `timezones`
are rejected. A configured but missing or invalid file fails closed rather than
falling back. `default_timezone` is used when `brain-bridge create` builds an
envelope. A profile grants no repository access, does not relabel agents and
never rewrites existing records; legacy/historical readers keep their own
pinned shapes. Use the same profile on every reader and writer of a source.
