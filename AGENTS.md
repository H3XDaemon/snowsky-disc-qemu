# AGENTS.md

Shared instructions for coding agents continuing this project. Read this, then
`emulator/docs/emulation.md`. Use `docs/README.md` as the documentation index. The goal: run the FiiO Snowsky Disc stock firmware under qemu-user
and drive its UI, as groundwork for custom firmware / a sync bridge.

## TL;DR of the current state

Full boot to the **main menu** works, **touch injection** works, and the **SD card / File
Browser** works (drop media in `./emulator/sdcard`, browse it to the leaf tracks). The three fixes that
got the UI up (all encoded in `emulator/scripts/10_setup_env.sh`): raise **`RLIMIT_MSGQUEUE`**
(`ulimit -q`), stub the **battery** sysfs at 100 %, and set **`LOCAL_IMG_ANIM=0`** to kill
the boot-animation overlay. Touch coordinates are **180°-rotated** and press/release must be
**separated in time** (and a ~1 s hold is a long-press — use ~0.3 s to open a list item). The
SD needs a re-mount after the guest's boot-time umount (`sd_mount()` in `lib.sh`). See
`emulator/docs/status.md` for screenshots and what's next.

## How to run

Host: `./emulator/run.sh up <…/main_os/ota_v257>` (once) → `./emulator/run.sh boot` → `./emulator/run.sh tap <x> <y>`.
Screenshots are copied to `./shots/`. For an **interactive** session use `./emulator/run.sh view` →
open `http://localhost:8080` (live screen, click=tap, drag=swipe; responsive CSS device
with physical buttons and audio/USB/microSD controls) — see `viewer/docs/usage.md`; the daemon is `viewer/server.py` /
`viewer/scripts/40_stream.sh`. `boot` now keeps the guests alive ~30 min (`GUEST_TTL`) for this. `./emulator/run.sh shell` gives a container shell where the
`/repo/emulator/scripts/*.sh` pipeline lives. Everything qemu-side runs **inside** the container
(named `snowsky-disc-qemu`, `--privileged`); `/work` is a Docker volume holding the extracted
rootfs and runtime state.

To view a captured screen, `Read` the PNGs in `./shots/` (e.g. `boot-b0.png`, `boot-b1.png`).
Because `mq_ui` alternates two sub-buffers, use `emu/fb-live` (0 or 1) to identify
the last-written buffer, or the viewer's `/frame` endpoint. The non-black pixel
count printed by `fb2png.py` is only a fallback heuristic, not evidence of recency.

## Hard-won facts (don't rediscover these)

- **NEVER** run `qemu-binfmt --reset -p yes` or `multiarch/qemu-user-static --reset`: it
  registers `qemu-aarch64` and hijacks the host VM's native binaries → Docker breaks
  (`exec format error`), needs a Docker Desktop restart. Register **only** mipsel (the setup
  script does). This bit us twice.
- `mq_open("ui")` returning **EMFILE** is `RLIMIT_MSGQUEUE` exhaustion, **not** fd count.
  Killed guests leak queues into a kernel mqueue instance a `mount -t mqueue` view doesn't
  show. `ulimit -q` fixes it.
- The shim **must** be freestanding (`-nostdlib`, raw syscalls): device glibc is 2.29, host
  toolchain is 2.36, so a normal `.so` won't load. Preload via `/rootfs/etc/ld.so.preload`,
  not `LD_PRELOAD` (env doesn't survive the guest's `popen()` children). ELF must carry the
  **nan2008** flag (`build_shims.sh` stamps it).
- Start **`mq_ui` first** (creates the `ui` queue), then `mq_player`. Boot waits for
  network listeners, both input devices and a framebuffer flush before capturing;
  use the readiness result rather than a fixed sleep (see `viewer/docs/usage.md`).
- Touch: append 16-byte `input_event`s to `/rootfs/dev/input/event1`. Press =
  `ABS_MT_TRACKING_ID=0` / `BTN_TOUCH=1`; release = `TRACKING_ID=-1` / `BTN_TOUCH=0`. The
  read-cb drains all queued events per call, so **inject press → sleep ~1s → release**, else
  LVGL only sees the net (released). The ~1 s hold above is a diagnostic long press;
  use the normal ~0.3 s tap helper for list items. Tap point = `(359-x, 359-y)` of what you see;
  `30_tap.sh` flips it for you.
