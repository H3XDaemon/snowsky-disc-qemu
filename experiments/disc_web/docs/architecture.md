# Application architecture

`disc_web` is an independent experimental consumer of the public Controller API and shared root Library.
It can move with its backend, frontend, tests and documentation after acceptance.
No path mutation or Assistant storage is needed.

```text
Browser (HTML / CSS / JavaScript modules)
    | same-origin JSON requests, cached-state polling
HTTP server (backend/server.py), loopback by default
    | token / request ID / operation admission
Device projection (backend/device.py) <-> Library snapshots / SQLite
    | one DiscSession + same-target HTTPClient
Controller
    | reviewed TCP and stock HTTP
Physical DISC or emulator

--demo selects backend/demo.py instead: no device construction or sockets.
```

## Ownership

Normal startup has no selected target and uses physical DISC port defaults. The
unconfigured session cannot connect or expose a prior loopback catalog. Explicit
`--emulator` selects emulator defaults and exposes developer presets through the
state projection; browser drafts are separated by mode. CLI targets take priority.

The server starts a session lifetime without enabling its connection. An explicit
Connect enables it. Each device operation takes a nonblocking application lock:
conflicting requests fail rather than waiting to execute later. Public session
methods retain their own serialization, mutation pacing, fresh preflight,
confirmation and observation-only recovery. Disconnect disables recovery.

All playback and playlist writes use facade methods. Library HTTP reads occur inside a session
operation with scan checks before/after, bounded `CatalogReader` pagination and
literal scopes. A playlist name must resolve uniquely; list rows are checked again
after its tracks are read. Artist-album navigation retains the artist filter in
both the URL and subsequent playback command. Action menus retain their opening
scope and original row token. Album navigation is enabled only when that source
actually supplies the album name; generic HTTP track rows do not. Unsupported
playlist-add sources remain disabled rather than being widened implicitly. The backend does not turn those
albums into generic whole albums.

Without a saved Library snapshot, views load a bounded complete live category
(at most 10,000 records and 60 HTTP requests), and search filters that view. After
synchronization, albums/artists/tracks use SQLite. Search always filters the
current view and never redirects to tracks. Album search includes all observed
artist credits; artist/playlist search uses names, and track search uses
title/artist/album. Detail views retain their scoped rows and selection tokens.
Navigation clears the query; refresh preserves it. Placeholders and empty states
describe the current entity in RU/EN. Favorites/playlists remain live. Virtualization and paged
presentation are future work.
Cached browsing uses a separate short source-token lock, so device cover reads or
an active synchronization cannot block reading the previous local snapshot.

All native dialogs share backdrop dismissal and page scroll ownership. Only a
primary pointer click beginning and ending outside the dialog dismisses it;
inside padding and drag-out gestures do not. The document remains fixed while
any dialog is open, with scrolling contained inside the modal. Closing the last
one restores the previous page position unless navigation changed the route.
Native Escape, focus return and existing operation lifetimes are preserved.

The top-bar sync icon opens a dedicated dialog; opening it never starts sync.
It renders actual server stages/page counts with indeterminate progress, preserves
errors and offline coverage, and can be dismissed while the server continues.
The import flow shares the same sync command. Refreshing the current list is a
separate secondary action in the dialog. Decorative missing-artwork sleeves use
title-derived palettes and escaped initials only; they are never stored as metadata.

Before a snapshot exists, visible album cards optionally request `kind=album_info` through the same library
endpoint. This reads the scoped album rows and returns distinct literal credits,
count and connection generation, without allocating playback selection tokens.
The browser serializes these reads, discards old-view/connection results and keeps
at most 256 summaries for 60 seconds within the view. Refresh/navigation clears
them. Failures retain the known group count. Once a saved snapshot exists, these
requests stop and its observed album memberships supply the summaries. There is
no Assistant import or guessed title/artist-to-album join. Empty
album/duration columns are hidden per view; the album detail retains its known
scope. A current-track duration is not applied to other catalog rows by name.

## HTTP surface

