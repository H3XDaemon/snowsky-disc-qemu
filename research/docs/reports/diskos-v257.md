# diskOS 1.2.0 on V2.57: review for the boot contract

Source review of [diskOS](https://github.com/b0hemia/diskos) at `0edcfba`
(release 1.2.0, the first with V2.57 support) and one emulator run, 2026-10-02.
Written for the "diskOS as a package" table of the boot-layer contract. Nothing
from diskOS is copied here; paths below are in the diskOS repository. **read**
= read in its sources, **run** = observed in the emulator, **inferred** = neither.

The earlier [V2.40 findings](diskos.md) and the preserved
[UI preview](../../../experiments/diskos/docs/preview.md) are historical; this
page does not change their status.

## What the diskOS image changes on V2.57 (read)

`diskos_installer/imagebuild.py` pins the V2.57 rootfs by SHA-256
(`111e4dd7…`, 80,596,992 bytes; `TESTED_FW` includes 257) and produces a 100,663,296-byte image (768 NAND blocks;
lzo, 131072-byte blocks) written to the start of `mtd2` over mask-ROM USB.

| Part | What it does |
| --- | --- |
| `usr/project/fiio_init.sh` patch | The stock script must match one known hash (identical from V1.95 to V2.57). Inserted before the coredump branch: `export PATH=/opt/diskos/bin:$PATH` (an `rm` guard for the card), OTA helpers, and a branch that starts `/usr/data/mq_ui`, then `/usr/data/mq_player`, when the selector says diskOS and `/tmp/.diskos_ready` exists. The stock start stays as the fallback. |
| `etc/init.d/S96diskos_select` | Runs `diskos-bootprobe`, which maps 4 KiB of `/dev/mem` at `0x10010000` read-only and reads port B `PxPIN` at `+0x100`. Volume Up held = bit 13 low. Result = stored default (Stock if `/usr/data/boot_default_stock` exists) XOR the key. Writes `/tmp/.diskos_boot_select` (`diskos` or `stock`) and a `.why` file; any failure means stock. |
| `etc/init.d/S97diskos_install` | First-boot installer: copies `/opt/diskos/mq_ui` to `/usr/data/mq_ui`, checks it against `/etc/diskos_manifest`, and makes `/usr/data/mq_player` a link to it. |
| `/usr/data/mq_player` link | The UI binary dispatches on `argv[0]`: as `mq_player` it executes the real stock player (keeping that name); otherwise it re-executes itself as bare `mq_ui`, so the stock watch loop's `pgrep -x` matches. |
| Debug Mode (Settings → System) | Off by default. Starts Dropbear (2022.83) over Wi-Fi with a new random password each time through `usr/project/diskos-debug.sh`. |
| Dev variant only | `etc/init.d/S99usbserial`: an always-on USB serial shell. |
| Also added | `/opt/diskos/bin/{diskos-selected,diskos-bootprobe,diskos-launch,diskos-artdec,rm}`, `/etc/diskos_manifest`, OTA key files when OTA is enabled. |

## Keys (read)

- Confirmed in the sources: pinctrl base `0x10010000`, port B `PxPIN` at
  `+0x100`, **bit 13 = Volume Up, active low** (`ui/tools/diskos_bootprobe.c`,
  `payload/S96diskos_select`, and the live "hold Volume Up to close an app"
  check in `ui/main.c`).
- The released word `0xF6EFE127` and the held word `0xF6EFC127` are test
  constants taken from a **V2.40** player (`tests/test_boot_select.py`,
  `ui/tests/boot_probe_test.py`). No V2.57 read is recorded.
- **Bits 14 and 15 are not named anywhere in diskOS.** In the released word
  they are 1, which fits active-low keys, but Volume Down and Play on those bits
  rest on other evidence. Volume Down appears only as the mask-ROM entry chord.

## Emulator run (run)

The UI of `0edcfba` was built from its `ui/` sources with the preview helper
(adapted outside this repository) and started over the stock V2.57 backend:
the stock UI initialised the player first, then the diskOS UI replaced it.

- Without `/tmp/.diskos_boot_select` containing `diskos` the binary executes the
  stock UI: at this release the UI itself insists on the `S96` record.
- With that record the UI starts, draws its home and library screens and takes
  touch. Card features stay closed ("Return to local playback to scan") until a
  **launcher verdict** exists: the UI wants the stock player to have been started
  through its own launcher path (the `/usr/data/mq_player` link).
- With the verdict (written by hand, or produced by starting the stock player
  through that link) the scan found the three generated tracks, and tapping one
  played all three in turn through the stock `mq_player`; pause and resume worked.
- It wrote `SYSCONFIG.WORK_MODE=0` and placed its `rm` guard under
  `/usr/data/diskos/bin`.

Not checked: a cold diskOS boot, the patched `fiio_init.sh`, `S96`/`S97` as
shipped (their records were written by hand), the hardware installer, Wi-Fi,
Bluetooth, USB modes, OTA, Debug Mode. One run per scenario; playback judged by
stock log timing and captured PCM growth, not by waveform.

## Notes for the "diskOS as a package" table

| diskOS image today | Point for the contract |
| --- | --- |
| `mq_ui` in `/opt/diskos`, installed and verified by `S97` | Fits the `ui` package entry. The entry must still end up running as bare `mq_ui`: diskOS re-executes itself for that, so the launcher must tolerate one extra `exec`. |
| `fiio_init.sh` patch | Replaced by boot's `/sbin/mq_ui`. But 1.2.0's UI **checks `/tmp/.diskos_boot_select` itself** and falls back to stock without it (run). As a package it needs that record written for it, or a release that takes boot's mode instead. |
| `/usr/data/mq_player` link and launcher verdict | Not covered by a `ui` launcher alone: the UI enables card features only when the stock player was started through its link (run). Under the contract the player is started by `fiio_init.sh` by name, so either boot provides an `mq_player` launch path a package can observe, or diskOS drops the verdict. This is the open point. |
| `PATH` with the `rm` guard | Part of the `fiio_init.sh` patch; a package gets no say over the stock player's `PATH`. Depends on the previous row. |
| Volume Up check, "Default UI" file | Same pin and polarity as boot's key read (read); redundant under boot's modes. |
| Dropbear and `diskos-debug.sh` | Package files; note Dropbear 2022.83. |
| Dev variant's USB serial shell | Boot's console; two gadget owners must not coexist. |

On a stock-init guest of this emulator the image hooks (`S96`, `S97`) would run
in `rcS` order and `/dev/mem` serves the key read, so a diskOS image is a
candidate for `01_image_rootfs.sh`; that was not tried.
