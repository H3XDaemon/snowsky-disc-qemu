# Assistant application prototype

Experimental application and CLI orchestration in `experiments/disc_assistant/assistant/`.
See the [prototype guide](../README.md) for setup, commands and acceptance, and the
[roadmap](../docs/roadmap.md) for deferred work.

| File | Responsibility |
| --- | --- |
| `__main__.py` | `start`, `listen`, `web`, `language`, `response`, `locales`, `history`, `sync`, `status`, `queue`, `index`, `search`, `rank`, `ask`; JSON output and errors |
| `database.py`, `journal.py` | Schema migrations, bounded request/decision events, retention, inspection/export/clear |
| `preferences.py` | Versioned Assistant SQLite settings; one persistent locale and speech policy with atomic legacy migration, override/reset and effective configuration |
| `config.py`, `config.example.toml` | Explicit device/search/storage configuration and aliases |
| `command_catalog.py`, `nlu/command_features.py`, `nlu/explain.py` | Versioned locale references, portable classifier and non-executing explanation preview |
| `nlu/interpreter.py`, `nlu/intents.py` | Replaceable text/context interpretation, literal grammar and validated intentions |
| `resolver.py`, `nlu/matching.py`, `ranking.py` | Catalog name resolution and explained ranking of interpreted music requests |
| `providers.py`, `speech.py` | Provider identity and independent asynchronous STT/TTS/capture/output contracts |
| `responses.py`, `locales/replies/*.toml` | Shared localized feedback, speech policy, template validation and reserved dialogue contract |
| `nlu/languages.py`, `locales/*.toml` | Validated language dictionaries; one active command/target/version dictionary and language-switch aliases |
| `playback.py` | Serialized, fresh Controller selection and playback-state verification |
| `device.py`, `controls.py` | Application ownership and intent adapters over Controller controls; Assistant Stop policy |
| `queue.py` | Controller queue adapter; Assistant continuous-context opt-in |
| `session.py` | Catalog synchronization using a borrowed persistent session or a one-shot connection |
| `live.py` | Thin config/ownership adapter over `controller.session.DiscSession` |
| `application.py` | Shared command orchestration, search, speech, preferences and guarded execution |
| `console.py` | Terminal adapter, startup sync/index and interactive text/maintenance commands |
| `web/` | Separate loopback browser adapter, microphone capture, live observations and diagnostics |
| `terminal.py` | `prompt_toolkit` editing, journal-backed recall, language-aware completion, configurable colors and screen clearing |
| `requirements.txt` | Python runtime pins: official Typesense async SDK, aiohttp and prompt_toolkit |
| `compose.yaml`, `.env.example` | Independent local Typesense service |
| `voice/services/`, `requirements-speech.txt` | Optional pinned speech model manifest, Whisper/Piper Docker services, installer/conversion dependencies |
| `voice/` | Bounded WAV input, Whisper CLI/server STT, Piper reply delivery and macOS say sample TTS, synthetic corpora and interpretation/catalog-selection evaluation |
| `tests/` | Configuration, CLI and session tests |

The application asks [library](../../../library/README.md) for persistence/search and
uses the existing [controller](../../../controller/) public APIs. No emulator or
viewer imports. Importing modules creates no storage, connections or microphone.
Use `experiments/disc_assistant/run.sh` for setup, local Typesense and CLI commands.
It selects the explicit `.venv/bin/python`, loads the private key and invokes
`-m experiments.disc_assistant.assistant` from the repository root; shell aliases
do not override its interpreter.

The official [typesense-python](https://github.com/typesense/typesense-python)
2.0.0 AsyncClient is used only by library search; its transport closes on CLI exit.
Aiohttp serves the web interface and bounded loopback speech adapters. Web always
uses Whisper Server. `setup --all` installs the runtime and optional speech bundle;
see [Piper and managed services](../docs/guides/tts.md). CLI/file STT may
retain its explicit CLI backend. Piper runs in its own Python 3.11 container;
optional host dependencies cover TOML editing, sample resampling and an explicit
public CA bundle for model downloads.
A transitive lockfile remains deferred.

`run.sh start` starts Typesense, then opens one foreground application for
connection, sync/index and interactive input. `listen` skips search startup and
automatic synchronization. Both use `DeviceSession`: a background socket reader
keeps receiving while the main thread waits for input, runs search or reads HTTP.
A separate session worker establishes the connection and performs bounded health
reads/reconnect. Device operations borrow the same client under a serialization
lock; only the receiver reads bytes. SQLite stays on the application thread.

The service holds the local device lock for its lifetime. Explicit disconnect
releases TCP and disables reconnect; `/exit` releases local ownership. Unexpected
loss invalidates observations and pending commands. Reconnect performs handshake
and fresh reads only; no selection, toggle or mode write is replayed. Search
failures leave controls available. See the implemented
[M2c contract](../docs/architecture/playback.md#m2c-persistent-device-session).

Existing one-shot commands keep their bounded connection lifecycle and JSON/exit
status contract for scripts and cron. Their initial connection refusal is retried
within the timeout before handshake/mutations; established one-shot sessions are
not reconnected. They require the interactive process to release the shared
ownership lock before device access. Offline search/index/status remain independent.
The request/decision journal now retains bounded local evidence, including operation
IDs and outcomes. It is not an IPC endpoint, replay mechanism or listening-history
collector. See the [journal contract](../docs/guides/history.md).

Explicit continuous context has two named mutation phases, mode then selection;
each allows at most one write and reports partial results. Controls never change
mode. The persistent client caches handshake only within its current connection,
retains interleaved events and applies the same fresh-state/source checks.

Russian and English metadata/aliases are searchable independently of the device's
UI language. Typed play requests now use lexical ranking and fresh selection verification.
The owner deferred dialogue/confirmation: `ask` launches the best result; `rank`
shows the same ordering without playback. See the
[command table](../docs/guides/commands.md).

`[language].locale = "ru"` is the initial default. `/language CODE` and startup
`--language CODE` persist one locale for both interpretation and responses.
`/language reset` stores the configured default. Old language lists migrate using
their first entry. Literal language-switch commands use the same settings handler.
Music names remain unrestricted; metadata version markers are independent of the
interaction locale. See the [architecture](../docs/architecture/pipeline.md).

The reusable device core is now in [Controller](../../../controller/docs/api.md):
receiver/reconnect, scan/state reduction, pagination, controls, mode readback and
queue/selection verification. Assistant supplies storage ownership and policy;
Controller imports no research/application modules. Explicit `experiments.disc_assistant` imports identify the current application namespace.

## User responses and locale contributions

Every traced result includes a `response` object with `code`, nullable localized
`text`, `language`, `speak` and reserved `interactive: false`. Console and one-shot
commands share the policy; the journal records the generated reply and template
provenance. Defaults are Russian replies and speech eligibility for problems only.
`/language en` changes input/output together; `/response mode all` changes speech eligibility.
Optional Piper browser replies are implemented; dialogue remains disabled. See the [response contract](../docs/reference/responses.md).

Community locales consist of command and response TOML catalogs. Follow the
[contribution guide](../docs/reference/locales.md), then run `/locales` or the
standalone validator. No runtime Python registry edits are required.

The browser entry point is `run.sh web --bootstrap`; see [Disc Assistant Web](../docs/guides/web.md). It owns the same device lock as the console.
