# DISC Web status

Initial implementation on 2026-09-22, branch `codex/disc-web`.

The application provides an independent local server, responsive music UI,
isolated synthetic demo, live library navigation, guarded indexed playback and
playlist editing. RU/EN localization and light/dark/system appearance are
available with browser-local preferences. See [README](../README.md) for exact live/demo
capabilities and launch commands.

The product remains experimental. This checkpoint is not full Controller feature
coverage or physical-device acceptance.

## Now Playing and queue — 2026-09-23

- Expanded player places artwork, transport controls and the queue together on
  desktop; mobile provides player/queue views. Both palettes and RU/EN are covered.
- Album and artist credits link to their library views. Playback status and an
  optional filename-format badge use available state, with no fabricated quality
  or hardware-output information.
- Drawer and expanded queue share refresh, loading/error/empty handling and
  current-row highlighting. Requests are guarded against late results from an
  older connection or refresh. Queue controls no longer depend on a nonempty
  background library page; Controller's source-token preflight remains unchanged.
- App checks passed 36 Python and 14 JavaScript tests. Repository firmware-free
  checks passed 502 Python and 51 JavaScript tests, including four shim builds.
  Browser demo checks covered desktop dark RU and mobile light EN at 390 px,
  queue selection, pause, album navigation and the mobile queue switch. No
  physical player connection or firmware run was made for this UI change.

## Synchronization visibility — 2026-09-23

- The library card separates saved timestamp/counts from current work and errors.
  An expandable detail view shows actual connection/catalog/enrichment/verification
  stages, with received pages rather than a percentage or estimated completion.
- Library supplies independent per-track artwork and duration counts for the
  current endpoint/snapshot. Shared images count for each associated track;
  storage errors show unknown coverage. Missing snapshots hide coverage entirely.
- Offline/stale states remain explicit. A failed sync does not replace the saved
  collection; UI text explains partial enrichment and scan-before-sync without
  adding automatic operations or changing playback.
- Web checks passed 36 Python / 14 JavaScript tests; focused Library enrichment
  checks passed eight tests. The firmware-free repository suite passed 503 Python
  / 51 JavaScript tests and four shim builds. Browser checks used mocked transports
  and a synthetic local catalog: desktop dark RU, mobile light EN at 390 px and
  dark RU at 320 px, active catalog reading, preserved data after failure, unknown
  metadata coverage and unavailable storage. No browser console errors or
  horizontal overflow were observed. No physical connection or firmware run.
- The agreed continuation order is saved in [the implementation plan](plan.md).

## Folder import through synchronization — 2026-09-23

- The import dialog presents memory-card transfer, DISC scanning and local
  catalog publication as three explicit actions. File confirmation counts remain
  separate from the discovered/catalog totals, including partial transfers.
- A same-generation confirmed scan enables the existing sync operation. A fresh
  saved snapshot offers Open collection; uncertain scans cannot advance the flow.
  A connection change blocks continuation of an old file selection. Reload shows
  only known server results, and demo stops at its scan preview without saving a
  fictional catalog. No Controller command behavior or device API changed.
- App validation passed 37 Python / 17 JavaScript tests. New synthetic checks
  exercise separate upload/scan/sync starts, nested paths, old snapshot retention
  until publication, uncertain results, partial batches and connection changes.
  Repository firmware-free checks passed 504 Python / 54 JavaScript tests and
  four shim builds.
- Browser verification used mocked device transports with real local application
  handlers and Library storage: selected a folder with two generated WAVs in
  different disc folders and a skipped sidecar, explicitly transferred/scanned/
  synchronized, then opened the saved albums. RU/dark and EN/light covered desktop,
  390 px and 320 px; reload retained the known scan/sync result without fabricating
  batch history. No horizontal overflow or console errors were observed. This is
  application-flow evidence, not new physical or firmware acceptance.

## Sound settings — 2026-09-23

