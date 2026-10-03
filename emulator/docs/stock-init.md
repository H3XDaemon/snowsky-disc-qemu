# Stock init boot, power events and `/usr/data`

Verified on the pinned **V2.57** firmware, 2026-10-02. The default boot is still
the **direct** one: the emulator starts `mq_ui` and `mq_player` itself. This page
describes the opt-in **stock-init** boot, where the guest starts the way the player
does, and the power events and storage options that go with it.

| | Direct (default) | Stock init (`BOOT_MODE=init`) |
| --- | --- | --- |
| Who starts the stock pair | `20_boot.sh` | stock `rcS` → `S98FIIO` → `fiio_init.sh` |
| Who restarts a crashed program | nobody | the stock five-second watch loop |
| Image hooks (`S22*`, `S99*`) | not run | run in `rcS` order; `stop` through `rcK` |
| `/tmp`, `/run` | directories of the work volume | fresh tmpfs at every power-on |
| Guest PIDs, queues, hostname, uptime | the container's | the guest's own namespaces |
| Idle power-off (`poweroff -f`) | needs the viewer or another supervisor | served by the guest's PID 1 |

```sh
./emulator/run.sh boot --init                  # or BOOT_MODE=init in emulator/.env
./emulator/run.sh boot --init --hold volume_up # keys held from power-on, see keys.md
./emulator/run.sh power reboot                 # rcK, then rcS again
./emulator/run.sh power off                    # rcK, guest stays off
./emulator/run.sh power cut --unsynced         # power loss
./emulator/run.sh power on                     # cold start, same /usr/data and card
```

Inside the container the same actions are `BOOT_MODE=init emulator/scripts/20_boot.sh`
and `emulator/scripts/25_power.sh on|reboot|off|cut [--unsynced]|status`.

## How the guest starts

```
container
  └─ emulator.runtime.machine run        supervisor: one per powered guest
       └─ unshare --pid --ipc --uts --time
            └─ emulator.runtime.guest_init   PID 1 of the guest, comm "init"
                 └─ chroot rootfs /etc/init.d/rcS    (qemu-user, as before)
                      ├─ S10mdev … S98FIIO → fiio_init.sh → mq_ui, mq_player, watch loop
                      └─ S99…                          image hooks, in name order
```

`guest_init` is a native program in the place of BusyBox init. It does what the
kernel and the `sysinit` lines of `/etc/inittab` do on the player, then runs the
real `/etc/init.d/rcS` with BusyBox init's environment
(`PATH=/sbin:/usr/sbin:/bin:/usr/bin`, `HOME=/`, `SHELL=/bin/sh`, `USER=root`).
`rcS` itself sources `/etc/profile`, so every `S??` script and `fiio_init.sh` run
with **`PATH=/bin:/sbin:/usr/bin:/usr/sbin`**: a program in `/sbin` is found before
one of the same name in `/usr/bin`.

| inittab `sysinit` step | In the emulator |
| --- | --- |
| `mount -t tmpfs tmpfs /dev`, later mdev | **Not done.** `/dev` keeps the emulator's stubs (`fb0`, input, GPIO, card nodes). Real `null`, `zero`, `full`, `random`, `urandom` nodes are created; `/dev/console` is a plain file. |
| `mount -t proc proc /proc` | The guest PID namespace's own proc; `/proc/sys` is read-only so guest scripts cannot change the shared VM kernel (`printk`, `core_pattern`). |
| `mount -a` (`/tmp`, `/run`, `/dev/shm`, `/sys`, `/dev/pts`) | Fresh tmpfs on `/tmp`, `/run`, `/dev/shm`. `/sys` stays the stub tree; no `/dev/pts`. |
| `hostname -F /etc/hostname` | Set in the guest's UTS namespace (`ingenic`). |
| `/etc/init.d/rcS` | The stock script, unchanged. |
| `console::respawn:-/bin/sh` | Not started. Use `guest_run` (below). |
| `shutdown`: `rcK`, `swapoff`, `umount -a -r` | `rcK` unchanged, then TERM/KILL of every guest process and unmount of the card and `/usr/data`. |

