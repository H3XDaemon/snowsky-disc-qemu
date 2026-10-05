# Changelog

User-facing changes to **snowsky-disc-qemu**, not vendor firmware announcements.
Keep entries short and group related work; protocol details and validation evidence
belong in the linked documentation. Vendor notes live in `firmware/docs/reports/<version>.md`.
See [release and support policy](firmware/docs/porting.md).

## [Current]

Current development since the `v2.57` pre-release; not a published release.
Active firmware: **V2.57**. Local protocol research is finalized in
[issue #10](https://github.com/eudj1n/snowsky-disc-qemu/issues/10); see the
[controller capability summary](docs/protocol/disc-capabilities.md).

### Added

- Disc Assistant research prototype with Russian/English commands to find and play
  tracks, artists and albums from the device library, pause/resume playback and
  navigate the queue through a persistent text console. [Setup](experiments/disc_assistant/README.md).
- Disc Assistant Web with text and microphone input, local Whisper speech
  recognition and optional spoken replies through Piper.
  [Browser interface](experiments/disc_assistant/docs/guides/web.md), [speech setup](experiments/disc_assistant/docs/guides/tts.md).
- Pluggable speech adapters and explicit model profiles for Disc Assistant, with
  optional Sherpa/GigaAM recognition, Silero/Vosk synthesis and TTS text normalization.
  Existing Whisper/Piper defaults remain unchanged. Includes browser recognition
  comparison and a device-free voice listening tool.
  [Adapter contract](experiments/disc_assistant/docs/guides/voice-adapters.md),
  [models and listening comparisons](experiments/disc_assistant/docs/guides/tts.md).
- Assistant current-track likes, now-playing questions, configurable volume steps
  and album/artist search priority, with a concise [command guide](experiments/disc_assistant/docs/guides/quick-guide.md).
- Installable Controller library with typed current-track/favorite/volume results,
  strict playback decoding and CI checks for types and wheel installation.
  [Controller API](controller/docs/api.md).
- Preserved the historical, unsupported diskOS UI experiment with isolated build/run
  helpers, recorded V2.40 results and criteria for revisiting its status. [Preview](experiments/diskos/docs/preview.md).
- Experimental local browser execution of DISC through TinyEMU/WebAssembly,
  with a separate build workflow, live screen, taps, swipe navigation, Back and screen sleep/wake controls. [Prototype](experiments/browser/docs/overview.md).
- Remote playback, seeking, play modes, favorites and guarded queue selection,
  with natural end-of-track/list checks. [Playback](docs/protocol/remote-control.md).
- HTTP file transfer, library browsing and custom playlist management/playback;
  artist-scoped album, genre and folder selection (including captured FiiO Control Play all) and guarded
  bulk playlist additions. [Library](docs/protocol/library-browsing.md).
- Disposable category-deletion checks documenting membership loss, file removal
  and stale references. [Deletion limits](docs/protocol/library-delete.md).
- Library scan cancellation and dedicated index reset with recovery checks;
  reset preserves source files. [Scan](docs/protocol/library-scan.md), [reset](docs/protocol/library-reset.md).
- Remote audio settings with verified stock Gain and physical-app filter mapping, channel balance
  and PEQ helpers with stock preset labels and ten-slot isolation checks; read-only gapless,
  folder-jump and ReplayGain preferences. [Settings and limits](docs/protocol/remote-settings.md).
- Work-mode/codec preferences and custom wallpaper uploads, including four styles
  and captured color/Date save behavior, with verified safe name limits. System
  themes now support verified opacity, color, style and overlay edits.
  [Modes and themes](docs/protocol/remote-modes-themes.md).
- Passive LAN discovery and an opt-in, time-limited bridge for one phone;
  FiiO Control on iPhone verified discovery, connection, emulator library access
  and rediscovery after disconnect. [Compatibility and limits](controller/docs/discovery.md).
- USB-power emulation that inhibits stock idle shutdown, plus idle/reconnect
  checks. USB data/DAC is not emulated. [Power behavior](emulator/docs/idle-power.md).
- CUE/DSF/DFF metadata and track-selection checks, plus opt-in stereo SACD ISO
  catalog/queue/favorites checks using approved local media. Native DSD output remains
  unvalidated. [Formats](docs/protocol/formats.md), [SACD scope](research/docs/reports/sacd.md).
- Sanitized physical-app fixtures, focused integration scenarios and optional
  local failure logs, including captured genre browsing/album selection.
  Long power tests run only when relevant. [Testing](docs/development/ci.md).
- Opt-in boot through the stock init scripts (`rcS`, `fiio_init.sh` and its watch
  loop, image hooks), with reboot, power-off and power-loss commands that keep
  `/usr/data` and the card. `/usr/data` can be a size-limited image, and a guest can
  be prepared from a rootfs image built on the stock firmware.
  [Stock init and power events](emulator/docs/stock-init.md).
- Keys held at power-on: static guest programs read the Volume and Play pin levels
  from `/dev/mem`, in step with the viewer's buttons. [Keys](emulator/docs/keys.md#keys-held-at-power-on).
- Guest environment presets: a battery gauge laid out like the player's with
  adjustable charge, serial number, USB cable state at boot, selectable stock
  settings profiles (including the untouched factory state), unlimited guest
  lifetime and power-off handling without the viewer.
  [Environment](emulator/docs/environment.md).
- A card like the player's: selectable size, exFAT and a real partition table,
  with which stock mounts the card by itself; forced removal while a track plays.
  [Card options](emulator/docs/media-library.md#card-image-options).
- Emulated `wlan0` with controllable state and address, a guest with no network
  that can gain a link later, and a bandwidth limit for slow-link tests.
  [Network](emulator/docs/network.md#emulated-links-isolation-and-shaping).
- Stock "Reset all" runs to completion in a stock-init guest; analysis showed it
  never involved the MCU. [Report](research/docs/reports/reset-all.md).
- The stock output stream state (format, rate, running, silence while paused)
  for programs and tests, a guard that refuses programs which run here but
  would die on the player's FPU handling, and a page on what the emulator
  cannot show. [Audio](emulator/docs/audio.md#output-stream-state), [limits](emulator/docs/limits.md).
- Guest programs receive the `argv[0]` their caller passed (binfmt `P` flag), as
  on the player. [Emulation](emulator/docs/emulation.md#binfmt_misc--register-only-mipsel).
- A stock-init guest's uptime and monotonic clocks count from its power-on
  (a time namespace), not from the Docker VM's boot. [Stock init](emulator/docs/stock-init.md).
- Statically linked guest programs (boot-layer packages) see the framebuffer and
  input devices as stock's dynamic programs do: the image rebuilds Debian's qemu
  with a patch that answers those ioctls (`QEMU_DEVICES`, default on). Readiness
  now counts a frame flushed by the UI process itself, whenever it happened — a
  static UI's single pan at start included.
  [Static programs](emulator/docs/stock-init.md#static-programs-and-the-devices).
- An opt-in model of the 3.5 mm and 4.4 mm outputs that feeds stock's own
  detection (unplugging pauses playback), and `EMU_CPUS` to slow the whole
  container. [Jack model](emulator/docs/audio.md#analog-output-jack-model),
  [slowing the guest](emulator/docs/limits.md#slowing-the-guest).
- Daily OTA catalog monitoring with tracking issues; no automatic firmware
  download or promotion. Optional viewer Power-on script for custom startup.

### Changed

- The emulator image gains `exfatprogs`: rebuild it
  (`docker build -t snowsky-disc-qemu-ci emulator/docker`) before using an exFAT
  card. Everything else works with the previous image.
- Known gap of the pinned qemu 7.2: `getsockopt(SO_ERROR)` returns the host's
  error number to a guest program. [Workaround](emulator/docs/limits.md#socket-error-numbers).

- Move emulator launch/configuration/build files into `emulator/` and rename its
  Compose service to `emulator`. Container-name overrides work throughout the launcher.
  [Setup and existing checkouts](emulator/docs/running.md).

- Separate current status and setup guidance from historical reports, preserving
  acceptance evidence and paused research conditions. [Documentation](docs/README.md).

- Organize manuals beside their components, with a shared [documentation index](docs/README.md)
  and automatic checks for local links.

- Separate runnable browser, diskOS and Assistant experiments from firmware research;
  component tests and launchers follow their owners. [Layout and migration](experiments/README.md).

- PEQ coverage now includes physical FiiO Control preset, Save/Reset and local
  preset workflows. The client retains validated JSON writes because the app's
  bulk Local Apply format is incompatible with V2.57. Auto EQ and broader SACD
  checks remain explicit follow-ups. [PEQ](research/docs/reports/peq.md), [SACD](research/docs/reports/sacd.md).

- Viewer now draws a responsive CSS device with visible physical buttons and
  audio/USB/microSD connectors, removing the photo skin and manual alignment.
  The browser experiment shares its layout and adds a combined Power control;
  QEMU/WASM badges distinguish the two pages. Updated screenshots and guides
  cover both. [Viewer](viewer/docs/usage.md), [browser experiment](experiments/browser/docs/overview.md).

- Centralize the active firmware default and reviewed runtime/acceptance profiles;
  TCP and WebSocket share device-version compatibility guards. Existing explicit
  `FW_VERSION` pins remain supported. [Firmware profiles](firmware/docs/firmware-profiles.md).

- Separate emulator, viewer, controller, firmware tooling and research into explicit
  components. Keep root launch commands; media now lives in `emulator/sdcard/` and
  Docker names use `snowsky-disc-qemu`. [Source layout](docs/architecture/repository.md).
- Support one validated firmware on `2.x`; older versions remain historical
  snapshots without promised backports. Hosted integration now targets V2.57 only.
- Keep immutable `v2.57` as a pre-release and `v2.40` as the historical stable
  release; the eventual stable V2.57 release will use a new tag such as `v2.57-r1`.
- Refresh setup/control documentation and V2.57 screenshots; retire the obsolete
  `main` branch and automatically delete merged PR branches.

### Fixed

- Setup and cleanup of a fresh work volume no longer detach the card image of
  another running emulator container (loop devices are shared by the Docker VM).
- WebSocket bridge releases its connection slot even when an invalid peer disconnects
  during cleanup, allowing the next client to connect. [Details](controller/docs/websocket.md).

- LAN bridge timeout cleanup now releases the control connection even during
  continuous upstream notifications.
- Stabilize library, SD and end-of-track tests around stock asynchronous behavior;
  read-only diagnostics tolerate transient player-process ambiguity.
- Correct MIPS binary-handler registration so it cannot intercept i386 programs;
  setup leaves other architectures' handlers untouched.
- `getsockopt(SO_ERROR)` returns MIPS errnos under the rebuilt qemu (Debian's 7.2
  returned the host's). [Limits](emulator/docs/limits.md#socket-error-numbers).
- The viewer's screen stayed black in Safari: its page now reads the frame stream
  as plain bytes (`/stream?raw=1`), which WebKit's `fetch()` delivers, instead of
  the multipart type it swallows. Reported in #56. [Viewer](viewer/docs/usage.md).

Detailed progress, limitations and follow-ups: [protocol research](research/docs/status.md).

## [2.57] — 2026-09-13 (pre-release)

Main OS **257**, recovery **18**. Reclassified as an immutable **pre-release
snapshot** on 2026-09-16; the tag and commit are unchanged. Entries below describe
that snapshot, not current development. Exact-commit CI evidence is in the
[release notes](https://github.com/eudj1n/snowsky-disc-qemu/releases/tag/v2.57).

### Added

- Viewer headphone, USB-status and SD controls; real guest card eject/insert,
  stock brightness tracking and clearer sleep/off status. USB was status-only.
- Fingerprint-checked diagnostics for V2.40/V2.57, firmware inventory tools and
  a reusable porting/acceptance checklist.
- Guarded V2.57 runtime profile, clean-volume button/reboot checks, MIT license
  and owner-attributed skin photo.

### Fixed

- Live browser audio starts at current PCM and recovers after stalls;
  Replay capture retains historical playback.
- SD reinsertion/remounting, automatic scans and UTF-8 filenames; empty cards
  no longer prevent fresh runtime initialization.
- Idle key polling no longer consumes a CPU core. Viewer startup waits for guest
  readiness instead of a fixed delay; pointer cancellation resets the cursor.
- Diagnostic process selection and SD test ordering no longer confuse worker
  processes or a busy card with an idle fixture.

### Changed

- V2.57 became the default, with V2.40 selectable at publication; existing
  firmware volumes are preserved rather than migrated automatically.
- WebSocket bridge became opt-in; Compose configuration moved to `compose.yaml`.
- Lossless changed-frame streaming and persistent status events reduce polling
  and reconnect automatically after viewer interruptions.
- Shared agent instructions moved to `AGENTS.md`; passwords/private-project
  references removed from public-facing documentation without rewriting history.

At publication, both firmware profiles had validation coverage. Hardware
BT/USB/DSD, MCU behavior and hardware-accurate power were not validated.
Current support and release gates are defined in [CI.md](docs/development/ci.md).

## [v2.40] — 2026-09-11

Main OS **240**, recovery **17**. Immutable emulator source release, not an
installable vendor firmware package. Both CI workflows passed on `e3aab81`.

### Added

- Stock UI boot, touch/swipes, FAT SD card and library scanning under qemu-user.
- Physical-button hotspots with app-configured volume gestures and guest-only
  power control; PCM capture, WAV export and browser audio with DAC gain tracking.
- Stock FiiO Link TCP control, our WebSocket bridge and a protocol inspector.
- Firmware-free and secret-backed integration CI, pinned build dependencies
  and weekly Dependabot updates without automatic merging.

### Fixed

- Audio-card discovery, scanner SD mount paths and handling of partial playback
  notifications.

### Project and limitations

- Renamed to `snowsky-disc-qemu`; default branch `2.x`, immutable releases,
  localhost-only ports and confined guest reboot/privileged operations.
- Firmware is excluded from Git and CI artifacts. Branch protection was
  unavailable on the private repository's GitHub plan at publication.
- Automatic scanning, native stock WebSocket, phone interoperability and
  hardware USB/BT/DSD/power behavior were not fully supported or validated.

See [STATUS.md](emulator/docs/status.md) for current capabilities and evidence.

[Current]: https://github.com/eudj1n/snowsky-disc-qemu/compare/v2.57...2.x
[2.57]: https://github.com/eudj1n/snowsky-disc-qemu/compare/v2.40...v2.57
[v2.40]: https://github.com/eudj1n/snowsky-disc-qemu/releases/tag/v2.40
