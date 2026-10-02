# Handoff: stock-init guest, power events and power-on keys

For **snowsky-disc-boot** and **snowsky-disc-web**, 2026-10-02. What the emulator
now provides for accepting a boot layer on a guest, how to call it, and which
service-side workarounds it replaces. Details live in the linked emulator pages;
this note is the map.

Everything here is opt-in. A guest prepared and booted the previous way behaves
as before, and the interfaces other repositories import are unchanged:
`emulator.runtime` (`keys`, `peripherals`, `boot_ready`), `emulator/scripts`
(`lib.sh` and the numbered scripts), `firmware.tools.firmware_inventory`,
`controller.fiio_link`, `research.diagnostics` (`probe_keys`, `player_memory`)
and `ci/cleanup.sh`. Additions to them are listed under
[Interface changes](#interface-changes).

## New commands, flags and variables

| What | Inside the container | Host launcher |
| --- | --- | --- |
| Boot through stock `rcS` / `fiio_init.sh` | `BOOT_MODE=init emulator/scripts/20_boot.sh` | `./emulator/run.sh boot --init` |
| Keys held from power-on | `BOOT_KEYS=volume_up,play` for `20_boot.sh` / `25_power.sh on` | `boot --hold volume_up,play` |
| Arm keys for the next power-on | `python3 -m emulator.runtime.gpio arm play` | `./emulator/run.sh keys arm play` |
| Hold / release / show pin levels | `python3 -m emulator.runtime.gpio hold\|release\|show` | `./emulator/run.sh keys …` |
| Cold start | `emulator/scripts/25_power.sh on` | `./emulator/run.sh power on` |
| Clean reboot (`rcK`, then `rcS`) | `25_power.sh reboot` | `power reboot` |
| Clean power-off (`rcK`) | `25_power.sh off` | `power off` |
| Power loss | `25_power.sh cut [--unsynced]` | `power cut [--unsynced]` |
| Machine state | `25_power.sh status` (JSON) | `power status` |
| Rootfs from an image built on stock | `emulator/scripts/01_image_rootfs.sh <image>` | `./emulator/run.sh up-image <image>` |
| `/usr/data` as an 83 MiB filesystem | `USERDATA_MB=83` at the first `10_setup_env.sh` | `USERDATA_MB=83` in `emulator/.env` |
| Keep the card image across setups | `SDCARD_KEEP=1` | same |
| No guest lifetime limit | `GUEST_TTL=0` | same |

Reference: [stock init, power events and `/usr/data`](../../emulator/docs/stock-init.md),
[keys held at power-on](../../emulator/docs/keys.md#keys-held-at-power-on).

## Keys at power-on

- The guest's `/dev/mem` is a sparse file with one word: GPIO port B `PxPIN` at
  `0x10010100`. `open("/dev/mem", O_RDONLY|O_SYNC)` and `mmap` of 4096 bytes at
  offset `0x10010000` work for a static program. Released value `0xF6EFE127`;
  bit 13 Volume Up, 14 Volume Down, 15 Play, active low.
- `BOOT_KEYS` (or armed keys) are low before the first guest instruction and are
  released when the UI is ready, at most 60 seconds after power-on in a
  stock-init guest. Armed keys apply to one power-on.
- The same state drives the stock `pb13`/`pb14` ioctl path, so a Volume button
  held in the viewer is visible in `/dev/mem`.
- Key names: `volume_up`, `volume_down`, `play_pause` (alias `play`).

## Stock-init guest and a guest from an image

- `rcS` runs every `S??*` in order with BusyBox init's environment; `rcS` itself
  sources `/etc/profile`, so hooks and `fiio_init.sh` see
  **`PATH=/bin:/sbin:/usr/bin:/usr/sbin`** (not the bare init `PATH`). `/sbin`
  still precedes `/usr/bin`: an image's `/sbin/mq_ui` is what `fiio_init.sh` starts.
- `S98FIIO` and `fiio_init.sh` are real: `mq_ui` first, `mq_player` two seconds
  later, then the five-second watch loop. Killing `mq_ui` brings both back in
  2.5–3 seconds.
- An image's `S22*` runs after `S21mount_ubifs` (with `/usr/data` mounted) and
  before `S98FIIO`; `S99*` after it. `rcK` calls `stop` in reverse order.
- At `S99` time `mq_ui` is not running yet: `S98FIIO` only backgrounds
  `fiio_init.sh`.
- The card is not mounted before the stock programs start; it appears a few
  seconds after the UI is up. A boot stage that needs the card must wait for it.
- `/proc/<pid>/comm` is the program name. `/proc/<pid>/exe` names the guest
  program **for BusyBox and other dynamically linked readers**, so
  `start-stop-daemon -S/-K -x` and pidfile checks work. A **static** program
  still reads `qemu-mipsel-static` there, and `cmdline` always starts with it:
  compare `comm` instead (identical on the player).
- Use `guest_run` for commands in a running guest: it joins the guest's
  namespaces. A program started with it is ended by reboot, power-off and cut.
- `01_image_rootfs.sh` accepts a squashfs or a zero-padded partition image built
  on the selected stock firmware (validated by the six pinned binaries). Use a
  separate work volume per image.

Checked on 2026-10-02 with `disc-boot-v257-review-only.bin` (sha256 `a83d4a43…`,
build `0265b5caadda+changes`), `USERDATA_MB=83`:

| Scenario | Result |
| --- | --- |
| Plain stock-init boot | `/run/disc-boot/boot.json`: `mode platform`, `reason default`, `keys.read true` |
| `BOOT_KEYS=volume_up` | `mode stock`, `reason key`, `volumeUp true` |
| `BOOT_KEYS=play`, package in `.disc/boot/install/service/` | `reason recovery`; `result.json` on the card with `installed true`; slot `a` populated; service `ready` |
| UI launch | `/sbin/mq_ui` ran `/usr/bin/mq_ui` through `fiio_init.sh`'s `PATH` |
| `cut --unsynced` right after the install, then `on` | `state.json` files readable, `unconfirmed` counted up, service `ready` again |

That run is evidence for the emulator features, not an acceptance of the boot layer.

## Reboot, power loss, cold start

- `reboot` and `off` go through the image's and stock's `stop` actions. A guest's
  own `reboot`/`poweroff` (also from a static program: `kill -TERM 1`,
  `kill -USR2 1`) do the same.
- Stock's own shutdown is `poweroff -f`: it syncs and powers down **without**
  `rcK`. Idle power-off, the empty battery and a long Power press all take that
  path, on the player as here. Do not rely on `stop` for durability.
- `cut` kills every guest process at once. With `--unsynced` the `/usr/data`
  image additionally loses whatever had not reached it (ext4: up to 5 s of
  metadata, up to 30 s of unsynced file data). The card keeps everything.
- Every power-on has empty `/run` and `/tmp`, new PIDs and no stale message queues.
- `/usr/data` (image or directory) and the card survive all four events and
  container restarts; only `10_setup_env.sh` rebuilds the card (unless
  `SDCARD_KEEP=1`) and nothing recreates `/usr/data`.

## Limits

- ext4 is not UBIFS: a passing power-loss test shows that durable state was
  synced and recovery reads it back, not that `fsync` ordering is right for
  UBIFS (`rename` over a file is safer on ext4). See the comparison table in
  the stock-init page.
- `/dev` is not a fresh tmpfs, there is no mdev and no kernel: modules, MTD/UBI,
  USB gadget, Wi-Fi and Bluetooth are absent. Stubbed commands print `[emu-init]`.
- BusyBox init itself does not run; a native PID 1 follows its order and signals.
- One `qemu-mipsel` binfmt registration is shared by all containers of the
  Docker VM; its flags must not be changed.

## Interface changes

Additions only; nothing was renamed or removed.

- `lib.sh`: `guest_run` joins a running stock-init guest's namespaces (unchanged
  otherwise; TTL `0` is no limit). New: `guest_init_pid`, `board_reset`,
  `guest_view_direct`, `userdata_attach`, `userdata_detach`, `userdata_mount`,
  `image_loops`.
- `16_network.sh`: new actions `reannounce` and `wait`.
- `emulator.runtime.keys.Device`: stopping a guest also ends a stock-init
  machine; `service_requests()` does nothing while a stock-init guest is alive
  (its PID 1 serves the request). The boot script timeout is 180 s.
- `emulator.runtime.peripherals.Peripherals.snapshot()` has a new `boot_keys`
  key; new `set_boot_keys()`.
- New modules: `emulator.runtime.gpio`, `machine`, `guest_init`.
- `ci/cleanup.sh` also detaches a `/usr/data` image.
- Fixed: setup/cleanup on a fresh volume could detach another container's
  `/work/sdcard.img` loop device.

## Revision to pin

Pin the merge commit of the pull request that carries this note. Until it is
merged, the branch head is `codex/boot-layer`.