| Endpoint | Behavior |
| --- | --- |
| `GET /api/state` | Latest import/scan job, cached normalized state, application session token, demo/endpoint information; no device query |
| `GET /api/sound` | Fresh reviewed gain/balance/filter/DRE through the existing Controller owner; foreground admission, no demo fallback |
| `GET /api/interfaces` | Local host IPv4 interfaces eligible for passive discovery; empty in demo |
| `POST /api/discover` | Token/request ID, selected current interface, six-second passive multicast listener; no TCP connection |
| `POST /api/connection` | Token/request ID/generation, local IPv4 and TCP/HTTP ports; replace the sole owner and enable connection |
| `GET /api/library?kind=...&name=...&artist=...` | Named category/detail projection; saved Library snapshot, bounded live HTTP reads or fictional demo rows |
| `GET /api/queue` | Fresh public facade queue result |
| `GET /api/cover` | Current device JPEG/PNG; no arbitrary proxy URL |
| `GET /api/artwork/<digest>` | Library-cached JPEG/PNG associated with the active endpoint/snapshot; available offline |
| `POST /api/upload?name=relative/path.flac` | Raw bounded file body, token, request ID and generation headers; private staging then async facade upload |
| `POST /api/sync` | Token/request ID/connection generation, asynchronous read-only Library synchronization |
| `POST /api/scan` | JSON request ID/generation, one async observed scan |
| `POST /api/action` | Explicit allowlisted command, request ID, connection generation and session token |

The process binds to loopback by default; explicit `--host` enables a local IPv4
or wildcard listener. Host validation uses the accepted socket’s local destination
and exact port, never arbitrary private addresses or forwarded headers. LAN mode
has no user authentication or TLS and is intended for trusted networks only.
Browser request IDs use cryptographic random bytes, including on HTTP LAN origins
where `randomUUID` is unavailable. Host and Origin checks reject cross-site and DNS
rebinding requests; POST also requires `X-Disc-Token`; action/scan JSON and raw upload bodies have separate bounds. No CORS is
enabled. Connection/discovery JSON uses the same 16 KiB bound. CSP restricts scripts, styles, images and connections to local assets;
live covers accept only JPEG/PNG. Error messages and names are inserted as text
or escaped HTML. Requests are not logged with private names or query strings.

The process remembers up to 4,096 request IDs and rejects further writes once
that budget is reached, rather than evicting IDs and allowing replay. This is not durable exactly-once delivery. Browsers never retry a
write or persist commands for reconnect. Unknown results remain uncertain.
JSON reads rejected as busy (HTTP 409) may retry up to six times with bounded
backoff, so cover/catalog overlap need not become a failed collection screen.
Transport failures, other HTTP errors and every POST fail without replay.

State polling every 1.5 seconds reads cached session state, not the device socket.
The catalogue projection includes saved observation time, active job stage/pages
and snapshot-scoped artwork/duration track counts. Presentation keeps the saved
result separate from in-progress work; these counts are coverage, not sync progress.
The browser disables control after a server/connection loss. Duration comes from
validated stock milliseconds; absent duration keeps seek disabled. Dragging or
keyboard adjustment previews a requested position and sends once on change. The
draft retains its original track/source/generation, so a track change during a
drag rejects the selection. A paused seek is explicitly pending observation;
it does not trigger resume, optimistic progress or retries.
Volume is the last value read back after this server's volume operation, or
unknown. Changes made using physical buttons are not yet tracked by this field.
The queue is a snapshot refreshed on opening or after this browser's commands;
continuous multi-browser queue invalidation is not implemented yet.
Now Playing and Queue occupy two sections of one non-modal right panel, with
one queue snapshot and explicit refresh. The panel reserves collection space on
wide screens and overlays it below 1200 px. Its fixed header stays visible while
each section scrolls independently. The mini-player remains accessible; opening
the panel does not lock background scrolling. Escape closes a native modal first,
then the panel; explicit panel dismissal restores focus to its opener. Additional
sections such as lyrics can reuse this shell when real content is available.
Late responses from an older request/connection generation are discarded, and
disconnect invalidates the displayed queue. Current-row highlighting requires
both the observed position and matching title/artist; it does not predict the next
track in random mode. The expanded player's format badge comes only from a
recognized observed filename extension, without codec-quality inference.

Album links preserve the known artist scope from cards, track actions and Now
Playing, including in demo browse and playback queues. Artist names on album
pages are navigation links. A legacy album URL without `artist` intentionally
represents the stock title group: multiple artists may be separate releases or a
compilation, so the UI offers explicit artist filters instead of guessing an
album-artist identity. The unfiltered group remains available. Search does not
change this metadata or scope. Artist-scoped playback uses the existing public
Controller selector and fresh membership guards.

Displayed track/queue rows carry opaque source tokens. The server keeps up to
32 source snapshots for ten minutes, tied to the connection generation. Commands
resolve the original scope and position from that snapshot; browser filtering
cannot renumber a selection. Controller compares the expected immutable rows
against fresh source data before sending. There is still no atomic stock revision.

