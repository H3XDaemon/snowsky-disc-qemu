# Assistant configuration and data

The maintained configuration template is
[`assistant/config.example.toml`](../../assistant/config.example.toml).
Select another file with `run.sh --config PATH ...` or `DISC_ASSISTANT_CONFIG`;
the default is `~/disc-assistant.toml`. Device endpoints, credentials and limits
belong in TOML/environment, while saved preferences and request history belong in
Assistant SQLite storage.

## Device and preferences

`[device].key` is a user-assigned persistent namespace. HTTP and TCP must target
the same device: emulator defaults are loopback TCP 12100 / HTTP 12113; physical
DISC normally uses HTTP 12103. Firmware support is selected through Controller's
reviewed capability registry using device-reported identity/version. A new
version does not inherit capabilities automatically.

One locale governs command interpretation and response text. Saved
`language.locale` and `response.mode` preferences override TOML defaults;
`--language CODE` selects and persists a locale. `run.sh language [CODE|reset]`
manages it without a device/search connection. An existing console reloads
external changes through `/language` or restart. See the
[locale architecture](../architecture/pipeline.md#one-interaction-locale) and
[response policy](responses.md).

Relative volume has separate configured up/down steps, default 20, and is clamped
to the reviewed device range 0..120. The [quick guide](../guides/quick-guide.md)
shows the exact configuration keys and natural-language commands.

## Storage and backups

`[storage].data_dir` defaults to:

| Platform | Directory |
| --- | --- |
| macOS | `~/Library/Application Support/disc-hub/prototype/` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/disc-hub/prototype/` |
| Windows | `%LOCALAPPDATA%/disc-hub/prototype/` |

An override must be absolute (or begin with `~`) and remain outside the repository.
Different independent profiles need different data directories; the ownership
lock and saved preferences are scoped to that directory.

- `library.sqlite3` stores catalog observations and snapshots.
- `assistant.sqlite3` stores preferences, request/decision history and command
  snapshots. It is not a listening-history database or replay queue.
- Managed Typesense data lives in the separate `disc-assistant_typesense-data`
  Docker volume and can be rebuilt with `index`, including when DISC is offline.
- Local `assistant/.env` contains the private search key; speech/model files use
  their configured external locations. Keep these out of Git.

Back up both SQLite files while all Assistant processes are stopped, or use
SQLite's online backup API. Preserve the TOML/aliases and required credentials.
Sync/index does not erase language preferences. Journal retention is separate
from catalog/index cleanup; old snapshots or interrupted collections can remain.
Do not infer automatic storage pruning from `/history prune`.

A catalog is an observation, not an atomic device revision. Track IDs are
snapshot-local, and CUE/duplicate identities can remain ambiguous. Use the
[Library contract](../../../../library/README.md) and
[playback guards](../architecture/playback.md), rather than persisting IDs as
replayable commands. Only synchronize an idle device; an already-running scan
may have begun before connection and escaped observation.
