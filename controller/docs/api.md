# Shared Controller session API

Implemented on **2026-09-18** for reviewed DISC **V2.57**. Assistant and a future
software remote can share connection/state/control behavior without interpreting
wire tags. This is an in-process Python API, not a new HTTP server or IPC daemon.

## Ownership and boundaries

| Layer | Owns |
| --- | --- |
| `controller.fiio_link`, `fiio_http`, `fiio_ws` | Existing diagnostic transport APIs, codecs and guarded stock operations |
| `controller.events`, `device`, `catalog` | Partial state reduction, scan guards, sequential event-preserving operations, bounded HTTP pagination |
| `controller.controls`, `playback`, `queue` | State-aware control, explicit mode readback, fresh selection verification and native queue observations |
| `controller.session`, `models` | One persistent receiver, serialized operations, reconnect without replay, normalized immutable snapshots/results |
| Assistant / application adapters | Language and intent, catalog persistence and ranking, automatic match policy, request journal, preferences and recommendation policy |
| Future application backend | One session shared by its adapters; browser authentication, HTTP/WebSocket presentation and optional local IPC |

Controller imports no Assistant, research, emulator, viewer or firmware components.
`DeviceConfig` contains only the device endpoint and transport/read budgets, with
physical ports 12100/12103 by default. Device compatibility is checked from the
remote handshake and reported version, not a local firmware profile.

The stock player accepts one TCP client. A reusable class does not allow separate
Assistant/remote processes to own simultaneous connections. A backend should own
one `DiscSession` and share it with its adapters. Optional `ownership=` accepts an
application-provided context manager held for the session lifetime; Controller
does not create lock files or select a personal data directory. Assistant keeps
its existing data-directory lock and thin configuration adapter in research.

## Use

Run from the repository root or install the standalone Controller wheel;
no search server or Assistant database is needed:

```python
from controller import DeviceConfig, DiscSession, OperationStatus, PlayMode

config = DeviceConfig("192.168.1.50")  # Select the actual player explicitly.
with DiscSession(config) as device:
    device.connect()
    if not device.wait_ready(35):
        print(device.snapshot().to_dict())
    else:
        print(device.snapshot().playback.track)
        result = device.play_artist("Linkin Park", album="Meteora", index=0)
        if result.status == OperationStatus.PLAYING:
            print(device.queue().queue)
        print(device.pause().status.value)
        print(device.resume().status.value)
        # Optional explicit persistent setting; ordinary selections preserve mode.
        # device.set_play_mode(PlayMode.REPEAT_LIST)
```

The context owns receiver/connection-worker lifetime. Use `connect`/`disconnect`
inside that lifetime; create a new instance for a new target or process lifecycle.
Connection is asynchronous. `wait_ready` provides a bounded startup wait; ordinary
commands fail `not_sent` when not ready rather than waiting to execute after recovery.
Exit closes the link without stopping playback or restoring settings.

| Method | Contract |
| --- | --- |
| `connect()` | Enable connection and observation-only recovery |
| `disconnect()` | Close TCP, discard connection observations and disable recovery; application ownership remains until context exit |
| `wait_ready(timeout)` | Return whether initial acquisition reached ready before the deadline |
| `snapshot()` | Cached immutable `DeviceSnapshot`; no network read or mutation |
| `current_track()` | Fresh read-only observation; returns `observed` or `unavailable` when current playback cannot be established |
| `set_favorite(bool)` | Fresh identity/favorite checks, one write if needed, verified readback |
| `set_volume(value)` / `adjust_volume(delta)` | Absolute 0..120 or nonzero relative adjustment; fresh readback, clamp relative requests, no-op at the limit |
| `pause()` / `resume()` | Read fresh state, toggle only when necessary and verify the same recording context |
| `next_track()` / `previous_track()` | Send once, verify observed track change or progress rollback; previous after >10 seconds can restart |
| `control(action)` | Equivalent named pause/resume/next/previous dispatch; unsupported actions raise `ValueError` |
| `set_play_mode(mode)` | Accept `PlayMode` or its string value; read/set/read back once; already satisfied sends nothing |
| `queue()` | Read the full native queue twice under budgets, preserve duplicate rows and check mode/state consistency |
| `play_artist(artist, album=None, index=None)` | Read a fresh named source twice, check the final row, select once, then verify playback/queue; indexed playback requires an album |