- A RU/EN sound panel exposes observed gain, L20..R20 balance, all six stock-named
  DAC filters and DRE. Each draft requires its own Apply; opening/refresh reads
  values, and ordinary state polling does not query settings. Demo/disconnected
  modes do not expose functioning controls.
- Controller's new narrow facade checks reviewed firmware, fresh displayed value,
  scan state, connection generation and mutation pacing. It sends once, confirms
  through readback, and never retries an uncertain change. Unknown firmware,
  invalid values and stale drafts cannot dispatch a write. UI results invalidate
  on reconnect and reject late responses.
- Web checks passed 38 Python / 18 JavaScript tests. Firmware-free repository
  checks passed 509 Python / 55 JavaScript tests and four shim builds. Ruff, strict
  mypy (12 boundary files) and the isolated Controller sdist/wheel installation
  and synthetic-session checks passed.
- Browser checks used a local synthetic TCP peer: gain/filter/DRE apply, keyboard
  balance, unsent-draft feedback, stale-value rejection followed by refresh, and
  clearing fields after disconnect. Desktop dark RU, mobile light EN at 390 px
  and dark RU at 320 px showed no horizontal overflow. The final preview had no
  console errors. No physical player connection was made.
- The complete disposable V2.57 `full` regression passed (exit 0), including the
  new persistent sound scenario for gain, balance extremes, all six filters,
  DRE, stale-value rejection and restoration. Temporary containers and volume
  were removed. This verifies remote state control, not physical analog/DSP
  performance.

## Initial validation

- Repository firmware-free suite passed in the existing CI Docker image with no
  network and a read-only repository, including the new application tests,
  41 JavaScript tests, shell syntax and all four shim builds.
- The new application boundary tests cover same-origin/token validation,
  duplicate rejection, no automatic connection, stale-generation/busy rejection,
  bounded catalog reads and preserved artist scopes. A real synthetic TCP peer
  checks one session, confirmed pause/volume, idempotent pause and no write after
  disconnect. No physical DISC or interactive emulator volume was used.
- Browser checks cover home/album navigation, demo album playback and queue
  selection, search by artist, and responsive album/expanded-player presentation
  at 390 px.
  Demo actions are presentation checks, not firmware evidence.

## Theme, localization and library editing checkpoint — 2026-09-22

- RU/EN dictionaries cover navigation, status, dialogs, actions and accessible
  names; track/album counts follow language plural rules. Music metadata is not
  translated. Switching languages preserves the current view.
- Light/dark/system appearance uses shared color tokens. The saved theme is
  applied before paint; system changes only affect the automatic choice.
- Indexed album and queue selections preserve original displayed positions,
  scope and expected rows, including after browser filtering. Expired, evicted
  or previous-generation source tokens are rejected.
- Custom playlists support create, rename, track add and member removal through
  public Controller operations. Source-file deletion is not exposed. At this earlier checkpoint, live custom
  playlist playback, seek and all-tracks/favorite indexed playback were gated.
- App checks: 14 Python boundary tests and 7 JavaScript tests passed. Controller
  focused selection/edit checks passed (22 tests). Repository firmware-free run
  passed 428 Python tests, its then-current 41 JavaScript checks and shim builds;
  the subsequent app-only tests include the new preference and source-token cases.
- Ruff and mypy passed. Controller sdist → wheel → isolated installation,
  synthetic TCP session and optional WebSocket imports passed.
- The complete disposable V2.57 `full` integration run passed (exit 0),
  and its temporary containers/volume were removed. `web_session_check` covered:
  indexed album/queue selection, stale displayed-source rejection and verified
  playlist create/add/rename/remove. It uses generated media, not the interactive
  volume or physical DISC.
- Browser verification covers RU/EN, both palettes, preference persistence after
  reload, 390 px home and expanded player, and demo playlist
  create/add/rename/remove with membership readback.

## Everyday playback checkpoint — 2026-09-22