Playlist edits run under the same session lease/pacer, resolve fresh list
positions by unique names, recheck source/membership and verify readback. A lost
reply is uncertain and cannot be automatically resubmitted. Removal changes
membership only; source files are never deleted by this UI.

## Shared Library

`backend/catalogue.py` owns application storage selection and sync admission.
Root `library/catalog.py` retains its two-equal-read and membership-multiplicity
checks. `library/store.py` atomically publishes complete immutable snapshots;
`library/snapshot.py` provides offline group/track projections. Core storage uses
SQLite schema 1, unchanged for Assistant; Typesense is not imported by Web.

`library/sync.py` owns the catalog/enrichment/publication stages. Web's worker
supplies its owned lease, cancellation/generation guard and bounded HTTP adapter.
`library/observation.py` owns current-track association and guarded artwork reads;
`library/enrichment.py` stores provenance, durations, optional descriptive metadata and deduplicated image bodies
separately from raw tags. `backend/enrichment.py` only adapts these Library APIs to
the active endpoint, browser identity and local artwork route. Browsing projects
known durations and track artwork; album art represents an observed member's cover.

Current-cover loading and sync use the same Library association rules: exact
unique title/artist/album, two fresh ordered album-membership comparisons, stable
path/position/duration/source around the image read. Ambiguous/shortened metadata
is skipped. Browser cover identities include path and queue position, preventing
same-title transitions from retaining another row's artwork. The stock endpoint
still has no atomic image/track identity. Enrichment is partial, and new snapshots
do not inherit old associations. No playback cycling or external lookup is used.

The default directory is separate from Assistant's. Endpoint keys include host
and both ports; they are not device serials. No old Assistant data is copied or
migrated. Demo never constructs Library storage. A snapshot timestamp reports an
observation, not continuing freshness. Upload/scan attempts invalidate the local
freshness marker. Reconnect and process restart also require explicit sync to
revalidate. External changes remain unknown until sync or fresh playback checks.

A sync job holds the same foreground gate as imports, configuration and commands,
then borrows the existing Controller operation lease. It has a 300-second deadline,
10,000-track bound and 1,000-request budget. Scan events, lost generations,
inconsistent reads and storage failures retain the previous head. Catalog pages
contain at most 100 rows. A failed HTTP GET may be repeated once within the total
request budget; the worker never automatically restarts a failed sync or retries a mutation. State/static assets and old cached views
remain readable while the job runs. Shutdown requests interruption before the
next page/publication; the current HTTP call remains socket-timeout bounded.

Cached views allocate a bounded display token recording snapshot ID, connection
generation, original ordinals and literal artist scope. A command verifies the
current head, resolves the exact stored album membership (including duplicates),
then passes immutable expected rows to Controller. Controller reads the fresh
scoped source before sending. Whole saved albums also supply expected membership.
No cached index is sent straight to the wire. Artist groups retain the existing
named-scope Controller path. Offline controls are disabled, and the server still
rejects commands without a ready connection. New publication clears display tokens.

## Import ownership

`backend/imports.py` owns one foreground job and a nonblocking admission gate
shared with other API operations. Cached state and static assets remain readable
during staging, transfer and scanning. `frontend/imports.mjs` owns file/folder
selection, per-file batch progress and explicit scan presentation. It preserves
browser `webkitRelativePath`, filters the documented audio extensions and
shows the skipped-file count. Names are relative, traversal/control characters
and invalid FAT path characters are rejected, and sizes follow the stock 31-bit
limit. Only one private temporary file exists per active transfer.

Uploads and scans call `DiscSession.upload_audio()` and `scan_library()` with the
original connection generation translated to the current Controller session. The generation is checked under the session
lease as well as before staging/dispatch. A batch stops on any unconfirmed item;
there is no durable queue, overwrite, automatic scan or resume. Demo consumes
bytes without staging or device construction and only simulates job progress.

During scans the Controller reader consumes start/count/end events without
interleaved queries. Cached job progress is separate from playback. Starting a
scan invalidates displayed source tokens. An observed end triggers a fresh view
read; a timeout is uncertain, never an automatic restart. The completed job stays
readable after a page reload until another explicit job replaces it.

## Connection ownership and discovery

`backend/connections.py` validates local IPv4 targets and inventories eligible
macOS/Linux interfaces. Its bounded listener uses Controller's reviewed exact
DISC multicast recognizer. Sender addresses are candidates, not authenticated
identities; the UI requires explicit selection and connection. TCP/HTTP ports
are known defaults, not fields supplied by the beacon. Only one discovery job
runs at a time. Demo performs neither interface inspection nor discovery.

