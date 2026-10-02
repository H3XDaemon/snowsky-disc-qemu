# Disc Assistant research prototype

> Historical snapshot preserved during the 2026-09-21 documentation refactor
> from source revision `9bfdbc4`. Dates, results and instructions below describe
> their original checkpoints; they do not authorize new work or define current status.
> Use the [current page](../../README.md) for active guidance.

Start with the [command quick guide](../guides/quick-guide.md).
Language understanding is organized under [assistant/nlu](../../assistant/nlu/README.md).


**Software MVP accepted (2026-09-19):** all 64 declared emulator scenarios passed.
See [acceptance evidence and reproduction](2026-09-19-mvp-acceptance.md).
Physical-device and human-speech/performance acceptance remain separate follow-ups.

Desktop prototype: **device catalog → SQLite → Typesense → ranked text commands → playback**.
The experiment lives entirely here until it is ready for promotion into the main
project. The [plan](../roadmap.md) describes the wider assistant/dock work.
It runs independently of the emulator and uses the shared
[Controller session/state API](../../../../controller/docs/api.md) and guarded device helpers.
Language, catalog/search policy and the request journal remain in this prototype.

- [assistant/](../../assistant/README.md): configuration, one-shot CLI and a persistent interactive session.
- [Disc Assistant Web](../guides/web.md): separate browser UI, text/microphone input and optional Piper replies.
- [library/](../../../../library/README.md): complete catalog reads, snapshot storage and search.
- [check.py](../../check.py): disposable acceptance with synthetic TCP/HTTP servers and a
  real Typesense container. No firmware or physical device is needed.

`search` returns metadata candidates. `rank` explains the ordering for a typed
`Включи …` / `Play …` command without playback; `ask` launches its best matching
artist or track after fresh device checks. The owner deferred interactive choice:
there is no confirmation prompt, including for fuzzy matches. [Browser text/microphone input](../guides/web.md) is available with
`./experiments/disc_assistant/run.sh web --bootstrap`. The owner reports successful
microphone play/stop on a physical player; quantified acceptance, listening history
and lyrics remain pending.
See the [command table and ranking policy](../guides/commands.md).
Localized [user responses](../reference/responses.md) include text, speech
eligibility and reserved dialogue metadata. [New locales](../reference/locales.md)
can be contributed as TOML catalogs without runtime Python changes.

## Run on a computer

Use Python 3.11+ and Docker with Compose. The entry point is
[run.sh](../../run.sh), independent of the root emulator launcher. No virtualenv
activation or exported secret is needed. From the repository root:

```sh
./experiments/disc_assistant/run.sh setup
# Or install the full web runtime with Whisper Server and Piper RU/EN:
./experiments/disc_assistant/run.sh setup --all
```

For Typesense exit 139 on vendor kernels without `/proc/self/io`, use the explicit
[I/O accounting compatibility option](../guides/typesense.md).

To compare Whisper decoder/thread/model choices on fixed recordings without
controlling a player, use [speech-benchmark](../evaluation/speech-benchmark.md).
Uncertain playback results now include [queue mismatch evidence](../guides/queue-diagnostics.md)
when a queue guard fails.

`setup` creates `assistant/.venv` if missing, installs the pinned requirements,
creates `~/disc-assistant.toml` if missing and generates a private search key in
`assistant/.env` if missing/empty. Existing config and keys are preserved. The key
is never printed. Edit the generated TOML before connecting to your player:

```toml
[device]
key = "my-snowsky-disc"
host = "192.168.1.50" # Replace with the actual player IP.
tcp_port = 12100
http_port = 12103
```

The template initially targets the emulator at `127.0.0.1`, HTTP **12113**;
physical DISC normally uses HTTP **12103**. Choose a distinct persistent
`device.key` per device. It is a user-assigned namespace, not a discovered serial
number. Both HTTP and TCP must point to the same device.

For microphone input and spoken replies, use `setup --all`, then
`./experiments/disc_assistant/run.sh web --bootstrap`. Web always uses Whisper Server.
Enable sound on the page; choose All available replies to hear successful controls.
See [speech setup and lifecycle](../guides/tts.md) for models, services,
config backup and external engine options.

Start the complete text-console flow:

```sh
./experiments/disc_assistant/run.sh start
```

The launcher starts local Typesense and waits for readiness, then one foreground
application connects to DISC, synchronizes the catalog, prepares the index and
opens a text console. Enter commands directly, without `ask` or shell quotes:

