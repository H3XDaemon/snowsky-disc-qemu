# FiiO Control application evidence

**Version provenance (owner confirmation, 2026-09-16):** all supplied iPhone
checks, screenshots and captures in this investigation used **FiiO Control
4.6.0**. This retrospective confirmation applies to the earlier batches too;
Dart's HTTP User-Agent does not itself establish the app version. DISC firmware
versions retain their individual wire/device evidence and are not inferred from
this confirmation. Sanitized iOS fixtures record `app_version` and its source.

## Screen coverage audit

Supplied-screen audit finalized 2026-09-16 within the agreed local DISC scope.
[Current capability summary](../../../docs/protocol/disc-capabilities.md) consolidates the observations
below, implemented helpers, unsupported actions and deferred work.
Scope: the DISC interface of FiiO Control, not every other supported product.
Record the app version, platform and DISC firmware with each batch; do not
assume an unchanged build.

Start with theme selection and every custom-theme editor panel. Then inventory
the other screens, including scrolled portions, nested settings, option dialogs,
context menus and disabled controls where visible. Opening a destructive-action
confirmation is enough to record its UI; do not reset/delete/update merely to
complete screenshots. Redact personal names, network identifiers and paths.

For each screen/control, record: screenshot reference and navigation path, visible
action and choices, matching helper/endpoint, evidence/test link, coverage status
and next evidence needed. Separate these statuses:

- Implemented and validated in the emulator.
- Observed in a physical-app capture (record separately from emulator coverage).
- Read-only or rejected by the tested DISC network interface.
- Visible but unverified / missing client implementation.
- Hardware-only or outside the current emulator scope.

Screenshot inventory completeness and protocol/hardware validation are separate;
a visible control alone is not proof of a supported command. The future web
remote frontend is not implemented just because a helper exists. Request focused
traffic captures only where existing contracts do not resolve a specific gap.

