# Stock metadata, artwork and lyrics for Library — 2026-09-23

## Scope and evidence

Read-only capability investigation for DISC Web, using the fingerprinted stock
V2.57 `mq_player` (`a5a6740435758bb3f3d008a4306c93a463c6634318957bbf32086bd7b00fabbc`),
Controller/Library source, existing sanitized protocol fixtures and the existing
local FiiO Control Android 4.6.0 analysis. No physical connection, device writes,
playback cycling, external lyric requests or firmware execution occurred.
Static findings below are fresh; referenced integration/physical results are
existing evidence, not a new acceptance run. Firmware, decompiled code and raw
app artifacts remain untracked.

The subsequent [runtime application-data inspection](2026-09-23-fiio-control-runtime-disc.md)
confirms a DISC Link connection without a universal product/function profile,
received current-track audio fields and current-cover requests. It found no
additional bulk metadata or lyric API in the supplied activity log; absence from
that log is not proof of service absence.

## Capability matrix

| Data | Verified stock surface | Current application boundary |
| --- | --- | --- |
| Catalog title, artist, album membership | Paged HTTP categories; TCP lists have related limited schemas | Controller and Library already expose the collection, regardless of how files reached the card |
| Duration and file path | Full current-track `a202` | Public `Track`, Web and guarded Library observations use these; no verified bulk per-file equivalent |
| Sample rate, bit depth, channels | Current-track `song_sample_rate`, `song_encoding_rate`, `song_channel` | Raw Controller retains them; public `Track` currently omits them |
| Reported bitrate, genre, track number, DSD/CUE/SACD/M3U flags | Additional fields of the current-track payload | Present in the formatter and preserved fixture schema; missing from public `Track`; do not infer compressed bitrate units or output hardware from these fields |
| Artwork | `GET /image/cover/`, fixed current cover | Controller and guarded Library capture exist; not arbitrary-file or whole-album artwork retrieval |
| External and embedded lyrics | Local firmware lyric processing | Static evidence of local support; no reviewed DISC remote lyric-text API |
| Album artist, disc/year and broader tags | Internal database/scanner fields | Not separate fields of the reviewed remote catalog/current-track contract |
| Full file bytes / sidecar contents | No general download route in the active HTTP table | No supported Controller file reader for metadata extraction |

The existing [remote-control integration](../../../tests/integration/remote_control.py)
checks a generated 30-second file as 44100 Hz, 16-bit, two-channel audio. The
[sanitized physical fixture](../../../controller/tests/fixtures/fiio_control_ios_460_playback.json)
preserves the extra metadata field names/types, but its metadata values were
replaced with synthetic values and are not measurements of the owner's files.

## Current-track metadata: an actionable Controller gap

V2.57 formatter `004d85ec` references the JSON format at `006d7c78`. In addition to
identity/path/duration, it emits `song_sample_rate`, `song_encoding_rate`,
`song_bit_rate`, `song_style_name`, `song_track`, `song_channel`, `is_sacd`,
`is_cue`, `is_dsd`, `is_m3u` and `m3u_file_path`.

A fresh offline decode of the sanitized fixture through
[`playback_snapshot`](../../../controller/wire.py) confirms these fields survive
the raw client boundary. [`Track.from_wire`](../../../controller/models.py)
projects only title, artist, album, queue position, path and duration. Thus this
is not a reason to change firmware: optional validated fields can be added to
the public model and then to Library observations and Web presentation.

Keep unknown values unknown, distinguish observed file properties from DAC/output
properties, and review units/DSD behavior before formatting labels. Retain partial
state-update behavior and seek/identity guards when extending the model. Cache
these observations while normally listening; never advance playback to fill gaps.

## HTTP: no hidden bulk metadata or file-download handler found

The fingerprinted table at `006d2580` contains 17 routes. Its active dispatcher
`004c15a8` matches method and path prefixes, then calls `00496d08` for unmatched
requests. The latter emits an empty HTTP 200, not a static-file response.

There is `POST /audio/` for upload and `DELETE /file/` for removal, but no matching
GET file/audio route, metadata route, or lyric route. `GET /image/cover/` at
`0049306c` opens the fixed `/usr/data/fiio/cover.jpg`; it does not accept a track
path selector. Adding guessed query arguments or HTTP Range cannot turn these
handlers into a general file reader. This conclusion concerns the inspected
stock HTTP service, not every hypothetical service or future firmware.

