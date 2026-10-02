# DISC Web

An experimental music remote with its own application server, interface and
launcher. It uses the public [Controller](../../controller/README.md) and shared
[Library](../../library/README.md), and has no
Assistant, viewer, emulator or speech dependencies. It stays under `experiments/`
until a separately agreed promotion.

## Run

Python 3.11+ is sufficient; there are no Python packages, Node dependencies,
external fonts, CDNs or frontend build steps to install.

```sh
# Fictional interactive collection. Never opens a connection to a device.
./experiments/disc_web/run.sh --demo

# Physical DISC: enter its address or find it from the connection dialog.
./experiments/disc_web/run.sh

# Developer-only emulator preset, still requires Connect in the browser.
./experiments/disc_web/run.sh --emulator

# Open the Web UI to devices on your trusted LAN (no user authentication).
./experiments/disc_web/run.sh --host 0.0.0.0

# Optional initial player address; it can also be entered in the browser.
./experiments/disc_web/run.sh --device 192.168.1.50
```

Open [127.0.0.1:8091](http://127.0.0.1:8091). Stop the process with Ctrl+C.
Use `--port` for another application port. The default bind remains `127.0.0.1`.
Use `--host 0.0.0.0` to listen on all IPv4 interfaces, or `--host 192.168.1.20`
to bind one local interface. Open `http://<computer-LAN-IP>:8091` on a phone
on the same network; startup prints detected LAN URLs. `0.0.0.0` is a bind
address, not the address to enter on another device. `--host` selects the Web
server address; `--device` selects the player. `--emulator` and `--demo` are
mutually exclusive. Both modes support the Web bind/port options.

LAN mode exposes the collection and player controls to reachable network clients.
There is no user authentication or TLS; use it only on a trusted network, without
router port forwarding. Same-origin checks and request tokens remain enabled,
but they do not authenticate LAN users. All browsers share one Controller owner.

Disconnect Assistant or FiiO Control before connecting DISC Web. There is one
stock TCP owner. Closing a browser tab does not disconnect the server or stop
device playback. The application does not connect on startup, boot an emulator,
download firmware or open a physical device during tests.

## Connect your player

Open the DISC connection card, enter the player's local IPv4 address and press
**Connect**. Normal startup has no selected player and uses TCP 12100 / HTTP 12103.
Developer mode `--emulator` selects 127.0.0.1 / TCP 12100 / HTTP 12113 and exposes
the physical/emulator preset buttons; ordinary users do not see these buttons.
Explicit `--device`, `--tcp-port` and `--http-port` override the initial target.
Neither mode connects automatically. Ports are editable under
**Connection ports**. The last submitted address is saved in this browser as a
draft, separately for normal and emulator modes; old loopback drafts are ignored
in normal mode. A server-selected target takes precedence over a browser draft.
Page load never initiates a connection. An already enabled server session
survives page reload. **Disconnect** stops its automatic connection recovery.
Changing the target closes the old session and invalidates old library selections.
The dialog closes after the submitted target reaches connected state. Failed
connections remain visible; reopening connection settings keeps the dialog open.

**Find on network** listens for six seconds on the selected computer interface.
DISC announces itself using UDP multicast to 224.0.0.255:12101; this is passive
discovery on the Python server, not UDP in the browser. Select a result, then
press **Connect**. Discovery never connects automatically. Announcements stop
while another TCP client owns the player. Wi-Fi client isolation, multicast
filtering and Docker networking can also prevent discovery; manual IP entry
remains available. Interface discovery supports macOS and Linux with `iproute2`.
Use the native host server on the same LAN for physical discovery. No LAN relay
or exposed control service is started. Demo disables connection and discovery.

## Available now

- Responsive home, album grid/detail, artist-scoped albums, tracks, favorites
  and custom playlist browsing; search within the current view.
- Before synchronization, visible album cards read their track credits and count on demand. Multiple
  distinct credits are labelled Various artists. Completely unknown album/time
  columns are omitted: stock catalog rows supply neither per-track album nor
  duration; duration in Now Playing comes from its separate observed state.
- Persistent bottom player and a spacious Now Playing screen with artwork,
  album/artist navigation, playback status and an adjacent queue. On mobile,
  switch between player and queue. Both queue views offer explicit refresh.
  A format badge uses the observed file extension. Available device metadata
  adds sample rate, bit depth, channels, genre, track number and source flags
  below the controls; these describe the source, not the output device.
- Missing album/artist artwork uses stable colored typographic placeholders with
  subtle hover/focus motion. These decorations never count as observed covers.
- Light, dark and system appearance; RU/EN interface with saved browser preferences.
- Browser connection settings and passive LAN discovery; developer emulator
  presets are enabled only with `--emulator`.
- Sound panel with observed gain, L20..R20 channel balance, six DAC filters and DRE;
  each change requires an explicit Apply and fresh device confirmation.
- Live whole-album/artist/playlist playback, indexed tracks from albums, the
  catalog, favorites, playlists and queue; pause/resume, previous/next, current-track
  favorite, absolute volume and random/repeat-list controls through `DiscSession`.
- Seek with time preview in both players, exact displayed-track protection and
  explicit pending/uncertain status for paused or unconfirmed device seeks.
- Track action menus with playback, supported playlist edits and navigation to
  known albums/artists; keyboard navigation and mobile bottom-sheet layout.
- Create/rename custom playlists; add tracks from all tracks or an unscoped
  album and remove playlist members, with fresh identity checks and readback.
- Import files or an album folder, preserving the selected root and nested paths.
  Audio files are sent sequentially, with per-file
  progress and readback. Up to 1,000 files per selection, each at most 2 GiB minus
  one byte (the stock signed Content-Length bound). Non-music files, including
  artwork and CUE sheets, are skipped with a count. Folder picking uses the browser directory
  chooser; drag-and-drop accepts individual files.
- Explicit library scan with discovered-track count and fresh catalog refresh
  after its observed end. Transfer and scan are separate user actions.
- Current-track cover from stock HTTP. Library retains safely associated artwork
  and durations for offline track/album display; missing fields use placeholders.
  The stock API supplies this enrichment for the current track only.
- An isolated demo with eight original SVG covers and fictional names, genre
  filtering, track/queue selections, simulated playback and favorites. It has no
  stored music files, audible output, persistence or real-device mutations.
  Import consumes selected bytes for a visual simulation, without saving files
  or changing the fictional catalog.

The interface labels demo mode, including on mobile. Demo actions simulate presentation and do not prove firmware behavior.
File browsing/deletion, artwork sidecars and additional device settings remain future
implementation stages. They must use reviewed public Controller operations. Browser audio streaming is
outside this implementation; live audio stays on DISC.

## Sound settings

Open the sliders button in the top bar. The panel reads the current player values
on opening or explicit refresh; it does not poll settings continuously. Choose a
value and press its **Apply** button. If that value changed on DISC in the meantime,
the edit is rejected and the panel asks for a new read. Connection changes clear
the displayed settings; uncertain writes are never repeated automatically.
Demo, disconnected and unsupported states expose no functioning setting controls.
Only reviewed V2.57 gain, balance, filter and DRE are supported. Filter names use
stock device labels, and balance units are steps, not percentages. Bluetooth
device selection/output identity and PEQ are not included.

## Saved library

Open the sync icon in the top bar, then press **Sync library** to read and verify
the current DISC catalog and publish one complete local snapshot. This does not scan the SD card, upload files or
change playback. First scan newly added media on DISC when needed, then sync.
There is no automatic sync or restart after failure. A failed network GET may be
repeated once within the request budget; two complete equal reads are still required.

Albums, artists and tracks (including album membership) then load from SQLite.
Search stays in the current view: albums by title or credited artist, artists by
name, tracks by title/artist/album, and playlists by name. Album/playlist detail
search filters only its tracks; artist detail filters that artist's albums. Home
search filters its albums. Typing never changes the page, including offline;
navigating to another page clears the query. Disconnecting leaves those views
available, with playback disabled; favorites, custom playlists and the current
queue still need a live player. The sync dialog shows the last observation, track
count and offline/stale status. **Library details** explains artwork and duration coverage
for the saved collection. During sync, real stages and received page counts are
shown separately from the last successful observation, without an estimated
percentage. Closing the dialog leaves the server operation running; the top-bar
icon shows activity and completion/failure produces a brief notice. A failed sync
preserves the previous snapshot. **Refresh current list** inside the dialog reloads
the current view; **Sync library** updates the saved collection from DISC.

Storage defaults to `~/.local/share/disc-web`; `--data-dir PATH` selects another
private directory. It is separate from Assistant storage. Snapshots are namespaced
by host and TCP/HTTP ports: this is an endpoint identity, not a hardware serial.
After a restart, use the same `--device` / port settings to browse that endpoint's
saved library without connecting. Moving a player to another IP creates a separate
namespace; reassigning an IP to another player requires a fresh sync.

Library keeps original metadata and duplicate recordings. Playback from a saved
track uses its album scope and compares the complete expected membership with a
fresh Controller read; old snapshot positions are never dispatched directly.
Offline metadata does not imply the player still contains those files. Known
imports/scans and new connection generations mark the snapshot as possibly stale;
external changes are not continuously detected. Sync is bounded to 10,000 tracks,
1,000 catalog requests and a 300-second observation deadline (an in-flight HTTP
request may use its socket timeout). Browsing the previous snapshot remains possible
while sync owns the connection. Other device operations fail busy rather than queue.

Library synchronization includes an optional enrichment stage for available
current-track artwork, duration and descriptive metadata. The same Library mechanism runs when Web
loads current artwork during listening. Exact, unique tags, fresh album membership
and stable current-track reads are required; duplicate or shortened metadata is
not guessed. This does not fill every track or cycle playback. New catalog
snapshots do not inherit observations by name.

Observations and source provenance live in `observations.sqlite3` beside the
catalog; catalog schema 1 and Assistant storage are unchanged. Coverage counts
tracks with each observed field, not unique images or fully enriched albums.
Unavailable metadata storage is shown as unknown coverage, not zero.
Cached artwork and durations survive disconnect
and restart. Artwork is restricted to JPEG/PNG, 8 MiB per image and 256 MiB total
body storage. The stock image endpoint has no atomic track identity, so guarded
reads remain observations. Local-file extraction, external metadata services and
shared Assistant/Web TCP ownership remain future stages.

## Import behavior

Open **Add music**, choose files or a folder, review the relative paths and press
**Transfer to DISC**. Files go below `/tmp/sdcard`; a selected `Album/Disc 1/Track.flac`
keeps that complete structure. Existing names and cached transfers block a file;
there is no overwrite or automatic rename. Stock has no atomic exclusive-create
API, so concurrent external HTTP writers can still race the preflight.

The server stages one file privately in the OS temporary directory, removes it
when the operation finishes and retains only the latest job status in memory.
A partial browser upload never reaches DISC. A failure stops the remaining batch;
no command is replayed after timeout or reconnect. A reload can observe the latest
server job, but does not resume the browser's remaining file list. Closing the
import dialog lets the current batch continue in the page.

**Start scan** is a separate explicit action, available without an upload.
Its count measures discoveries, not a percentage. There is no cancel/reset control
in this UI. An unconfirmed end may mean scanning continues on DISC. The observed
end does not prove every format/file was indexed. Transfer readback checks a
fresh directory entry and completed byte count; it is not a device-side hash.

The import dialog follows three separate steps: memory card, DISC library, saved
collection. It shows confirmed/waiting file counts and prompts for **Sync library**
after a confirmed scan on the same connection. This uses the same explicit sync
operation as the sync dialog; neither scan nor sync starts automatically.
After successful publication, **Open collection** opens the saved albums.
Catalog totals are not proof that every selected file was imported: remaining or
unconfirmed files keep a separate message even after a successful sync.

Changing connections blocks continuation of a previously started selection until
it is cleared or selected again. On page reload only the latest server job is
available; the UI does not claim to restore the complete batch. Demo finishes
with its scan preview and never enables catalog synchronization.

## Validation and documentation

```sh
./experiments/disc_web/run.sh test
```

Tests use loopback synthetic peers and curated data. They are also discovered by
the repository's firmware-free runner. Node is only needed for the frontend
utility and preference tests, not to run the application.

- [Architecture and API](docs/architecture.md)
- [Saved implementation plan](docs/plan.md)
- [Current status and next stages](docs/status.md)
- [Contributor instructions](AGENTS.md)

Current-track audio properties also appear in the track action menu for safely
associated saved rows, including offline. Unknown values are hidden; source DSD
suppresses the PCM bit-depth presentation. Device-reported bitrate is retained by
Library but not displayed as compressed-file bitrate. Demo properties are explicit
fictional examples and never substitute for missing device observations.

## Genre filters

After updating Web, run **Sync library** once to save the player's native genre
catalog. **Albums** and **Tracks** then offer genre filters, which work offline.
The selected genre is retained in the URL, album navigation and the switch between
albums and tracks. **Play genre** selects that complete native genre; album Play
and individual rows select only their displayed genre scope. A mixed-genre album
can therefore show different track counts under different filters.

Genres are literal device labels; they are not inferred from the current track
or translated. A group the stock API cannot resolve is disabled. Old snapshots
remain browsable and show a sync hint. Genre rows retain separate positions and
do not inherit catalog artwork/durations by title. Playlist edits from genre rows
remain disabled until their batch-source workflow has its own facade. Playback
requires a ready player and fresh source verification; browsing does not connect,
scan the card or start playback. Demo follows the same genre navigation using
explicit fictional data.