```text
local-disc-emulator> /device
local-disc-emulator> /language ru
local-disc-emulator> /response mode errors
local-disc-emulator> Включи Linkin Park - Numb
local-disc-emulator> Пауза
local-disc-emulator> Продолжи
local-disc-emulator> /queue
local-disc-emulator> /status
local-disc-emulator> /exit
```

The prompt uses your configured `[device].key`; `/device` shows its key, address,
ports and current connection state. It remains available while disconnected and
does not switch targets. For another device, launch with its own `--config` file.
Simultaneous consoles also need distinct `[storage].data_dir` values because the
existing process ownership lock is scoped to that directory.

Use `./experiments/disc_assistant/run.sh listen` to open the same console with the
existing snapshot/index, without Docker startup or automatic sync/index. This is
text input; microphone capture is not implemented yet. `/help` lists console
commands. `/language ru` or `/language en` selects one language for commands and
responses and saves it for later sessions. `/language reset` stores the configured
default. Natural commands such as `Переключи язык на английский` use the same
handler. `/response mode none|errors|all` controls future speech eligibility only.
Explicit file synthesis and transcription are available; automatic spoken replies
and dialogue remain pending. `/locales` checks installed catalogs.
`/sync` refreshes the catalog; `/index` rebuilds search after changes.

To explicitly select and persist English at startup:

```sh
./experiments/disc_assistant/run.sh --language en listen
```

See [architecture and migration](../architecture/pipeline.md) for interpreter,
speech provider and single-locale contracts. Music metadata remains multilingual.

File-based voice input is now available before microphone work:

```sh
./experiments/disc_assistant/run.sh --language ru synthesize 'Пауза' --output /tmp/disc-pause.wav
./experiments/disc_assistant/run.sh transcribe /tmp/disc-pause.wav
./experiments/disc_assistant/run.sh rank --audio /tmp/disc-pause.wav
./experiments/disc_assistant/run.sh ask --audio /tmp/disc-pause.wav
```

Install/configure the external STT model/executable first; TTS currently uses
macOS `say`. Only `ask` executes the command. In the console use `/transcribe FILE`,
`/rank --audio FILE` or `/ask --audio FILE`. Corpus generation, evaluation,
format limits and known recognition errors are documented in
[ASSISTANT_VOICE.md](../guides/voice.md). No microphone or spoken reply
delivery is implemented yet.

The terminal uses `prompt_toolkit`: Up/Down recall, Ctrl-R history search, Tab
completion, history suggestions accepted with Right, and Ctrl-L or `/clear` to
clear the screen. `/help` is readable multiline text. Ctrl-C while editing cancels
the input; Ctrl-D on an empty line exits. Recall reuses this device's interactive
request journal, subject to retention, with up to 1,000 entries and no separate
history file. Disabling journaling keeps only session history. `/history clear
--yes` clears saved and editor history; clearing the screen preserves it.
Redirected input/output and `TERM=dumb` keep the plain scripting interface.
After updating an existing checkout, rerun `run.sh setup` to install new pinned
dependencies, then restart `listen`; existing config and keys are preserved.
Prompt, input, results and errors use separate colors. The optional `[terminal]`
section customizes styles; `NO_COLOR=1` disables colors. Font family/size belong
to your terminal's settings. See [terminal appearance](../guides/commands.md#terminal-appearance).