- Public Controller selection now covers complete/indexed custom playlists and
  indexed all-tracks/favorites, with fresh displayed-source and queue checks.
- Seek uses validated duration and the exact displayed track/source. A paused
  device seek remains explicitly unconfirmed until playback yields fresh
  position evidence. No implicit resume or retry is performed.
- Track menus offer play, supported playlist edits, known-album and artist links.
  They retain original source positions after filtering and support keyboard
  navigation. On mobile they appear as a bottom sheet.
- Demo indexed playback retains the complete selected source as its queue;
  demo seek preserves paused/playing state and remains silent.
- New synthetic Controller tests cover final playlist shifts, stale catalogs,
  unknown versions, seek bounds, paused seek and lost-connection no-replay.
  UI checks cover menu navigation, right-click/keyboard access, playlist member
  edits and pointer/keyboard seeking on desktop and at 390 px, in RU/EN and both
  palettes. The current app suite passed 15 Python and 8 JavaScript tests.
- Repository firmware-free validation passed 439 Python tests, 45 JavaScript
  tests, shell checks and all four shim builds. Ruff, mypy and isolated
  Controller wheel installation/synthetic-session checks passed.
- The complete disposable V2.57 `full` run passed (exit 0), including the expanded
  web-session acceptance for catalog/favorites/custom-playlist playback, playing
  seek, paused seek without resume, explicit resume observation and stale-track
  rejection. Temporary containers and volume were removed. No physical DISC or
  interactive emulator volume was used.

## Import and scan checkpoint — 2026-09-22

- The import dialog accepts individual files and directory-picker album folders,
  preserving the root and nested paths. Batches are sequential and stop on an
  unconfirmed item. Limits: 1,000 audio files, 2 GiB minus one byte each; the
  maximum file size is a validated bound, not a throughput acceptance result.
- Transfer has separate receiving/sending/verifying/finished states. The public
  Controller facade requires completed byte count plus a fresh directory entry;
  collisions, stale generations and incomplete staging never dispatch a write.
- Scanning is a separate explicit operation with discovered count. It owns the
  session without interleaved queries, invalidates displayed source tokens and
  refreshes the view after the observed end. Timeout/disconnect is uncertain.
- Demo consumes selected bytes only for presentation: no saved files, changed
  catalog, audio output or device connection. RU/EN and both palettes cover the
  import flow, including skipped file types and uncertain results.
- CUE exploration on a disposable V2.57 stack returned completed byte progress
  but no confirmable directory entry. The operation correctly remained uncertain;
  CUE was excluded from the supported importer. Artwork/CUE and other sidecars
  are explicitly skipped with a count, rather than reported as verified copies.
- Synthetic tests cover private staging cleanup, partial bodies, foreground
  admission, reconnect during staging, duplicate requests, path/size bounds,
  case-insensitive collision and observed scan ownership/no replay.

Validation for this checkpoint: app suite passed 20 Python and 9 JavaScript
tests; repository firmware-free run passed 450 Python and 46 JavaScript tests,
shell checks and four shim builds. Ruff, mypy and isolated Controller package
installation/synthetic-session checks passed. The full disposable V2.57 run
passed, followed by a focused `queue` run covering the final nested-folder upload,
byte equality, collision rejection, explicit scan and fresh index membership.
Both successful stacks were removed. The CUE exploratory run remained a failed
verification, as recorded above; it is not part of the supported import surface.
Browser checks cover folder picking, two identical leaf names in separate disc
folders, skipped sidecars, sequential demo transfer, explicit scan, RU/EN and
light/dark layouts at desktop and 390 px. No physical DISC or interactive
emulator volume was used.

## Connection settings checkpoint — 2026-09-22

- The RU/EN connection dialog supports local IPv4, editable TCP/HTTP ports,
  physical/emulator presets, a browser-saved draft and explicit connect/disconnect.
  Target replacement closes the old owner and invalidates displayed selections;
  active imports and stale requests block replacement. Demo cannot discover or connect.
