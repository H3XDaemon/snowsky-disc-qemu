# Library

Shared catalog observations, SQLite snapshots and optional search for DISC Web
and Disc Assistant. The component is independent of both applications; its
root-level location does not imply a stable public package API.

The core uses Python 3.11+ and the standard library. Typesense is optional and
loaded only by the search adapter. Run `python3 -m unittest discover -s library/tests -t .`.
Application launchers own connections and storage locations. Existing Assistant
databases, snapshot IDs and search signatures remain unchanged by the move.

- `catalog.py`: bounded pagination of `all/song`, `album` and `album/song`;
  full membership comparison with duplicate multiplicities; two equal reads.
- `snapshot.py`: offline artist/album projections and duplicate-preserving selection context.
- `sync.py`: common stable-catalog synchronization and optional enrichment stage.
- `observation.py`: current-track metadata/artwork observation and conservative
  association with a catalog row, using the application's existing session lease.
- `enrichment.py`: separate snapshot-scoped observations and bounded artwork storage.
- `store.py`: SQLite schema 1, snapshot-scoped internal IDs, literal source
  observations, atomic snapshot/index publication and concurrent-import guards.
- `search/typesense.py`: official async SDK adapter, versioned search projection,
  title/artist/album/explicit and projected spellings, per-document import checks, matched-field
  evidence and stale-index rejection.
- `tests/`: synthetic fixtures and firmware-free component tests.

The catalog reader receives an HTTP client owned by the application session;
it opens no TCP connection. Store/search work offline from DISC. Library has no
assistant, voice, emulator or viewer dependency. Imports perform no I/O.

SQLite is durable; Typesense is rebuildable. A failed import/index never replaces
the previous published object. New snapshots intentionally invalidate old search
projections. A random collection is built completely before SQLite points to it;
there is no shared mutable Typesense alias or partial collection exposure.

Source rows do not expose reliable permanent recording identities. Duplicate
names/IDs are preserved, not merged; each row has a snapshot ID and exact source
scope/position. Old snapshots remain stored. Reconciliation, favorites, history,
lyrics, edition metadata and general retention policies remain future work. Do not treat
these cached positions as playback selectors or a score as calibrated confidence.

Runtime data belongs outside the checkout; this package stores only source code
and synthetic tests. The shared modules and component tests now live at the repository root and run
in the firmware-free suite; Assistant remains experimental.


Recording edition markers live in `version_markers.toml` and `versions.py`.
Their recognition is independent of the Assistant interaction locale; English
Live/Remastered labels remain visible when Russian commands are active. Locale
query-version phrases may extend this vocabulary. These are lexical conventions,
not authoritative recording identity or quality metadata.


Common recording labels also remain explicit query constraints across locales:
`Включи Linkin Park — Numb live` requires a live edition even in Russian mode.
Locale-specific version phrases extend those shared labels. A missing requested
edition is not silently replaced with a studio recording.

Search spelling projection lives in `transliteration.toml` and `transliteration.py`.
The current table folds Cyrillic to Latin for matching; it does not assert phonetic
or ISO transliteration equivalence. Exact source metadata is unchanged. The table
fingerprint participates in versioned index signatures. After changing it, restart
the process and rebuild the index; add paired spelling/collision tests before
extending the table. This Library utility has no dependency on command locales.

## Multiple artist credits

`artists.py` derives an ordered `artists` array from an explicit semicolon-delimited
source tag: `Eminem;Dido` becomes `["Eminem", "Dido"]`. Members are trimmed; blank
members and case-insensitive Unicode-equivalent duplicates are omitted. Commas,
slashes, ampersands and `feat.` are not separators: they may be part of an artist's
name. Changing separator policy requires evidence and regression coverage.

The literal `artist` and source row remain unchanged in SQLite. `Store.documents`
projects the array from existing snapshots, so no database migration or device
rescan is needed. Typesense schema 3 indexes both the full credit and the members;
each member also contributes configured aliases and spelling projections. Restart
the Assistant and run `/index` (or `run.sh index`) after upgrading. Old index
signatures are rejected until rebuilt.

Ranking policy `lexical-v4` matches a track by any credited member, including a
member followed by a title without a separator. Literal members outrank alias
collisions. The selected candidate retains the full original credit: fresh device
catalog checks and playback use the stock artist selector, never a fabricated
member-only selector. This does not create an aggregate queue of every solo and
collaborative recording by a person. Artist-only commands select one matching
native artist group under the existing deterministic ranking policy.