Use `/debug on` to stream request stages and search diagnostics, `/debug off` to
stop, or launch with `run.sh --debug listen`. For a playback-free diagnosis, use
`/rank Включи Макс Корж`. One-shot `run.sh --debug rank 'Включи Макс Корж'` keeps
the JSON result on stdout and traces on stderr. Traced results include
`timing.total_ms` and `request_id` even with journal collection disabled; IDs alone
do not guarantee saved history. Debug is session-only and follows the `debug`
terminal color. See [timing boundaries and trace fields](../guides/commands.md#timing-and-live-debug-traces).

The application owns one TCP socket and continuously receives events, including
while waiting for input or doing HTTP/search work. Unexpected disconnects trigger
bounded reconnect and fresh observations, never command replay. Commands submitted
while disconnected fail rather than waiting to play later. `/disconnect` disables
reconnect and releases TCP for FiiO Control; `/connect` enables it again. `/status`
shows connection state and the latest observations. The local data-directory
ownership lock stays held until `/exit`, EOF or interruption during an operation.
In plain input mode, Ctrl-C also exits immediately. Exiting leaves native
playback and Typesense running; use `down` separately to stop search.

Search startup/index failures leave the console available for playback controls.
An unavailable player does not block the console indefinitely: inspect `/status`
and retry `/sync` then `/index` after connection recovery. Startup and `/sync`
reuse an identical snapshot only after two complete equal network reads. Startup
also checks the matching Typesense collection and document count before reusing
it; a missing collection is rebuilt. Explicit `/index` always rebuilds.

### One-shot commands and scripts

The existing flow remains available for scripts and future cron jobs, with JSON
results and nonzero failure exit codes. One-shot device commands (`sync`, `queue`,
`ask`) require the console to exit first when sharing its data directory. Offline
`status`, `search`, `rank` and `index` can run independently. There is no IPC forwarding
or automatic replay of a failed cron command.

```sh
./experiments/disc_assistant/run.sh up
./experiments/disc_assistant/run.sh sync
./experiments/disc_assistant/run.sh status
./experiments/disc_assistant/run.sh index
./experiments/disc_assistant/run.sh search 'Linkin Park Numb'
./experiments/disc_assistant/run.sh search 'линкин парк намб' --limit 5
./experiments/disc_assistant/run.sh --language ru rank 'Включи линкин парк намб'
./experiments/disc_assistant/run.sh --language ru ask 'Включи линкин парк намб'
```

`up` starts the separate local `disc-assistant` Typesense stack and waits up to
45 seconds for HTTP readiness after Compose startup. It uses `[typesense].port`
from TOML, including for the Docker port publication. The legacy `TYPESENSE_PORT`
in `.env` is used only by manual Compose invocations. Change the TOML port if 8108
is occupied. Remote Typesense can be used by index/search; `start` checks its health without
starting Docker, while `up` only manages local HTTP Typesense. No CORS or LAN port exposure is enabled.

For a different configuration, place the option **before** the command:

```sh
./experiments/disc_assistant/run.sh --config /absolute/path/disc.toml setup
./experiments/disc_assistant/run.sh --config /absolute/path/disc.toml sync
```

Alternatively set `DISC_ASSISTANT_CONFIG`. Relative config paths resolve against
the calling directory. The script can be invoked by absolute path from anywhere.

The runner always calls `.venv/bin/python`, bypassing aliases such as
`alias python=/usr/bin/python3`. It selects an installed Python 3.11+ when creating
the environment; override with `DISC_ASSISTANT_PYTHON=/absolute/path/python3`.
An existing incompatible environment is reported instead of being silently deleted.
See `./experiments/disc_assistant/run.sh help` for commands.

The `.env` supports literal `TYPESENSE_API_KEY` and `TYPESENSE_PORT` assignments
with optional quoting/comments. It is parsed as data, never sourced as shell code.
The local key takes precedence over a previously exported default key. A custom
`api_key_env` in TOML selects that environment variable instead. Keep keys out of
browser code and committed files. The underlying Python CLI remains available
through the explicit venv interpreter and does not itself load `.env`.

`sync` needs an awake, idle V2.57 DISC with its media library already scanned.
Disconnect FiiO Control/other TCP inspectors first; stock control is single-client.
It reads metadata only, without scanning, reset, file edits or playback. It publishes
SQLite only after two equal full reads. `index` and `search` need Typesense but no
connection to the player. `rank` resolves exact metadata locally and uses Typesense
for fuzzy track retrieval. `ask` also requires the awake player, sends at most one
selection and verifies the resulting metadata/state and native queue. Volume is
unchanged; play mode is preserved unless `playback.continuous_context=true` explicitly
enables repeat-list mode. Mutations are never automatically retried.
`status` reads local state without contacting either
service; `index_current` means matching locally recorded generations/config,
not a live Typesense health check. Commands return JSON; failures exit nonzero.

Controls and queue observation bypass search and catalog storage:

```sh
./experiments/disc_assistant/run.sh --language en rank 'Pause'
./experiments/disc_assistant/run.sh --language ru ask 'Пауза'
./experiments/disc_assistant/run.sh --language en ask 'Resume'
./experiments/disc_assistant/run.sh --language en ask 'Next track'
./experiments/disc_assistant/run.sh --language en ask 'Previous track'
./experiments/disc_assistant/run.sh --language en ask 'Stop'
./experiments/disc_assistant/run.sh queue
```

`Stop` means pause with position/queue retained; no separate hardware stop is
claimed. Already-satisfied pause/resume/stop sends nothing. Unknown current state
blocks blind toggles. Previous selects the preceding queue row at any elapsed
position; first row is a no-op. Native Controller previous retains its restart shortcut.
See the [command contract](../guides/commands.md).

To continue through the end of the selected album/artist context, opt in in your
personal TOML (existing configs preserve the player's mode):

```toml
[playback]
continuous_context = true
```

This sets persistent device mode 3 before a music selection and verifies it.
`mode_change` reports that separate operation even if selection later fails;
there is no automatic rollback. `ask` reports the actual native queue and
continuation policy. A one-track context repeats. Recommendations from other
albums and arbitrary ordered queue construction remain future work. No host
process is needed for the native queue to continue after CLI exit.

Search returns the observed title, artist, album, matched fields/tokens, a ranking
score and snapshot provenance. The score is **not a confidence percentage**.
Duplicates remain separate candidates, including identical CUE rows. Explicit
aliases are configured locally; there is no automatic transliteration claim.
Query token dropping is disabled so a missing title is not silently replaced by
an artist-only result. One-shot `sync` always publishes a new generation and makes the old projection
stale until `index` finishes successfully. Console `/sync` does so only when the
snapshot content changes. Changed aliases/search server also require reindexing.

## Data and limitations

The SQLite file is `library.sqlite3` under `[storage].data_dir`, defaulting to:

- macOS: `~/Library/Application Support/disc-hub/prototype/`.
- Linux: `${XDG_DATA_HOME:-~/.local/share}/disc-hub/prototype/`.
- Windows: `%LOCALAPPDATA%/disc-hub/prototype/`.

Assistant preferences live alongside the catalog in `assistant.sqlite3`, in a
versioned `settings(key, value_json, updated_at)` table. The canonical settings are
`language.locale` and `response.mode`. Legacy split-language settings migrate
atomically, preferring the first old input language over the old response locale. It applies to the application data directory, across devices
and configs using that directory; use different directories for independent
profiles. Saved values override TOML defaults; `--language CODE` overrides and persists locale. Device endpoints, credentials and
operational limits remain in TOML/environment, not in this preferences table.
One-shot `run.sh language [CODE|reset]` manages the same setting without search
or a device connection. An already-open console reloads external changes through
`/language` or on restart. Catalog sync/index rebuilding does not erase preferences.
Back up both SQLite databases; language selection does not create a catalog. Schema 2 additionally stores the
request/decision journal in `requests` and `request_events`, preserving existing
settings. Listening intervals are not collected yet.

An override must be absolute (or start with `~`) and outside the repository.
New data directories are private to the user. Back up SQLite with all prototype
processes stopped, or use SQLite's online backup API. Keep the TOML alias config
with the backup. Typesense lives in the separate `disc-assistant_typesense-data`
Docker volume and can be rebuilt using `index`, even when DISC is offline.

A snapshot is a complete **observation**, not an atomic device revision. Stock API
pagination has no revision token. Two equal reads catch many races but cannot
prove that a scan was not already underway or that no edit happened between
checks. Only confirmed scan notifications block it: `a60a/000F` (start), `a622` (count),
and `a60a/0005` (end) if received during the reads. An end received before the reads
allows a new observation, without claiming that a cancelled scan was complete.
Other `a60a` statuses such as initialization `0010` are not scan evidence; an already-running scan may be
missed by the existing diagnostic client. Only sync while the player is idle.
One-shot playback retains events across Controller queries for its bounded
operation. The interactive session also receives events while idle and remembers
observed scan activity for later operations. Scans that began before connection
can still be missed; cross-application coordination remains deferred.

Tracks carry a new internal ID **per snapshot** plus the literal `album/song`
scope/position/raw row. Identity continuity across rescans is deliberately not
claimed: the API does not expose enough information to distinguish every CUE or
duplicate recording. These IDs/positions cannot be used as cached playback commands. `ask` recomputes
the current artist-scoped position; metadata-identical copies use the first current
row and are reported as such, rather than claiming permanent recording identity.
No history reconciliation is implemented yet.

If any page fails, counts/positions change, album/root membership differs, the
request/track budget is exceeded or publication loses a concurrent-import race,
the previous snapshot survives. Unsupported catalog shapes fail explicitly;
there is no guessed album fallback. Settings gate the prototype to reported
`soc_version=257`; they do not provide a verified device-language getter.

Imports are staged in bounded memory. SQLite retains old snapshots; successful
index attempts retain old collections. Failed attempts remove only their own
new collection when possible. Automatic pruning/migrations beyond schema 1 are
not implemented; monitor storage during repeated experiments. Do not run an
unbounded sync/reindex loop. Interrupted indexing may leave an unreferenced
collection; a fresh `index` never reads it. Cleanup/retention is a promotion task.

Stop Typesense with:

```sh
./experiments/disc_assistant/run.sh down
```

`down` keeps the index volume and also works if the TOML/key is missing. The
runner does not expose volume deletion. It never stops the emulator or deletes SQLite.

## Request history

Input, parsing, search candidates, ranking, automatic selection and operation
outcomes are now retained locally, including unrecognized phrases and failures.
Use the returned `request_id` to inspect a request; these are observations, not
proof of completed listening or a queue of commands to replay.

```text
/history
/history show REQUEST_ID
/history export "/absolute/path/request history.jsonl"
/history clear --yes
```

One-shot `run.sh history` has the same commands. For cron attribution, run
`run.sh --source scheduled --language en ask 'Pause'`. Collection defaults to enabled with
90-day retention and 10,000 completed requests. Configure `[journal].enabled`,
`retention_days` and `max_requests` in TOML. Restart the console after config/code
updates. See the [journal contract](../guides/history.md) for migration,
bounded evidence, export, retention and interrupted-operation semantics.

## Verification and promotion

Unit tests use the standard library, without a device, Docker or search server
(after `setup`, the runner uses its venv). They can also run directly with
`python3 -B -m unittest discover -s experiments/disc_assistant -t . -v`:

```sh
./experiments/disc_assistant/run.sh test
```

Explicit acceptance uses the prototype venv and a locally available server image:

```sh
docker pull typesense/typesense:30.2
./experiments/disc_assistant/run.sh check
```

The check starts a unique disposable Compose project on an ephemeral loopback
port, tests the real CLI/controller/SDK path, then removes its servers, temporary
SQLite database and index volume. It covers exact, typo, Cyrillic-alias, album,
duplicate/CUE and missing queries, index loss/rebuild and catalog/index lag.
This is a small functional fixture, not a ranking benchmark for a personal library.

Validation on 2026-09-17: the firmware-free project suite and prototype unit
tests passed (39 prototype tests), as did the disposable Typesense acceptance above. Read-only CLI
`sync`/`status` also passed against the interactive V2.57 guest with an empty
catalog. A later read-only check on the configured physical V2.57 DISC imported
792 rows through two equal full reads into a disposable SQLite database, then
removed it. This also reproduced `a60a/0010` after connection and verified the
fix that classifies scan events by payload rather than treating all `a60a` as scans.
The owner subsequently confirmed successful `sync → index → search` against
the physical player. The read-only slice is ready for the next implementation
step. On 2026-09-18, `rank`/`ask` added bilingual commands, deterministic lexical
ranking and fresh Controller playback checks. Command/target/version phrases now
live in per-language TOML dictionaries; the later architecture increment selects
one `[language].locale` for input and output
(default `["ru", "en"]`); the 97-test checkpoint covered controls,
queue observations and partial mode/selection failures. A
read-only alias query on the existing physical-library snapshot resolved correctly.
The owner chose automatic best-match
playback and deferred clarification. Measured ranking quality and physical `ask`
playback remain unvalidated; microphone input follows the text-to-playback path.

Full text-to-device scenario automation with real Typesense is now available:

```sh
bash ci/assistant.sh /absolute/path/to/main_os/ota_v257 /tmp/assistant-run-01
```

This opt-in runner creates a disposable guest/search stack, runs 46 RU/EN cases
with independent state/queue checks, and retains reports/screenshots in the new
output directory. See [scenario instructions](../evaluation/emulator-acceptance.md)
for selected cases, known failures and adding fixtures. It does not use personal
settings, libraries or the physical player.

The older focused firmware acceptance uses a fresh V2.57 stack and generated audio:

```sh
./experiments/disc_assistant/emulator_check.sh /absolute/path/to/main_os/ota_v257
```

It never uses the interactive work volume or personal SD contents. The check covers
controls, native artist-album queues and natural EOF across five modes. It requires
the `snowsky-disc-qemu-ci` image; optional `ASSISTANT_LOGS` retains guest logs outside
the checkout or under ignored `work/`. Synthetic `run.sh check` also covers controls
without search credentials/current index and explicit continuous-context mode.

An earlier generated-media guest check passed on 2026-09-18: controls, native
previous/restart before and after ten seconds, native continuation after disconnect, and type-7 natural
EOF in all five modes. Physical-device acceptance remains separate.

The persistent-session increment passed 116 prototype unit tests (114 in the
full firmware-free run, plus focused interrupt/reconnect rejection tests), together with
313 shared Python and 37 JavaScript tests. Disposable Typesense acceptance checks
`start → sync/index → console`, one handshake/socket across commands, unchanged
snapshot/index reuse and reconstruction of a missing collection. A focused guest
check is available without repeating the five-mode acceptance:

```sh
./experiments/disc_assistant/emulator_check.sh /absolute/path/to/main_os/ota_v257 persistent
```

It passed on V2.57 with generated media: shared sync/control/queue session,
unsolicited track changes while idle, observation-only reconnect, final EOF with
silent `0202` on a healthy connection, and explicit disconnect staying disconnected.
Physical sleep/Wi-Fi recovery, FiiO Control competition and live audio remain
separate acceptance work. No physical playback was exercised by this increment.

The prototype suite is intentionally run explicitly; `ci/unit.py` has not been
changed to discover this experimental directory. Before promotion, register its
component tests in shared CI, broaden physical-catalog coverage and establish
resource/ranking baselines and decide the stable storage/API
contract. Then move the reviewed assistant/library components and update imports,
entry points, docs and CI together. Promotion does not require splitting repositories.


## Optional NLU and vector research

The separate [NLU experiment](../../assistant/nlu/evaluation/README.md) compares rules, character
matching and local multilingual embeddings on frozen authored RU/EN phrases,
plus real Typesense lexical/vector/hybrid retrieval against synthetic metadata.
It uses explicit isolated dependencies/model preparation and read-only reports;
normal `run.sh start`/`ask` behavior and requirements are unchanged. The guide
contains reproduction commands, measured results and remaining limitations.

The [command catalog and explanation preview](../reference/command-catalog.md)
add `run.sh explain TEXT` / `/explain TEXT` and `commands [rebuild|import FILE]`.
They keep locale examples, reference vectors and optional trained text classifiers
in versioned Assistant SQLite snapshots. They require no new runtime dependencies
and never change the executing interpreter. The supervised study and import
instructions are linked from that guide.

For reviewed command data and training, see the [v2 workflow](../evaluation/nlu-data.md):
private history queues, explicit annotation, immutable dataset snapshots and a
four-way supervised comparison. Current model results remain diagnostic; live
execution and independent human/Pi acceptance remain separate steps.
[Independent sources and optional shadow comparison](../architecture/interpretation-sources.md)
are now implemented: `/shadow on` records comparisons, `/debug on` displays them,
and `/explain TEXT` previews each source without execution. The primary still
executes commands. MVP scope is one action per request; complex commands are deferred.


## Offline shadow reports and current MVP gate

After collecting with `/shadow on`, export `/history export /tmp/disc-history.jsonl`.
Then run the following from a shell; no runtime config/device is needed:

```sh
./experiments/disc_assistant/run.sh shadow-report \
  --history /tmp/disc-history.jsonl --output /tmp/disc-shadow-report
```

The new private directory contains readable/JSON reports, source evidence and a
pending annotation queue. `--review-scope all` includes agreeing inputs;
`--reviewed PATH` computes quality from explicit reviewed annotations.
See [workflow and denominators](../evaluation/shadow-reports.md).

[The MVP](../reference/mvp.md) is input through execution on DISC with
agreed error limits. First measure the baseline, then agree thresholds. The
[MVP checklist](https://github.com/eudj1n/snowsky-disc-qemu/issues/21) distinguishes
implemented work from acceptance; [AGENTS.md](../../AGENTS.md) supports session handoff.
Further component improvements are separate tasks.


Semicolon-separated artist credits now expose individual members for search and
ranking while retaining literal device selectors. After upgrading, restart the
console and run `/index`; an existing SQLite snapshot needs no `/sync`. See the
[Library metadata policy](../../../../library/README.md#multiple-artist-credits).