- Passive six-second multicast discovery runs on a selected native host network
  interface. Results require selection and an explicit Connect. No LAN bridge,
  public binding or automatic device selection was added.
- With owner authorization, the physical DISC was discovered on both available
  LAN interfaces. The browser search found the same player; selecting it and
  connecting with TCP 12100 / HTTP 12103 reached ready state and loaded the live
  library. Page reload retained the server session. This was a connection and
  read-only browsing check: no playback, media or settings mutations were tested.
  Private addresses, catalog contents and physical screenshots are not retained
  in this report. This does not constitute full physical-feature acceptance.
- App tests passed 25 Python and 10 JavaScript checks. The repository firmware-free
  run passed 455 Python and 47 JavaScript tests, shell checks and four shim builds.
  Synthetic peers verify old-owner closure, no duplicate connection for unchanged
  settings, monotonic generations and stale/busy rejection without writes.
  Browser checks cover discovery, connection, reload and RU/dark and EN/light
  dialogs at desktop and 390 px. No firmware/runtime code changed.

## Catalog presentation refinement — 2026-09-22

UI refinement on 2026-09-22: visible album cards now show observed track credits
and counts, with separate lines so long credits cannot hide the count. Optional
summary reads retain the album's artist scope and never create playback tokens.
Empty album/time columns are omitted instead of suggesting unavailable catalog
metadata. Primary coral buttons use dark text (calculated contrast 6.94:1 in dark
appearance and 5.47:1 in light appearance). Physical read-only browsing confirmed
an album's credit/count and the compact track table; playback was not changed by
the check. App tests passed 26 Python / 11 JavaScript checks; firmware-free checks
passed 456 Python / 48 JavaScript tests and all four shim builds. The final
frontend suite passed 12 tests including bounded retry for busy reads and zero
replay for POST/transport failures. This addresses observed cover/catalog
contention while preserving mutation admission.

## Shared Library checkpoint — 2026-09-22

- Promoted the Assistant's catalog package to root `library/` and updated both
  consumers and CI. SQLite schema 1 and Assistant search behavior remain unchanged;
  Web does not require Typesense or import Assistant.
- Explicit synchronization borrows the existing Controller session and publishes
  only two matching complete catalog observations with verified album membership.
  Failed or interrupted synchronization preserves the previous snapshot. The UI
  reports progress, observation time and stale/offline status in RU/EN.
- Saved albums, artists and tracks remain browsable after disconnect and process
  restart. Search covers the entire saved collection, and track rows now have
  observed album metadata. Cached playback resolves exact album membership and
  requires Controller's fresh comparison before sending; cached positions are
  never sent directly. Local views remain available during device cover reads.
- Authorized physical read-only synchronization completed with 779 tracks and
  132 successful page reads. Earlier attempts encountered HTTP timeouts; pages
  are now limited to 100 rows, with one bounded retry of a failed network GET.
  Both complete observations still have to match. No physical playback, file or
  settings mutations were performed. Personal catalogs and screenshots remain
  outside Git.
- Browser checks verified persisted offline browsing after server restart,
  global search, album metadata, disabled offline playback/sync controls, EN/light
  desktop and RU/dark 390 px layouts. The server starts disconnected; the saved
  snapshot remains available independently of connection admission.
- Validation: Assistant suite passed 434 tests; Web passed 33 Python and 12
  JavaScript tests; final firmware-free CI passed 492 Python and 49 JavaScript
  tests, shell checks and four shim builds. Disposable V2.57 `queue` acceptance
  also passed the added stable-sync, cached selection, stale membership rejection
  and offline-view scenarios. Its temporary stack was removed.

This establishes shared catalog storage. Duration extraction, persistent artwork,
lyrics and external metadata enrichment are subsequent work, not supplied by this
snapshot schema.

## Library-owned enrichment checkpoint — 2026-09-22

