# Emulation deep-dive

How the Snowsky Disc firmware is run without the hardware, and every non-obvious
thing that had to be true before the UI would reach its main screen.

## Stack

Current runtime profiles are V2.57 (default) and V2.40. The blocker investigations
below describe how support was established; raw function addresses refer to the
original V2.40 analysis unless labelled otherwise. Use [DIAGNOSTICS.md](../../research/docs/diagnostics.md)
for version-aware addresses and [VIEWER.md](../../viewer/docs/usage.md) for current interaction.

```
macOS/Linux host
  └─ Docker (privileged Linux VM)
       └─ qemu-mipsel-static (user-mode)   ← runs the MIPS32 guest binaries
            └─ chroot /work/rootfs         ← unpacked firmware root filesystem
                 ├─ mq_ui       (LVGL GUI, owns POSIX mqueue "ui")
                 └─ mq_player   (audio/backend, owns "player", pushes state to "ui")
```

- **User-mode** qemu (not full-system): we execute the two userland binaries directly;
  there is no guest kernel. Anything the binaries expect from the kernel/drivers we
  fake with sysfs/dev stubs and an ioctl shim.
- The interpreter is Debian's qemu 7.2 **rebuilt** in the image
  (`emulator/docker/qemu/snowsky-disc-devices.patch`; `/usr/local/bin/qemu-mipsel-static`
  links to the build-named `/usr/local/lib/qemu-mipsel-<build>/qemu-mipsel-static` that
  binfmt registers): it answers the framebuffer/input ioctls for **static** programs,
  which load no shim, and translates `getsockopt(SO_ERROR)`. Debian's binary stays at
  `/usr/bin` for `QEMU=/usr/bin/qemu-mipsel-static`. See
  [stock-init.md](stock-init.md#static-programs-and-the-devices).
- `--privileged` is required: qemu-user needs to reserve a large contiguous guest VA,
  binfmt_misc must be writable, and POSIX mqueues must be mountable.

## binfmt_misc — register ONLY mipsel

The guest does `popen()`/`execve()` of other MIPS binaries (`/bin/sh`, `cmd_watchdog`,
`cat …/name`). For those child execs to run, the kernel needs a binfmt_misc handler
that hands MIPS ELFs to qemu.

**Do not** run `qemu-binfmt --reset -p yes` / `multiarch/qemu-user-static --reset`: it
registers *every* qemu interpreter including `qemu-aarch64`, which then intercepts the
host VM's own native arm64 binaries (containerd-shim, unpigz, …) → `exec format error`,
breaking Docker until you restart Docker Desktop. This happened twice.

Instead register a single mipsel entry with a mask that matches MIPS32-LE ELFs and
nothing else (`emulator/scripts/10_setup_env.sh`). The mask ignores ELF bytes 6–15 so it matches
busybox (which sets `EI_ABIVERSION`) as well as glibc binaries. The entry's flags are
`FP`: `F` opens qemu at registration so execs inside the chroot work, `P` hands the
caller's `argv[0]` to qemu (Linux 5.12+ `AT_FLAGS_PRESERVE_ARGV0`), so a guest program
sees the `argv[0]` it was started with, as on the player, instead of its file's path.
A program that re-executes itself until `argv[0]` is a bare name (diskOS's UI does)
looped forever without it. The entry is shared by every container of the Docker VM and
the kernel keeps the interpreter file it opened at registration: setup replaces an entry
registered without `P` or with another interpreter path (the rebuilt qemu's path names
its build), and re-registers once when a static probe shows the kernel still holds a
previous binary.

## The ioctl shim (`emulator/shims/fbshim.c`)

The guest opens `/dev/fb0` and issues framebuffer ioctls, and reads input-device names.
There is no real framebuffer/driver, so an `LD_PRELOAD`-style shim intercepts `ioctl`:

- `FBIOGET_VSCREENINFO` → report 360×360, yres_virtual 1080, 32bpp, XRGB8888 (R@16 G@8 B@0 A@24)
- `FBIOGET_FSCREENINFO` → smem_len = 360·1080·4, line_length = 1440, visual TRUECOLOR
- `EVIOCGNAME` → return the input device name
- all other `0x46xx` fb ioctls (PAN/BLANK/PUT) → return 0 (no-op)
- Volume GPIO `pb13`/`pb14`, touch/LCD sleep/wake and DAC attenuation writes are emulated
  narrowly for physical controls; see [KEYS.md](keys.md).
- Framebuffer `mmap`/`memcpy` calls are observed to publish `emu/fb-live` (the buffer) and
  `emu/fb-flush` (the copying process's PID, the readiness evidence); actual memory
  operations are delegated to the guest libc's `mmap64`/`memmove`.
- libc `reboot` is intercepted for guest BusyBox poweroff/reboot: no shared-kernel reboot,
  only an `emu/power-request` consumed by the viewer's guest-scoped supervisor.
- Empty `read` calls on `/dev/input/event0` wait 5 ms, preventing the physical-key
  reader from spinning on the regular-file stub's EOF. Actual reads delegate to the
  guest libc's `__read`; queued events and other files are not delayed.
- V2.57 USB sink-role/ADC1 reads follow the viewer cable byte, so the stock
  detector controls idle-power inhibition. Narrow device/ioctl gates leave other
  ADC channels unavailable and do not model USB data; see [IDLE_POWER.md](idle-power.md).

The shim is **freestanding** (`-nostdlib`, raw MIPS syscalls). A normal glibc-linked
`.so` fails to load because the host toolchain glibc (2.36) ≠ device glibc (2.29):
`cannot open shared object`. Freestanding + no NEEDED entries sidesteps that.

Two gotchas that were fixed:
- **nan2008**: the device loader is `ld-linux-mipsn8`; the shim's ELF `e_flags` must have
  the nan2008 bit or it is rejected. `build_shims.sh` stamps `0x70001407` at offset 36.
- **fd leak**: the shim logged to `/fbshim.log` on every ioctl and never closed the fd.
  Over the boot animation's hundreds of PAN ioctls this exhausted the fd table, and the
  *next* `mq_open("ui")` failed — which looked like an mqueue bug but was fd exhaustion.
  Fixed by closing the log fd (and not logging on the hot path).

It preloads via `/rootfs/etc/ld.so.preload` (a file the guest ld.so reads), **not**
`LD_PRELOAD`: the env var does not survive the guest's `popen()` children, and the path
must resolve inside the chroot.

`/dev/fb0` is a plain file; qemu maps it with `mmap` and the guest draws into it. See
[TOUCH.md](touch.md) / `emulator/runtime/fb2png.py` for reading it back.

## Blocker 1 — frozen splash: `mq_open("ui")` = EMFILE

`mq_ui` creates the POSIX message queue `ui` (`mq_maxmsg=32, mq_msgsize=8192`); `mq_player`
opens it and pushes UI state. Under emulation `mq_open` failed with **EMFILE** ("too many
open files") even though the process had ~8 fds open.

EMFILE from `mq_open` is not only the fd limit — it also fires on **`RLIMIT_MSGQUEUE`**
exhaustion (bytes of POSIX-queue memory per user). Each queue costs `maxmsg·msgsize` =
256 KB. Guest processes killed with SIGKILL leave their queues allocated in the kernel's
own mqueue instance, which a `mount -t mqueue …` view does **not** list, so
`rm /dev/mqueue/*` never freed them. After a handful of runs the limit was blown.

**Fix:** `ulimit -q 268435256` before launching. (qemu-user 7.2's mqueue passthrough is
otherwise correct — verified a clean glibc test binary creates `/dev/mqueue/qt` fine.)

## Blocker 2 — "battery too low, shutting down" screen

With the queue working, the UI left the splash but showed a battery icon and
`电量过低，倒计时关机 / 19S` (battery too low, shutdown countdown). The fuel gauge is read
from `/sys/class/power_supply/cw221X-bat/capacity`; absent, it reads 0%.

**Fix:** create that sysfs tree with `capacity=100, status=Full, …` (`10_setup_env.sh`).

## Blocker 3 — main screen built but never shown (boot animation overlay)

With a healthy battery the UI went *back* to the SNOWSKY splash and stayed. Tracing showed
`mq_ui` actually **built** the main screen (it opened all `main_screen/main_1/*.png` assets)
— but the boot logo animation (`power_on/opening_*.png`, state flag `power_on_ing`) is an
**infinite-loop overlay drawn on top** of it and never auto-clears under emulation (~17
loops observed). The config key `LOCAL_IMG_ANIM` controls it.

That observation is from the original V2.40 work. **On V2.57 it does not
reproduce** (checked 2026-10-02 in a direct boot): with `LOCAL_IMG_ANIM=1` and
the fresh `LANGUAGE=100` the language wizard is shown, and with
`LOCAL_IMG_ANIM=1` and a valid `LANGUAGE` the main menu is on screen 15 seconds
after boot. Setup sets the flag to 0 on V2.40 only (V2.40 needs it, and it
skips the logo); the `factory` [settings profile](environment.md#stock-settings-profiles)
leaves it at 1. On V2.57 setup no longer writes it: the column is the Settings > Cover
Animation choice (`1` Rotate, `0` Static), and forcing it reset that choice at every
`./emulator/run.sh boot`.

**Fix:** `sqlite3 sysconfig.db "UPDATE SYSCONFIG SET LOCAL_IMG_ANIM=0"` → the overlay is
skipped and the real first-boot flow can proceed. Current setup also presets
English, so the normal flow reaches the main menu without the language wizard;
the wizard appears only with an out-of-range `LANGUAGE` value.

**Catch on a fresh rootfs (two parts):** `/usr/data` is a **separate UBIFS partition** on the
device (`etc/init.d/S21mount_ubifs`) and is *empty* in the squashfs. On hardware the init
scripts `S98FIIO` + `fiio_init.sh` populate it from templates in the read-only rootfs. We
don't run init, so:

1. **Seed `/usr/data`** — most importantly copy the zlog configs
   `usr/project/config/zlog_{player,ui}.conf` → `usr/data/fiio/log/` (and `usr/project/db/*`,
   e.g. `dic.db`, → `usr/data/fiio/db/`). Without the zlog config, `mq_player`'s `zlog_init()`
   fails (`Error: zlog_init`), the backend never starts, and **no `sysconfig.db` is ever
   created** — so on a truly fresh rootfs you're stuck on the splash with an empty
   `usr/data/fiio/db/`.
2. **Priming boot** — even seeded, `sysconfig.db` is created by `mq_player` on first boot with
   `LOCAL_IMG_ANIM=1`. So a throwaway boot creates the DB, then (V2.40 only) we set
   `LOCAL_IMG_ANIM=0`, then boot for real.

`emulator/scripts/10_setup_env.sh` does both automatically. The opt-in
[stock-init boot](stock-init.md) runs the real `rcS`, `S98FIIO` and `fiio_init.sh`
instead; the same seeded and primed `/usr/data` serves both modes. (The language choice and this flag then
persist in the `/work` volume.)

The first-boot **language wizard** is gated on the same DB: it shows only while `LANGUAGE` is
out of range (fresh default 100). `LANGUAGE` is a **0-based index** (switch in mq_ui
`FUN_004776e4`): `0 zh · 1 tw · 2 en · 3 ja · 4 ko · 5 es · 6 it · 7 de · 8 pt · 9 ru`. Setting
any valid value picks the language and skips the wizard; `10_setup_env.sh` presets `LANG_CODE`
(default 2 = English). (Out-of-range codes like 100/102 fall back to Chinese — which is why the
"language index = code − 100" guess was wrong.)

## Blocker 4 — the SD card / File Browser shows nothing

With the main menu reached, opening **Browse files** showed an empty `/tmp/sdcard`. The card
is emulated as a **real FAT block device**, not a bind: `10_setup_env.sh` builds a FAT image
from `./emulator/sdcard`, exposes it as real nodes `/dev/mmcblk0` + `/dev/mmcblk0p1` (`mknod b 7 <loop
minor>` — a symlink to `/dev/loopN` can't be resolved from inside the guest's chroot), and
mounts it at `/tmp/sdcard`. Yet the browser stayed empty.

The cause is in `mq_ui`'s `util/src/mount_storage_dev.c`. Three facts decompiled/observed:

- The card is gated on `system("[ -e /dev/mmcblk0 ]")` (`FUN_004891b8`) — hence the real node.
- `FUN_004147ac` parses `/proc/mounts` for the **exact** mountpoint string `/tmp/sdcard`.
- On startup `mq_ui` **`umount`s `/tmp/sdcard` once** and expects a hotplug handler to remount
  the card (`mount -o iocharset=utf8 /dev/mmcblk0p1 /tmp/sdcard`). On hardware `mdev`/init does
  that on the insert uevent; **under emulation nothing does**, so the mount we set up is torn
  down and never comes back — the browser scans an empty dir.

Two red herrings ruled out along the way: it is **not** a Docker-volume mount-propagation
problem (the guest's own `mount -o iocharset=utf8` runs fine under qemu-chroot even though
`/work` is `private,slave` — a fresh mount under it is `private` and survives), and it does
**not** need a synthetic netlink uevent — the File Browser **re-scans `/tmp/sdcard` live on
entry**, so the card just has to be mounted when you open the app.

**Fix (`sd_mount()` in `lib.sh`, called from `10_setup_env.sh`, the end of `20_boot.sh`, and
`30_tap.sh`):** after the boot-time umount, re-mount `/dev/mmcblk0p1 -o iocharset=utf8` at
**both** the guest rootfs path `…/rootfs/tmp/sdcard` (the content the browser reads) and the
container's own `/tmp/sdcard`. The guest is chrooted, so its `umount /tmp/sdcard` only hits the
rootfs path — the container-path mount survives and keeps the exact `/tmp/sdcard` line
`FUN_004147ac` looks for present across the whole boot. The browser then lists the card and is
navigable all the way to the leaf tracks (`Test Artist / Greatest Hits / *.wav`).

Current setup mounts the guest card **inside chroot**, so the source recorded in
`/proc/mounts` is `/dev/mmcblk0p1`; see the scanner fix below. The viewer now also
supports explicit SD removal/insertion. Boot remounting and insertion-triggered
auto-scanning remain separate operations; see [MEDIA_LIBRARY.md](media-library.md).

## Scanner source-path fix (2026-09-11)

Browse files only needed the mountpoint above; **Update media lib** also checks
that the mount source is accessible inside chroot. The old container-side mount
recorded `/work/rootfs/dev/mmcblk0p1`, which fails that check. `sd_mount()` now mounts
the guest SD **inside chroot**, recording source `/dev/mmcblk0p1`. This fixed the
scanner stuck at zero: the stock scan found four tracks, and the same four appeared
over FiiO Link. Existing old-source mounts are migrated; the container-side helper
mount is retained. See [NETWORK.md](network.md).

## What mq_player sends at boot

Sniffing the `ui` queue (see `research/diagnostics/uisniff.c`) shows the backend push these FiiO-Link
frames right after start (there is **no** explicit "show main" command — the transition is
internal to `mq_ui` once the animation is gone):

| tag | value | meaning |
|-----|-------|---------|
| `aa1d` | `0064` | battery = 100 |
| `a634` | 0 | — |
| `aa24` | `{"volume":120,"brightness":20,"dac_filter":1,…}` | settings blob |
| `a102` | 0 | play state |
| `a712` | 0 | — |
| `a620` | `{"SN":"","NB":"","WIFI_MAC":…}` | device info |
| `aa1c` | 0 | — |
| `a202` | `{"state":2}` | player state |

See [PROTOCOL.md](../../docs/protocol/protocol.md) for the frame format.

## Framebuffer capture

`fb0` = 360×1080×4 (three 360×360 sub-buffers). `mq_ui` does **not** use `FBIOPAN_DISPLAY`;
it alternates drawing to buf0/buf1, so the current screen is the **last-flushed** buffer
(a static screen is not re-flushed, so the other buffer holds a stale frame). `emulator/runtime/fb2png.py`
emits every sub-buffer and prints each one's non-black pixel count. For the actual latest
buffer, use the shim's `emu/fb-live` byte (0/1; 255 = no observation yet), also consumed by
the viewer. Higher pixel count is only a heuristic, not evidence of recency. Pixels are
BGRX and the panel is 180°-rotated, so the converter reverses pixel order.

## Ordering / timing

Start `mq_ui` first (creates `ui`), then `mq_player` (retries `mq_open("ui")`).
Current `20_boot.sh` waits for network listeners, both input devices and a
framebuffer flush by the UI process that holds the touch device (`emu/fb-flush`,
see [stock-init](stock-init.md#what-the-supervisor-does-around-the-stock-programs)),
then remounts the SD before capturing. Input/frame readiness has a 60-second timeout. The historical ~20–24 s boot measurement is not a fixed
startup delay; `./emulator/run.sh boot <seconds>` adds only an optional diagnostic wait.

## Known hardware errors

`WATCHDOG: feed failed`, `adc get voltage failed: Bad file descriptor`,
`gpio_get_value fail` for unemulated pins — from absent hardware; the backend keeps running.
The volume pins and brightness/touch/LCD paths are now handled. A missing brightness path
or failures reading `pb13`/`pb14` indicate an outdated setup/shim and break screen sleep
or held buttons; see [KEYS.md](keys.md). The
initial **`open("/dev/gpio")` must succeed** or `mq_player` aborts with `failed to open
device` before it inits the DAC / pushes UI state (→ stuck splash). So `10_setup_env.sh`
creates 0-byte stubs for `/dev/gpio`, `/dev/jz_adc_aux_0`, `/dev/jz_watchdog` (open works,
later ioctls generally still fail). V2.57 `15_controls.sh` additionally installs
USB-power stubs: ADC enable succeeds for sequential channel initialization,
ADC1 reports cable state, and ADC0/2/3 reads explicitly fail with ENODEV.
Those other sensors are not needed for boot and are not emulated.

## Troubleshooting

- **`fb2png` prints `…-b2 non_black_px=0`** — normal. There are three sub-buffers; `mq_ui`
  only ever draws to buf0/buf1 (alternating), so buf2 stays black. Prefer the
  `emu/fb-live` marker (0/1) or the viewer's `/frame` endpoint for the current frame.
  Non-black counts alone cannot distinguish an old frame from the latest one.
- **`sysconfig.db missing` on the very first `10_setup_env` of a fresh rootfs** — expected
  (see the `/usr/data` catch above); the script seeds `/usr/data` then primes the DB. If it
  still reports missing after priming, check `/work/mq_player.log`.
- **`/work/mq_player.log` = `Error: zlog_init`** — the backend can't init logging because the
  zlog config isn't in `usr/data/fiio/log/`. `10_setup_env.sh` seeds it from
  `usr/project/config/zlog_{player,ui}.conf`; if the seed step didn't run (older checkout),
  `git pull` and re-run, or copy those two files manually.
- **`docker run`/`docker start`/`docker exec` hangs and a new container is stuck in
  `Created`** — the Docker Desktop VM got wedged (often after an earlier OOM or a killed
  `docker` operation left a zombie containerd-shim). Existing containers keep working, but new
  ones won't start. Fix: **restart Docker Desktop**, then `./emulator/run.sh up …` again. Give the VM
  ≥8 GB (two qemu-user MIPS processes plus the popen/`cmd_watchdog` children are memory-hungry;
  running out is what wedges it).
