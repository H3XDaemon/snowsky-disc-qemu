# Disc Assistant

An active experimental text/voice application for the SNOWSKY DISC. It runs
independently of the emulator and controls a physical player or stock V2.57 guest
through the shared [Controller API](../../controller/docs/api.md).

The **software MVP is accepted** against the 64-case emulator text cohort.
Physical-device, human-speech and platform-performance acceptance remain separate.
See [current status and evidence](docs/status.md).

## Start

From the repository root, with Python 3.11+ and Docker available:

```sh
./experiments/disc_assistant/run.sh setup --all
# Review ~/disc-assistant.toml before connecting to a player.
./experiments/disc_assistant/run.sh web --bootstrap
```

For a text console, use `setup` followed by `start`. Existing installations can
use `listen` with their current catalog/index. One foreground application owns the
device connection; close FiiO Control before connecting.

- [Setup and lifecycle](docs/guides/setup.md)
- [Command examples](docs/guides/quick-guide.md) and [complete command reference](docs/guides/commands.md)
- [Configuration and data](docs/reference/configuration.md)
- [All documentation](docs/README.md), [architecture](docs/architecture/pipeline.md) and [roadmap](docs/roadmap.md)

## Components and checks

- [`assistant/`](assistant/README.md): common request flow, NLU, CLI/web adapters,
  language/response policy and request journal.
- [`library/`](../../library/README.md): catalog observations, SQLite snapshots and search.
- [`evaluation/`](evaluation/): offline speech/search comparisons and curated acceptance.
  NLU-specific tools stay under `assistant/nlu/evaluation/`.

Run firmware-free checks with `./experiments/disc_assistant/run.sh test` and
`node --test experiments/disc_assistant/assistant/web/test_*.mjs`.
`run.sh check` exercises disposable Typesense and synthetic peers.
[Stock-firmware scenarios](docs/evaluation/emulator-acceptance.md) use separate
resources and generated media; they do not connect to the physical player.

NLU rules execute; learned sources remain shadow-only. Requests have one action
and one saved locale. Fresh device checks guard playback, and uncertain mutations
are never replayed. Private catalogs, journals, audio and models stay outside Git.