`GET /log/` is also not a catalog export. Static inspection of `004c1890` shows
packaging of the log directory and `sysconfig.db`, not `song.db` or audio files.
It creates a temporary archive on the player; no request was made in this audit.
Directory APIs are filtered media browsers, not complete sidecar inventories.
See [HTTP contracts](../../../docs/protocol/http-api.md).

## Local lyrics versus remote lyrics

The local lyric handler `0044f22c` tries an external lyric file, then embedded
lyric content when available. Lookup `0046d128` builds a same-stem `.lrc` path;
conversion routines `0046cbd8` and `0046cf38` write UTF-8 content to the fixed
`/usr/data/fiio/encoder.lrc`. An online-lyric branch can take priority. This is
static evidence of the pipeline, not validation of every audio tag, encoding,
plain-text lyric or synchronized lyric format on hardware.

No route in the inspected HTTP table exports that file. The current-track JSON
also contains no lyric text. Commands `064b`/`064c` are absent from the 111-entry
TCP allowlist (fresh fingerprinted check); local settings callbacks are not
remote getters for lyric content.

The existing Android app analysis contains
`PlayerLyricController._fetchCurrentLyric`, constructing
`http://<host>:13488/currentLyric` and parsing a lyric response. DISC's inspected
HTTP service is on 12103 and has no such route. This is a cross-product lead,
not proof of DISC compatibility; that separate port/service was not probed.
The firmware also contains online-provider clients, but provider availability,
matching quality and reuse permissions were not investigated or exercised.

## Album identity and local-file association

The firmware's database query strings include `ALBUM_ARTIST`, `DISC`, `TRACK`,
`DURATION`, sample properties and production year. Some artist grouping paths
use `COALESCE(ALBUM_ARTIST, ARTIST)`. A remote `author` or artist selector must
therefore not be promoted to an authoritative album-artist tag without checking
its specific source. Same-title releases, compilations and CUE/ISO entries need
explicit identity rules; title + artist alone is not a permanent file identity.

Existing catalog lists do not provide verified nonempty paths for every row;
only current-track paths have that evidence. A mounted-card/source-folder reader
can extract full tags, artwork and sidecars, but association back to the device
catalog must preserve ambiguity and duplicate multiplicity. SD access also does
not imply access to the player's internal `/usr/data/fiio/db/song.db` partition.

## Recommended continuation (not implemented by this audit)

1. Expose validated current-track audio properties through Controller, then
   Library enrichment and the Web panel. This benefits SD, USB Storage and Web
   imports equally, as tracks are normally played.
2. Add an optional local-file source to the existing Library synchronization
   enrichment stage: mounted SD, USB Storage volume or user-selected source
   folder. Web import supplies the same source observations early; it is not the
   exclusive path. Preserve provenance and conservative association on resync.
3. Build lyric presentation on confirmed sources: embedded content / sidecars
   from the local-file source first. A separate explicit provider may be evaluated
   later; it must not masquerade as device-provided lyrics.
4. If full remote enrichment without file access is required, investigate a
   separately scoped device-side service/custom firmware for catalog/file/lyric
   reads. That is a new deployment capability, not something a host-side
   Controller wrapper can manufacture from the verified stock endpoints.

## Reproduction

Use the existing diagnostics against a local stock binary identified as V2.57:

```sh
python3 -m research.diagnostics.inspect_http_routes /path/to/mq_player --version 2.57
python3 -m research.diagnostics.inspect_link_commands /path/to/mq_player --version 2.57
```

In the existing fingerprinted Ghidra project, use `-readOnly -noanalysis` with
`DecAt.java` for `004c15a8`, `0049306c`, `004936b8`, `00496d08`, `004c1890`,
`004d85ec`, `0044f22c`, `0046d128`, `0046cbd8`, `0046cf38`. Follow the
[analysis workflow](../methods.md); never reuse addresses for another binary.
Only documentation changed. Local Markdown targets and diff whitespace were
checked; no firmware regression run is needed for this report.