Artist and album names are literal. This API does not search, rank or resolve
aliases. Indices are zero-based positions in the current artist-album source,
not permanent IDs or cached search offsets. Album Play all also verifies the
reported album. No atomic device revision exists, so external edits can still race
reads and mutations. Queue observation likewise is not a lease on its positions.

Physical playback reported on 2026-09-18 exposed different album text between
HTTP catalog and now-playing metadata: the latter can contain only a prefix of
the full catalog name. Confirmation accepts that difference only when two fresh
`artist/album` reads agree and the requested full name is the only name compatible
with the nonempty prefix. Title, artist, playing state and type-7 source remain
exact; the full native queue is checked and indexed playback must report the
requested position. A final state read follows the extra album queries. Ambiguous
prefixes, changed catalogs/queues and other metadata differences remain uncertain,
with no replay. No fixed truncation length or universal ID mapping is assumed.

## Normalized data and outcomes

`DeviceSnapshot` contains connection state, enabled flag, connection generation,
latest `PlaybackSnapshot` and any connection error. Connection states are
`disconnected`, `connecting`, `ready`, `reconnecting`. Playback states are
`unknown`, `loading`, `playing`, `paused`, `stopped`. Final stop requires observed
completion evidence; a missing reply or a loading snapshot alone cannot prove it.

`Track` exposes `title`, `artist`, `album`, and optional zero-based
`queue_position` and optional device media `path`. These are observed metadata,
not a permanent recording identity; CUE entries can share a media path.
`PlaybackSnapshot` additionally holds optional position in milliseconds, named
play mode, scan activity, observation time, favorite flag and named playback source. Missing fields remain unknown.
Snapshots are detached immutable dataclasses; receiving another push cannot
mutate a previously returned snapshot. `to_dict()` on the top-level snapshot or
result is JSON-serializable, with string enum values through `json.dumps`.

`QueueSnapshot` contains immutable ordered `QueueItem` entries, selected position,
named mode, continuation policy and playback observation. Duplicate/CUE entries
stay separate. A retained queue after EOF does not establish active playback.

`CommandResult` provides an operation ID, action, `OperationStatus`, mutation-attempt
flag, playback observation, optional queue/outcome/reason, and requested/previous
mode for mode changes. Volume operations retain `volume` and `previous_volume`;
failures may carry `error_type`. Optional `confirmation.queue` preserves bounded evidence
of a failed queue guard (observed/expected fields and mismatch codes); see
[queue diagnostics](../../experiments/disc_assistant/docs/guides/queue-diagnostics.md). Statuses are `not_sent`, `uncertain`, `confirmed`,
`already_satisfied`, `playing`, read-only `observed` and `unavailable`. `playing` verifies device
metadata/state, not audible output. An error after a possible write is uncertain;
never automatically repeat it. Operation results can have fewer fields than the
cached session snapshot; unknown state is not fabricated from earlier success.

The receiver continuously updates state, including while a caller blocks on HTTP,
search or user input. Adapters can read cached snapshots independently; a callback
subscription or browser event endpoint is not part of this first public surface.
Do not implement a second raw socket reader in a presentation adapter.

## Protocol and concurrency guarantees

The persistent core retains the prototype's single receiver, tagged-query
serialization, connection-generation checks, bounded event buffer, 2.1-second
mutation pacing and per-operation mutation guards. EOF/loss invalidates pending
work; reconnect repeats handshake and fresh observations only. Explicit disconnect
suppresses reconnect. Health reads use mode every 30 seconds when operations are
idle, with capped backoff/jitter after loss. Physical sleep/Wi-Fi behavior remains
a separate acceptance question.

`PlaybackClient` and the persistent client share `MutationPacer`. New connections
start one conservative 2.1-second interval because prior device activity is
unknown; handshake/read time counts toward it. Later operations wait only for
the remaining interval since an actual mutation attempt. Reads and rejected
replays do not extend it, and an idle session has no fixed per-command sleep.
Waits precede fresh state/catalog validation; the socket enforces the same deadline
as a backstop and marks attempts before I/O, including failed writes. Persistent
waits are interrupted by disconnect and cannot dispatch on a replacement connection.
This does not coordinate external physical-button activity or provide atomic
firmware state; normal confirmation and uncertain outcomes still apply.

The persistent session is currently **TCP only**. Existing diagnostic TCP/WS/HTTP
APIs remain available and compatible; they do not acquire these new lifecycle or
state guarantees automatically. Extending the facade to other transports or
settings requires its own tests and declared outcome semantics.