- The first-boot **language wizard** is gated on the `LANGUAGE` column: it shows only while
  LANGUAGE is out of range (the fresh default is 100). `LANGUAGE` is a **0-based index** (switch
  in mq_ui `FUN_004776e4`): `0 zh · 1 tw · 2 en · 3 ja · 4 ko · 5 es · 6 it · 7 de · 8 pt · 9 ru`.
  `10_setup_env.sh` presets it (`LANG_CODE`, default **2 = English**), which both picks the
  language AND skips the wizard, so a fresh `/work` volume boots straight to the English main menu.
- **SD card / File Browser**: `mq_ui` (`mount_storage_dev.c`) **umounts `/tmp/sdcard` once at
  startup** and expects a hotplug handler to remount the card — which nothing does under
  emulation, so the browser shows nothing. The File Browser **re-scans `/tmp/sdcard` live on
  entry**, so the fix is just to keep the card mounted: `sd_mount()` (`lib.sh`) re-mounts
  `/dev/mmcblk0p1 -o iocharset=utf8` after the boot-time umount (called from `10_setup_env.sh`,
  end of `20_boot.sh`, and `30_tap.sh`). It is **not** a Docker-volume propagation issue and
  needs **no** synthetic netlink uevent — both were dead ends. The card is a real FAT block
  device (`mknod /dev/mmcblk0[p1] b 7 <loop minor>`, not a symlink — the guest's chroot can't
  resolve `/dev/loopN`). Drop media into `./emulator/sdcard`; it is rebuilt into the image each setup.
- `/usr/data` is a **separate partition** (empty in the squashfs). Two consequences on a fresh
  rootfs, both handled by `10_setup_env.sh`: (a) it must be **seeded** with the zlog configs
  (`usr/project/config/zlog_{player,ui}.conf` → `usr/data/fiio/log/`) + `usr/project/db/*`, or
  `mq_player` dies at `zlog_init` and never creates `sysconfig.db`; (b) `sysconfig.db` is then
  created on first boot with `LOCAL_IMG_ANIM=1`, so a **priming boot** is needed before the flag
  can be set to 0. State persists in the `/work` Docker volume.
- If `docker run`/`start`/`exec` hangs and a new container is stuck in `Created` (existing ones
  still work), the Docker Desktop VM is wedged — **restart Docker Desktop**, then retry. Give it
  ≥8 GB. This is the same OOM-adjacent failure seen mid-project.
- `fb2png.py` reporting `-b2 non_black_px=0` is normal (only buf0/buf1 are used).

## Where things are

See `docs/architecture/repository.md` for component boundaries and the entry-point inventory.
Use explicit package imports and `python3 -m package.module` from the repository
root. Do not add directory-specific `sys.path` searches. Controller must remain
independent of emulator, viewer, firmware, research and experiments; integration tests use
emulator runtime primitives, not viewer internals. Unit tests live with their
component; cross-component scenarios and generated media live under `tests/`.

- Emulation pipeline: `emulator/scripts/` (numbered). Shared helpers/paths: `emulator/scripts/lib.sh`.
- Shim source: `emulator/shims/fbshim.c` (fb + input-name ioctls). Diagnostic mq_open interposer:
  `emulator/shims/mqshim.c` (only needed if you suspect an attr/errno issue — normally unused).
- Runtime/diagnostics: `emulator/runtime/inject.py` (touch), `research/diagnostics/uisniff.c` (sniff the `ui` mqueue non-destructively),
  `emulator/runtime/fb2png.py` (framebuffer → PNG, BGRX + 180° rotation), `viewer/server.py` (live viewer +
  touch/swipe HTTP bridge; served by `viewer/scripts/40_stream.sh`, `viewer/docs/usage.md`).
- RE: `research/ghidra/` scripts + notes. Key functions: `mq_ui` main `FUN_004036ec`, touch device
  open `FUN_0055da20`, touch read-cb `FUN_0055db8c`.
- Firmware acquisition + decrypt: `firmware/README.md` (password `fo123`; rootfs and
  six stock binary hashes pinned in `firmware/v<version>.json`).
- Protocol + real-device RE: `docs/protocol/protocol.md` (FiiO Link frames, verified-live 12100 handshake
  `0599…`, the corrected 12103 route mapping — **TCP device control is auth-free**;
  stock file transfer uses separate HTTP, see `docs/protocol/http-api.md`), `docs/protocol/device.md`
  (ports/mDNS, no stock debug unlock), `research/docs/reports/diskos.md` (V2.40 builds;
  only the size cap blocks). Network/auth `mq_player` function addresses are in `research/ghidra/README.md`.