- Library now owns synchronization stages, metadata association and observation
  storage. Web supplies the existing session lease, admission, request budgets
  and cancellation guard, and renders the resulting fields. Current-cover reads
  during listening use the same Library mechanism as explicit synchronization.
- The stock source supplies only current-track duration and artwork. Exact unique
  title/artist/album, two fresh album-membership reads and stable track identity
  around the image read are required. Duplicate/CUE ambiguity, shortened tags,
  changed paths/positions/durations/source and scans are rejected. The stock cover
  endpoint has no atomic image identity; observations retain this limitation and
  source provenance. No track cycling or external lookup is performed.
- Separate snapshot-scoped SQLite observations preserve raw catalog schema 1.
  Cached track images and durations appear in tables; albums can use an observed
  member's image. New snapshots never inherit associations by title. Images are
  deduplicated and bounded to 8 MiB each / 256 MiB total bodies, scoped to the
  active endpoint and snapshot when served. Missing fields remain unknown.
- Authorized physical read-only sync completed with 779 tracks and one enriched
  current track. Its image and 4:53 duration appeared in the saved track table and
  survived a server restart/offline browsing; album detail used the cached image.
  RU/dark desktop and EN/light 390 px layouts were checked. No physical playback,
  file or settings mutations were performed; personal data stayed outside Git.
- Validation: Web passed 36 Python / 13 JavaScript tests; firmware-free CI passed
  502 Python / 50 JavaScript tests, shell checks and four shim builds. Final focused
  Library/Web enrichment tests passed 10 checks. Disposable V2.57 `queue` acceptance
  passed with sync-time duration observation, guarded cached selection, stale
  membership rejection and offline browsing; the temporary stack was removed.

## Contextual search — 2026-09-22

Search now remains on the current page, including with a saved Library snapshot.
Albums match titles and all credited artists; artists/playlists match names;
tracks match title/artist/album within the current list. Artist and album details
retain their original scope and selection identities. RU/EN placeholders and
empty-state hints follow the page; navigation clears the query and refresh keeps it.
Browser checks verified album/credit matching, artist albums, exclusion of tracks
outside an album, and the 390 px layout. Web passed 36 Python / 13 JavaScript
tests; firmware-free CI passed 502 Python / 50 JavaScript tests and four shim
builds. No backend or device protocol changes were required.

The disconnected-view connection action now shares the sidebar device card's
neutral surface and border, with a compact device label and arrow. RU/dark desktop
and EN/light 390 px checks passed; the action still opens connection settings.
Existing Web and firmware-free checks pass; no connection behavior changed.

## Collection UI refinement — 2026-09-23

- Replaced the persistent saved-collection banner with a sync dialog opened from
  the top-bar icon. It shows four actual server stages, received-page counts,
  indeterminate progress, last observation, coverage and retained error details.
  Closing/reopening does not restart or cancel the job. Refreshing the current
  list remains a separate secondary action; demo cannot synchronize.
- Missing album and artist artwork now uses stable title-derived palettes,
  oversized escaped initials and subtle hover/keyboard-focus effects, respecting
  reduced motion. Real artwork takes precedence and decorative placeholders never
  enter Library metadata. Artist cards no longer repeat “Browse albums”.
- Browser checks used a synthetic TCP peer and catalog: sync completion, dismissal
  and reopening during work, failed reads preserving the saved collection, demo
  isolation and unchanged demo covers. RU/dark and EN/light layouts were inspected
  at desktop and 390/320 px; final console checks were clear. No physical device
  was used. Web tests passed 38 Python / 18 JavaScript checks; firmware-free CI
  passed 509 Python / 55 JavaScript tests and four shim builds.

## Optional LAN listener — 2026-09-23