`status()` and `operation()` remain advanced adapter interfaces for Assistant's
existing output and fresh catalog-selection workflow. The operation lease pins a
client/generation and serializes work; callers must not retain the client beyond
the lease, nest operations, read its socket or construct an unreviewed mutation.
Its outbound persistent surface admits the reviewed reads and playback/mode,
favorite, volume, four sound settings and exact scan-start mutation tags only. `LiveClient` inherits narrow shared
command implementations, not the raw `Client`; reset/cancel and unrelated settings writes remain
absent. `PlaybackReader`, `ControlClient` and `SelectionClient` describe the
capabilities required by guarded operations. Use facade methods for new application features; do not
expose arbitrary tag forwarding through a web endpoint.

There is no native `stop()` in this API. Assistant maps its Stop intent to pause
while preserving position/queue. Repeat-list opt-in is likewise Assistant policy;
Controller only executes an explicitly requested named mode. History, preferences,
search results and automatic recommendation launches are not Controller features.

## Sound settings

`sound_settings(expected_generation=None)` returns an observed `CommandResult`
with `confirmation.settings` containing `gain`, `balance`, `filter` and `dre`,
and `confirmation.soc_version` from fresh identity readback. Values are strictly
validated: gain/DRE 0 or 1, balance -20..20 (L20..center..R20), filter 0..5.
Filter names are `FAST_LL`, `SLOW_LL`, `SLOW_PC`, `FAST_PC`, `NON_OS`, `Wideband_FF`.
The reviewed capability is explicitly enabled for V2.57 only.

`set_sound_setting(name, value, expected=current_value, expected_generation=None)`
waits for remaining mutation pacing, then checks identity, scan state and a fresh
setting value. A changed expected value returns `not_sent` / `sound_changed`.
An equal requested/current value returns `already_satisfied` without a write.
Otherwise one setter is sent and bounded fresh reads confirm the requested value;
the confirmation contains `name` and `value`. Missing/mismatched readback or loss
after dispatch is `uncertain`, never replayed. Invalid names/values are rejected
before I/O. No settings are automatically restored on disconnect.

These methods borrow the existing owner and do not enumerate Bluetooth devices,
identify a hardware output, expose PEQ or establish physical audio performance.
The wire mappings and earlier independent persistence evidence remain in
[remote settings](../../docs/protocol/remote-settings.md).

## Validation

The 2026-09-18 checkpoint passed 322 firmware-free Python tests (including nine
new session/boundary tests), 37 JavaScript tests and 142 Assistant prototype tests.
The disposable Typesense end-to-end check and generated-media V2.57 persistent
acceptance also passed. This checkpoint does not claim new physical-device validation.

The subsequent shortened-album fix passed 330 firmware-free Python tests, 37
JavaScript tests and 144 Assistant tests. Eight new Controller regression tests
cover corroborated prefixes, ambiguity, changing catalogs, wrong metadata/positions
and retained timeout observations. The generated V2.57 fixture independently
reproduces a shortened album in now-playing metadata; Assistant and the public
facade both confirm it through fresh catalog/queue evidence. The owner supplied
the physical failure and matching `/status`; physical revalidation of the fix is
still pending.

Controller unit tests use an independent synthetic wire peer and enforce the
production import boundary. They cover immutable state, one connection across
commands, idempotent pause/resume, uncertain writes, no replay, explicit disconnect,
final-stop silence, queue changes, named modes and rejection of unsupported operations.
Assistant regression tests preserve one-shot/console, Stop policy, ranking and
request-journal behavior. Synthetic wire fixtures deliberately retain raw tags;
they independently check the client rather than calling its encoders as a server API.

Generated-media V2.57 acceptance uses
`tests/integration/session_check.py`, invoked by the prototype's existing disposable
`emulator_check.sh OTA_PATH persistent` scenario. It exercises facade selection,
pause/resume, mode changes/readback, queue and normalized state on the same socket
as Assistant operations, then checks idle pushes, reconnect without replay and
healthy final-stop silence. It never uses personal media or the interactive volume.

## Complete named albums

`DiscSession.play_album(album, *, index=None, expected=None)` selects the complete native album across raw
artist credits and verifies fresh source membership and playback queue. Existing
`play_artist(artist, album=...)` selects only that artist's album scope. Shared
TCP/WS `play_album(album, index=None, http=...)` helpers use reviewed V2.57 type 3
with fresh source bounds, reject empty/reserved names and never retry mutations.
The session helper adds two equal source reads and final row identity protection.
The stock catalog has no release identifier or atomic revision token.