## Disc Assistant checkpoint

The text/voice music assistant lives in `experiments/disc_assistant/`. Read its
[AGENTS.md](experiments/disc_assistant/AGENTS.md) before changing it, then
[architecture](experiments/disc_assistant/docs/architecture/pipeline.md) and
[current status](experiments/disc_assistant/docs/status.md). Keep it under experiments until a
separately agreed promotion or repository split; documentation remains English.

The owner accepted the **software MVP against the stock V2.57 emulator** on
2026-09-19: 64/64 text scenarios (35 RU / 29 EN), including 19 no-mutation cases
with zero observed writes. [Acceptance evidence](experiments/disc_assistant/docs/reports/2026-09-19-mvp-acceptance.md)
preserves the report, candidate and reproduction commands; issue #21 is complete.
This is known regression acceptance, not a human-speech accuracy estimate.
Physical acceptance (#23) and speech quality/native-Docker/Orange Pi performance
(#24) are separate follow-ups, not reasons to reopen this accepted boundary.

- Use `./experiments/disc_assistant/run.sh`, not the emulator launcher.
  `setup --all` installs the optional speech runtime; `web --bootstrap` starts
  search/speech and the browser adapter on loopback 8090; `start` opens the text
  console. Config defaults to `~/disc-assistant.toml`, targeting emulator TCP
  12100 and direct HTTP 12113 (physical DISC normally uses HTTP 12103).
- `assistant/application.py` owns the common request flow; console/web are
  adapters. Speech contracts, factories and deployment profiles live in
  `assistant/voice/`; see `experiments/disc_assistant/docs/guides/voice-adapters.md`. Web selects Whisper Server or optional resident Sherpa RU per audio request;
  changing engines restores Preview, with no fallback. Piper replies require browser sound opt-in.
  Assistant owns interpretation, response locale, search/ranking and history;
  Root `library/` owns shared catalog snapshots/indexing; read `library/AGENTS.md` before changing it. Shared persistent state and guarded
  playback belong in [Controller](controller/docs/api.md), with no research imports.
- Preserve one action per request, one saved input/response locale and fresh
  selection/queue checks. Never automatically replay an uncertain mutation.
  Learned sources remain shadow-only. The shared `MutationPacer` waits only for
  the remaining stock 2.1-second interval before fresh preflight; do not restore
  unconditional command sleeps or remove the firmware guard.
- Stock control has one client owner: do not steal an active console/FiiO Control
  connection. Keep private catalogs, journals, recordings, models and credentials
  out of Git; commit only curated synthetic fixtures and sanitized reports.
- Prototype checks: `./experiments/disc_assistant/run.sh test`. Firmware acceptance:
  `bash ci/assistant.sh /absolute/path/to/main_os/ota_v257 /tmp/disc-new-run` uses
  disposable emulator/search resources and generated media. Use a new output
  directory and preserve the accepted report. Choose tests by impact; docs-only
  updates do not require another firmware or physical-device run.

## Conventions

- For another firmware/product, read `firmware/docs/porting.md` and its `firmware/docs/reports/<version>.md`
  report first. `firmware/inventory/` contains observed inputs, not runtime enablement
  profiles. Keep vendor-reported changes separate from verified emulator features;
  update `CHANGELOG.md` for emulator changes. Never replace V2.40 hashes/addresses blindly.
- Keep `CHANGELOG.md` human-readable: short, grouped user-facing outcomes with
  links to domain docs, not packet layouts, test transcripts or experiment logs.
- Actively support one firmware: the latest validated version (currently V2.57).
  Develop on `2.x`; preserve older versions as historical release snapshots, without
  promised backports or continuing integration gates. Promote only after validation,
  not on an OTA announcement. Preserve inventories and analysis; see `firmware/docs/porting.md`.
  V2.40 runtime/diagnostic profiles remain temporarily, but hosted CI runs only V2.57;
  their removal is a separate implementation task, not part of this policy change.
- Read `firmware/docs/firmware-profiles.md` before adding firmware. The single active default
  is `firmware/active-version`; `emulator/.env` may pin a reviewed override. Keep runtime
  capabilities, diagnostic addresses and acceptance selection in the runtime profile.
  Controller compatibility is independent and selected from device `soc_version`,
  never local `FW_VERSION`. Unknown versions do not inherit reviewed capabilities.
- `FW_VERSION` selects a reviewed runtime profile (default `2.57`, opt-in `2.40`).
  Setup/boot validate product/version and six binary fingerprints before execution.
  Key patch validation normalizes only the permitted instruction, then checks the full
  stock hash and executable PT_LOAD mapping. Read-only key/network/HTTP diagnostics select
  separately verified V2.40/V2.57 addresses by full binary fingerprint (see
  `research/docs/diagnostics.md`); legacy GDB breakpoint files remain V2.40-specific.
- Public-release preparation: `docs/development/public-release.md`. Keep passwords out of the root
  README and private-project names out of tracked files. Do not change visibility or
  rewrite immutable history without explicit approval. Code/photo license: MIT.
- Default development branch: `2.x`; firmware-based release tags `v2.40`, then
  `v2.40-r1` for emulator fixes against the same firmware. See `docs/development/ci.md` for pinned
  CI, secret-backed downloads and release gates. Never log a direct firmware URL.
  Existing `v2.57` is an immutable pre-release snapshot; keep it and use a new name
  (next available: `v2.57-r1`) for the eventual stable V2.57 release.
- Full firmware-free suite: `docker run --rm --network none -v "$PWD:/repo:ro"
  snowsky-disc-qemu-ci bash /repo/ci/test.sh` after `docker build -t snowsky-disc-qemu-ci emulator/docker`.
  `ci/integration.sh` uses a fresh disposable Compose stack, never the interactive volume.
  V2.57 CI alone presets `LIGTH_ON_TIME=7` (never) while stopped and verifies UI
  index/timeout readback, avoiding screen-timeout interference in long network tests.
  Do not copy this into interactive setup or treat it as a remote-wake fix; see
  `docs/development/ci.md`. `POWER_SAVE` is unchanged in ordinary CI; opt-in `idle`/`idle-usb`
  instead use reviewed 120-second screen and 0/300-second idle fixtures.
- Select tests by impact; do not rerun long power acceptance for unrelated work.
  Documentation-only changes need diff/link checks, not firmware execution.
  Normal code changes use firmware-free checks plus the relevant focused scenario;
  shared runtime changes additionally need `full`. Run `idle` and `idle-usb` for
  power/USB/timer/shutdown/reconnect changes, a new firmware profile, and the exact
  release candidate. They are explicit local gates, not part of `full` or the
  current hosted workflow. Keep the real 310-second USB observation; do not shorten
  firmware timers to make it pass faster. See `docs/development/ci.md#test-selection-policy`.
- Firmware and anything derived from it (rootfs, `.enc`, `.squashfs`, FiiO binaries, Ghidra
  project, captured `shots/`) are **git-ignored** — never commit firmware. Commit code,
  scripts, docs, and the curated screenshots in `docs/images/`.
- Prefer editing the pipeline scripts over ad-hoc container commands, so the repo stays the
  source of truth and the work stays reproducible from another machine.
- Screenshots for the docs live in `docs/images/`; throwaway captures go to `shots/` (ignored).

## Research scope and handoff

The agreed local DISC protocol checkpoint is finalized. Closed issue #10 stays
closed. Read `research/docs/status.md` for current scope and pause conditions;
`docs/protocol/disc-capabilities.md` owns supported behavior. Detailed dated
captures and earlier priorities live in `research/docs/reports/`, not in a new
request to repeat them. PEQ/SACD scope for PR #20 was accepted on 2026-09-19;
remaining #8/#9 investigations are optional backlog, not checkpoint blockers.

PEQ #9 is paused by owner after capture 225312. No capture, reconnect/write or
scheduled follow-up until explicitly resumed. Physical Custom 10 restoration is
unknown after Auto EQ Save/disconnect (screenshot 6851, master -4.6). First resumed
step: capture reconnect/read Custom 10 before Reset, without repeating Save;
then reset/readback/Off on the approved slot. Diagnose a failed reconnect without
replaying writes or silently rebooting. No repeated preset/Local Apply sweep,
Random, catalog enumeration or login. Share/account/cloud remain deferred to #11.
The JSON PEQ helper is reviewed; captured malformed Local Apply bytes and code
240 BYPASS must not be copied into public writes. See the PEQ report.

SACD #8 covers stereo metadata/identity and same-path title replacement. Different
track-layout replacement, seek/EOF, DST/multichannel, redistributable fixture and
hardware DSD/DoP remain unverified. Do not run media tests to update status.
Old ignored logs may be absent; distinguish dated evidence from fresh verification.

Library selections use their reviewed scoped selectors and fresh positions;
artist-scoped albums must not become generic albums. Root-tab Play all wire
semantics and current-track/CUE deletion remain unverified. Keep source-delete
helpers restricted as documented; preserved captures are not instructions to
repeat physical mutations. Themes use the reviewed system/custom distinction;
read `docs/protocol/remote-modes-themes.md` before new work.

Component documentation belongs beside code; root `docs/README.md` is the index.
Follow `docs/decisions/0001-component-and-documentation-ownership.md`: current
status is concise, dated evidence is preserved, and issues own actionable backlog.
Issue #29 places launch/build infrastructure in `emulator/` and names the Compose
service `emulator`. Use `emulator/run.sh` and `emulator/.env`; there is no root
launcher or automatic config migration. Keep guest-internal `/emu` markers and
existing Docker project/image/container/volume identities unchanged. See
`emulator/docs/running.md` and ADR 0002.

## Emulator and protocol implementation notes

Local audio works: `tinyshim` redirects `/proc/asound/cards` discovery to `/etc/asound.cards`
(x2000), so stock firmware selects I2S3_OUT (6), hw:0,3. No audio binary patches.
Capture: `/audio.pcm` + `/audio.fmt`; `./emulator/run.sh audio` exports a WAV, and the viewer offers
Enable sound / Replay capture. See `emulator/docs/audio.md` for runtime evidence and corrected route
interpretation (`0x10000000` is INPUT). USB/BT and DSD remain unvalidated.

Physical controls now work in the viewer: volume single/double/hold respects the app's
assignments; media play/pause is `0xfa`; `0x103` sleeps/wakes the screen. GPIO, brightness,
touch/LCD stubs and browser DAC gain are implemented. Long Power safely stops only guest
processes; Power while off boots them again (not stock standby/shutdown emulation).
The viewer draws its device with HTML/CSS: visible Power, Play/pause and volume
buttons, plus audio/USB/microSD connectors. No photo or alignment settings are used.
Gesture shortcuts and audio replay live in collapsed **Debug**. Shared page/device
styles live in `viewer/static/device.css`, copied into the standalone browser
experiment by its UI refresh/build. QEMU/WASM badges distinguish execution modes.
See `viewer/docs/usage.md` and `experiments/browser/docs/overview.md`.
Raw power code `0x108` can invoke `poweroff -f` and is blocked in the viewer — do not sweep
event codes blindly. See `emulator/docs/keys.md` and the current screenshots in `emulator/docs/status.md`.
The stock idle-poweroff path also calls BusyBox `reboot`; `fbshim` blocks the kernel call
and publishes `emu/power-request` for the viewer to stop only this guest. This was tested
with actual guest `poweroff -f` after verifying its dynamic symbol binding to the shim.
`fbshim` observes framebuffer mmap/memcpy and records `emu/fb-live` so the viewer picks
the actual last-written buffer instead of a stale frame when both buffers changed.

V2.57 viewer USB now models power, not just a battery-status graphic: `15_controls.sh`
enables narrow AW35615 sink-role/ADC1/charger stubs in `fbshim`. Stock detection
sets `83a768`, inhibiting idle shutdown without changing POWER_SAVE. ADC0/2/3
remain unavailable (ENODEV); USB data/storage/DAC are not implemented. V2.40
retains its old charging-status-only behavior. Cable transitions can wake the
display; Sleep and Screen off are separate from idle power-off. Opt-in disposable
`CI_SCENARIO=idle` and `idle-usb` cover long lifecycle behavior; ordinary full CI
checks native cable detection briefly. See `emulator/docs/idle-power.md`. Never defeat idle
policy with fake touches or replay mutations after reconnect; a stopped guest
requires explicit local Power before a new handshake and fresh state reads.

Network services now bind 12100/12103: Compose names the real Docker interface `eth1`
(Compose >=2.36), and `emulator/scripts/16_network.sh` re-announces its existing address after
the stock netlink detector subscribes. No Wi-Fi DB overrides or network binary patches.
Guest `ip` read queries use stock BusyBox (the standalone ip address dump fails in qemu).
`guest_run()` drops dangerous capabilities; wrappers block automatic OTA/NTP/hwclock
and network reconfiguration. All ports publish only on localhost. Recreate the container
with `./emulator/run.sh compose up -d --build`, then boot/view. See `emulator/docs/network.md` for repeatable
probes, `controller/fiio_link.py` for host control. V2.40's active HTTP callback `004b9d38`
has no WebSocket route in table `006c7a50`; unknown URLs return empty 200 via `0048f8f8`.
The bundled mg_dash code is not the active router; the earlier password-gate explanation
was wrong. Reproduce with `research/diagnostics/inspect_http_routes.py` and `controller/diagnostics/probe_websocket.py`.
An explicit native WS→TCP bridge now serves host `12103/api/websocket`, forwarding
FiiO Link to `emulator:12100`; other HTTP paths proxy to unchanged guest `12103`. Host
`12113` bypasses it for stock HTTP diagnosis. The opt-in `wsbridge` Compose profile starts the bridge unprivileged,
read-only, without guest volumes; Dockerfile supplies python3-aiohttp. No firmware patch.
Enable with `./emulator/run.sh compose --profile wsbridge up -d wsbridge`; ordinary up/start/boot
do not launch it. CI enables the profile explicitly.
`./emulator/run.sh wscheck --control` compares TCP/WS and checks volume/playback (leaves paused).
`http://localhost:12103/bridge/` is a read-only protocol inspector; disconnect it before
another client (stock TCP is single-client). See `controller/docs/websocket.md`. LAN discovery
and FiiO Control app compatibility are tracked in `controller/docs/discovery.md`.
V2.57 UDP discovery is plain `SNOWSKY DISC` to 224.0.0.255:12101, ~2 s, no
embedded IP/ports. TCP accept suppresses it before handshake; disconnect resumes
it (`CI_SCENARIO=discovery`). Passive host tool: `controller/fiio_discovery.py`.
Opt-in `controller/bridge/lan_bridge.py` runs on the HOST, binds a specific LAN IPv4 and allows
one phone IP; TCP 12100 -> localhost 12100, HTTP 12103 -> localhost 12113. It exposes
unauthenticated control/file APIs: require explicit approval, trusted LAN, acknowledgement
flag and bounded duration. Never autostart it or change default Compose localhost
bindings. mDNS `_fiio._tcp` statically uses 12102, not a substitute control endpoint.
Physical iPhone FiiO Control discovered the host adapter, connected, opened the
emulator library and rediscovered it after confirmed disconnect. LAN listeners
were then closed. This does not validate every app operation or physical iOS
background/reconnect; emulator idle/USB behavior is covered separately above.

Stock HTTP file/playlist operations and remote settings are documented in
`docs/protocol/http-api.md` and `docs/protocol/remote-settings.md`. Use `controller/fiio_http.py` for
`/dir/`, raw-body `/audio/` uploads, `/progress/`, single-path `/file/` deletion and
custom playlists. HTTP 200 is not success; progress can survive deletion. Playlist
headers named `list_id`/`src_list_id`/`dst_list_id` use positions, not database IDs.
Custom playlist playback on V2.57 uses list type 5 and JSON `{"id":<position>}`:
`0100` takes a track position first; `0101` starts the list. This JSON ID also
means list position, not SQLite LIST_ID. `play_playlist(position, index=None,
http=..., expected_name=...)` checks fresh HTTP list/track rows and name before
sending; the HTTP client must target the same device. Catalog ordering need not
match insertion order. No atomic revision exists; serialize edits and never
replay selections. See `docs/protocol/playlists.md`; focused `CI_SCENARIO=playlists` checks
TCP/WS with ID gaps, rename/add/remove and stale/empty-selector rejection.
V2.57 `play_genre` uses captured type 8 with empty album for whole-genre Play all,
type 10 for an indexed genre track, or type 8 for a named genre-scoped album; type 8's
argument is parsed by sscanf, not JSON (fixed keys/spacing, no quote/backslash
escaping). `play_folder` uses type 4 and positions from fresh HTTP localdir,
including directory rows; Play all skips directories, not recursive. Both check
fresh bounds. `add_selection_to_playlist` checks destination name and source
filters/ranges; genre album groups expand without leaking other genres. DELETE
does not accept these group categories even though it returns HTTP 200. Focused
`CI_SCENARIO=library` tests generated media, TCP/WS and direct/proxied HTTP,
including index-only scoped track deletion and rescan recovery. No arbitrary
source-delete helper. Physical capture `2026-09-16-185016` confirms scoped-album
commands and HTTP genre hierarchy. Whole-genre type 8 is now compared against
type 10 in disposable CI (modes 0/4, queue/order/restart). Do not use empty-album
type 8 for indexed playback: that separate path failed the exploratory probe.
Folder playback/bulk actions are not in the capture;
see `docs/protocol/library-browsing.md` before continuing the remaining workflows.
Avoid stock batch recursive deletion (it constructs shell commands). `0622/0000`
starts a scan; watch `a60a` start/finish and `a622` counts. Gain/DRE/filter/SPDIF and
PEQ helpers are shared by TCP/WS; filter and EQ network enums differ from SQLite.
V2.57 gain is 0 Low / 1 High, not menu row order. `GAIN_LABELS`/`FILTER_LABELS`
map stock UI names; all two/six values have TCP/WS and SQLite acceptance. Expanded
iPhone filter rows are now paired by physical capture `2026-09-16-192141` and
the owner's 3→4→5→6→1→2 walkthrough, with final fresh restoration readback.
English screenshot IMG_6817 labels rows 5/6 identically (Reference super slow
roll-off), but codes 000D/000E differ; never deduplicate by label. Russian names
remain clipped. Do not infer analog response from label/code correspondence.
Fixture tests pin all six; curated English app screenshot is in docs/images/.
V2.57 `cancel_library_scan()` sends `0622/0001` once without draining events.
Cancellation leaves a partial replacement index, not a rollback; `a60a/0005`
also occurs after cancel. Do not query through the sequential client while
collecting scan events or replay cancel after reconnect. See `docs/protocol/library-scan.md`;
`CI_SCENARIO=scan-cancel` checks TCP/WS and recovery on disposable generated media.
V2.57 `reset_library(confirm=True)` sends dedicated `0621/0000` once, not `0800`.
It drops SONG/MY_LOVE and queue tables; files/settings/custom-list rows survive.
Immediate HTTP favorites have invalid total -1; custom songs can have count >0
with no items, and empty `a202` does not mean stopped playback. Rescan rebuilds
tracks/custom membership but not MY_LOVE; guest restart recreates empty favorites.
Never reset during a scan, replay an uncertain reset, or silently reboot. See
`docs/protocol/library-reset.md` and disposable `CI_SCENARIO=library-reset`.
Channel balance uses getter `0712`, setter `0713`, reply `a712`: helper integers
-20..20 mean L20..0..R20; wire high byte 0=left/1=right, low byte=magnitude.
It is not signed 16-bit or percent. `BALANCE_VOL` stores the packed value;
the opposite DAC channel receives 0..20 attenuation steps. `tests/integration/settings_check.py`
checks TCP/WS, SQLite and DAC mirrors and restores state; focused scenario
`CI_SCENARIO=settings` is available. Physical analog output remains unvalidated.
V2.57 has a separate TCP receive allowlist (111 tags at `6d84e0`): local UI
callbacks do not prove remote support. `research/diagnostics/inspect_link_commands.py` inspects
it by full binary fingerprint. Gapless/folder jump/ReplayGain are read-only via
`0501` JSON; `0647/0687/0718/0648/064d/064e` are rejected over TCP and WS even
with populated callbacks. `tests/integration/preferences_check.py` verifies no state change and
fresh reads after each negative probe. `0820/0821/0822` and `064b/064c` are also
absent (static evidence). Invalid tags clear the current TCP receive buffer,
including coalesced later frames; do not pipeline a negative probe with a query.
Admission alone is insufficient too: `0426` is admitted but has no handler.
The new CI scenarios use only disposable generated media. Never substitute the
broad `0800` factory-reset command for the app's library-reset action.

`docs/protocol/remote-modes-themes.md` covers stock work-mode control (Link 1 USB DAC,
8 local, 10 AirPlay), the five `06d3` source-codec preferences, and lock-screen HTTP.
Mode/codec readback does not establish hardware audio. Codec changes reopen the
local player; restore the desired mode afterwards. `controller/fiio_theme.py` uploads
and activates complete custom PNGs: an empty-body custom POST clears its image
path, and `flag-in-use: 0` still clears the previously active theme. System-theme
selection uses a separate source namespace. The capture checklist in that doc
requires HTTP 12103 and TCP 12100; an ordinary HTTP proxy may miss the latter.
Physical app captures confirm full unchanged PNG retransmission for color/Date
and four custom styles. `upload_lock_screen(..., style=...)` allows `default/0`,
`default/1`, `default/2`, `clock/0`; `subclass` stays custom/default and flags
remain explicit. `CI_SCENARIO=themes` checks direct/proxied HTTP on disposable
V2.57 without unrelated tests. Do not infer automatic time-flag changes or
physical rendering from style readback. The app's 96-byte encoded Russian alias
exceeds the stock 63-byte bound: header truncation occurs BEFORE percent-decoding
and can persist invalid UTF-8. Boundary tests verify this through direct/proxy HTTP
and raw SQLite bytes; keep the client rejection despite HTTP 200/blank GET alias.

Physical iOS captures are summarized in `research/docs/reports/fiio-control-app.md`; only sanitized
protocol fixtures live in `controller/tests/fixtures/`. Full `a202` snapshots and state-only
deltas coexist; DISC uses 0 playing / 1 paused. Paused seeks have no immediate
position acknowledgement. Current queue is observed via HTTP `curlist/song`, then
TCP `0100` index + type 0 + localized queue label. `play_queue_index()` now reads
the current queue length before selecting without a label; `tests/integration/queue_check.py`
checks label variants and empty/replaced queues (`CI_SCENARIO=queue` for fresh
empty-queue coverage). A raw out-of-range selector can leave `0202` silent until
a valid album is selected again. Never replay stale queue selections. The physical trace ran in random mode
and moved 3 → 11 → 3, so never infer queue position by increment/decrement alone.
`play_mode()` reads `0105` but expects `a102`, not the mechanically derived `a105`.
`0426` has no assigned handler in V2.40/V2.57; retained counter JSON strings do not prove
support. Use `0406`, HTTP `curlist/song` and `0202` instead. The focused
`CI_SCENARIO=queue-reads` verifies both read commands without relying on M21 semantics.
Natural EOF on V2.57 is checked over TCP/WS for all five modes with six-second
WAV/FLAC tracks, gapless/folder jump off. Modes 0/4 finally send `a103=0` then
metadata-free `a202 state=2`; fresh `0202` is silent, but mode reads and the
retained HTTP queue work. Internal stopped state is 3, not wire 2. Full loading
snapshots also have state 2; duplicate state-0 deltas are not repeats. Observe
events without queries during EOF and never infer stop from timeout alone.
See `docs/protocol/track-end.md` and disposable `CI_SCENARIO=track-end`; physical timing,
gapless/folder-jump enabled and stopped-state resume remain unvalidated.
CUE/DSF/DFF metadata and positional selection are covered by disposable V2.57
`CI_SCENARIO=formats`. Both CUE entries can share path and `song_track=0`;
queue IDs can collide with ordinary tracks, and HTTP `mark` can select the wrong
row. Keep snapshot/position identity, never deduplicate by ID. CUE favorites
responses lose path/track/isCue even though distinct database tracks survive and
positional playback works. Generated DSF/DFF establish source metadata, not native
DSD/DoP or hardware output. SACD ISO now has separate approved-sample checks; see
`research/docs/reports/sacd.md` and `docs/protocol/formats.md`.
`research/docs/reports/m21-comparison.md` is reference only: M21's FiiO Music uses UTF-16 length
units, a different state enum and toggle semantics. DISC remains the priority;
do not copy those Android rules into its client.

Manual Update media lib now works too: `sd_mount()` mounts INSIDE chroot so
`/proc/mounts` records source `/dev/mmcblk0p1`, accessible to the scanner. The old
`/work/rootfs/dev/mmcblk0p1` source passed Browse files but failed the scanner's
`access(source)` gate. Four test tracks were scanned and returned over TCP.
V2.57 Auto update is a volatile UI flag (defaults to 1 each restart), triggered by
SD insertion (`aa22`), not by the emulator's boot remount alone. Repeated scans work
after dismissing the result via the OK button background (130,303) and unlocking
the UI; backlight-on may still show a clock lockscreen. Click the Auto text row
(170,141), not its circle. `sd_mount()` primes stock `blkid /dev/mmcblk0p1`: the two
mmc nodes alias one loop device, and cold enumeration otherwise misses the partition
name needed by stock hotplug remounting. Cyrillic add/rename/delete are checked in
`tests/integration/storage_check.py` (V2.57 only). USB export/eject remains unvalidated. See
`emulator/docs/settings.md` and `emulator/docs/media-library.md`; do not inject broad netlink broadcasts.
