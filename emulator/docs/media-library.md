# Media-library auto-update investigation

Verified on the pinned **V2.57** firmware, 2026-09-12. Repeated stock automatic
scans work under emulation after fixing SD discovery and respecting the UI gates.
USB mass-storage mode is **not a prerequisite** for the SD-insertion scan path.
User-facing configuration is covered in [SETTINGS.md](settings.md).

For an explicit remote scan, the stock Link command `0622000C0000` is now verified
on disposable V2.40 and V2.57 guests through TCP and WS. It does not require an SD
insertion event or screen tap. See [HTTP_API.md](../../docs/protocol/http-api.md#upload--index--play)
for completion events and the upload/reindex acceptance scenario. The automatic
insertion workflow below is a separate trigger.
V2.57 remote cancellation is now checked too: it leaves a partial index and uses
the same finish event as a full scan. See [LIBRARY_SCAN.md](../../docs/protocol/library-scan.md).

## Conditions for an automatic scan

The stock `aa22` SD notification updates the card-present state and shows a popup.
After its one-second timer, all four conditions must hold:

| Condition | V2.57 UI guest address | Meaning |
|---|---|---|
| Auto update enabled | word `0x83a5d0 != 0` | UI-local setting, initialized to `1`; resets on process restart |
| Card present | word `0x83a720 != 0` | Updated by SD notifications |
| No blocking UI state | byte `0x8dee8e == 0` | Shared UI flag, including the scan/result dialog |
| Screen unlocked | byte `0x8e1735 == 0` | Lock/display state; backlight-on alone does not mean unlocked |

The popup itself is suppressed during the startup overlay (`0x8def90`). Its getter
is `0x484aa0`; the lock handler's stock log identifies it as `power_on_ing`.

**An indexed track is not proof that the UI has finished its workflow.** The
successful scan leaves a result screen with an **OK** button. Until dismissed,
`0x8dee8e` remains `1`, so another insertion is ignored for scanning. Pressing the
button background at display `(130,303)` clears it. Earlier center taps were
confounded by the clock lockscreen: a separate defect in the OK text hit target
has not been established. Auto update was separately observed to toggle by clicking
the text row `(170,141)`, while clicking its small circle `(313,141)` did not toggle it.

A complete remove/add cycle works, and **another add without remove also works**
after the result is dismissed. The earlier repeated-add failure was caused by UI
state, not a requirement to reboot or reconnect USB. An insertion while locked
was blocked; lighting the screen, dismissing the clock lockscreen with a tap and
waiting did not replay that scan. A new insertion after unlocking did scan.

Editing files alone did not update the index during the test's two-second
observation window. This event path does not establish periodic filesystem watching.

## SD discovery failure and emulator fix

The emulator exposes `/dev/mmcblk0` and `/dev/mmcblk0p1` as two names for the same
loop device containing a FAT filesystem. With a cleared `/run/blkid/blkid.tab`
cache, stock `blkid` enumeration listed only `mmcblk0`. The stock storage-add
handler first unmounts `/tmp/sdcard`, then determines the filesystem using
`blkid | grep /dev/mmcblk0p1`. With no matching line, it fails to remount the card.
The resulting Scanning screen can remain at zero despite working file browsing
before that insertion.

The controlled comparison was:

1. Clear only `blkid.tab` and `blkid.tab.old` in the disposable guest.
2. Run stock `blkid`: only the whole-card alias is listed.
3. Run stock `blkid /dev/mmcblk0p1`: the real FAT signature is detected and cached.
4. Run stock `blkid` again: the partition alias is now listed too.
5. Send SD remove/add: the stock handler restores the guest mount, and scanning works.

`emulator/scripts/lib.sh:sd_mount()` now performs that explicit partition query after
mounting. This prepares the stock discovery cache during setup/boot and existing
remount operations. It does not synthesize filesystem information, alter library
rows, or patch firmware. The scanner still requires a guest-visible mount source
`/dev/mmcblk0p1`; the earlier [source-path fix](network.md) remains necessary.

Normal emulator boot **does not send an insertion notification**. This change
repairs stock hotplug remounting; it does not automatically scan on every boot.
A future lifecycle command can send a scoped event once startup/UI state is ready.

## Card image options

`10_setup_env.sh` builds the card from the media folder. Three independent
options make it closer to the player's card (30.9 GiB exFAT, one partition):

| Variable | Default | Effect |
| --- | --- | --- |
| `SDCARD_MB` | content + 32 | Card size in MiB. The image is sparse, so `31642` costs only what is stored. An explicit size also creates a card from an empty folder. A size too small for the media folder fails the setup instead of producing a short card. |
| `SDCARD_FS` | `vfat` | `exfat` formats exFAT (needs `exfatprogs` in the image, see `emulator/docker`). Stock mounts either with its own `mount -o iocharset=utf8`. |
| `SDCARD_PARTITION` | `0` | `1` writes an MBR with one partition at 1 MiB. `/dev/mmcblk0` and `/dev/mmcblk0p1` are then different devices, as on the player. |
| `SDCARD_KEEP` | `0` | `1` keeps an existing image instead of rebuilding it. |

With `SDCARD_PARTITION=1` the discovery failure described above does not occur:
stock's `blkid | grep /dev/mmcblk0p1` finds the partition with an empty cache, in
both libblkid versions of the rootfs (stock's `LD_LIBRARY_PATH` selects the older
`/usr/lib/libblkid.so.1.0`, which does not read the cache the emulator primes).
**Stock then mounts the card itself** a moment after `mq_player` starts
(`mount_storage_dev.c: mount to /tmp/sdcard succeeded`), and on every insertion.
The emulator's own remount stays as a fallback: it acts only when the card is
still unmounted four seconds after the UI is up, which is the normal case for
the default unpartitioned image in a [stock-init](stock-init.md) guest.

The layout is read from the image; `python3 -m emulator.runtime.card show`
prints it. The viewer's eject and insert work with both layouts.

## Forced removal

The viewer's ordinary eject refuses while the player holds a file open
(`SD card is busy`), because stock's removal handler deletes the mount point
directory even after a failed unmount. A **forced** removal is what a hand does:

```sh
curl -H 'Content-Type: application/json' -d '{"name":"sd","inserted":false,"force":true}' \
  http://localhost:8080/peripheral
```

(`Peripherals.set_sd(False, force=True)` from Python.) A busy mount is detached
from the namespace at once, then stock receives the same `remove` event. Observed
with a track playing: the removal takes 0.1 s, stock stops playback and closes
the file, the mount point is empty for its cleanup, and a later insertion is
mounted by stock with the content unchanged. One difference from hardware
remains: between the pull and stock's reaction, reads of the already open file
still succeed instead of failing with an I/O error.

## USB mass-storage hypothesis

Ghidra's decompilation of `mq_player` mode handler `0x4e5af4`
(`loop_mode_handle_thread`, `all_mode_control.c`) shows that entering storage mode
unmounts the SD before configuring the USB gadget. When leaving storage mode,
`storage_exit_and_remount_tf` closes it, calls `sync`, and invokes storage remove
and add helpers (`0x4c473c(1)` / `0x4c42b8(1)`). This makes **returning from USB
storage** a relevant separate scenario for media-library acceptance.

However, the UI Auto getter has a single established caller: the SD popup timer.
There is no USB-connected requirement in its four-condition predicate, and the
successful live SD cycles ran without a USB mass-storage session. Static remount
code alone does not prove that USB exit emits the required UI notification or
triggers a scan. Physical USB export/eject and simultaneous host/player access
were not exercised; do not infer that scanning runs while a PC owns the card.

## Reproducible acceptance

`tests/integration/storage_check.py --disposable` runs after the existing checks in the isolated
**V2.57** integration stack. It requires the generated CI fixture only, validates
the firmware, and uses read-only UI memory snapshots matched to the binary's
SHA-256, inode and ELF PT_LOAD mapping. Unknown versions are rejected; UI addresses
have not been ported to V2.40. No memory writes or fabricated library rows are used.

```sh
FW_VERSION=2.57 bash ci/integration.sh /absolute/path/to/main_os/ota_v257
```

The test covers cold-cache discovery, the result-dialog and screen-lock gates,
complete remove/add cycles, repeated add, and these exact comparisons:

| Operation | Expected index |
|---|---|
| First insertion | `Кириллица Ё й/CI Tone — Проверка.wav` |
| Add `Новый трек — Ё.wav` | Both files |
| Rename it to `Переименован — й.wav` | New name present, old name absent; total still two |
| Delete the original track | Only `Переименован — й.wav` |
| Repeat insertion after OK | Same single track, another scan worker invocation |

For each completed scan, exact SD paths are compared with `SONG.PATH`, and TCP
`0401` totals/titles are compared across all returned pages. Counts alone cannot
verify a rename. It also checks the backend worker and actual result dismissal.

Events use netlink protocol `15`, unicast **only** to the fingerprinted player PID
inside the selected chroot. They are never multicast or sent to kernel PID zero.
NUL-separated fields are ordered as follows, with a final NUL:

```text
add@/devices/platform/mmc/mmcblk0
ACTION=add
SUBSYSTEM=block
DEVNAME=mmcblk0
```

The parser handles `ACTION` before `DEVNAME`; preserve this order. Sending an add
executes real guest unmount/remount code, so use a disposable volume for these
experiments. The user's interactive stack and media are not test fixtures.

## Reverse-engineering map

All addresses are guest virtual addresses in the exact pinned V2.57 builds.
Ghidra 12.1.3 headless with Java 21 was used alongside MIPS objdump and live probes.

| Binary | Address | Purpose |
|---|---|---|
| `mq_ui` | `0x4618a8` / `0x461c7c` | Auto toggle / getter |
| `mq_ui` | `0x41f108` | `aa22` / `TFCARD_KEY_EVENT_REPORT` handler |
| `mq_ui` | `0x481d8c` / `0x481d10` | SD popup / timer and auto-scan predicate |
| `mq_ui` | `0x481a78` | Changes the shared blocking UI state |
| `mq_ui` | `0x47b034` / `0x47a994` | Scan screen entry / result OK callback |
| `mq_ui` | `0x47cea0` | Lock/display handler, writes `0x8e1735` |
| `mq_player` | `0x46f7b0` / `0x4f3c54` | Uevent listener / SD callback (1 add, 2 remove) |
| `mq_player` | `0x4c42b8` / `0x4c34ec` | Storage add / blkid filesystem discovery |
| `mq_player` | `0x4e5af4` | Mode transition loop, including USB storage exit/remount |

Raw disassembly, Ghidra projects and captures remain ignored. Physical USB testing,
V2.40 auto-scan UI acceptance, and integrating insertion into normal boot remain
separate work; the existing V2.40 integration checks cover the shared mount change.