Target replacement shares foreground admission with library operations and
imports. The old session is stopped before the replacement starts; HTTP always
uses the same target. An application generation offset stays monotonic across
session replacements, clears source tokens and prevents old browser/import
generations from matching a new Controller session. The completed import job is
cleared on accepted configuration. No operation is replayed onto a new target.
`frontend/connection.mjs` persists only a validated connection draft, never a
connect command. Startup remains disconnected; browser reload retains the
server's existing enabled session.

## Frontend

The UI uses local system fonts, original SVG artwork and no frontend framework or
build step. `core.mjs` holds pure rendering/search/navigation helpers. `app.js`
owns routes, requests and DOM presentation; `style.css` owns layout and responsive
breakpoints. `locales/ru.json` and `locales/en.json` hold interface strings;
`i18n.mjs` handles placeholders, plural rules, static accessibility labels and
live language changes. Device metadata remains untouched. `theme.js` applies
saved/system appearance before CSS paints and observes system changes in auto
mode. Both preferences tolerate unavailable localStorage and sync between tabs.
These modules have no device side effects or build dependencies.

The responsive design includes a fixed desktop sidebar, mobile bottom
navigation, persistent mini-player and shared listening panel. Album and artist links are
deep-linkable and retain Unicode names.

The visual direction is an original music-library interface: warm paper surfaces,
quiet green neutrals, coral primary actions, generous cover art and restrained
typography. It does not reuse assets or logos from commercial music services.

The import dialog uses `frontend/import-flow.mjs` to project separate transfer,
scan and saved-catalog states. A confirmed scan must belong to the displayed
connection and follow the current file selection before its sync action is
enabled. Sync uses the existing foreground request helper; publication must be
available and freshly verified before offering the saved collection. Batch counts
remain independent of scan/catalog totals. The projection dispatches no commands
and never restores an in-memory selection after reload.

## Extension boundaries

The sound panel reads on opening or explicit refresh and applies one draft at a
time through `sound_setting`. Web passes the displayed value and connection
generation to Controller. Only a confirmed/already-satisfied result with matching
name/value updates the observed UI; stale, failed or uncertain results require a
new read. The panel invalidates observations on connection changes and ignores
late responses from an old request. It never forwards tags, caches guessed sound
defaults, automatically restores settings or retries a write.

Add missing persistent operations to Controller with their own typed results and
fresh identity checks before exposing them here. Settings and future file operations need their own verification, not success based on HTTP 200. Maintain the distinction between removing a list member and deleting a file.

Assistant can later use a shared application runtime/adapter. The current server
is not a generic Controller daemon and does not make independent Assistant and
Web processes simultaneous TCP owners. This integration and root-level promotion
are separate decisions.

Current-track `Track` fields reach Now Playing through the existing cached state.
Saved row projections expose Library's snapshot-scoped `metadata` for the track
action menu. Both use the same RU/EN formatter and hide unknown fields; DSD source
flags suppress PCM bit depth. Reported bitrate is retained without a compressed
bitrate label. Cover requests retain their existing six-field track identity plus
connection generation; Library still compares the complete before/after Track,
including descriptive properties, to reject transitions during observation.
The seek adapter accepts the extended public Track while preserving all existing
identity/source/generation checks. No new endpoint, device query or mutation was
introduced. Enrichment migration adds a default-empty JSON column without
changing catalog schema 1 or discarding previous observations.

## Native genre scopes

Web opts into Library's native genre facets during sync. They publish with the
same snapshot and budgets, without converting genre positions to catalog IDs.
`GET /api/library` accepts `genre` for `albums`, `tracks` and `album`; combined
artist/genre scopes are rejected. Responses include observed genre availability
and an opaque source token for whole-genre/genre-album playback. Older snapshots
return unknown genre coverage and require explicit sync; no fallback to a broader
album or live query is made while reading a saved scope.

Genre source tokens bind snapshot and connection generation, exact expected rows,
genre and optional album. `action=genre` consumes that token for Play all; indexed
`action=track` uses the same scope through `DiscSession.play_genre`. Expired or
replaced snapshots fail before dispatch. Native genre rows are separate positional
observations: duplicates retain multiplicity, ambiguous album navigation remains
absent and no main-catalog artwork association is guessed. Artist navigation
explicitly leaves the genre scope; album links retain it. Search filters only
rows already in the selected genre. Offline controls remain disabled.
