# Stock DISC HTTP file and library API

The active Mongoose listener on **12103** supplies file/library operations alongside
FiiO Link TCP 12100. The emulator exposes stock HTTP directly on **12113**; its
optional bridge proxies these same requests on 12103. These are stock handlers,
not a new firmware service or the inactive Mongoose dashboard.

## Evidence and scope

Disposable V2.40 and V2.57 integration tests establish folder creation, streamed
FLAC upload, progress, single file/empty-folder deletion, library pagination, custom playlist
create/rename/add/remove/delete, and remote reindexing. Generated files are checked
byte-for-byte inside an isolated guest; playlist effects are checked with read-only
SQLite. The same scenario runs directly and through the HTTP proxy, with scanning
over TCP and WS respectively. PNG upload is additionally verified on V2.57.

Both full local integration runs passed on 2026-09-15. The firmware-free suite also
passed; the expanded suite now has 164 Python tests, 23 JavaScript tests, shell syntax checks and four MIPS shim
builds. These are local results, not a claim about a hosted CI run.

Physical DISC V2.57, 2026-09-15: `/dir/tmp/` and catalog pages matched the emulator
schema. A unique temporary folder and generated Unicode-named FLAC were created;
listing and completed byte-count progress matched. Deleting the file allowed the
empty folder to be removed, and a fresh parent listing confirmed its absence.
No scan, playback or settings changes were made in that physical HTTP probe.
The physical `/image/cover/` request also returned a 48,864-byte `image/jpeg` body
with JPEG start/end markers; only response metadata was retained, not the artwork.
This does not establish a byte-for-byte hash of the uploaded physical file, M21 compatibility,
or every app operation. Private raw responses remain in ignored `work/`.

A [2026-09-23 metadata and lyrics audit](../../research/docs/reports/2026-09-23-library-metadata.md)
rechecked the fingerprinted V2.57 route table and dispatcher. It separates current
artwork/audio metadata, local lyric processing and the absence of a general
file-download handler on this HTTP service.

## Request conventions