## Displayed selections and playlist editing

`play_album`, `play_artist` and `play_queue_index(index, *, expected=None)` accept
an immutable tuple of `QueueItem` rows from a previously displayed source.
Positions, titles and artists must still match the complete fresh source.
Indexed album selection verifies both the queue and selected track. Queue
selection also checks current identity and mode; ambiguous/stale state fails
before mutation. A missing expected snapshot retains the existing fresh-read
behavior for non-UI callers. Stock has no atomic revision token.

The V2.57 `playlist_edit` capability enables these session methods:

- `create_playlist(name)` and `rename_playlist(name, new_name)`.
- `add_playlist_track(name, index, *, expected, album=None)`, using all/song or
  a complete unscoped album source.
- `remove_playlist_track(name, index, *, expected)`, removing membership only.

Edits share the serialized session, pacing and scan guard. They re-resolve unique
names to fresh playlist positions, compare source/membership, send once and
verify readback. Duplicate/ambiguous tracks are rejected conservatively. Empty
HTTP 200 responses do not establish success; lost replies remain uncertain with
no replay. There is no public source-file deletion or playlist deletion here.
`tests/integration/web_session_check.py` exercises these operations on generated
media in disposable V2.57 `queue` and `full` CI scenarios.

## Catalog playback and seek

`play_playlist(name, *, index=None, expected=None)` resolves a unique current
playlist name, checks two equal source reads and rechecks names/members inside
the final low-level preflight. `play_catalog_track(index, *, favorites=False,
expected=None)` selects the original all-tracks/favorites position, never a song
ID or an index renumbered by a browser filter. Both accept displayed `QueueItem`
tuples and verify the selected track, source, queue membership and mark.
Unknown versions cannot inherit the V2.57 `catalog_playback` capability.

`seek(position_ms, *, expected: Track, source: PlaybackSource)` requires the
exact displayed track (including path, queue position and duration), a fresh
playing/paused state and a position before the known end. The `seek` capability
and observed socket enforce one paced `0103` attempt; reconnect never replays it.
`Track.duration_ms` is an optional validated stock duration, not an estimate.

During playback, confirmation requires a fresh `a103` in the requested
whole-second position window while the same track/source is still observed.
This is observation, not an atomic firmware acknowledgement. Paused seek returns
`uncertain` with outcome `seek_waiting_for_playback`: it clears cached position,
does not resume, and does not retry. `confirmation` retains requested/rounded
milliseconds. The browser separates requested preview from observed progress.
A later explicit resume may produce the first useful position tick.

Generated V2.57 FLAC acceptance covers both seek states and stale-track rejection.
This does not extend validation to SACD/CUE seek or hardware audio output.

## Audio import and explicit scan

`DiscSession.upload_audio(source, destination, *, on_progress=None,
expected_generation=None)` streams one local audio file to a child of
`/tmp/sdcard`. The reviewed V2.57 operation waits for mutation pacing, checks
current compatibility, rejects a cached transfer or case-insensitive name
collision, then checks scan/connection state immediately before its single HTTP
write. There is no overwrite option. Directory preflight/readback is bounded
at 100 pages. File size follows the stock 31-bit positive Content-Length limit.

The optional callback receives `(bytes_read, total_bytes)` while HTTP consumes
the source; this is transfer progress, not device acknowledgement. A confirmed
result additionally requires completed stock progress with the exact size and a
fresh directory entry. Empty HTTP 200 or cached progress alone is insufficient.
`outcome=destination_exists` is a non-sent collision. Interrupted writes or failed
readback are uncertain and never retried. Stock has no exclusive-create operation;
an external writer can race the best-effort preflight. No device hash is claimed.

`DiscSession.scan_library(*, timeout=300, on_progress=None,
expected_generation=None)` starts one scan and consumes start/count/end events
under the session lease, without interleaved catalog or health queries. The
callback receives the discovered count; the confirmed `scan_ended` result keeps
it in `confirmation.discovered`. An end signal is not proof that every source
file was indexed, and the firmware uses the same end event for cancellation.
Timeout/disconnect stays uncertain; no cancel, reset, reconnect replay or implicit
scan-after-upload is performed. Applications explicitly refresh their catalog
after an observed end.

