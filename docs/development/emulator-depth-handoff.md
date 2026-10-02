# Handoff: stock-init guest, power events and deeper emulation

For **snowsky-disc-boot** and **snowsky-disc-server**, 2026-10-02. (The gateway
service moved from snowsky-disc-web, frozen that day, to snowsky-disc-server; the
workarounds named below exist there under the same paths.) What the emulator
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
- **How sure each of these is.** Bit 13 = Volume Up, active low: confirmed in
  diskOS's sources and in stock's `pb13` path. Bit 14 = Volume Down: supported
  only by stock's `pb13`/`pb14` volume GPIO pair. Bit 15 = Play: given in the
  task brief, confirmed by no source in this repository. The released word is a
  read from a **V2.40** player (a diskOS test constant); no V2.57 read exists.
  Confirm bits 14, 15 and the word on a V2.57 player before relying on them
  ([diskOS review](../../research/docs/reports/diskos-v257.md#keys-read)).
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
- The card is not mounted while `rcS` runs. With `SDCARD_PARTITION=1` stock
  mounts it a moment after `mq_player` starts; with the default image the
  emulator mounts it a few seconds after the UI is up. A boot stage that needs
  the card must wait for it.
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

## Guest environment, card, network, audio (later pull requests)

Each of these is opt-in and documented on its own page:
[environment](../../emulator/docs/environment.md),
[card](../../emulator/docs/media-library.md#card-image-options),
[network](../../emulator/docs/network.md#emulated-links-isolation-and-shaping),
[audio](../../emulator/docs/audio.md#output-stream-state),
[limits](../../emulator/docs/limits.md).

| Variable or command | Effect |
| --- | --- |
| `GUEST_TTL=0` | No guest lifetime limit; stop explicitly |
| `POWER_WATCH=1` | Direct boot serves stock `poweroff -f` without a viewer (`emulator.runtime.power_watch`) |
| `USB_POWER=1` | Cable plugged from the first instruction; stored for later boots |
| `BATTERY_PROFILE=device`, `BATTERY_CAPACITY`, `BATTERY_VOLTAGE_UV`, `BATTERY_TEMP`; `battery set` | The player's gauge layout with adjustable values |
| `DEVICE_SN=<14 chars>` | `/usr/data/fiio/sn.txt` |
| `SETTINGS_PROFILE=emulator\|factory\|always-on`, `SETTINGS=COLUMN=INT,…` | Stock settings presets |
| `SDCARD_MB`, `SDCARD_FS=exfat`, `SDCARD_PARTITION=1` | A card like the player's; with a partition stock mounts it itself |
| `Peripherals.set_sd(False, force=True)` | Card pulled while a track plays |
| `WLAN0=1` (+ `WLAN0_STATE`, `WLAN0_ADDR`, `WLAN0_MAC`); `python3 -m emulator.runtime.network link wlan0 …` | Emulated `wlan0` with controllable state and address |
| `NETWORK=isolated`; `python3 -m emulator.runtime.network link …` | Guest with no network; links can appear later |
| `python3 -m emulator.runtime.network shape --rate … --delay … --loss …` | Slow link towards clients |
| `JACK=3.5\|4.4\|none`; `Peripherals.set_jack()` | Stock's own output detection; unplug pauses |
| `/emu/asound/card0/pcm3p/sub0/{status,hw_params}`, `emu/audio-state` | Output stream as on the player; silence vs samples |
| `FPU_GUARD=reject\|warn\|off` | `guest_run` refuses programs that would hit the player's FPU trap |
| `EMU_CPUS=0.25` | Slow the whole container |

Findings worth knowing:

- Stock "Reset all" never involved the MCU; it needs `/usr/data/wpa_supplicant.conf`,
  which exists once `wlan0` does. It runs to its `reboot` in a stock-init guest with
  `WLAN0=1` ([report](../../research/docs/reports/reset-all.md), which lists what it
  removes from `/usr/data`).
- Stock keeps the output stream RUNNING while paused and feeds it zeros: judge
  "playing" by samples or by the open file's read position, not by the stream state.
- qemu 7.2 returns the host errno from `getsockopt(SO_ERROR)` (111, MIPS expects 146);
  use the system call's own `errno`. Fixed in newer qemu; not replaced here.
- The guest clock cannot be shifted; a guest's `avahi-daemon` aborts under qemu 7.2;
  a Docker Desktop container is not on the host LAN.
- [diskOS 1.2.0 on V2.57](../../research/docs/reports/diskos-v257.md): what its image
  changes and what a `ui` package would still need.

## What the service's workarounds can become

| Workaround in snowsky-disc-server | Replace with |
| --- | --- |
| `scripts/runtime/guest_supervisor.py` (polls `Device.service_requests()`, 2 h lifetime) | `POWER_WATCH=1` for `20_boot.sh` in a direct boot (`power_watch start\|stop\|status`; log lines `Power request: stopping` / `completed` are kept; state in `/work/power-watch.json`). A stock-init guest needs nothing. `Device.service_requests()` is unchanged for callers that keep polling. |
| `GUEST_TTL='7200'`, `guest_run 7200 …` | `GUEST_TTL=0`, `guest_run 0 …`, and an explicit `99_stop.sh` / `25_power.sh off` |
| `scripts/runtime/battery_overlay.py` | `BATTERY_PROFILE=device` at setup: the same attribute set. The overlay stays a no-op on top of it. |
| `--card-headroom-mb` and the padding file | `SDCARD_MB=<size>` at setup |
| Manual `Peripherals.set_usb(True)` after every `up` | `USB_POWER=1` at setup or boot |
| `printf '00000000000000' > sn.txt` | `DEVICE_SN=…` at setup |
| `unshare --net` plus a hand-made dummy `eth1` for the offline boot | `NETWORK=isolated` for `20_boot.sh`, then `python3 -m emulator.runtime.network link eth1 --state up --addr 192.0.2.2/24 --gateway 192.0.2.1`; run clients with `ip netns exec disc-guest …` |
| `/api/device` `output: null` | Pass `--asound-dir /emu/asound/card0` in the emulator. The service's profile check accepts only `/proc/asound/cardN`; that path cannot be provided for a static program, so the check needs an emulator exception. |
| `start-stop-daemon -x` checks skipped as "emulated" (`tests/integration/deployment_boot.py`, in the frozen snowsky-disc-web only) | They work in a stock-init guest (`/proc/<pid>/exe` is the program for BusyBox). A static program's own checks should compare `comm`. |
| Hard-float build found only on the device | `guest_run` now refuses it (exit 126) before it starts |

Not replaceable here: wrong-clock tests (the service needs its own offset option),
LAN reachability and mDNS for Local Network Access (a host-side stand-in, see the
network page), USB gadget and storage mode, real memory limits.

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

- `lib.sh`: `guest_run` joins a running stock-init guest's namespaces and an
  isolated guest's network namespace, and first runs the FPU guard (exit 126
  for a trapping program; `FPU_GUARD=warn|off`). TTL `0` is no limit. New:
  `guest_init_pid`, `guest_netns`, `fpu_guard`, `board_reset`, `guest_view_direct`,
  `userdata_attach`, `userdata_detach`, `userdata_mount`, `image_loops`,
  `loop_attach`. `kill_guest` also stops a power watcher. `sd_mount` mounts the
  card's own filesystem type.
- `10_setup_env.sh`: the card is built by `emulator.runtime.card`; its log line
  changed. The settings update and the gauge files are written by
  `emulator.runtime.settings` and `emulator.runtime.battery` (same defaults).
  The card is mounted again after the priming boot.
- `15_controls.sh`: also resets the `/dev/mem` word, `emu/proc-exe`, the
  `/emu/asound` tree and `emu/audio-state`; applies `USB_POWER` and `JACK`.
- `16_network.sh`: new actions `reannounce` and `wait`; `prepare` honours an
  isolated guest and `WLAN0`. The guard also lets stock read `ip addr show wlan0`.
- `emulator.runtime.keys.Device`: stopping a guest also ends a stock-init
  machine; `service_requests()` does nothing while a stock-init guest is alive.
  The boot script timeout is 180 s.
- `emulator.runtime.peripherals.Peripherals`: `snapshot()` has new keys
  `boot_keys` and `jack`; new `set_boot_keys()`, `set_jack()`, `jack()`;
  `set_sd(inserted, force=False)`. The SD netlink port is the player's PID in its
  own namespace. Error text for a non-block card node changed slightly.
- `emulator.runtime.audio`: new `output_state()`.
- New modules: `emulator.runtime.gpio`, `machine`, `guest_init`, `battery`,
  `settings`, `power_watch`, `card`, `network`, `abi`.
- `ci/cleanup.sh` also detaches a `/usr/data` image.
- `emulator/docker/Dockerfile` adds `exfatprogs`: rebuild the image for
  `SDCARD_FS=exfat` (everything else works with the previous image).
- `firmware/v2.57.json`: new acceptance scenarios and `diagnostics.output`; the
  identity fields are unchanged.
- Fixed: setup/cleanup on a fresh volume could detach another container's
  `/work/sdcard.img` loop device; attaching an image failed when the container
  lacked the node of a newly created loop device.

## What was run

Every pull request of the series passed the firmware-free suite and its own new
scenario on its branch head, and the top of the series (`328b2a5`) passed
`full`, `stock-init`, `environment`, `card-network` and `audio-guards`.

The series touches the cable state (`USB_POWER`) and idle power-off (the power
watcher, a stock-init guest's PID 1), so the two long power scenarios of
`firmware/v2.57.json` matter. They were **not** run during the series. They were
run afterwards, on 2026-10-02, on the merge of the three follow-up branches
(#42, #43, #44) with `2.x` at `6ed3168`, together with everything above:
firmware-free suite, `stock-init`, `environment`, `card-network`, `audio-guards`,
`full`, **`idle`** (TCP and WS lifecycle, natural shutdown, explicit boot) and
**`idle-usb`** (310 seconds paused with the cable in, unplug restores idle
counting) all passed. Both power scenarios use the direct boot with default
presets; idle power-off of a stock-init guest is covered by `stock-init` (guest
`poweroff -f`) and the empty-battery case by `environment`, not by a 300-second
idle run in those modes.

## Revision to pin

Merges into `2.x`: stock-init and power events #37 `4f6069f`; environment
presets #38 `a7fc408`; card, network and Reset all #39 `0045d21`; audio, jack
model and guards #40 `b9c5323`; diskOS review and this note #41 `6ed3168`.
Each is usable on its own in that order. **Pin `6ed3168`** for the whole series,
or the merge of the follow-up fixes (#42, #43, #44) once they are in.