The user's iOS 4.6.0 HAR additionally records `GET /localdir/tmp/` on physical DISC:
`start-pos: 0`, `num-max: 100` returns one `sdcard` directory, `total-num: 1` and
`mark-pos: 0`. This is the playback-browser route, distinct from `/dir/tmp/`.
See [app capture evidence](../../research/docs/reports/fiio-control-app.md#ios-460-observed-http-2026-09-15)
for theme requests and the trace's limitations.

- File paths are **URI suffixes**, e.g. `/audio/tmp/sdcard/Test/Track.flac`.
  Percent-encode UTF-8, spaces, literal `+`, `%`, `?` and `#`; preserve `/` separators.
- Pagination and library filters are **HTTP headers**, not query parameters:
  `start-pos`, `num-max`, `type`, `artist`, `album`, `style`, `list_name`.
  Numeric headers are **decimal**, unlike TCP hexadecimal fields.
- Header names containing Unicode values use percent-encoded UTF-8. A literal plus
  must be `%2B`, because the library handler decodes `+` to space. Stock copies named
  headers into 256-byte buffers before decoding; the client limits the encoded value
  to 255 bytes.
- Uploads send the **raw file body with Content-Length**. No multipart wrapper,
  base64 body or HTTP chunked transfer is used. The firmware's `HTTP_CHUNK` callback
  denotes streaming receive events, not a requirement for chunked transfer encoding.
- **HTTP 200 does not establish success.** Invalid operations, busy scanner and
  unknown routes can all return empty 200. Read back the resulting state. The client
  never retries mutations after a timeout, because the first write may have completed.

## Files and images

The separate lock-screen upload, stock-theme selection and metadata headers are
documented in [REMOTE_MODES_THEMES.md](remote-modes-themes.md#lock-screen-http).
Do not use an empty-body custom-theme POST to edit metadata: it clears the image path.

| Request | Observed behavior |
|---|---|
| `GET /dir/tmp/sdcard/…/` | Transfer-browser page; `total-num` header and JSON records |
| `POST /dir/tmp/sdcard/New%20folder` | Create one directory; new entry in JSON and `is-exist: 0`. Existing directory gives empty 200 and `is-exist: 1` |
| `POST /audio/tmp/sdcard/…/Track.flac` | Stream file bytes, create missing parents, truncate an existing file at that path |
| `GET /progress/tmp/sdcard/…/Track.flac` | JSON `{name, now_size, percentage}`; complete is **1.0**, not 100 |
| `DELETE /file/tmp/sdcard/…/Track.flac` with empty body | `remove()` on exactly one path; also removes an empty directory |
| `GET /localdir/tmp/sdcard/…/` | Playback browser page; also supplies `mark-pos` |
| `POST /image/tmp/sdcard/…/Image.png` | General image upload, **V2.57 route only**; PNG bytes verified |
| `GET /image/cover/` | Current `/usr/data/fiio/cover.jpg`; JPEG response verified on physical V2.57, empty in the generated fixtures without artwork |

Directory record:

```json
{"pos":0,"is_dir":false,"name":"Track.flac","is_cue":false,"is_m3u":false,"is_image":false}
```

`/dir/` returns empty 200 without a count for both an empty directory and a missing
path; the client preserves `total: null`, not an invented zero. PNGs uploaded
successfully in V2.57 were absent from the tested `/dir/` and `/localdir/` listings.
These are filtered media browsers, not a complete filesystem inventory.

Progress can remain cached **after deletion**. It cannot prove a file still exists
or verify its contents. `HTTPClient.upload()` conservatively rejects an observed
existing destination or cached transfer unless `overwrite=True` is explicit. This
can reject reuse of a deleted path. The check is best-effort: stock has no verified
atomic exclusive-create request, and another writer can race it.

There is no validated file rename, resume/range upload, or general file download
request. Folder import can be implemented as a sequence of folder/file requests.
The client restricts mutations to children of `/tmp/sdcard` and exposes only the
empty-body single-path delete. Stock batch directory deletion constructs shell
commands and is intentionally not exposed; use individual file deletions followed
by empty-directory removal.

## HTTP catalog and custom playlists

`GET /song_category_tree/`, headers `type: all/song`, `start-pos: 0`, `num-max: 20`:

```json
[{"pos":0,"name":"Track.flac","author":"CI Artist","count":0}]
```

Response headers include `total-num`, `mark-pos` (often -1), and `type`. Catalog page
size is capped at 200 in V2.57. Follow returned positions within that exact ordering;
do not substitute TCP song IDs or SQLite IDs.

Active category table: `all/song`, `artist`, `artist/song`, `artist/album`,
`artist/album/song`, `album`, `album/song`, `style`, `style/song`, `style/album`,
`style/album/song`, `love/song`, `curlist/song`, `custom`, `custom/song`.
Baseline acceptance exercises all-song pages, named album songs and custom
lists. V2.57's focused `library` scenario additionally checks genre/album filtering,
pagination and grouped bulk expansion; see [genres and folders](library-browsing.md).
Existence of other category handlers is not full behavioral validation.

Physical iOS capture on 2026-09-16 additionally confirms `curlist/song`: the app
requests offset 0, limit 100, with empty `artist`/`album`/`style` headers. The reply
contains 15 queue rows (`pos`, `name`, `author`, `count`), `total-num: 15` and
`mark-pos: 0`. Selection/navigation proceeds over TCP without another queue GET.
The reported mark is therefore a snapshot. See
[queue evidence](remote-control.md#current-queue-in-the-stock-ios-app).

| Operation | Method / path | Headers / body |
|---|---|---|
| List custom playlists | `GET /song_category_tree/` | `type: custom` |
| List playlist tracks | `GET /song_category_tree/` | `type: custom/song`, `src_list_id: <position>` |
| Create playlist | `POST /custom_list_cmd/` | `type: create`, `list_name: <encoded name>`, empty body |
| Rename playlist | `POST /custom_list_cmd/` | `type: update`, `list_id: <position>`, `list_name`, empty body |
| Add catalog range | `POST /add_custom_list/` | `type: all/song`, `dst_list_id: <position>`, JSON `[[first,last]]` |
| Remove playlist entries | `DELETE /song_category_tree/` | `type: custom/song`, `src_list_id`, **`delete_source: 0`**, JSON ranges |
| Delete playlist | `DELETE /song_category_tree/` | `type: custom`, **`delete_source: 0`**, exactly `[[position,position]]` |

Ranges are **inclusive zero-based positions**. Despite the `_id` names, custom-list
headers refer to the playlist's position in `LIST_ID` order. Acceptance deliberately
creates an internal ID gap before rename/add/delete to catch accidental ID use.
List positions can shift after deletion; refresh them before the next operation.
Deleting records with `delete_source: 0` preserves audio files, but general-
catalog deletion also removes matching favorites and playlist entries; scanning
does not restore that membership. Source deletion can leave stale references
or affect other playlists. See [verified deletion scopes](library-delete.md).
Physical FiiO Control 4.6.0 captures now confirm both source flags for scoped
track deletion and subsequent file listing. An offset-one read after deleting
one of two tracks returns `items: []` but `total-num: 1`; refresh from zero
instead of treating the album as empty. Source-file deletion through the category
route is not exposed in the client.
For V2.57 genre/group bulk addition, prefer `add_selection_to_playlist()` with
the displayed destination name; it checks filters and current range bounds.
Group categories accepted by ADD are **not** accepted by DELETE: `style/album`
returns empty 200 unchanged. Scoped song deletion with `delete_source: 0` is
tested only on disposable data; no general deletion helper is added. See
[bulk selection and deletion limits](library-browsing.md#deletion-is-a-different-contract).

V2.57's `0501` settings advertise `http_replace_link: 1` and `http_custom_list: 1`.
This explains why the missing TCP `0405` reply was not evidence that custom playlists
were unavailable. These flags are useful capability hints; successful operation
still requires validation for each product/firmware.

Playback uses TCP `0100`/`0101` with list type 5 and JSON `{"id":<position>}`;
the JSON ID is positional too. See [custom-playlist playback](playlists.md) for
the guarded TCP/WS helper, catalog refresh requirements and acceptance scope.

## Upload → index → play

`Client.scan_library()` / `WSClient.scan_library()` send **`0622000C0000`** once.
Observed events are `a60a/000F` (start), `a622/<count>` (hex count), then
`a60a/0005` (ended, also emitted after cancellation). Busy/rejected/failed scans
need separate handling; `a622` alone is not completion. After completion, query
the catalog and require the new track to appear. Upload alone did **not** add a
track to the index in the test.

V2.57 cancellation is verified through `cancel_library_scan()` on TCP/WS:
`0622000C0001` cooperatively stops the scanner and leaves a **partial replacement
index**, not the old complete index. The stop flag is not a library reset, and
`a60a/0005` does not distinguish cancelled from full completion. See the
[scan lifecycle, evidence and tests](library-scan.md) before implementing progress UI.

Dedicated `reset_library(confirm=True)` is a separate TCP/WS operation (`0621`),
not HTTP deletion. It discards index/favorites, preserving files and custom-list
rows, but immediate HTTP responses can be inconsistent. A rescan does not recreate
the missing favorites table. See [reset scope and recovery](library-reset.md).

The acceptance test uploads a fourth track, indexes it through the network command,
removes that test file, and reindexes back to the three original fixtures. No
synthetic SD event or screen tap is needed for this explicit scan.

```python
from controller.fiio_http import HTTPClient
from controller.fiio_link import Client

http = HTTPClient('PLAYER_IP', 12103)
print(http.directory('/tmp/sdcard'))
http.mkdir('/tmp/sdcard/New album')
http.upload('track.flac', '/tmp/sdcard/New album/track.flac')
# Inspect listing/progress; HTTP 200 alone is insufficient.
with Client('PLAYER_IP') as link:
    link.handshake()
    link.scan_library()
    # Consume events until a60a/0005, then refresh the catalog.
```

Read-only CLI: `python3 -m controller.fiio_http --host PLAYER_IP --port 12103 --catalog custom`.
For local emulation the client defaults to `127.0.0.1:12113`.

## Reproduction / static references

`tests/integration/http_check.py` is wired into `ci/integration.sh`; it runs only against disposable
fixtures. `controller/tests/test_fiio_http.py` tests actual HTTP framing, binary bodies, Unicode,
position ranges, malformed replies, path bounds and no retry after uncertain writes.

Reproduce route discovery with `research/diagnostics/inspect_http_routes.py` and a fingerprinted
stock binary. V2.57 handlers: directory GET `48ba5c`, POST `48bc98`, delete file
`48bfd0`, audio upload `48c574`, progress `48c3cc`, category GET `4936b8`, category
DELETE `49484c`, playlist command `4939c4`, add-to-list `493ee4`, image upload `48e46c`.
Header/path helpers are `496b70`, `496c1c`, `496c60`; library header decoding is
`4c8c28`. These are V2.57 addresses, not offsets to apply to V2.40.