### Schema 4: prefilter known raw credits

Schema 4 / lexical-v5 add a derived SHA-256 `artist_key` for exact raw-credit
filtering before Typesense top-50 retrieval. This prevents unrelated artist names
inside titles from crowding out a requested artist. The full original credit and
semicolon member projection remain unchanged. Run `/index`, not `/sync`. The
SQLite schema remains version 1. Compare the [measured variants](../experiments/disc_assistant/docs/reports/2026-09-18-review-evaluation.md).


## Application integration

DISC Web stores an independent, endpoint-scoped catalog and does not require
Typesense. Its explicit sync borrows the one Controller session. Assistant keeps
its existing data directory, device key, optional search projection and execution
policy. Sharing this component does not allow two independent TCP owners.

`Store.snapshot(device)` returns the published head and an offline `Snapshot`.
Its `tracks()`, `groups()` and `selection()` methods preserve literal credits and
album memberships, including identical titles and repeated CUE entries. They do
not promise a live device revision. Applications must retain snapshot provenance
and pass fresh expected source rows through Controller before playback.

## Enrichment during synchronization

`synchronize()` owns the catalog-to-enrichment flow. Applications supply an owned
client/HTTP transport, private stores, request budgets and a final cancellation /
connection check; stage callbacks support progress reporting. After two matching
catalog reads, Library observes the available current track, verifies scan and
connection guards, publishes the complete catalog and stores any supported
enrichment against its new generation. Optional metadata failures preserve the
complete catalog; observed scans or cancellation still block publication.

`observe_current()` is also the common path for enrichment during listening.
Stock HTTP exposes the current cover; Link exposes current-track duration and
optional audio properties, genre, track number and source flags. Library never advances playback to obtain metadata. Association requires
an exact title/artist/album match unique within that snapshot and two fresh album
reads matching its full ordered membership. Shortened names and ambiguous
duplicates, including repeated CUE entries, remain unassociated. Track path,
duration, queue position and source must remain stable around the cover read.
The stock cover endpoint has no atomic track identity: this is a guarded
observation, not proof of an atomic image/track pair.

`observations.sqlite3` is independent of catalog schema 1. It retains source,
path, association method and observation time; it never replaces raw tags.
Track observations are scoped to endpoint, snapshot and exact row. A new snapshot
does not inherit old metadata by name. JPEG/PNG artwork is content-addressed and
deduplicated, with an 8 MiB per-image and 256 MiB total-body budget; a full artwork
budget still permits duration observations. Offline consumers can display the
stored fields. Missing or unsupported fields remain unknown.

`Enrichment.state()` reports snapshot-scoped track counts separately for any
observation, artwork and duration. Shared image bodies count once per associated
track; these are field-availability counts, not unique images or album coverage.

Local-file tag extraction and external providers can extend this Library stage
later; neither is implemented or contacted by this source. Full-collection
durations/artwork are therefore not promised by a stock-only synchronization.

The current-track enrichment also stores available `Track.metadata` in a separate
JSON column, with an additive migration preserving old observations and artwork.
This is the same guarded observation used during sync and current-cover loading;
no extra polling or playback commands are added. Missing descriptive values are
not filled from a previous observation. A valid metadata-only observation may be
stored when duration and artwork are unavailable. `reported_bit_rate` remains a
literal device report, not a measured compressed bitrate. Original tags and
catalog schema 1 are unchanged; duplicate, scan and snapshot guards still apply.

## Optional native genre facets

`CatalogReader.read_stable(include_genres=True)` reads `style`, `style/song`,
`style/album` and `style/album/song` within the same page/request budget as the
base catalog. Both complete observations must agree, including genre membership.
Album memberships within each genre must match its track multiset, and their
combined multiplicities must fit the base catalog. Unresolvable literal groups
are retained as unavailable; reserved tokens are never translated into guessed
localized labels. Network, inconsistent-read and budget failures retain the
previous snapshot.

`synchronize(..., include_genres=True)` publishes these facets atomically inside
snapshot metadata without altering catalog schema 1 or track identities. This is
opt-in for consumers; DISC Web enables it, while Assistant's existing sync is
unchanged. `Snapshot.genres is None` means no genre observation (older snapshot),
whereas an empty list is an observed empty genre list. `genre_rows(name, album)`
returns the native scoped rows; their positions must not be used as main catalog
ordinals. No genre is inferred for duplicate main catalog rows or entire albums.