PID 1 also reaps orphans. Without that a killed `mq_ui` stays a zombie that
`pgrep -x mq_ui` still finds, and the watch loop never restarts it.

The guest also gets a **time namespace** whose `CLOCK_BOOTTIME` and
`CLOCK_MONOTONIC` start at this power-on: `/proc/uptime` and `sysinfo()` count
from the boot, as on a player, not from the Docker VM's boot (days). A reboot
starts them again. The wall clock stays the host's
([not adjustable](environment.md#guest-clock-not-adjustable)). `guest_run`
enters that namespace too, so its commands see the same uptime.

### What is stubbed

The init **scripts are stock**. `17_init_stubs.sh` replaces only commands they
call that need the player's kernel or radio (`emulator/scripts/guest-init-stub.sh`;
each stub prints an `[emu-init]` line on the console and succeeds):

| Script | Command | In the emulator |
| --- | --- | --- |
| `S10mdev` | `mdev -df` | No device manager; the stub stays alive so its pidfile is real. |
| `S11module_driver_default` | `insmod *.ko` (eight modules) | No guest kernel. Drivers are the existing shim/stub files. |
| `S21mount_ubifs` | `mount_ubifs.sh userdata /usr/data/` | No MTD/UBI. Mounts the [`/usr/data` image](#usrdata-as-its-own-filesystem) when there is one, else nothing. |
| `S30rpcbind`, `S60nfs`, `S80dnsmasq` | `rpcbind`, `rpc.*`, `exportfs`, `dnsmasq` | Not started: they would serve the Docker network. |
| `S40network` | `ifup -a` / `ifdown -a` | The container owns the interfaces. |
| `S43wifi_bcm_init_config` | (script unchanged) | No `wlan0`: it gives up after its own three-second wait. With [`WLAN0=1`](network.md#emulated-links-isolation-and-shaping) it writes `wpa_supplicant.conf` and `macaddr.txt` as on the player. |
| `S49ntp` | `ntpd` | Already blocked by the network guard; `Starting ntpd: FAIL`. |

Running for real: `S01time_correct`, `S05avahi-setup.sh`, `S20urandom`, `S30dbus`
(a system bus is up), `S50avahi-daemon` (the daemon starts and exits; mDNS is
not served, see [network](network.md)), `S91nqptp`, `S98FIIO` and `fiio_init.sh`. Some of their lines fail the same way on the stock rootfs because
the programs are not in the V2.57 image: `nqptp`, `sshd`, `ssh-keygen`,
`/usr/project/switch_usb.sh`.

`rcK` runs the same scripts in reverse with `stop`. `S98FIIO` has no `stop`, so
the stock pair is ended by the TERM/KILL that follows, as on the player.

### What the supervisor does around the stock programs

The stock programs expect events that hardware delivers. The supervisor repeats
what the direct boot already does, for every start of the pair (also after the
watch loop restarted it):

- **Network**: a fresh `mq_player` subscribes to address events but never asks
  for the existing address. The Docker address is re-announced once per
  `Network detect thread started` line on the console ([network](network.md)).
- **Card**: stock mounts a card whose partition it can enumerate by itself
  (`SDCARD_PARTITION=1`, see [media library](media-library.md#card-image-options)).
  For the default unpartitioned image the supervisor mounts it four seconds after
  the new UI's first frame if stock has not, and keeps it mounted for the next
  20 seconds.
- **Keys** held from power-on are released when the UI is up, or after 60 seconds.
- "The UI is up" means: a process named `mq_ui` (`/proc/<pid>/comm`, what
  stock's own `pgrep -x` matches) holds the touch device and a process named
  `mq_player` holds the key device, and a frame was drawn since power-on. A UI
  started from another file (a boot layer's `ui` package through `/sbin/mq_ui`)
  counts like stock's; a launcher or watcher that only carries the name does not.
- **Lifetime**: `GUEST_TTL` seconds after power-on the guest is cut; `0` is no limit.

### Commands in a running guest

`guest_run` (`emulator/scripts/lib.sh`) joins the guest's namespaces when a
stock-init guest is running, so `pgrep`, `killall`, `/proc` and message queues
agree with the stock programs. Its interface is unchanged:

```sh
source /repo/emulator/scripts/lib.sh
guest_run 10 /bin/ps
guest_run 0 /usr/data/my-service     # 0 = no time limit; dies with the guest
```

A program started this way is part of the guest: `reboot`, `off` and `cut` end it.

## Process identity under qemu-user

| What a guest program reads | Player | Emulator |
| --- | --- | --- |
| `/proc/<pid>/comm`, `pgrep -x`, `pidof`, `killall` | program name | **same** (`mq_ui`, `mq_player`, `init` for PID 1) |
| `/proc/<pid>/exe` through BusyBox or any glibc program | program path | **same in stock-init mode**: `fbshim` reports the guest program instead of `qemu-mipsel-static` (`emu/proc-exe`, `PROC_EXE=1` enables it for a direct boot too) |
| `/proc/<pid>/exe` read by a **static** program | program path | `/usr/local/bin/qemu-mipsel-static`: no shim is loaded into a static program |
| `/proc/<pid>/cmdline` | `argv` | `qemu-mipsel-static`, the program's **full path**, then `argv[0]` and the arguments |
| `argv[0]` inside the program | as started (`mq_ui`) | **same**: the binfmt entry's `P` flag hands the caller's `argv[0]` to qemu |

So BusyBox `start-stop-daemon -S/-K -x <program>` with or without a pidfile works
in a stock-init guest: a second start reports `already running`, and `rcK` stops
the daemon. `-n <name>` works in both modes.

`cmdline` cannot be corrected: the kernel builds it for the interpreter. A
static program that must recognise another process should compare
`/proc/<pid>/comm` (or the name field of `/proc/<pid>/stat`): that is identical
on the player and here. The `P` flag is part of the one `qemu-mipsel`
registration shared by every container of the Docker VM; `10_setup_env.sh`
replaces an entry registered without it, which changes `argv[0]` for other
stacks' next execs as well (an improvement for them too, and nothing in this
repository or its known consumers reads the guest's `argv[0]` through the host).
For a script the reported `exe` is the interpreter as invoked (`/bin/sh`), not the
resolved `/bin/busybox`.

## Static programs and the devices

The guest's `/dev/fb0`, `/dev/input/event0` and `event1` are regular files; no
kernel driver stands behind them. A dynamically linked program gets their
`ioctl`s answered by the preloaded `fbshim` (`/etc/ld.so.preload`). A
**statically linked** program (a boot-layer package, diskOS's UI as built for the
player) never runs the guest's `ld.so`, so it reached the kernel and got `ENOTTY`:
`vinfo: Not a tty`, no touch panel, never ready.

The image's interpreter is Debian's qemu 7.2 rebuilt with one patch
([`emulator/docker/qemu/snowsky-disc-devices.patch`](../docker/qemu/snowsky-disc-devices.patch)):
while the guest marker `/emu/qemu-devices` holds `1`, qemu itself answers the
`ioctl`s of **regular files at those paths** — the same geometry as `fbshim`
(360×360×32, three sub-buffers, `ingenicfb`), `FBIOPAN_DISPLAY` publishing
`emu/fb-live` for the viewer and reported back by `FBIOGET_VSCREENINFO`,
`FBIOBLANK` accepted; for the input nodes `EVIOCGNAME` from the sysfs stub
(`cst816t`, `x2000_key`), `EVIOCGVERSION`, `EVIOCGID` (I²C / host bus),
`EVIOCGBIT` (`EV_KEY`+`EV_ABS` with `BTN_TOUCH` and the five axes the
emulator sends; the key codes of `keys.md`), `EVIOCGABS` (0..359 for the panel's
position axes, `EINVAL` on the key device, as the kernel answers), `EVIOCGKEY`
and the other state reads (nothing held), `EVIOCGRAB` and the setters accepted.
Events are read from the files as before (`inject.py`, `keys.py` append them).
Character devices, other files and dynamically linked programs are untouched;
the shim still answers first for them.

- `QEMU_DEVICES=1` (default, `emulator/.env`) writes the marker at setup and
  every power-on; `QEMU_DEVICES=0` leaves the kernel's `ENOTTY` (the previous
  behaviour). `QEMU=/usr/bin/qemu-mipsel-static` selects Debian's unpatched
  interpreter altogether.
- The binfmt entry follows the chosen interpreter: setup replaces an entry whose
  `interpreter` line differs. The kernel opened the interpreter at registration,
  so after an image rebuild it may still hold the previous binary: setup runs the
  static probe `/emu/devprobe` (`emulator/tests/guest/devprobe.c`) through the
  entry and re-registers once if the devices are not answered. An image built
  without the stage reports `QEMU_DEVICES=1 but … lacks the device patch`.
- Firmware-free: `emulator/tests/test_devices.py` runs the probe under
  `qemu-mipsel-static -L <sysroot>`; the stock-init scenario below runs it in the
  live guest and flips the marker.

The patch also makes `getsockopt(SO_ERROR)` return guest errnos
([limits](limits.md#socket-error-numbers)). What it does not do: a static program
still reads `qemu-mipsel-static` from `/proc/<pid>/exe` (table above), and the
audio interposers (`asndshim`, `tinyshim`) remain preload-only, so a static
program that opens the DAC itself is not covered.

## Power events

| Event | Command | On the player | `rcK` | What survives |
| --- | --- | --- | --- | --- |
| Clean reboot | `power reboot`, or guest `reboot` | `reboot` | yes | `/usr/data`, card |
| Clean power-off | `power off`, or guest `poweroff` | `poweroff` | yes | `/usr/data`, card |
| Forced power-off | guest `poweroff -f` (stock idle power-off) | the same call | no | everything written (it syncs first) |
| Power loss | `power cut` | battery removed | no | everything the guest had written |
| Power loss, volatile writes lost | `power cut --unsynced` | battery removed | no | only what had reached the `/usr/data` image |
| Cold start | `power on` | Power key | — | starts from the stored state |

- A guest program's `kill -TERM 1` / `kill -USR2 1` (BusyBox `reboot` and
  `poweroff` without `-f`, also from a static program) reaches the guest's PID 1
  and runs the clean path. The shared kernel is never asked to reboot.
- A reboot is a new power-on: new namespaces, PIDs from 1 again, empty `/run` and
  `/tmp`, no message queues from the previous boot.
- `cut` kills the guest's PID 1; the kernel then kills every process of that PID
  namespace at once. Nothing in the guest runs another instruction.
- `cut --unsynced` needs the `/usr/data` image. Right after the kill, while dirty
  pages are still only in memory, the image file is copied; that copy (what had
  reached the "flash") replaces the image. Its journal is replayed with
  `e2fsck -p`; a copy that needs more than that is discarded and the machine
  state says `unsynced data kept`. The card is not treated this way: everything
  written to it survives.
- The viewer's Power button and `99_stop.sh` stop a stock-init guest as a power
  cut (without `--unsynced`), the same "all processes end" meaning they have in
  the direct boot. `Device.service_requests()` leaves a stock-init guest's
  `emu/power-request` to its PID 1.
- Machine state is `emu/machine.json` (`state`, `boots`, `reason`); the console of
  the current run is `/work/console.log`, the supervisor's own log `/work/machine.log`.

## `/usr/data` as its own filesystem

On the player `/usr/data` is the 83 MiB `userdata` MTD partition under UBIFS and
is empty in the squashfs. By default the emulator keeps it as a directory of the
work volume. With **`USERDATA_MB`** (for example `83`) set at setup,
`10_setup_env.sh` creates `/work/userdata.img` once: an ext4 filesystem of that
size behind the guest block node `/dev/ubi1_0`. From then on the image **is**
`/usr/data` in both boot modes; delete the image (with the guest off) to go back.
An existing directory `/usr/data` is not migrated: the image starts empty and is
seeded like a fresh volume.

An 83 MiB image gives about 73 MiB of filesystem and 70 MiB free. The player's
UBIFS reports a different (also smaller than 83 MiB) size; choose `USERDATA_MB`
for the free space you want to test against.

| | UBIFS on the player | ext4 image here |
| --- | --- | --- |
| `write()` without `fsync` | buffered; lost on power loss until written back (about 5 s write-back, up to 30 s) | same class of behaviour: journal commit every 5 s, delayed allocation up to 30 s. Only visible with `power cut --unsynced`. |
| `rename()` over a file | atomic; the new content must be `fsync`ed first or the file can be empty after power loss | atomic; ext4 additionally flushes the data on rename-over (`auto_da_alloc`), so a missing `fsync` can go unnoticed here |
| `fsync` of the directory after `rename` | needed for the rename to survive | needed as well, but a journal commit within 5 s hides its absence |
| Full filesystem | `ENOSPC`; free space is an estimate (compression, write-back budget) | `ENOSPC` at an exact block count; no compression |
| Wear, bad blocks, bit flips, torn pages | real | not modelled |
| After power loss | journal replay on mount | journal replay (`e2fsck -p` on the copy, then on mount) |

A passing power-loss test here shows that the durable state was synced and that
recovery reads it back. It does not prove correct `fsync` ordering on UBIFS.

`SDCARD_KEEP=1` makes `10_setup_env.sh` keep an existing card image instead of
rebuilding it from the media folder, so what the guest wrote to the card survives
a new setup. `reboot`, `off`, `cut` and `on` never rebuild either store.

## A rootfs from an image

`01_image_rootfs.sh <image>` (or `./emulator/run.sh up-image <image>`) extracts a
squashfs rootfs image, optionally zero-padded to the flash partition size, in
place of the OTA chunks. The image must be built on the selected stock firmware:
the product version and the six pinned binaries are validated before the rootfs
is accepted, and a rootfs is never replaced. Setup then applies the usual shims,
stubs and key patch on top. Use a separate `WORK_VOLUME` for every image.

```sh
WORK_VOLUME=snowsky-disc-image USERDATA_MB=83 SDCARD_KEEP=1 \
  ./emulator/run.sh up-image /absolute/path/to/rootfs-image.bin
./emulator/run.sh boot --init
```

Files the image adds in `/etc/init.d` and `/sbin` take part in the boot exactly
as on the player: `S22*` runs after `S21mount_ubifs`, `/sbin/mq_ui` is what
`fiio_init.sh` starts.

## Limits

- No guest kernel: no modules, MTD/UBI, mdev events, USB gadget, Wi-Fi radio or
  Bluetooth.
- Stock's "Reset all" completes only here (it ends in `reboot`) and only with
  `WLAN0=1`; see the [report](../../research/docs/reports/reset-all.md).
- BusyBox init itself does not run; `guest_init` follows its documented order
  and signals. `respawn` entries and the serial console are absent.
- Guest mounts are visible to the container (no mount namespace): tools that
  read the rootfs from outside keep working, and a power cut leaves kernel
  mounts that the next power-on removes.
- One stock-init guest per rootfs. Privileged Docker with `unshare` is required
  (the existing requirement).

## Validation

`CI_SCENARIO=stock-init bash ci/integration.sh <ota_v257>` builds a disposable
guest with an 83 MiB `/usr/data` image and checks, with two generated init hooks
and a static MIPS pin probe:

- power-on keys seen by the static program at `S22` and released after boot;
- a static program sees the framebuffer and both input devices (setup's
  `/emu/devprobe`), its pan reaches `emu/fb-live`, and `QEMU_DEVICES=0`
  (marker `0`) restores the kernel's `ENOTTY` without a reboot;
- `S21` mounted the image before the `S22` hook; hook `PATH`;
- the pair started by `fiio_init.sh`, `mq_ui` first; names, PID 1, hostname;
- `start-stop-daemon -x` refuses a second start; `/proc/<pid>/exe`;
- `mq_ui` killed → both programs restarted by the stock loop (2.5–3 s observed),
  listeners and the card back;
- reboot: hook `stop` in reverse order through `rcK`, empty `/run` and `/tmp`,
  `/usr/data` and card content kept;
- `cut --unsynced`: no `rcK`, synced file kept, unsynced file lost, cold start;
- guest `poweroff -f` served without a viewer and without `rcK`;
- clean power-off, then a direct boot on the same volume.

Firmware-free unit tests cover the pin word, the launcher options, namespace
selection in `guest_run`, the stubs and the lifecycle state handling.