Both methods optionally require the original connection generation under the
operation lease, so staged work cannot dispatch on a replacement connection.
Progress callbacks must be short and must not invoke session operations.
Folder import belongs to the caller's serialized sequence of relative audio
paths; the stock upload handler creates missing parents. Artwork/CUE sidecars
are outside this facade's confirmable directory-readback surface.

Disposable V2.57 acceptance covers streamed byte equality, duplicate rejection,
nested audio paths, scan lifecycle and fresh index membership. Large-file limits
are validated as bounds, not a maximum-size or physical throughput benchmark.

## Current-state operations

The session facade exposes current-track reads, favorites and volume directly.
Within an existing serialized `session.operation()`, advanced adapters can use
`controller.operations.current_track(client, action, value=None, delta=None,
timeout=8)` or `playback_control(...)`, both returning `CommandResult`.
They use named reviewed capabilities, fresh preflight,
one mutation phase and explicit readback. Favorite operations verify track
identity before and after the write; stock supplies no atomic identity-conditioned
setter. Repeated favorite/volume requests are no-ops. Relative volume uses fresh
settings and clamps to 0..120. Connection failures never trigger mutation replay.
Legacy dictionary envelopes remain internal implementation details. Assistant
serializes the typed control result at its response/journal adapter boundary.

`PlaybackSource` and `WirePlaybackState` name reviewed wire enums. The latter is
separate from the normalized `PlaybackState`: a stock stopped value alone may mean
loading and is not proof of completed playback. Unknown wire values remain unknown.
TCP and WS share strict decoding: malformed scalar types (including booleans in
integer fields), malformed song objects and invalid volume are rejected. Absent
fields remain absent; unknown integer states are retained without promoting them
to a known playback state.

## Packaging and static checks

[`controller/pyproject.toml`](../pyproject.toml) builds the
`snowsky-disc-controller` 0.1.0 distribution with the existing `controller` import
name. Core TCP/HTTP needs only Python 3.11+; `[websocket]` and `[bridge]` install
aiohttp. `controller.__all__` defines public exports. See the
[standalone README](../README.md) for the 0.x compatibility policy.

[`ci/python-quality.sh`](../../ci/python-quality.sh) runs pinned Ruff across Controller,
incremental strict mypy over models/decoders/contracts/guarded commands/session,
the Assistant result serializer, and a static consumer contract. The legacy catalog/transport call sites in three
modules temporarily permit untyped calls; their own bodies/signatures are checked.
This is not a claim that every legacy module is fully typed.

The gate builds an sdist, builds a wheel from it, installs into a clean environment
outside the checkout, and runs real synthetic-peer operations. It checks the type
marker and bridge HTML, core operation without aiohttp, and optional-extra imports
after installation. Building/testing neither publishes the package nor creates a
new repository.

## Current-track descriptive metadata

`Track` retains optional `sample_rate_hz`, `bit_depth`, `channels`,
`reported_bit_rate`, `genre`, `track_number` and `is_dsd` / `is_sacd` / `is_cue` /
`is_m3u` observations. Missing, zero, negative or malformed optional numeric
values become `None`; booleans are never coerced from integers or strings.
Raw clients still retain the original extra firmware fields for diagnostics.
`Track.metadata` projects available descriptive values; snapshots serialize the
optional fields alongside the existing title/artist/album/path/duration fields.

`reported_bit_rate` is the literal positive `song_bit_rate` integer, not a promise
of measured compressed-file bitrate. Observed FLAC values match a PCM data-rate
scale. These properties describe the current source, not the active DAC, Bluetooth
route, negotiated output format or measured audio quality. No album-artist identity
is inferred. The six-field `Track.identity` preserves existing seek selection
checks independently of newly available descriptive fields.

## Genre playback

`DiscSession.play_genre(genre, album=None, index=None, expected=None)` selects a
reviewed V2.57 genre source through the existing owner. Optional immutable
`QueueItem` rows pin the displayed membership. Two fresh complete scoped reads,
capability/scan checks and a final HTTP position/identity check precede one write.
Whole genres and genre albums use type 8; indexed whole-genre tracks use type 10.
Confirmation checks native queue membership, source and selected position. A
shortened album is resolved only within that genre. Invalid/reserved selectors,
stale sources and unsupported versions fail without a playback write; uncertain
results are never replayed. This does not combine artist and genre selectors.