`run.sh --host 0.0.0.0` explicitly enables all IPv4 interfaces; a specific local
IPv4 is also accepted. Default startup remains loopback-only and disconnected.
Startup prints detected LAN URLs. All browsers share the existing Controller
owner; LAN mode has no user authentication or TLS and requires a trusted network.
Host validation follows the accepted socket's actual local destination and port,
while Origin, request-token, generation and replay guards remain enabled.
Request IDs use cryptographic random bytes on HTTP LAN origins as well as localhost.

Browser validation opened the demo through the computer's LAN IP and successfully
changed the selected demo track with no console errors. The temporary listener
was closed; no physical player was connected. Web tests passed 41 Python / 19
JavaScript checks, including wildcard-listener admission and forged/duplicate
Host/Origin rejection. Firmware-free CI passed 512 Python / 56 JavaScript tests
and four shim builds. Access from a separate phone was not tested.

## Explicit emulator mode — 2026-09-23

Normal startup now waits for a player address with physical DISC port defaults
(TCP 12100 / HTTP 12103); developer preset buttons are hidden. `--emulator`
selects loopback with HTTP 12113 and exposes physical/emulator presets. Explicit
address/port overrides remain available. Neither mode connects automatically;
`--demo` and `--emulator` are mutually exclusive.

Unconfigured startup cannot connect via the legacy action or expose a prior
loopback catalog. Connection drafts are separate by mode; normal mode ignores
old loopback drafts, and explicit server targets take precedence. Unit checks
cover the first configured connection, snapshot isolation and CLI defaults.
Browser checks verified normal EN/light at 390 px and developer RU controls with
correct ports, without connecting a physical player or emulator. Web passed 43
Python / 20 JavaScript tests; firmware-free CI passed 514 Python / 57 JavaScript
tests and four shim builds.

## Dialog interaction refinement — 2026-09-23

All dialogs now dismiss on a backdrop click, with inside padding and drag-out
protection. A shared scroll lock preserves the background position across modal
transitions and restores it after closing; long dialogs scroll internally.
Browser demo checks covered backdrop/escape dismissal, internal scrolling,
background wheel blocking, track-menu to playlist transitions, scroll restoration
from a deep track-list position, and the 390 px layout. Unit checks cover gesture
boundaries, cancelled pointers, stacked dialogs and navigation. Web passed 43
Python / 22 JavaScript tests; firmware-free CI passed 514 Python / 59 JavaScript
tests and four shim builds. No physical player was used.

## Listening side panel — 2026-09-23

Now Playing and Queue share one non-modal right panel. Wide layouts reserve space
beside the collection; narrow layouts keep the mini-player visible below an
overlaid panel. Artwork scales with viewport height, section scrolling is
independent, and the header stays accessible. Track controls, queue selection,
metadata navigation and generation guards remain shared with the mini-player.
The shell can gain a lyrics section later; no empty lyrics control is exposed.

Browser demo checks covered RU/dark desktop and EN/light at 390 px, play/next,
queue selection, browsing alongside the panel, separate scroll positions, nested
modal Escape, focus restoration and mobile album navigation. Web passed 43 Python
/ 22 JavaScript tests; firmware-free CI passed 514 Python / 59 JavaScript tests
and four shim builds. No physical player was used.

## Album identity and artist navigation — 2026-09-23

Album links now retain known artist scope from cards, track menus and Now
Playing. Album-page artists are clickable. Name-only links remain stock title
groups and offer artist filters when several artists are present, preserving
compilations without assuming album-artist tags. Demo browse, album playback and
track queues now honor the same artist scope as live Controller selections.

Duplicate-title fixtures cover demo queue isolation, rejected cross-artist track
selection, cached live browse and guarded scoped playback. Browser checks covered
legacy and scoped links, artist navigation, Now Playing, and mobile selection of
a one-track album sharing its title with another artist's five-track album.
Web passed 46 Python / 23 JavaScript tests; firmware-free CI passed 517 Python /
60 JavaScript tests and four shim builds. No physical player was used.

## Next implementation stages

The [saved implementation plan](plan.md) owns the agreed stage order and
completion checkpoint: Now Playing/queue, synchronization visibility, folder
import through synchronization, then reviewed sound settings.

