# Branches, CI and firmware inputs

## Documentation links

`python3 -m ci.docs` checks local Markdown, reference-style and HTML link targets
in tracked/non-ignored Markdown files. The hosted firmware-free workflow runs it
before building the toolchain; documentation-only moves need no firmware execution.

## Python library quality gate

Hosted firmware-free CI also installs the pinned tools in
[`ci/requirements-quality.txt`](../../ci/requirements-quality.txt) and runs
`bash ci/python-quality.sh` with that environment on `PATH`. This checks
Controller lint, incremental strict typing and the installed-wheel contract.
The wheel test builds in a temporary copy, preserves the checkout, checks a core
installation without aiohttp, and then verifies the WebSocket/bridge extras.
The extras installation needs package-index access; ordinary Docker firmware-free
tests still run with networking disabled.

## Version policy

`2.x` is the default development branch for firmware 2.x. The obsolete `main`
branch has been removed; its commits remain in `2.x`. A future incompatible major
gets `3.x`.
Firmware V2.57 is the active/default version and the only hosted integration target.
V2.40's legacy runtime profile remains temporarily, pending a separate cleanup task.
Its presence is not a promise of continuing support or backports.

We actively support **one validated firmware** and retain older releases as
historical snapshots. Switch only after validating the candidate and preserving
the previous version's final validated snapshot; OTA detection alone does not
trigger the transition. See [the support policy](../../firmware/docs/porting.md#support-policy--one-active-firmware).

The first validated V2.40 milestone is
[v2.40](https://github.com/eudj1n/snowsky-disc-qemu/releases/tag/v2.40). Emulator-only follow-up fixes
for that firmware use `v2.40-r1`, `v2.40-r2`, etc. Never move/reuse an existing tag.
This is a firmware-based naming convention, not npm/SemVer package versioning.
Choose an unused firmware-based tag after validation. Do not merely replace the rootfs hash:
binary patches, diagnostic addresses, UI coordinates and protocol behavior must be checked.
GitHub immutable releases are enabled: publish only once the release contents are final.
The existing `v2.57` is retained as a pre-release snapshot; `v2.40` remains the latest
stable historical release. The next stable V2.57 release uses a new unused name,
currently `v2.57-r1`. Neither tag has been moved or deleted.
Deleting an immutable release/tag does not free its name for later reuse, even
if the repository setting is subsequently disabled. Use an unused `-rN` name;
do not delete a published tag merely to republish different code under that name.
See [GitHub's immutable-release rules](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).

Before releasing, require firmware-free CI, full integration and the explicit
long `idle` / `idle-usb` scenarios for **the firmware being released** to have
succeeded **on the exact release commit**, review the
declared limitations in STATUS.md, and publish only
source/release notes, never firmware. Tags/releases are not created automatically.
For example, inspect `gh run list --branch 2.x --commit <full-sha>` before publishing.
Retired versions leave required integration coverage; remove their current workflow
choices and compatibility code in the corresponding cleanup task.
Their immutable tags and analysis reports remain available as historical snapshots.
The daily OTA metadata check does not replace these release gates.

### Test selection policy

Choose validation by the behavior affected, not by running every scenario after
each edit. The following is the agreed policy as of 2026-09-16:

| Change | Validation |
| --- | --- |
| Documentation only | Diff, links and consistency; no firmware run |
| Normal implementation change | Firmware-free suite and relevant focused integration where applicable |
| Shared runtime, setup, shim or transport changes | Firmware-free suite and `full`; add long scenarios if power/lifecycle behavior is affected |
| USB detection, power, timers, shutdown or reconnect | Also run explicit `idle` and `idle-usb` |
| New firmware profile or final release candidate | Firmware-free, `full`, `idle` and `idle-usb` on the candidate commit |

`full` includes a short native USB cable-detection check, **not** the 310-second
USB idle observation. Both long scenarios are already opt-in, including in local
development; the current hosted workflow runs `full` only and has no long-test
switch. Record explicit local long-test results and their commit for a release.
No additional CLI flag or workflow change is needed to skip them during unrelated
work. `idle` with its default `all` phase does not include `idle-usb`.

Keep the real five-minute firmware threshold and 310-second USB observation.
Shortened timers would test a different condition. Document any validation not
run; earlier success is not evidence for a subsequently changed implementation.

Focused V2.57 `CI_SCENARIO=peq` exercises all supported device presets and ten
user slots independently of unrelated settings. `CI_SCENARIO=sacd` additionally
requires an owner-approved `CI_SACD_ISO=/absolute/path/to/sample.iso`; it uses a
temporary copy and is never selected by `full` or hosted CI. Its logs/PCM must
remain local because the input may be private. See [PEQ](../../research/docs/reports/peq.md) and [SACD](../../research/docs/reports/sacd.md).

The research Assistant has a separate, opt-in end-to-end runner:
`bash ci/assistant.sh OTA_DIR NEW_REPORT_DIR`. It provisions generated media,
Typesense and a disposable V2.57 guest without published ports or personal settings.
See [Assistant emulator scenarios](../../experiments/disc_assistant/docs/evaluation/emulator-acceptance.md) for selected
cases, JSON/Markdown reports and framebuffer evidence. This regression cohort is
not part of `full`, hosted CI or physical-player MVP acceptance; known mismatches
produce a nonzero exit status. Its oracle unit tests run in firmware-free CI.

### Branch policy after public publication

- `2.x`: changes through pull requests, mandatory **Firmware-free checks** from
  GitHub Actions, branch up to date before merging and resolved review conversations.
  No mandatory second-person approval for this owner-maintained project.
- Protection for `2.x` includes administrators; force pushes and branch deletion
  are disabled.
- GitHub automatically deletes PR head branches after merge when permitted by
  branch protection. Keep development in short-lived branches targeting `2.x`.
  Local branches are not deleted automatically; use `git fetch --prune` to remove
  stale remote-tracking references and `git branch -d <branch>` for merged local
  branches after switching to an updated `2.x`.
- Firmware integrations remain exact-commit release gates, not required checks on
  fork PRs. Secrets are only used in trusted manual integration runs on `2.x`.

On 2026-09-11 the private repository's plan returned HTTP 403 for protection.
The owner approved public publication and configuring this policy on 2026-09-13.

## Firmware-free CI

Source ownership and the entry-point inventory are in [REPOSITORY.md](../architecture/repository.md).
Python unit tests live in each component's `tests/` directory; shared harness tests live in
`tests/unit/`. The runner detects omitted modules and discovers JavaScript and
shell checks across every component. Cross-component scenarios live in
`tests/integration/`; generated media helpers live in `tests/fixtures/`.

`.github/workflows/ci.yml`: every push/PR plus manual dispatch; hosted Ubuntu 24.04.
No secrets, firmware, privileged containers, cache upload or image publishing.

- Validate the regular Compose definition.
- Build `emulator/docker/Dockerfile`: multi-architecture Debian image pinned by index digest,
  Debian and security packages pinned via the 2026-09-10 snapshot.
- Run all Python tests (including synthetic WebSocket integration tests), JavaScript
  tests, shell syntax checks and cross-compile all four MIPS shims. **Any Python skip fails CI.**
- Test container uses a read-only source mount and `--network none`.

Local equivalent:

```sh
docker build -t snowsky-disc-qemu-ci emulator/docker
docker run --rm --network none -v "$PWD:/repo:ro" snowsky-disc-qemu-ci bash /repo/ci/test.sh
OTA_DIR=/tmp/unused ./emulator/run.sh compose config --quiet
```

Checkout is pinned to a full action commit SHA and does not persist credentials.
Actions use Node.js 24 (`checkout` v7, `setup-docker-action` v5 and
`setup-compose-action` v2). `.github/dependabot.yml` checks GitHub Actions weekly and
groups proposed updates into PRs; SHA pins are retained and tested by `test_ci_pins.py`.
No automatic merging is enabled. This updater does not change Docker Engine/Compose
input versions, the Debian snapshot, or firmware checksums; those require explicit updates.
The firmware-free and firmware-integration workflows install **Docker Engine
28.5.2 and Compose 2.39.4** using official
Docker actions pinned to full SHAs. Compose's binary cache is disabled. The first
hosted integration attempt exposed an older preinstalled Engine: `interface_name`
requires Engine >=28.1 as well as Compose >=2.36. Do not rely on runner defaults.
Node/Python/aiohttp/toolchain versions come from the same dated package indexes.
The hosted runner/kernel/build backend can still change; this is a pinned userland
and repeatable functional test, **not a claim of bit-identical Docker image builds**.
Updating the image digest or snapshot is an explicit dependency change requiring tests.
Old snapshots also freeze security fixes; update them deliberately, not never.

## Private firmware integration

`.github/workflows/firmware.yml`: manual dispatch **on `2.x` only**, hosted disposable
runner; no fork PR trigger, no `pull_request_target`, no self-hosted runner. Only
trusted maintainers may change/run this workflow: a ref condition does not protect
secrets from someone who can edit trusted workflow code.

```sh
gh secret set FIRMWARE_V257_URL --repo eudj1n/snowsky-disc-qemu
gh workflow run firmware.yml --ref 2.x
```

Paste the direct HTTPS ZIP download URL at the hidden prompt; do not pass it as a
command argument or put it in `.env`, YAML, docs or a chat. The workflow has no
version selector: it reads `firmware/active-version` and passes only the profile's
`url_secret` (currently `FIRMWARE_V257_URL`) as `FIRMWARE_URL` to the download step.
The unused historical secret may remain stored for archival work, but is not
passed to current CI jobs. `tests/unit/test_ci_pins.py` checks this selection and
the trusted-branch policy. See [profile selection](../../firmware/docs/firmware-profiles.md).
Version, rootfs size/hash, chunk count and exact binary/patch fingerprints are in
`firmware/v<version>.json`; no direct download URL is committed.

For the daily OTA monitor and verified OTA file access, see [OTA.md](../../firmware/docs/ota.md).
Firmware integration still uses fixed ZIP inputs.

`firmware/tools/fetch_firmware.py` receives the secret only in its download step. It requires
HTTPS (including redirects), suppresses download exception details, bounds ZIP/chunk
sizes and extracts validated chunk basenames (77 for active V2.57). The legacy local
V2.40 downloader still validates its 85 chunks until cleanup. It never extracts archive paths,
kernel or recovery images. The ZIP wrapper itself has no pinned checksum; the actual
consumed rootfs **is SHA-256 verified before unsquashfs or firmware execution** by
`00_extract_rootfs.sh`. A changed wrapper is acceptable only if that payload is identical.

The workflow first runs the firmware-free suite on the same commit, then:

1. Downloads/extracts chunks to runner temporary storage.
2. Starts the regular Compose services with `ci/compose.yml` overlay: no published ports,
   randomly named container/work volume and a separate generated SD directory.
3. Decrypts/verifies/extracts the selected firmware, checks six binary fingerprints,
   applies its guarded key patch, primes a new config DB, and boots normally.
   On V2.57, `tests/integration/discovery_check.py` observes stock UDP announcements, suppression
   before/after a TCP handshake and recovery after disconnect, without changing
   media/settings or exposing LAN ports. See [discovery](../../controller/docs/discovery.md).
4. Confirms an initially empty TCP catalog, slowly drags to Settings, scrolls to
   Update media lib, taps Update now, and checks all three generated tracks are
   indexed (Unicode WAV and two FLACs with artist/album tags).
5. Restarts before any track selection, verifies repeated viewer SD eject/insert,
   busy-card rejection, media preservation and USB charging state; on V2.57 it
   also verifies the native USB-power flag after cable insertion/removal. It
   waits for insertion-triggered auto-scan completion, exact SD/SQLite/TCP
   agreement and result dismissal before comparing the two transports; a mounted
   card alone does not establish a stable catalog.
6. Compares TCP/WS protocol/catalog/settings, checks volume restore, play/pause,
   exclusive connection and reconnect, then checks byte-exact periods of the
   generated waveform in the decoded 32-bit PCM (promoted from signed 16-bit WAV).
7. Checks physical-button events with TCP/sysfs readback and dynamic BusyBox `reboot`
   binding to `fbshim` without invoking a kernel reboot.
8. Runs the same [remote-control acceptance](../protocol/remote-control.md) over TCP and WS:
   selection, next/previous, seek, modes, album/queue/favorites and physical event
   notifications, with read-only memory/SQLite checks. The WS client uses Docker DNS
   with a localhost Host header; server Host/Origin protections remain enabled.
   Then runs `tests/integration/queue_check.py`: optional queue-label equivalence, guarded current
   queue selection, replacement and stale-index rejection, and recovery after a
   raw invalid-index probe. Both TCP/WS and HTTP mark/metadata readback are checked.
   `tests/integration/queue_reads_check.py` follows with five-mode `0105` reads and bounded `0426`
   absence checks during playback, pause and after queue replacement.
9. Runs [stock HTTP acceptance](../protocol/http-api.md) directly and through the proxy: streamed
   upload with byte-exact file checks, directory operations, catalog paging, and
   custom playlist lifecycle with internal-ID gaps. TCP/WS scans add the uploaded
   fourth track and remove it from the index after file deletion. V2.57 also uploads PNG.
   On V2.57, `tests/integration/playlists_check.py` then verifies whole-list and track playback
   over TCP/WS, HTTP queue order/mark, playlist ID gaps, rename/add/remove and
   fresh-preflight rejection after deletion/renaming or with empty lists.
10. Runs [remote settings/PEQ acceptance](../protocol/remote-settings.md) over TCP/WS, checking
    gain, DRE, filter, SPDIF, channel balance, user bands/master gain and SQLite
    persistence, then restores settings. Both gain values and all six filters
    are exercised. Balance also checks left/right DAC
    attenuation mirrors at center, ±1 and ±20.
    The separate persistent sound check changes/restores gain, balance, all six
    filters and DRE through `DiscSession`, and rejects a stale displayed value.
11. Runs [modes/codecs/themes acceptance](../protocol/remote-modes-themes.md): USB/local/AirPlay
    control transitions, five codec preferences, five stock lock screens, exact
    custom PNG and metadata, and empty-body/activation quirks. TCP/WS and direct/proxy
    HTTP are exercised.
12. On V2.57, runs `tests/integration/formats_check.py`: generated two-track CUE/WAV, DSF and DFF,
    stock scanning, TCP/HTTP catalog agreement, metadata and positional selection
    over TCP/WS, including CUE queue/favorites. Checks source preservation and
    restores the original three-track index. Records stock ID collisions and
    lossy favorites without rewriting them; see [formats and identity](../protocol/formats.md).
    Then runs `tests/integration/track_end_check.py`: three generated six-second WAV/FLAC
    tracks, a custom queue and all five modes over TCP/WS. Event-only observation
    proves natural completion/repeat/wrap/stop with gapless/folder jump off;
    checks retained queue, fresh mode reads and stopped/playing runtime. Restores
    mode, removes its fixtures/list and reindexes the original three tracks.
    See [EOF contract](../protocol/track-end.md), including silent `0202` after final stop.
    Before SD hotplug acceptance, runs `tests/integration/scan_cancel_check.py` with
    1024 additional generated WAVs: idle/active cancellation over TCP/WS, partial
    index agreement, unchanged source bytes and full-scan recovery. Removes its
    fixtures and reindexes the original three before the SD scenario's reboot.
    Then `tests/integration/library_reset_check.py` verifies dedicated `0621` on paused TCP/WS
    fixtures: index/favorites loss, preserved source/settings/custom lists,
    immediate inconsistent replies, scan-only recovery limits and explicit
    guest-restart persistence/recovery. No direct DB writes or factory reset.
    Runs automatic SD scanning and Cyrillic add/rename/delete checks, then
    `tests/integration/preferences_check.py`: fingerprinted TCP allowlist, three
    read-only playback preferences, and six rejected local-only setters over TCP/WS.
    Confirms unchanged SQLite/config/runtime and continued fresh network reads.
13. Stops its guest, unmounts/detaches its SD loop, removes only its own stack/work
   volume and generated media. The interactive `snowsky-disc-work`/`sdcard` remain untouched.

Local equivalent using already extracted chunks:

```sh
bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Optional local diagnostic PNGs; never uploaded by Actions:
FW_VERSION=2.57 CI_SHOTS="$PWD/shots/v257" bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Optional local guest logs, copied before disposable-volume cleanup (success or failure):
FW_VERSION=2.57 CI_LOGS="$PWD/work/ci-v257" bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Focused queue run: fresh setup/scan/reboot, fresh-empty checks, then TCP/WS queue checks.
CI_SCENARIO=queue FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Focused 0105/0426 reads, including an initially empty queue on TCP and WS.
CI_SCENARIO=queue-reads FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Focused settings/PEQ and balance over TCP/WS, plus guarded persistent sound settings.
CI_SCENARIO=settings FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Stock/system and four custom styles via direct/proxied HTTP; no media scan.
CI_SCENARIO=themes FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Three read-only preferences and six rejected local-only writes over TCP/WS.
CI_SCENARIO=preferences FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Custom playlist playback and fresh HTTP preflight over TCP and WS.
CI_SCENARIO=playlists FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Genre/scoped-album/folder selection, bulk-add expansion and index-only deletion.
CI_SCENARIO=library FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Seven destructive category-delete cases on disposable generated media only.
CI_SCENARIO=library-delete FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Cooperative indexing cancellation, partial catalog and subsequent full scan.
CI_SCENARIO=scan-cancel FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Destructive library reset, only on the disposable generated-media fixture.
CI_SCENARIO=library-reset FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Natural track/list completion for five modes; no seek/next/EOF injection.
CI_SCENARIO=track-end FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# CUE/DSF/DFF metadata, ambiguous identities and positional selection.
CI_SCENARIO=formats FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Stock UDP announcements before, during and after one control connection.
CI_SCENARIO=discovery FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Natural screen timeout, idle shutdown and explicit local boot/reconnect.
CI_SCENARIO=idle FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
# Native USB-power detection; paused for more than the five-minute idle limit.
CI_SCENARIO=idle-usb FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
```

`CI_SCENARIO` accepts `full` (default), `queue`, `queue-reads`, `settings`, `themes`,
`preferences`, `playlists`, `library`, `library-delete`, `scan-cancel`, `library-reset`, `track-end`, `formats`,
`discovery`, `idle` or `idle-usb`. All use the same
random-name isolated stack and cleanup. Focused runs execute only their selected
checks, not unrelated integration scenarios. Most use the shared setup/scan/reboot
preparation; `scan-cancel`, `library-reset`, `track-end` and `formats` start after boot and prepare their
own network scans.
`library` is V2.57-only and starts after boot with its own generated tagged FLACs
and stock scan. It checks genre/album filter isolation, nested/empty folders,
guarded TCP/WS selection, direct/proxied bulk add, rejected grouped deletion and
index-only track deletion/rescan recovery. Source hashes are preserved and the
captured type-8 whole-genre Play all is compared with type 10 in modes 0/4. The
three-track baseline is restored. The same check runs in `full` before formats.
See [the library contract](../protocol/library-browsing.md); no long power tests are involved.
`library-delete` is a focused-only V2.57 research scenario (not part of `full`).
It starts after boot, generates its own additional media and compares index,
favorites, two overlapping playlists and source files for seven DELETE cases,
then verifies scan recovery and restores the three-track baseline. It checks
direct/proxied HTTP with TCP/WS state control. See [deletion scope](../protocol/library-delete.md).
`themes` is V2.57-only, starts after boot without a media scan, and calls
`modes_themes_check.py --themes-only`. It covers five system slots, read/merge/write/verify system edits (opacity, RGB,
four styles and independent overlays, original image/SQLite checks and restoration), four custom
styles with explicit time off/on, full-image and metadata preservation, unsafe
empty-body/activation semantics, alias encoded-byte boundaries (including raw
over-limit diagnostics) and system-theme restoration over direct and
proxied HTTP. No TCP/WS mode/codec changes, interactive volume or long power
checks are involved. The same style assertions run in ordinary `full` on V2.57.
`discovery` is V2.57-only, starts after boot and does not need a media scan. It
observes multicast inside the disposable namespace, not across the host/LAN
boundary. The opt-in phone LAN bridge is never launched by CI or normal Compose.
`idle` and `idle-usb` are V2.57-only and bypass the always-awake fixture below.
They set display index 3 (120 seconds) and reviewed idle limits only while their
disposable guest is stopped. `CI_IDLE_PHASE=quiet|power|all` selects the `idle`
phases (`all` default); `usb` is also accepted, equivalent to `idle-usb`.
USB acceptance is separate from `all`. These long scenarios are opt-in rather
than additions to the 25-minute hosted full gate; `full` retains a short native
USB-flag check. See [power/reconnect scope](../../emulator/docs/idle-power.md).
`formats` is V2.57-only and generates its original fixtures with Python's standard
library. No FFprobe/container dependency is added; SACD ISO and native DSD output
are not covered. See [scope and reproduction](../protocol/formats.md).
`track-end` is V2.57-only, uses existing Python/SoX dependencies and adds no
normal Compose setting, image mutation or firmware patch. Event observation is
bounded at 35 seconds per mode and stops early after proven continuation or a
terminal sequence plus a two-second quiet tail. Query timeouts alone never pass.
For V2.57 scenarios other than `idle`/`idle-usb`, `tests/integration/awake_check.py --configure` sets `LIGTH_ON_TIME=7` (never)
in the **stopped disposable guest's** settings DB before boot, then checks the
fingerprinted UI's index 7 / timeout 65535 readback. This is test-fixture setup,
not a network capability or firmware patch. `CI_DISPOSABLE=1` is supplied only by
`ci/compose.yml`; the normal Compose stack, setup scripts and interactive settings
are unchanged. `POWER_SAVE` is not modified. Explicit screen sleep/wake and
BusyBox reboot-shim binding checks still run.
`preferences` is V2.57-only; it does not change settings or require additional
restarts. Read-only SQLite/memory comparisons verify the rejected-write probes.
`playlists` is also V2.57-only and uses only generated custom lists/media; it
restores the play mode and leaves playback paused on a valid album before cleanup.
`scan-cancel` is V2.57-only and prepares its own baseline through stock network
scanning rather than the settings UI. See [the scan contract](../protocol/library-scan.md).
`library-reset` is also V2.57-only; it seeds favorites/custom lists via stock
APIs, checks exact removal/preservation and never touches the interactive volume.
It explicitly restarts its own guest to separate persistent data from live caches;
the client helper never reboots. See [the reset contract](../protocol/library-reset.md).
Only focused queue runs assert the queue
is empty before any track has been played; the full run reaches queue checks after
other playback scenarios.

`queue-reads` prepares its index with the verified stock TCP `0622/0000` scanner
instead of navigating the settings UI. It checks the generated files byte-for-byte,
requires an initially empty index, and verifies all three indexed names. The full
scenario and `queue` retain the UI scan test in `tests/integration/guest_check.py`.

### Idle shutdown versus protocol failure

A full V2.57 run failed in `queue_reads_check.py` before the playlist checks:
after paused playback, selecting play-all produced state 2, then no `0202` reply.
Guest logs showed screen-off, `release_local!`, network teardown and watchdog
stop **before** that selection; `start_local` subsequently reported
`g_fiio_local is null!`. This is not evidence of a bad playlist payload.

V2.57 static evidence: UI `473548` maps display index 3 to 120 seconds and 7 to
`0xffff`; timer `472ed8` skips display timeout at the latter value. Stock setter
`4ee9a0` saves the index via `43db60`, config slot 6 (`LIGTH_ON_TIME`). The
separate `echo_powerMG` loop `4f44d0` can call shutdown `4e6f0c`, which releases
the local player through `466d00` → `458354` → `44ffd0` before closing networking
and invoking confined `poweroff -f`. Its idle counter is not simply elapsed wall
time: one marker-mismatch branch adds 60 and then 1 per iteration. Therefore a
stored `POWER_SAVE=300` does not establish that shutdown needs five more minutes
after the latest network command. Network playback is not a UI touch keepalive.

The CI fixture keeps the screen timer out of long remote-protocol scenarios;
it does not fix or claim physical sleep/remote-wake compatibility. Separate
[idle/USB acceptance](../../emulator/docs/idle-power.md) observes counters, natural shutdown and
explicit local boot/reconnect without defeating the firmware's power policy.

The workflow does not upload/cache firmware, rootfs, guest logs, captures or derived
images. The hosted runner is discarded afterwards. Secret masking is not a guarantee
against private guest data in local logs: keep `CI_LOGS` under ignored `work/`,
inspect/redact before sharing, and never enable it as an Actions artifact.
Secret masking is also not a guarantee
against careless logging; never add `set -x`, verbose download output, or raw network
exceptions. A secret also does not preserve an expired/disappeared upstream file.

## V2.57 emulator release scope

V2.57 integration additionally runs `tests/integration/storage_check.py --disposable`: cold-cache
SD discovery, stock remove/add, repeated Auto update with result dismissal, screen
lock/unlock, and exact Cyrillic add/rename/delete comparisons across SD/SQLite/TCP.
It uses V2.57-only fingerprinted UI reads. The legacy V2.40 local scenario remains
available until cleanup, but is not run by hosted CI. See [MEDIA_LIBRARY.md](../../emulator/docs/media-library.md).

Preserve the historical V2.40 tag/baseline. Its legacy local profile/test target
remain until cleanup, and are no longer mandatory release gates. The hosted workflow
neither offers V2.40 nor receives its historical download secret.
Release gates cover the parts implemented or
affected by emulation: guarded boot/patches, framebuffer and input, storage/hotplug,
network adapters, PCM/browser audio and guest power confinement. The active firmware
must pass integration on the exact release commit, alongside firmware-free CI.

Vendor feature changes are reference information, not a mandatory acceptance suite
for this project. Add a targeted check when a change affects an emulator interface,
shim or patch, or reproduces an emulator regression. Unverified vendor fixes are not
advertised as verified emulator features. Hardware-dependent BT/USB behavior remains
outside this release's validated scope.