Raw screenshots/captures stay in ignored `shots/` or `work/`. Commit only minimal,
sanitized evidence; approved curated screenshots belong in `docs/images/`, not
links to ignored local files. Custom-theme saves and library batch actions now
have capture evidence below. Opacity and color-slider captures are now analyzed
below. Official catalog/account synchronization is deferred by owner decision
to [issue #11](https://github.com/eudj1n/snowsky-disc-qemu/issues/11); no capture is currently requested.

### Wallpaper screens: first batch (2026-09-16)

Owner-provided iPhone screenshots `IMG_6789.PNG` through `IMG_6794.PNG`, Russian
UI, show 17:30–17:31. The owner explicitly confirms this inspection used the
**physical DISC**, not the emulator. These are phone-app screens while connected
to that device, not photographs of the player's display or a network capture.
App/firmware versions are not visible; the earlier reported
iOS 4.6.0 / DISC V2.57 context is not fresh version evidence. Images are not copied
into Git; filenames identify the supplied evidence, not repository links.

| Screen/control | Screenshot | Existing coverage and remaining evidence |
| --- | --- | --- |
| Wallpapers → My wallpapers carousel / All | 6789, 6791 | One custom and five system tiles match the tested slot counts. `read_lock_screen()` reads each slot. No separate list/catalog helper or remote frontend. |
| Apply / Applied | 6789, 6791 | Clock is marked applied in the app. `select_system_lock_screen()` covers system selection; custom upload also activates. Screenshot alone does not prove device readback or a standalone custom-activation request. |
| Official wallpapers | 6790 | Shows “No wallpapers”. No catalog helper; endpoint and cause of empty state unknown. Owner reports cloud synchronization requires FiiO registration/sign-in. Deferred to [issue #11](https://github.com/eudj1n/snowsky-disc-qemu/issues/11); do not infer an authentication failure or unsupported device API from this empty page. |
| Custom → tap image to change / Apply now | 6792–6794 | Full 360×360 PNG replacement/activation implemented. Image picker, crop and conversion flow are not shown or implemented by the helper. Existing-image reapply resends the full PNG, confirmed by `173912` and `174708`; crop/conversion remains app-side and unobserved. |
| Background opacity (owner-confirmed label) | 6792; follow-up `230929` | System slot 1 maps displayed 100 → 49 → 0 → 100 directly to `alpha`; GET confirms 49/0/100. Owner observes a dimmed background at 49, no picture at 0, and refresh only after unlock/relock. Custom-slot opacity rendering is not tested by this capture. [Evidence](#physical-system-theme-opacity-2026-09-16). |
| Time, Date, Battery, Track information | 6793 | All four appear checked. Helper exposes `time/date/battery/id3`; metadata is emulator-tested. Date/time changes and full-image saves are physically captured below; physical rendering of all overlays remains unverified. |
| Style selection, four thumbnails | 6794 | Three digital layouts and one analog clock are visible; the first thumbnail is selected. Initially a fixed-style helper gap; now four wire values are captured and emulator-tested (see style-save evidence below). Thumbnail ordering is inferred from the requested walkthrough, not encoded in packets. |
| Two color-gradient sliders | 6794, 6822–6825 | `231820` confirms system metadata saves of exact RGB values. Upper selects hue; lower visually runs white → selected hue → black, with saved white/pink examples. Exact numerical conversion and black endpoint remain untested. [Evidence](#physical-system-theme-colors-2026-09-16). Custom saves still use a full PNG. |

The two tiles labelled FIIO Sheep have different artwork; names are not unique
theme identities. Clock is the selected wallpaper in the list, while the first
custom layout is selected in its editor: these are different selection levels.
The custom image preview lacks overlays even though all four checkboxes appear
checked; this does not prove a rendering failure or that flags are ignored.

The subsequent [physical capture](#physical-custom-theme-save-2026-09-16) resolves
the color/Date save sequence: the app resends the complete image. The second
[style capture](#physical-custom-style-save-2026-09-16) confirms four custom
style values and unchanged subclass, with a time-flag change in the request.
Official-catalog loading is deferred to issue #11; image-picker/cropping remains
a separate app-side gap.

### Physical system-theme colors (2026-09-16)

Inputs: `2026-09-16-231820.pcap` / `.har` and `IMG_6822.PNG`–`IMG_6825.PNG`.
FiiO Control 4.6.0 is owner-confirmed; fresh Link `a501` at frame 1287 reports
`soc_version: 257`. TCP reassembly shows the handshake and initial read commands
`0501`, `0607`, `0627`, `0639`, `0202`, `0629`, `0628`; no color-setting Link
command is observed. [Sanitized fixture](../../../controller/tests/fixtures/fiio_control_ios_system_theme_colors.json).

All **14 HTTP exchanges** match HAR by paired request method, semantic headers,
status and request/response body hashes. Relevant TCP bytes are contiguous and
untruncated, with no retransmissions/lost segments; HTTP lengths agree. The app
first reads custom slot 0 and system slots 0..4, then makes four POST/GET pairs
for active **FIIO Sheep / system slot 1**. All return HTTP 200.

| Request seconds / frame | RGB (`front-color`) | Fresh GET frame | Screenshot correspondence |
| --- | --- | --- | --- |
| 4.187 / 1387, initial GET | 191,139,66 | 1387 is the GET request | 6822: golden/brown preview |
| 30.668 / 1926, POST | 253,0,255 | 1945 | 6823: magenta preview |
| 52.784 / 2103, POST | 251,255,0 | 2112 | No dedicated supplied image of this yellow-green save |
| 72.226 / 2342, POST | 255,255,255 | 2351 | 6824: white preview, lower slider at left |
| 92.651 / 2477, POST | 255,169,169 | 2486 | 6825: pink preview, upper at red/left |

Every POST has an empty body. Apart from `front-color`, semantic headers are
unchanged: opacity 100, style `default/2`, all four overlay flags 1, active flag
1, stock slot/source/subclass and percent-encoded alias. Each following GET
confirms the exact RGB bytes. The initial and four subsequent slot-1 image
responses are identical 360×360 PNGs, 199846 bytes, matching the prior opacity
capture's image hash. GET omits `preview-flag`: these are default-preview bytes,
not an independently read original file. No custom-slot POST occurs; its initial
alpha 60/red/inactive metadata is merely a read, not a new custom-opacity test.

**Slider interpretation from screenshots plus traffic:** the upper rainbow
slider selects hue. The lower track runs white → selected hue → black; the
observed white endpoint and intermediate pink fit a lightness control, rather
than three independent RGB sliders. Moving upper from the initial orange area
to magenta produces near-full magenta while the lower thumb stays visually near
the middle; the initially desaturated golden color is not proof of a fixed
saturation parameter. Preserve RGB directly in a controller. No numeric thumb
values, precise RGB/HSL/HSV conversion, rounding or interpolation formula were
recovered, and the lower black endpoint was not saved in this trace.

After the white preview (upper near yellow), the pink screenshot has the upper
thumb at the red/left end. This does not establish whether reopening reconstructed
an undefined hue from white or another user movement occurred; the wire carries
only RGB, not a retained hue coordinate. Screenshot clocks have minute precision,
so the table pairs visible colors, not exact screenshot/action timestamps.
These are phone previews, not photographs or a new physical-display observation.

**Restoration:** final readback is pink 255/169/169, not initial 191/139/66.
The same theme remains active with unchanged noncolor metadata, but original
color restoration is not claimed. Do not automatically replay a restore command.
Existing system selection preserves exact saved RGB (including near-primary
values); a new regression compares its requests with this fixture. Dedicated
system editing is now implemented with verified readback; see
[the helper contract](../../../docs/protocol/remote-modes-themes.md#system-theme-editing). No repeat color capture is needed
to establish the observed RGB save/readback contract; exact UI-formula cloning
is outside this checkpoint. Official catalog work is deferred to issue #11;
local helper/capability consolidation is complete in the final summary.

### Physical system-theme opacity (2026-09-16)

Owner supplied `2026-09-16-230929.pcap` and `.har`, labelled **Background
opacity**, with the actual order **100 → 49 → 0 → 100**. This differs from the
requested custom-image walkthrough: all requests target **system slot 1,
FIIO Sheep**, not the custom slot. App 4.6.0 is owner-confirmed; no fresh firmware
version is present. [Sanitized fixture](../../../controller/tests/fixtures/fiio_control_ios_system_theme_opacity.json).

All seven HTTP exchanges match HAR (methods, semantic request headers, request
and response body hashes). Relevant TCP payloads are contiguous, untruncated,
without retransmissions; HTTP body lengths agree. No TCP 12100 packets occur.
PCAP relative times below identify request starts; all responses are HTTP 200.

| Seconds / request frame | Action | Result |
| --- | --- | --- |
| 6.275 / 1267 | POST system slot 1, `alpha=100` | Empty response; no immediate GET |
| 27.310 / 1313 | POST `alpha=49` | GET at 27.383 / 1322 returns 49, active slot 1 |
| 38.504 / 1450 | POST `alpha=0` | GET at 38.564 / 1459 returns 0, active slot 1 |
| 60.750 / 1615 | POST `alpha=100` | GET at 60.801 / 1624 returns 100, active slot 1 |

Every POST goes to `/image/lock_screen/` with **zero body bytes**. Other semantic
headers stay constant: slot 1, `file-source: lock_screen/system`,
`subclass: lock_screen/system/default`, `alias: FIIO%20Sheep`,
`msg-style: default/2`, `front-color: r=191;g=139;b=66`, all four overlay flags 1,
and `flag-in-use: 1`. Readbacks match. All three returned PNGs are identical,
360×360 / 199846 bytes; SHA-256 is in the fixture. GET omits `preview-flag`, so
this is equality of default-preview responses, not proof about original bytes
on disk. No initial GET establishes the previously active theme; final readback
confirms alpha 100 and system slot 1 active, not full restoration of unseen state.

**Physical observations, reported by the owner:** at 49 the background becomes
partly visible/dimmed; at 0 the picture disappears against a dark background.
The control represents opacity, not inverse transparency. These three observed
values map directly to the wire; no precise linear brightness curve is claimed.
While already locked, the effect required unlocking and locking again. This
establishes a visible refresh limitation in this session, not a missing save:
GET already reports the saved value. Packets do not identify the local lock
transition or prove which internal component delays repainting. No reboot test.

Controller implications: present an opacity percentage (0 hides the background,
100 is full opacity); verify saved metadata separately from rendering and explain
that unlock/relock may be needed. Do not automatically unlock the device or
repeat writes just because the current lock screen looks unchanged. Keep system
metadata-only POSTs distinct from custom saves, which require the full PNG.
The system-selection helper preserves returned metadata;
`update_system_lock_screen` now adds verified system metadata editing. Regression tests cover preservation of
captured 49/0/100 values and the empty-body system request, not a new editor or
emulated physical repaint. Custom-slot opacity rendering remains unobserved.

### Physical custom-theme save (2026-09-16)

Inputs: `2026-09-16-173912.har` and matching `.pcap`, captured by the owner on
physical DISC. Surge HAR creator: iOS 5.22.0. App/firmware versions were not
newly confirmed. Source hashes and sanitized fields are in the
[regression fixture](../../../controller/tests/fixtures/fiio_control_ios_custom_theme_save.json).
Raw captures and PNG bodies are not committed.

Of 17 HAR entries, 14 target DISC HTTP 12103, all `/image/lock_screen/`:
six initial GETs, four custom POSTs, three custom readbacks and one system POST.
All 14 have HTTP 200 responses. Other traffic is excluded from the evidence.
The PCAP has matching 14 HTTP connections and **no TCP 12100 packets**; it does
not establish that the app never uses TCP for other theme actions.

TCP payloads were reassembled by sequence number in each direction: no gaps or
conflicting overlaps, all relevant payload packets untruncated, and all 28 HTTP
messages' bodies match Content-Length. Request/response body multisets match the
HAR exactly. All nonempty bodies are 360×360 PNGs. HAR timestamps have only
whole-second precision and entries are not reliably chronological within a
second; the PCAP establishes POST-before-GET ordering below. Times are UTC+05:00
and identify the start of each request, not completion of the large upload.

| Time | Operation | Observed result |
| --- | --- | --- |
| 17:39:23 | Read custom and five system slots | Clock active; custom inactive, white RGB, alpha 100, all four overlay flags 0, `default/0` |
| 17:39:46.832 | Custom POST: color `(0,96,226)` | Complete original PNG resent; activates custom slot. GET at 17:39:47.283 confirms color, active flag and identical image |
| 17:40:05.075 | Custom POST: date 0 → 1 | Color unchanged, other flags 0; same complete PNG. GET at 17:40:05.382 confirms date and image |
| 17:40:14.736 | Identical custom POST repeated | Same metadata and image; 200, no immediate readback. No action log to distinguish another tap from app behavior |
| 17:40:31.940 | Custom POST: white color and date 0 | Same PNG. GET at 17:40:32.157 confirms original custom metadata/image, still active |
| 17:40:35.832 | Select system Clock, slot 0 | Empty-body system POST, 200; no final GET proving active-theme restoration |

Every custom POST and custom GET contains the same **203,218-byte** PNG, SHA-256
`ef76ab578f8daa06a5ff1b52101259420cb5da701d276cc4dce87757409e1442`.
There is no metadata-only write in this trace: color/Date changes use ordinary
full-image replacement plus all metadata. This agrees with `upload_lock_screen()`
and the previously tested empty-custom-body path-clearing quirk. No new endpoint,
TCP command or speculative metadata-only helper is necessary for these actions.

Two important limits remain:

- App POST alias is the percent-encoded label `Пользовательский` (96 encoded
  bytes; the earlier count of 90 was incorrect). Custom GET returns empty alias.
  Follow-up [boundary tests](../../../docs/protocol/remote-modes-themes.md#alias-limit-v257) prove stock
  truncation before decoding, including incomplete UTF-8 in SQLite. The 63-byte
  guard is retained. Tests compare other semantic headers and deliberately
  reject the app's unsafe alias; this is not exact whole-request parity.
- Initial wire overlay flags are all **0**, despite the earlier screenshot's
  checked-looking circles. The inputs are not simultaneous and there is no action
  log connecting them; neither a UI bug nor ignored flags is established.

System GET metadata contains `clock/0`, `default/0`, `default/1`, `default/2`,
but every custom save here uses `default/0`. These system values are leads, not
validation of the other custom styles or their visual-thumbnail mapping. Alpha
never changes; the two color sliders' individual semantics remain unobserved.

Validation: all five `controller/tests/test_fiio_theme.py` tests pass, including synthetic
full-image saves for the four captured metadata states and long-alias rejection.
The container firmware-free suite passed: **259 Python / 23 JavaScript tests**,
shell checks and four shim builds. No runtime/helper change or physical write by
our tools was needed. Firmware integration and long power tests were not rerun
for this fixture/test/documentation change; prior emulator evidence is identified
separately above, not reported as a fresh firmware run.

### Physical custom-style save (2026-09-16)

Inputs: `2026-09-16-174708.har` / `.pcap`, continuation of the physical DISC
walkthrough. The [sanitized fixture](../../../controller/tests/fixtures/fiio_control_ios_custom_theme_styles.json)
records source hashes, request times, styles and flags without image bytes or
addresses. Versions were not newly confirmed by these files.

All 17 HAR entries are `/image/lock_screen/` on HTTP 12103: six initial reads,
five custom saves and five readbacks, then one system selection. All receive 200.
PCAP sequence reassembly verifies complete, nonconflicting byte coverage and
Content-Length for 34 HTTP messages; HAR/PCAP request and response body multisets
match. No TCP 12100 packets occur. PCAP resolves the within-second ordering which
the HAR alone cannot establish. Each custom POST is followed by its GET.

| POST start (UTC+05:00) | Custom style | Time flag | Subsequent GET start |
| --- | --- | --- | --- |
| 17:47:22.463 | `default/0` | 0 | 17:47:22.716 |
| 17:47:32.790 | `default/1` | 0 | 17:47:33.043 |
| 17:47:38.350 | `default/2` | 0 | 17:47:38.536 |
| 17:47:44.101 | `clock/0` | 1 | 17:47:44.302 |
| 17:48:00.313 | `default/0` | 1 | 17:48:00.501 |

Each GET confirms the posted style, time flag and active custom slot. Date,
battery and ID3 flags remain 0; alpha remains 100, RGB white, and subclass always
`lock_screen/custom/default`. Every custom POST/GET carries the same 203,218-byte
PNG as the preceding capture, with SHA-256
`ef76ab578f8daa06a5ff1b52101259420cb5da701d276cc4dce87757409e1442`.
Clock system selection at 17:48:03.856 is empty-body and receives 200; there is
again no final GET proving active-theme restoration. The custom time flag is 1
at the end versus 0 at entry: restoration of all custom settings is **not** proven.

The app's clock POST already contains time=1, so firmware did not introduce that
particular change in its response. A separate tap versus automatic app coupling
cannot be determined from packets. The requested sequential-thumbnail walkthrough
suggests three digital styles in order followed by the analog clock, but there
is no synchronized action log; expose wire strings, not undocumented UI indices.

Implementation: `upload_lock_screen(..., style=...)` allowlists these four values
and preserves independent flags, full image, current subclass and alias guard.
The earlier long Russian app alias still exceeds the helper bound; fixture tests
compare the remaining semantic headers and generated image bytes, not claim
whole-request equality or copy private artwork.

Validation: focused fresh **V2.57 `themes` passed** directly and through the HTTP
proxy, including every style with time=0 and time=1, unchanged image and metadata,
SQLite flag values, five system slots, unsafe empty-body behavior and restoration
of the original active system theme. Stock preserves time=0 even for `clock/0`;
this is persistence/readback evidence, not physical rendering evidence.
The test uses a generated PNG, disposable volume, no published ports and no edits
to the interactive or physical player. Stack and volume were removed afterwards.
Firmware-free suite: **261 Python / 23 JavaScript tests**, shell checks and four
shim builds passed. No full integration, legacy-profile integration or long power
rerun for this narrowly scoped helper change. No Dockerfile/Compose changes:
the existing image/dependencies and tracked scenario reproduce the experiment.

### Library, PEQ and settings screens: second batch (2026-09-16)

Owner-supplied `IMG_6795.PNG`–`IMG_6806.PNG`, 18:07–18:08, continue the physical
DISC app audit. The pictures do not independently identify firmware/app versions
or provide network readback. Raw screenshots and personal library contents are
not copied into Git. Coverage below means existing protocol helpers and their
tests, **not** a completed replacement frontend or validation of every app action.

| Screen/control | Screenshot | Existing coverage / gap |
| --- | --- | --- |
| All songs | 6795 | TCP `library('tracks')`, HTTP `catalog('all/song')`, positional selection and all-song playback exist. App's batch-selection actions are not shown. |
| Artists | 6796 | Physical captures now confirm `artist` → `artist/album` → `artist/album/song`, type-7 scoped-album selection and whole-artist Play all. Guarded `play_artist` adds fresh source checks. Root-page Play all produced no playback command in `213631`; its cause/selector semantics remain deferred. [Evidence](../../../docs/protocol/library-browsing.md#physical-folder-album-and-artist-flow-2026-09-16). |
| Albums | 6797 | Catalog, named album tracks and positional/whole-album playback are tested. Root Play all was ineffective with no playback dispatch in `213631`. Track batch addition is captured in `215831`; see the later batch evidence. |
| Genres | 6798 | Guarded `play_genre` covers whole-genre, indexed tracks and genre-scoped albums with emulator acceptance. Physical capture confirms the hierarchy, whole-genre Play all and scoped-album selectors; indexed whole-genre selection remains emulator-only. [Contract](../../../docs/protocol/library-browsing.md). |
| Folder → sdcard | 6799 | `/localdir/` browsing and guarded `play_folder` have emulator acceptance for ordinary audio, including directory rows in positional indices and nonrecursive Play all. Physical capture now confirms type-4 indexed/whole-folder selection and directory-inclusive positions. The capture does not establish nested-folder contents. |
| Favorites | 6800 | Empty state shown. Explicit current-track favorite on/off and V2.57 favorite-index selection/readback are tested. No general batch favorite-by-ID helper or favorite play-all helper. Empty screenshot does not establish those operations. |
| Custom Playlist and New Playlist dialog | 6801–6802 | Empty state, plus button and name/confirm/cancel dialog shown. HTTP create/rename/add/remove/delete and guarded whole-list/index playback are tested; this image does not prove creation succeeded or show populated-list menus. |
| Mini-player | 6795–6801 | Track/artist metadata, play/pause and next have physical captures and emulator tests. Placeholder artwork alone does not prove cover retrieval failed. Opening the full player is frontend navigation, not a new protocol command. |
| PEQ, off/save, graph, master and band controls | 6803; follow-ups `203157`, `214316` | All 21 supported codes/ten User slots have disposable acceptance. Physical BYPASS=`00F0` echoes/reapplies the previous mode; public writes remain rejected. Compact band/master edits, device Save no-op and current-profile Reset are captured and emulator-tested. Local Save, remaining editor controls and Auto EQ remain open. [PEQ evidence](peq.md). |
| Update / Reset music library | 6804 | `scan_library()`, cooperative cancel and dedicated `reset_library(confirm=True)` are tested. Actual app reset command sequence is unobserved; do not reset a personal library merely for this audit. |
| Gain | 6804–6805 | High/Low choices, High checked. Follow-up stock UI tracing establishes **0 Low / 1 High**, both TCP/WS values and SQLite tested. The screenshot alone does not establish that mapping or measure dB. |
| Bluetooth codec, SPDIF, balance, DRE | 6804 | Existing settings helpers/tested control paths; five source-codec choices already physically captured. SPDIF appears off and DRE on; balance/codec subpages are not included in this batch. No claim about physical audio/DSP output. |
| Filter | 6806, 6816, 6817 | Six choices; slow minimum-phase checked. Physical walkthrough maps all six app rows to helper 0..5 / wire 9..14 and confirms restoration. Subsequent English screenshot supplies full labels, but rows 5/6 both say “Reference super slow roll-off” despite different codes. Russian endings remain clipped. [Physical mapping](../../../docs/protocol/remote-settings.md#physical-fiio-control-filter-mapping-2026-09-16). |
| User Feedback | 6804 | Entry visible only. No implementation; classify as app/support functionality unless capture demonstrates a device operation. Destination and submitted data unknown. |

PEQ screenshot: visible scale -24..+12 dB, master control, graph labels 31..16k,
zero-valued gains/frequencies and an off-labelled button. The view is clipped at
the right/bottom; do not derive the total band count from visible sliders. The
ten-band contract comes from protocol evidence. Zero frequency/Q readback with EQ
off is already known; this image alone neither diagnoses a bug nor justifies
relaxing setter validation. The safe helper still requires a user preset before
editing, and only exposes validated peaking filter type 0.

Repeated/similar album and genre labels and multi-artist labels are visible.
Preserve returned rows/positions and literal names; do not deduplicate, trim or
split labels based on screenshots. Displayed similarity cannot establish whether
underlying tags differ, nor prove an index defect.

Follow-up emulator validation on 2026-09-16: guarded `play_genre` (including
genre-scoped album), `play_folder` and `add_selection_to_playlist` now cover the
genre/folder playback and bulk-add gaps above. Fresh V2.57 TCP/WS and direct/proxy
tests are recorded in [LIBRARY_BROWSING.md](../../../docs/protocol/library-browsing.md). This does not
identify the app's exact commands from screenshots. The initially deferred
physical genre capture has now arrived; see the follow-up below. The app's
folder selection is now physically confirmed by the later `211747` capture;
Both scoped-track Delete flags are now captured; album-group Delete is UI-unsupported (see the later Delete evidence). The later owner correction with IMG_6818
establishes that sdcard browsing offers no batch actions; folder-to-playlist is
not an app-parity capture task in this UI.

The third batch below supplies genre/album batch toolbars and PEQ selection/save
screens. Folder contents and individual-item menus remain unseen. Request
targeted TCP/HTTP captures for concrete gaps, not repeat screenshots already supplied.
The later `2026-09-16-192141` physical filter capture plus `IMG_6816.PNG` closes
the six-row label/code mapping: reported actions 3→4→5→6→1→2 match setters and
replies, followed by fresh restoration readback. HAR is empty; PCAP carries the
evidence. [Timeline, fixture and limits](../../../docs/protocol/remote-settings.md#physical-fiio-control-filter-mapping-2026-09-16).
Do not sweep unknown codes or change physical gain with active listening.

### Genre hierarchy, batch actions and PEQ: third batch (2026-09-16)

Owner-supplied `IMG_6807.PNG`–`IMG_6815.PNG`, 18:12–18:15, continuation of the
physical DISC audit. These are screenshots, not evidence that any shown action
was submitted or persisted. Versions are not displayed. No raw screenshots or
personal library contents are committed.

Owner decision, 2026-09-16: **PEQ is a separate workstream**, tracked in
[issue #9](https://github.com/eudj1n/snowsky-disc-qemu/issues/9). Record its screens
here, but do not request further PEQ captures or implement its missing workflows
as part of the current library audit. Existing PEQ helpers/tests remain intact.

| Screen/control | Screenshot | Coverage and interpretation |
| --- | --- | --- |
| Genre detail → album rows | 6807 | Six visible album-like rows, each with its own track count. The later `185016` capture confirms `style/album` with the named genre filter. Genre-to-album-to-track browsing must not be flattened into a genre song list. |
| Album detail → tracks, Play all | 6808 | Physical `185016` confirms type 8 with both genre and album. Guarded `play_genre` preserves that scope; generic type-3 album selection is not interchangeable. |
| Select all / Cancel / per-row selection | 6809–6810 | Two red selected rows, others outlined. No command is inferred merely from selection marks. The same visual toolbar appears at album-group and track levels. |
| Add to Playlist | 6809–6810, 6818 | Guarded `add_selection_to_playlist()` has emulator acceptance for genre-group expansion, scoped tracks and disjoint ranges. Physical `215831` confirms track addition; `221421` confirms one `style/album` POST expanding first/third album groups, total 105 and a 100-row destination page. Owner reports no batch actions in sdcard browsing. [Validated sources and limits](../../../docs/protocol/library-browsing.md#bulk-addition). |
| Delete | 6809–6810 | Scoped track deletion is captured with `delete_source` 0 (`224332`) and 1 (`225423`); directory readback distinguishes index removal from file removal. Album-group action shows unsupported (`IMG_6820`), without a supplied trace. Public source-delete helper remains absent. [Contract and limits](../../../docs/protocol/library-delete.md). |
| Save this PEQ → device / local data | 6811; follow-up `214316`, 6830–6832 | Owner chose device; capture sends `0626/0000`, a V2.57 no-op because edits already persist. No target-slot dialog confirmed. Compact band/master edits and Reset `0675` are captured; reset profile readback succeeds. Owner navigated back without disconnecting. Local Save/Apply evidence is recorded below; export remains unverified; Share/login is deferred by owner. [Evidence](peq.md#physical-device-editing-save-and-reset-2026-09-17). |
| EQ Device presets | 6812; follow-up `203157` | Off, ten named factory tiles, User 1..10 and **BYPASS** are visible. All 21 supported codes/ten User slots now have acceptance. Capture identifies BYPASS=`00F0` separately from Off=`00FF`; V2.57 reapplies the previous mode and echoes 240, so public setters exclude it. Exact app-label spelling remains separate from stock labels. [Evidence](peq.md#physical-presetbypass-capture-2026-09-17). |
| Auto EQ | 6813 | Headphone measurement and target-curve selectors, Random / Save as / Reset, response graph and frequency/gain/Q rows. No curve catalog, matching algorithm, generation/save or device-application helper. Existing `set_peq()` can send validated bands, but does not implement Auto EQ. The graph's ±18 scale is not proof of accepted device gain limits. |
| Local | 6814; 6835/6837/6841; captures `215948`, `221148` | Save creates card `p1`/`p2` in My custom without an additional captured device mutation. Follow-up Apply sends master plus bulk hex bands in a format incompatible with V2.57's setter. Exact emulator replay moves the first-band cut to the last; the JSON helper applies it correctly. No physical post-Apply band getter precedes Reset, but final baseline restoration and Off are captured. Overflow shows Deleted/Share/Rename (6842). Owner reports Share says “Please login first” and excludes that flow; export/synchronization remain unverified. [Evidence](peq.md#physical-local-apply-and-v257-format-mismatch-2026-09-17). |
| Selected | 6815 | Empty view with a truncated password/retrieval prompt. Meaning and endpoint unknown; this is not evidence of TCP 12100 authentication, an unlock password or a firmware secret. |
| Official | 6814–6815 | Tab label only; its contents are not provided. Do not treat the blank Selected screen as the official catalog. |

The genre heading says “total songs: 6” while the six rows look like albums
with larger individual counts. Record the nesting, not an inferred six-track
library or a diagnosed index defect; wire schemas/counts must resolve the units.
Outlined checkmarks are also used on unselected batch rows. As with the theme
screens, a tick outline alone is not reliable proof of an enabled setting.

The requested genre capture is now analyzed below; no repeat is needed for
the observed hierarchy and scoped-album commands. Subsequent folder selection
is captured; `213631` records ineffective root-category Play all with no playback
dispatch. Subsequent `215831`/`221421` cover track/group additions and rename;
`224332`/`225423` cover scoped-track Delete. These captures need no repeat.
No media reset, cloud login or preset overwrite is needed for this audit. PEQ captures/changes belong to issue #9 when explicitly resumed;
do not combine them into the current library trace.

### Physical genre flow (2026-09-16)

Inputs: `2026-09-16-185016.pcap` and `.har`, supplied for the previously requested
physical genre workflow. Firmware 257 is confirmed by fresh settings; app version 4.6.0 is confirmed retrospectively by the owner. [Sanitized fixture](../../../controller/tests/fixtures/fiio_control_ios_genres.json)
contains source hashes and frame references; raw captures/artwork stay outside Git.

- PCAP has 13 device HTTP requests versus 3 in HAR. Browsing proceeds through
  `style` → `style/album` → `style/album/song`; the last carries both genre/album.
- Scoped-album indexed and whole-list playback match our type-8 helper. Position
  15 selects the 16th of 19 tracks; two Next commands select 17/19 and 18/19.
- Whole-genre Play all uses type **8 with an empty album**; physical readback
  shows a 54-track queue. Follow-up disposable TCP/WS comparison with type 10
  passes in modes 0/4, and the helper now uses the captured form for Play all.
  Indexed whole-genre selection retains type 10; it is not covered by this capture.
- The first genre attempts six CUE entries with zero duration, loading state and
  repeated `a60a/000D`, without playback progress. Do not call that successful EOF
  or infer a decoder/file defect without further evidence. Ordinary tracks in the
  second genre do reach playing state and progress.
- No folder-track selection, bulk mutation or root-category Play all is present.
  A root folder GET alone does not validate folder playback.

See [timeline, client differences and reproduction](../../../docs/protocol/library-browsing.md#physical-genre-flow-2026-09-16).
Firmware-free tests cover matching HTTP filters/scoped selectors and the captured
Play-all form, keeping indexed genre selection on its independently tested path.

### Physical folder and artist follow-up (2026-09-16)

`2026-09-16-211747` and `2026-09-16-212141` PCAP/HAR pairs resolve folder
selection, ordinary named-album selection and the artist hierarchy. The app
uses type 7 with artist + album for scoped tracks/Play all, and an empty album
for Play all inside an artist. It does not reuse the ordinary type-3 album
selector. Folder type 4 matches the existing helper, including its positional
directory row. Timeline, sanitized fixture and limits are recorded in
[library browsing](../../../docs/protocol/library-browsing.md#physical-folder-album-and-artist-flow-2026-09-16).
No root-category playback or batch mutations occur in these captures.

The owner subsequently confirms that **FiiO Control on iPhone** has Play all on
all four root tabs: All songs, Artists, Albums and Genres. Button presence is now
established by owner report. The subsequent `2026-09-16-213631` PCAP/HAR
records navigation through all four roots, but **no playback command** for the
reported ineffective taps. The final named-genre action sends type 8 and reaches
playing state/nonzero progress on the same connection. Classify the root buttons
as visible but ineffective in this captured app state, not rejected by DISC or
proven permanently unsupported. Exact root-selector/order semantics stay unknown;
reopen only with changed behavior or concrete app-code evidence. See
[timeline and limits](../../../docs/protocol/library-browsing.md#root-tab-play-all-produces-no-playback-request-2026-09-16).

### Batch-action availability correction: IMG_6818 (2026-09-16)

The owner reports batch actions on the same detail screens where Play all works,
except sdcard browsing. On the individual-track player, the available library
action is favorite on/off; there is no Add to Playlist. These availability claims
come from the owner's walkthrough, not extrapolation from the single image.

IMG_6818 itself shows an album track list (15 songs), Select all / Cancel and a
toolbar with Add to Playlist / Delete. It does not show a destination picker,
successful addition, Delete confirmation or source-file checkbox. Outlined
checkmarks do not establish the selected set. Raw image and personal track names
are not copied into the repository. The proposed folder capture is withdrawn;
the [corrected scenario](../../../docs/protocol/library-browsing.md#pass-b-album-track-batch-addition-corrected-after-img_6818)
uses two nonadjacent album tracks and an empty test playlist. The subsequent
`215831` PCAP/HAR confirms this action using an existing empty destination:
one chunked HTTP POST, source ranges 0/0 and 2/2, destination position 1, then
count 2 and the expected two tracks on a fresh GET. The existing helper matches
the decoded request; chunk framing in HAR is not part of the JSON contract.
Only one post-add membership read is present in `215831`.
[Timeline and limits](../../../docs/protocol/library-browsing.md#physical-album-track-addition-2026-09-16).

Subsequent `221421` PCAP/HAR confirms creation, genre-album group addition and
rename: one `style/album` POST for group positions 0 and 2, then `custom_list_cmd`
with `type: update` and `list_id: 2`. Fresh GET reports the new name with count
105 unchanged. Only the first 100 membership rows are captured; no full-identity
or cross-rename membership comparison is claimed. Existing helpers match these
requests. The firmware Delete scope now has [disposable acceptance](../../../docs/protocol/library-delete.md),
including cross-list loss and stale references. Physical `224332` now confirms
the unchecked source-file checkbox maps to `delete_source: 0` for scoped track
deletion; album B disappears from the genre catalog while A retains two tracks.
`IMG_6820` and the owner report album-group Delete shows “This function is not
yet supported”; no packets were supplied for that pass, so its wire dispatch is
unknown. `225423` then confirms track-level flag one with current row `[[1,1]]`
for A1; the directory retains only A2 and previously index-deleted B1. Its empty
post-delete track page has offset one and total one, not an empty album. Both
track-level variants are complete; no repeat group capture is needed. [Delete evidence](../../../docs/protocol/library-delete.md#physical-ios-track-deletion-and-unsupported-group-action-2026-09-16). [Evidence](../../../docs/protocol/library-browsing.md#physical-genre-album-groups-and-playlist-rename-2026-09-16).

## Android 4.6.0 input (2026-09-15)

User-provided `FiiOControl V4.6.0.apk`:

- Manifest package: `com.fiio.control`.
- Manifest version: `4.6.0`, version code **105** (verified with Android SDK `aapt2`).
- APK SHA-256: `516c6d882a6723b03d7860f8ab000ce8dc600d9fabe986bfe187ba15d37d110c`.
- ARM64 `libapp.so` SHA-256: `c8364937febff7ddd493f3874c38580908433ae9bb42388cc5d79a3785265f6c`.
- Flutter engine contains Dart **3.10.9**, Android ARM64 release.
- Three DEX files plus Flutter AOT libraries. Java analysis alone does not recover
  the Dart Link command builder. JADX 1.5.6 completed with 51 decompilation errors;
  its output is partial, not a complete source reconstruction.

The user reports iOS app version 4.6.0 too. This identifies a useful comparison
version; it does not establish the same build, wire commands or platform behavior.

## Concrete AOT leads

These strings and package paths are present in the ARM64 snapshot. Their presence
identifies analysis targets, not a recovered call graph or validated command:

| Area | Observed names |
|---|---|
| Link command builder | `linkmodule/utils/link_command_builder.dart` |
| Library operations | `getUpdateLibraryMsg`, `getCancelUpdateLibraryMsg`, `getResetLibraryMsg` |
| Modes | `getWorkModeMsg`, `getSetWorkModeMsg` |
| File transfer | `linkmodule/linked_device/service/wifi_music_http_service.dart` |
| Themes | `linkmodule/linked_device/service/wallpaper_http_service.dart` |
| Newer local catalog | `fiio_v2/link_device_v2/service/local_play_http_service.dart`, `local_dir_http_service.dart` |
| Folder UI/controller | `fiio_v2/link_device_v2/ui/local_dir_browser_page_v2.dart`, `controller/local_dir_browser_controller.dart` |
| Playback/batch search targets | `playAll`, `playAllAlbum`, `playAllAlbumSong`, `add_songs_to_playlist_dialog.dart`, `delete_source`, `delete_source_file` |
| Theme contract strings | `/image/lock_screen/`, `back-groud`, `lock_screen/system`, `lock_screen/custom`, `lock_screen/custom/default` |

The folder/batch leads were rechecked locally after synchronizing to `28c5008`;
the ARM64 library still matches the SHA-256 above. These are independently
present snapshot strings, not attributed call sites. In particular,
`playAllAlbum` does not establish a root Albums command, and `delete_source_file`
does not establish a visible checkbox, its default or the transmitted value.
No Dart AOT control-flow reconstruction or new device test is claimed.

Wallpaper leads rechecked on 2026-09-16 against the same full ARM64 hash:
`WallpaperThemeCloudService`, `WallpaperCloudTheme.fromJson`,
`WallpaperItem.fromCloudTheme`, `fetchThemeList`, `get-theme-list?deviceId=`,
`/wallpapers`, `_buildFontColorSlider`, `_updateFontColor`, `computeFontColor`
and `wallpaper_bg_opacity`. These identify candidates for the remaining catalog
and slider investigation. Strings alone do **not** connect the URL fragments to
a service, identify its host/device ID, recover color/alpha conversion or prove
that iOS calls it. No endpoint was guessed or queried. Further catalog investigation belongs to deferred issue #11, with no active
capture request; do not classify the empty Official page as unsupported.

The theme strings agree with already tested firmware endpoints. No reset tag
has been recovered from this APK, and no reset was sent to physical DISC.
Separately, V2.57 firmware analysis and disposable tests established dedicated
`0621/0000`: see [library reset](../../../docs/protocol/library-reset.md). The owner confirms the app
offers library reset (2026-09-16), but its exact frame/follow-up sequence is still
unobserved; firmware evidence is not an app capture.
Generic Dart runtime proxy strings also occur; they do not prove that FiiO Control
honors the phone's HTTP proxy configuration.

Selected binaries, partial decompilation and inventory remain in ignored
`work/fiio-control-460/`. No APK, app assets or decompiled sources belong in Git.
At this checkpoint, the [Blutter project](https://github.com/worawit/blutter) had
only been inspected as a route to Dart AOT function/object-pool analysis.
The [2026-09-22 follow-up](2026-09-22-fiio-control-profiles.md) successfully ran it
against the same APK and recovered the bundled product/function database and
startup refresh call sites. Earlier string-only findings above retain their
original evidence limits.

## iOS 4.6.0 observed HTTP (2026-09-15)

The user captured FiiO Control and Surge on the same iPhone. The HAR creator is
Surge iOS **5.22.0**; the app reports `Dart/3.10 (dart:io)` as User-Agent. App
version 4.6.0 is user-reported, not encoded in that User-Agent.

`2026-09-15-231411.har` contains **10 requests**, all to physical DISC HTTP port
12103, all with status 200. Entries are stored newest first; ordering below uses
`startedDateTime` (UTC+05:00). Encoded response bodies decode completely and match
their recorded lengths.

| Time | Request | Observed result |
|---|---|---|
| 23:15:20 | GET `/image/cover/` | 48,864-byte JPEG |
| 23:15:26 | GET `/localdir/tmp/` | `start-pos: 0`, `num-max: 100`; one `sdcard` directory, `total-num: 1`, `mark-pos: 0` |
| 23:16:47 | Six GET `/image/lock_screen/` | System slots 0..4 and custom slot 0; all 360×360 PNGs |
| 23:16:52 | POST `/image/lock_screen/` | Select system slot 1, `FIIO%20Sheep`, empty body |
| 23:16:57 | POST `/image/lock_screen/` | Select system slot 0, `Clock`, empty body |

Theme GETs identify the slot through `x-fields-to-update` and `file-source`.
The app omits `preview-flag`, using the stock preview default. Our helper explicitly
requests the original image instead. Both selection POSTs echo the corresponding
GET metadata, setting `flag-in-use: 1` and preserving the already percent-encoded
alias. This matches `select_system_lock_screen()` without runtime changes.

The initial GET reports Clock active. The final POST requests Clock again, but
there is **no subsequent GET** proving the final active state. No custom image
upload, mode/codec command or library reset is present. The custom GET has an empty
alias; this agrees with the previously observed emulator behavior.

The curated [fixture](../../../controller/tests/fixtures/fiio_control_ios_460_themes.json) retains
only the two selections' protocol metadata and source hash. A regression test in
`controller/tests/test_fiio_theme.py` compares generated POST headers and empty bodies with
these actual iOS requests. Images, personal cover artwork and raw HARs are omitted.
The expanded firmware-free suite passed: **165 Python tests, 23 JavaScript tests**,
shell checks and four shim builds.

`2026-09-15-231846.har` is 88 bytes with `entries: []`. The user repeated the same
actions after removing ports from Surge rules and also tried Packet Capture.
This empty HTTP export does not establish a device failure or a TCP-only action.
If the removed port was in `force-http-engine-hosts`, the documented default of
port 80 explains why DISC's 12103 traffic would no longer match that option.
The exact edited profile was not supplied. Neither HAR contains the Link stream
on 12100 or raw packet data.

## iOS raw TCP capture (2026-09-15)

User-supplied `2026-09-15-233337.pcap`, SHA-256
`ac46002c2e579c075f46c0d2df7b34fa06f2c2b570f5f55cd59cb3defdf804f8`, is a classic
little-endian PCAP with BSD NULL link headers. It spans 23:33:37.714–23:34:25.796
(UTC+05:00), contains 773 packets, and has no capture-truncated packets. Only
DISC's 12100 traffic was decoded; unrelated phone traffic stays out of fixtures.
There are 70 DISC packets and no HTTP 12103 packets in this capture.

An already-existing connection first sends `0657000c0001` at 23:33:50.592 and
receives a TCP reset, with no Link response. Its connection setup predates the
capture. This does **not** establish that the command reached the player or that
USB DAC caused a failure: Surge's virtual-interface capture is not a simultaneous
capture on the physical DISC interface.

A new connection at 23:34:05.511 completes TCP setup, then exchanges
`0599000c0000` → `a599000C0306`. Its bidirectional payload sequences are contiguous,
with no gaps, retransmissions or leftover partial Link frames: **160 app bytes /
14 frames**, **790 device bytes / 20 frames**. It stays connected throughout all
four mode transitions; a reset appears only at 23:34:25.785, at the end of the trace.
The cause of that final reset is not established.

### Initialization and advertised capabilities

After handshake the app sends, in order:

```text
05010008
0607000c0000
062700100000A0A9
0639000c0000
02020008
0629000c0000
0628001000000009
```

`0627` and `0639` share one TCP payload; Link framing must handle coalescing.
The initial mode response is `a607000C0008` (local); EQ is off (`a639/00FF`),
master is zero (`a629/0000`), and the PEQ response contains ten bands with zero
frequency, gain and Q. Our decoder accepts this observed disabled state, while
the custom-EQ writer still rejects zero frequency/Q. No dedicated `a627` reply
appears. `a60a/0010` is observed during initialization, with its meaning unresolved.

The `a501` JSON includes:

| Field | Observed value |
|---|---|
| `soc_version`, `maxVolume` | 257, 120 |
| `http_replace_link`, `http_custom_list` | 1, 1 |
| `cus_count`, `sys_count` | 1, 5 |
| `width`, `height`, `quality`, `rgb` | 364, 364, 100, 888 |
| `image` | String containing JSON array `["png", "gif"]` |
| `video` | String containing JSON array `["mp4"]` |

These are advertised capabilities, not proof of working GIF/MP4 uploads. In
particular, advertised 364×364 differs from the actual 360×360 PNG responses in
the earlier HAR. Retain the tested 360×360 PNG upload contract until alternate
formats/dimensions are independently exercised. The HTTP flags agree with the
already tested HTTP library and playlist routes; this trace itself has no HTTP.

### Physical mode cycle

| App time | Request | Device response | Meaning |
|---|---|---|---|
| 23:34:10.416 | `0657000c0001` | `a607000C0001` at 10.452 | USB DAC |
| 23:34:15.634 | `0657000c0008` | `a607000C0008` at 15.686 | Local |
| 23:34:17.768 | `0657000c000A` | `a607000C000A` at 17.836 | AirPlay |
| 23:34:21.652 | `0657000c0008` | `a607000C0008` at 21.881 | Local |

Each setter produces a matching mode notification **without a subsequent `0607`
query**. FiiO Control requests `02020008` after both returns to local, but no
`a202` occurs anywhere in this trace. Do not substitute a known paused/stopped
state for the missing snapshot. Other notifications are `a824/0000` and paired
`a714`/`a502` values, first `003C`, later `0020`; no app volume setter is captured.
Mode response values validate our existing wire mapping on physical DISC, but
do not prove USB audio enumeration or AirPlay audio playback.

The [curated fixture](../../../controller/tests/fixtures/fiio_control_ios_460_modes.json) retains
handshake, mode requests/replies, disabled PEQ and a subset of capability metadata.
The app uses lowercase hex length digits (`000c`); our encoder uses uppercase
(`000C`). Tests normalize header case only, preserving payload bytes.
Regression tests compare TCP/WS setters with app frames, decode physical
mode replies, and check the disabled PEQ state. No runtime client changes were
needed. At this stage codec selection, custom-image metadata saves and library
reset were unobserved; the later capture below supplies the codec sequence.

Validation: the firmware-free suite passed **167 Python tests, 23 JavaScript
tests**, shell checks and four shim builds. After preserving the original hex
header case in the fixture, the 16 settings/framing tests passed again.

## iOS codec capture (2026-09-15)

`2026-09-15-234051.pcap`, SHA-256
`824f1f598070e75c27045afde4420d600ebb242b95d14de0cc18c6c90afa64d8`, contains 409
packets over 23:40:51.809–23:41:37.065 (UTC+05:00), none capture-truncated.
68 packets belong to one DISC TCP 12100 connection; no 12103 packets are present.
Its payload sequences are contiguous, without gaps/retransmissions or trailing
partial Link frames: 240 app bytes / 20 frames, 790 device bytes / 20 frames.
TCP setup and `0599` → `a599/0306` are captured. A reset appears at the end;
all codec requests and replies precede it.

Initial mode is local (`a607/0008`). The startup sequence matches the previous
capture, including disabled PEQ and no `a202` response to `0202`. Opening the
settings page sends the following read requests (not setters):

| Query | Response(s) | Interpretation |
|---|---|---|
| `064a/0000` | `a64a/0001` | Gain value 1 |
| `06d4/0000` | `a6d4/0004` | LDAC sound quality preference |
| `0824/0000` | `a824/0000` | SPDIF off |
| `0603/0000` | `a603/0001`, then `a603/000A` | Same filter in device enum and Link enum (+9) |
| `0813/0000` | `a813/0001` | DRE on |
| `0712/0000` | `a712/0000` | Observed setting query; meaning not established by this trace |

A second codec query at 23:41:09.794 again returns 4. The user reports selecting
the codec rows bottom-to-top, then restoring the initial row. The accompanying
screenshot selects the bottom LDAC sound-quality row. The wire sequence is:

| Request time | Exact app frame | Exact DISC reply | UI choice |
|---|---|---|---|
| 23:41:18.630 | `06d3000c0003` | `a6d4000C0003` | LDAC balanced |
| 23:41:21.880 | `06d3000c0002` | `a6d4000C0002` | LDAC connection stability |
| 23:41:24.964 | `06d3000c0001` | `a6d4000C0001` | AAC |
| 23:41:27.782 | `06d3000c0000` | `a6d4000C0000` | SBC |
| 23:41:30.565 | `06d3000c0004` | `a6d4000C0004` | LDAC sound quality, restored |

There is no setter for the initially selected bottom row before value 3. Each
setter receives a matching notification without a new `06d4` getter. The final
`a6d4/0004` arrives at 23:41:31.386, confirming the returned preference, not just
an outgoing request. Response delays range from about 44 to 821 ms in this trace;
do not treat that sample as a universal timeout bound.

The [curated fixture](../../../controller/tests/fixtures/fiio_control_ios_460_codecs.json) preserves
both initial reads and all five transitions, with original hex case. The regression
test compares our TCP/WS setters with parsed app frames and decodes every physical
reply. Existing mappings need no runtime change. Actual negotiated Bluetooth codec,
bitrate and audio quality remain untested by this network capture.

Validation: all **17 settings/framing tests passed**, including the new capture
regression. Runtime code is unchanged; the full firmware integrations were not
repeated for this fixture/documentation change.

## iOS playback and favorites capture (2026-09-15)

`2026-09-15-234648.pcap`, SHA-256
`d915be7d66c070da3f8a4bd93ab774dcbb16cbd36477de5e673ff9a5c6b32961`, contains 586
packets over 23:46:49.148–23:47:42.811 (UTC+05:00), none capture-truncated.
90 packets belong to one DISC TCP 12100 connection and 71 to HTTP 12103.
The Link streams have contiguous sequence numbers, no retransmissions/gaps or
incomplete trailing frames: 172 app bytes / 14 frames, 2948 device bytes / 31 frames.
The user performed the requested playback cycle and added like/unlike at the end.

| Time | App action/frame | Observed response |
|---|---|---|
| 23:46:52.841 | Initial `02020008` | No `a202` before selection |
| 23:47:07.223 | `0100001000000001`, first all-tracks position | Full `a202` at 07.632, `state: 2`, `love: false` |
| 23:47:09.782, 09.885 | No new app query | Two `a202` deltas, `state: 0` |
| 23:47:18.509 | `0201000c0000`, pause | Two `a202` deltas, `state: 1` |
| 23:47:21.859 | `0201000c0000`, resume | Two `a202` deltas, `state: 0` |
| 23:47:25.360 | `0201000c0000`, pause | Two `a202` deltas, `state: 1` |
| 23:47:33.462 | `0104000c0001`, like | Full `a202` at 33.643, `love: true`, `state: 1` |
| 23:47:36.246 | `0104000c0000`, unlike | Full `a202` at 36.298, `love: false`, `state: 1` |

The three full snapshots have identical nested song metadata. `song` is a string
containing JSON, `love` is a Boolean, and state-only deltas contain no track fields.
`a103` ticks report 1000..8000 ms before pause, then 9000..12000 ms after resume;
none occur between the first pause and resume or after the final pause. A single
`aa05/0001` also appears during startup; its meaning is not established here.

No `0202` is sent after track selection, including when the current-track screen
is used. Treat subsequent full snapshots as asynchronous updates; this trace
cannot establish why the initial query is silent or whether querying during
playback would succeed. Like/unlike set an explicit current-track flag, unlike
the play/pause toggle. Their confirmation is the updated `love` field, not an
`a104` acknowledgement. No favorite-list HTTP request appears after either action.

HTTP streams also reassemble contiguously; all three requests return status 200
with complete Content-Length bodies:

- `GET /localdir/tmp/`: `start-pos: 0`, `num-max: 100`; one `sdcard` directory.
- `GET /song_category_tree/`: `type: all/song`, `start-pos: 0`, `num-max: 100`,
  empty `artist`, `album`, `style` headers; 100 records with keys `pos`, `name`,
  `author`, `count`. Response also supplies `total-num` and `mark-pos`.
- `GET /image/cover/`: 48,864-byte JPEG with valid start/end markers.

This shows the stock app combining HTTP catalog/cover retrieval with TCP track
selection and playback/favorite notifications. Catalog contents and cover artwork
remain private. The [fixture](../../../controller/tests/fixtures/fiio_control_ios_460_playback.json)
retains actual commands, deltas and position values; full snapshots replace song
metadata and queue size with synthetic values and recalculate frame lengths.
Tests cover decoding the nested song, Boolean favorite transitions, repeated
state deltas, position units and TCP/WS toggle equivalence. Runtime clients are
unchanged; the stock favorite command was already exercised in emulator integration.

Validation: **17 remote-control/framing tests passed**, including the new trace
regression. Full firmware integrations were not repeated for this fixture/doc change.

## iOS paused seek and play-order capture (2026-09-15)

`2026-09-15-235540.pcap`, SHA-256
`00da5a3a19bc08d4ed0bb954ae616f79adb8341d914fbb998b32690ee5eb99bd`, contains 861
packets over 23:55:41.542–23:56:59.448 (UTC+05:00), none capture-truncated.
106 packets belong to a single DISC TCP 12100 connection; 40 belong to HTTP 12103.
The Link payload sequences are contiguous, with no gaps/retransmissions or trailing
partial frames: 332 app bytes / 25 frames, 1607 device bytes / 28 frames.
HTTP contains one `GET /image/cover/`, status 200, complete 48,864-byte body.

### Current-track query succeeds on pause

Startup includes `0501` reporting play mode 1, then `02020008` at 23:55:59.836.
A full `a202` arrives at 59.890 with `state: 1`, `love: false`, `work_mode: LOCAL`
and nested song metadata, before any control commands. This is a successful
current-track query while paused. Earlier initial-query silence is not a general
limitation of pause or FiiO Control compatibility. A track-context dependency is
plausible but has not been isolated experimentally. `0202` still has no request ID,
and future clients must also accept unrelated asynchronous `a202` updates.

### Two batches of paused seek attempts

The user reports that the slider did not move while paused, prompting repeated
attempts, then moved on resume. All eight attempts are visible as `0103` frames
with eight ASCII-hex **millisecond** digits:

| Request time | Exact frame | Requested milliseconds |
|---|---|---:|
| 23:56:10.240 | `0103001000003eda` | 16090 |
| 23:56:11.690 | `010300100001d651` | 120401 |
| 23:56:14.740 | `010300100001a768` | 108392 |
| 23:56:16.007 | `0103001000025191` | 151953 |
| 23:56:31.029 | `0103001000026a67` | 158311 |
| 23:56:31.593 | `01030010000334c1` | 210113 |
| 23:56:33.462 | `01030010000267a4` | 157604 |
| 23:56:34.010 | `0103001000034cab` | 216235 |

There are no Link position or state replies during either batch. After the first
resume (`0201/0000` at 20.605), duplicate playing deltas arrive at 22.339/22.343,
then ticks 152000, 153000, 154000, 155000 ms. The pause at 26.991 produces duplicate
paused deltas. After the second resume at 35.026, duplicate playing deltas are
followed by ticks 217000 and 218000 ms; the final pause at 37.543 again returns
two paused deltas. Both resumptions are consistent with the **last** requested
position in their batch. The trace does not tell when the decoder internally
applies the seek, nor prove a precise rounding rule from the first delayed tick.

The future remote should distinguish a user-requested pending seek position from
device-confirmed progress. It can keep the slider at the requested position on
pause and reconcile it when progress resumes. Lack of an immediate `a103` is not
evidence that a seek failed and is not a reason for automatic retries.

### Play-order cycle and icons

From initial mode 1, the app sends `0102/0002`, `0003`, `0004`, `0000`, `0001` at
23:56:47.095, 48.962, 51.346, 53.296, 55.030. Each receives a matching `a102`
within about 20–25 ms. Final random mode is confirmed, and no playback resume
occurs during these changes. The six screenshots map to 1 → 2 → 3 → 4 → 0 → 1
by the supplied ordering; their displayed 00:00 time is later than this trace.
See the [icon/behavior table](../../../docs/protocol/remote-control.md#commands). End-of-track/list
behavior is described from stock code analysis, not exercised by this capture.

The [fixture](../../../controller/tests/fixtures/fiio_control_ios_460_seek_modes.json) retains exact
seek/mode/toggle/delta/position frames and a minimal initial-state summary, with no
song metadata or images. iOS seek payloads use lowercase hex; client comparisons
normalize case only for these numeric commands. Regression coverage compares
both TCP and WS encoders, checks absence of paused position replies, both first
post-resume positions, all mode confirmations and final paused/random state.

Validation: **18 remote-control/framing tests passed**. Runtime clients are
unchanged; firmware integration runs were not repeated for this fixture/doc change.

## iOS current-queue capture (2026-09-16)

`2026-09-16-001300.pcap`, SHA-256
`ba7160176115f2b7c07d72235e8e8953902af1384a95b79691e1eba3080567e8`, contains
1400 packets over 00:13:00.883–00:14:10.649 (UTC+05:00), none capture-truncated.
152 packets belong to DISC TCP 12100, 373 to HTTP 12103. Link payload sequences
are contiguous with no gaps/retransmissions or trailing partial frames: 252 app
bytes / 13 frames, 4833 device bytes / 63 frames. HTTP payload sequences are also
contiguous and all response Content-Length bodies are complete.

Startup performs the known handshake and gets a full paused current-track reply
to `0202`. `0501.playMode` is **1 (random)** throughout this capture; the app sends
no play-mode setter. The selected album has 15 tracks.

| Time | App request | Confirmed result |
|---|---|---|
| 00:13:24.252 | `0101`, payload `0003` + album name | Full `a202`: album source 3, `playing_num: 1/15`, `pos_id: 1` |
| 00:13:43.741 | `0100003b00020000Список воспроизведения` | Full `a202`: queue source 0, `3/15`, `pos_id: 3` |
| 00:13:51.442 | `0201000c0001` | Full `a202` at 53.175: `11/15`, `pos_id: 11` |
| 00:13:58.977 | `0201000c0002` | Full `a202` at 59.099: `3/15`, same song as the selected third row |
| 00:14:05.445 | `0201000c0000` | Two `a202` state-only replies with state 1 |

All selection/navigation snapshots initially report state 2 and are followed by
duplicate state-0 notifications and position ticks. Old-track ticks continue
between the next command and its new full snapshot; the observed 1.73-s response
delay is another reason not to retry navigation blindly.

The nine HTTP requests are five cover GETs, one `/localdir/tmp/`, and three
`/song_category_tree/` GETs with types `album`, `album/song`, `curlist/song`.
All return 200. Catalog requests use offset 0, limit 100; artist/style are blank,
and album is percent-encoded only for `album/song`. The album and queue responses
contain identical 15-row arrays (`pos`, `name`, `author`, `count`), while their
marks differ: album/song -1 before playback, queue 0 after album playback starts.
The app does **not** issue TCP `0406`, `0426` or `0105` here.

For all four post-album full snapshots, the one-based `pos_id`/`playing_num`
matches the name/artist of the zero-based HTTP queue row. These snapshots give
positions 1 → 3 → 11 → 3. No new queue fetch occurs after the type-0 selection;
the old HTTP `mark-pos` cannot be treated as live state. The observed next/previous
positions are consistent with random mode, not sequential index arithmetic.
No general shuffle-history or queue mutation rule is proven by this sequence.

Type-0 selection on DISC is now physically observed, with a localized queue-label
suffix and UTF-8 byte length **0x3b = 59**. Do not replace this with the Android
M21 header length. This capture alone cannot establish whether the label is
required. The later [emulator checks](../../../docs/protocol/remote-control.md#validated-current-queue-helper)
compare Russian, absent and arbitrary labels and introduce a guarded dedicated
helper; generic `play_index()` still rejects type 0.

The [fixture](../../../controller/tests/fixtures/fiio_control_ios_460_queue.json) retains exact queue
selection/navigation commands and HTTP request metadata. Catalog text and song
identities are synthetic; snapshots are reduced to the fields needed to compare
row positions and source types. Raw album/track names, artwork and unrelated phone
traffic are omitted. Regression coverage exercises the HTTP queue reader, Unicode
selector framing, physical position/source transitions and TCP/WS navigation.

Validation: **27 HTTP/remote-control/framing tests passed**. No runtime client
behavior was changed and full firmware integrations were not repeated.

## Capture follow-up

Use the action checklist in [REMOTE_MODES_THEMES.md](../../../docs/protocol/remote-modes-themes.md#fiio-control-capture-checklist).
For Surge, first distinguish missing LAN takeover from an existing connection not
parsed as HTTP. Official references:

- [Surge general options](https://manual.nssurge.com/profile/general.html): iOS LAN takeover and host/port matching.
- [HTTP processing](https://manual.nssurge.com/http/overview.html): nonstandard HTTP ports versus raw TCP.
- [Surge iOS release notes](https://kb.nssurge.com/surge-knowledge-base/release-notes/surge-ios):
  Network Layer Packet Capture exports TCP/UDP/ICMP in `.pcap`; HTTP capture exports HAR.

Keep an explicit `force-http-engine-hosts = 192.0.2.21:12103` match for HTTP,
replacing this documentation address with the DISC's actual LAN address.
Do not force the Link port 12100 through the HTTP engine. To reproduce this capture,
start Network Layer Packet Capture before reopening FiiO Control and connecting
to DISC, perform the mode cycle in the checklist, then stop and export **`.pcap`**.
This recovered both connection setup and bidirectional Link frames in the supplied
PCAP. Work modes, codec, playback, favorites, paused seeks and play-order changes
are now captured, as is HTTP current-queue browsing and TCP type-0 selection.
The recent traces also confirm a successful paused `0202` query;
the earlier silence remains a narrower track-context question. Custom-theme
metadata saves still need the backup/restore scenario in the checklist; library
reset remains unobserved. Further mode captures are unnecessary to establish
the app's enum mapping; actual end-of-track/list behavior is a separate check.
Type-0 label/empty/replaced-queue checks now have a dedicated disposable scenario
and client helper, described in the remote-control contract.
`0105`/`0426` are not observed in these DISC app traces. They were subsequently
investigated directly in the emulator: [read-command results](../../../docs/protocol/remote-control.md#remaining-queue-related-reads-0105-and-0426).

Record both app versions and actual capture topology alongside a trace. A successful
HTTP capture does not establish capture of the separate Link TCP stream on 12100.