Do not expose placeholder settings as functioning controls or use diagnostic
clients to bypass the persistent facade.

## Current-track metadata — 2026-09-23

- Public Controller Track now retains observed sample rate, bit depth, channels,
  reported rate, genre, track number and DSD/SACD/CUE/M3U flags. Invalid optional
  values remain unknown. Seek retains the original six-field track identity and
  fresh source/generation protection; descriptions are not playback selectors.
- Library records the fields through the existing stable current-track observation
  during sync and artwork loading. An additive enrichment migration preserves
  prior data. Association, duplicate and scan guards remain unchanged; nothing is
  carried into another snapshot. Metadata can survive an unavailable cover/duration.
- Now Playing and saved-track action menus show available source properties in
  RU/EN and both themes. DSD suppresses PCM bit depth; reported bitrate is retained
  but not labelled compressed bitrate. No output-route or quality tier is inferred.
  Demo properties are explicitly fictional and isolated.
- Validation: firmware-free suite passed 521 Python / 61 JavaScript tests and four
  shim builds. Final focused checks passed 16 model/Library tests and 47 Web Python /
  24 JavaScript tests, including extended seek payloads. Ruff, strict mypy (12
  files), isolated sdist/wheel core and optional-extras checks passed. Markdown
  targets and whitespace were checked. Browser demo review covered desktop and
  390/320 px layouts, dark RU and light EN, Now Playing and track menus; no console
  errors or horizontal overflow were observed. No new physical connection or
  firmware execution was performed; device command semantics are unchanged.
- The current-track stage is complete in [the plan](plan.md). The owner deferred
  mounted SD/USB/source-folder enrichment on 2026-09-23; it is not the next stage.
  This implementation does not promise complete metadata over stock Wi-Fi.

## Native genre filters and playback — 2026-09-23

- Albums and Tracks now expose stock genre filters after one new Library sync.
  Facets, genre tracks and genre-album memberships publish atomically after two
  matching observations. Saved filters work offline; mixed-genre albums keep the
  correct subset and duplicate multiplicities. Genre deep links, back navigation,
  album/track switching and contextual search retain the selected scope.
- Whole-genre, genre-album and indexed playback use the new public
  `DiscSession.play_genre` with snapshot/connection tokens, expected membership,
  fresh preflight and queue confirmation. Artist/genre combinations are rejected,
  not broadened. Ambiguous metadata/artwork joins and genre playlist edits remain
  unavailable. Old snapshots retain ordinary browsing and display a sync hint;
  unresolved literal genre groups are disabled without alias guessing.
- Firmware-free checks passed 531 Python / 62 JavaScript tests and four shim
  builds. Web checks passed 50 Python / 25 JavaScript tests; focused genre checks
  cover stale snapshots, changing membership, duplicates, missing genre facets,
  unsupported firmware, final preflight races and no retry after uncertainty.
  Ruff, strict mypy (12 files), isolated Controller sdist/wheel and extras passed.
- The disposable V2.57 `library` scenario passed on TCP/WS. Its added persistent
  facade check synchronized native facets and confirmed whole genre (type 8),
  indexed genre (type 10), genre album and indexed genre album (type 8), exact
  queue sizes/positions and rejection of a stale expected source. Generated media
  was restored/removed and the disposable stack was cleaned up. No physical
  player or interactive emulator volume was used.
- Browser verification used a synthetic ordinary-mode offline collection with
  duplicate names and split-genre albums, plus the isolated demo for Play genre.
  Desktop dark RU and mobile light EN/dark RU at 390/320 px covered filtering,
  scoped navigation, search, queue contents and disabled offline controls. No
  horizontal overflow or browser console errors were observed.
- The [plan](plan.md) now records the owner's broader Controller coverage goal and
  bounded candidates. Local-file enrichment and PEQ investigation remain deferred.
