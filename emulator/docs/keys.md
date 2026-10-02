# Physical buttons

Controls are available on V2.40 and V2.57 (default). For version-aware read-only
probes and the V2.57 address map, see [DIAGNOSTICS.md](../../research/docs/diagnostics.md).
Historical addresses below refer to V2.40.


Implemented and tested on 2026-09-11. The viewer now has **Volume −, Volume +,
Play / pause, Power / lock**. These replace the four misleading legacy buttons below.
The audit findings are retained as the explanation for the fix.

## Using the controls

- Volume: single click, double click, or hold. Assignments remain in the stock app under
  **Settings → System settings → Custom volume settings**. No config database or guest
  memory writes are used by the viewer.
- Play / pause: short click toggles playback. Stock long/double play gestures have no
  playback action; the viewer deliberately does not invent one.
- Power: short click sleeps/wakes the screen. Hold **1.8 s** to stop the guest; click
  while off to boot it again (readiness-based, see [VIEWER.md](../../viewer/docs/usage.md)). The viewer
  and container remain running.
- Buttons also accept Space/Enter when focused. Volume holds start after 650 ms and
  repeat every 200 ms; the double-click window is 280 ms. These are emulator timings,
  not measured physical-driver timings.

Power-off is intentionally a **host-managed guest stop**, not firmware `0x108`:
firmware standby policy/shutdown animations are not emulated. Only processes whose
`/proc/<pid>/root` matches this rootfs are signalled. Raw `0x108` is rejected by the API.
The shared boot/stop scripts use the same scoped stop helper, not a container-wide qemu kill.
The guest's own idle-poweroff is also confined: `fbshim` intercepts libc `reboot`, writes
`emu/power-request`, and the viewer stops only this guest. Without a running viewer the
kernel reboot is still blocked; the request waits for the supervisor. This is not a
security sandbox for arbitrary direct syscalls or unrelated binaries.
V2.57 USB power now follows the existing viewer cable switch through stock
sink-role/ADC detection and inhibits idle power-off, without changing the user's
idle setting. Display timeout and the separate Sleep timer are independent.
See [power/reconnect validation and limits](idle-power.md).

After installing these changes, restart the guest and viewer once:

```sh
./emulator/run.sh boot
./emulator/run.sh view
```

Then reload the page. `boot` installs the shim through setup; a browser reload alone
cannot replace a shim already loaded into a guest process.

## Keys held at power-on

A key that is already down when the player powers on produces no input event.
Boot-stage programs read its **pin level**: GPIO port B input register `PxPIN`
(`0x10010100`, pinctrl base `0x10010000` + `0x100`), active low, through an
`mmap` of `/dev/mem`. Bit 13 is Volume Up, 14 Volume Down, 15 Play. With no key
down the word is `0xF6EFE127` (read on a player, V2.40, 2026-08-13). Bit 13 is
confirmed by diskOS's sources and stock's `pb13` path; bit 14 only by stock's
`pb13`/`pb14` pair; bit 15 and the word on V2.57 are unconfirmed
([diskOS review](../../research/docs/reports/diskos-v257.md#keys-read)).

The guest's `/dev/mem` is a sparse regular file that holds this one word, so a
**static** program, which no preload shim can reach, reads the same levels as
the stock `pb13`/`pb14` GPIO ioctl path. One state drives both
(`emulator/runtime/gpio.py`): a Volume button held in the viewer is low in
`/dev/mem` too.

```sh
./emulator/run.sh boot --hold volume_up,play     # down from before the first guest instruction
./emulator/run.sh keys arm play                  # held at the NEXT power-on (viewer Power, power on)
./emulator/run.sh keys hold volume_down          # down until `keys release`
./emulator/run.sh keys show                      # {"word": "0xF6EFE127", "held": [], "armed": []}
```

Inside the container: `BOOT_KEYS=volume_up,play` for `20_boot.sh` / `25_power.sh on`,
and `python3 -m emulator.runtime.gpio …`. The viewer accepts
`POST /peripheral {"name": "boot_keys", "keys": ["volume_up"]}` and reports the
armed keys as `boot_keys` in `/device.json`.

Keys held from power-on are released when the UI is ready (60 seconds at most in
a [stock-init](stock-init.md) guest); armed keys apply to one power-on. Names are
`volume_up`, `volume_down` and `play_pause` (`play` is accepted). The Power key
is not on this port and is not modelled as a pin.

## Implementation and verification

- `viewer/static/keys.js` classifies physical gestures. `emulator/runtime/keys.py` injects their custom codes,
  maintains active-low volume GPIO state and manages guest-only power. Cancellation,
  lost focus, pointer loss and a 1.5 s server-side hold timeout prevent stuck keys.
- `emulator/scripts/15_controls.sh` initializes GPIO, backlight, touch-controller and LCD stubs.
  `fbshim.c` handles only the relevant GPIO/device ioctl requests; other pins retain
  their original failure behavior. The viewer blanks the screen at brightness 0 and
  rejects touchscreen actions until wake; physical media/volume controls remain available.
- DAC attenuation writes are mirrored into `emu/dac-left` and `emu/dac-right` and applied
  by Web Audio, independently per channel. PCM/WAV capture remains unchanged, before the
  hardware volume stage. See [AUDIO.md](audio.md).
- `fbshim` observes framebuffer `mmap`/`memcpy` and records the last-written buffer in
  `emu/fb-live`. This fixes the stale-frame problem when both buffers change between polls.
  It delegates actual memory operations to the guest libc, with no build-host libc dependency.

### Idle CPU (2026-09-12)

The stock `echo_loop_key` thread expects blocking evdev reads. Our `event0` is an
append-only regular file: at EOF, `read(fd, buffer, 16)` returns zero immediately,
and the stock loop retries without sleeping. On V2.57 this thread alone consumed
99.6% of one core; a two-second `strace -c` sample recorded 33,163 reads (tracing
itself slows the loop). The viewer and `mq_ui` each used only a few percent.

`fbshim` delegates `read` to the stock libc's exported `__read` alias, preserving
its error/cancellation handling. Only a positive-length read returning EOF on the
exact `/dev/input/event0` path sleeps for 5 ms before returning. Data already queued,
touch `event1`, regular files and audio reads have no added wait. A key arriving
during this sleep waits at most one polling interval, plus host scheduling delay;
the existing 120 ms pulses and 200 ms hold repeats are unchanged. No firmware
addresses or binary instructions are changed by this fix.

An eight-second V2.57 sample after the fix measured the key thread at 0.9% and
`mq_player` overall at 1.9% of one core. An idle `docker stats` snapshot dropped
from about 108% to 10% with the viewer connected. These are local measurements,
not CPU limits; decoding and animated screens can still use more CPU.

For diagnosis, run `ps -L -p <player-pid> -o pid,tid,pcpu,stat,wchan:24,comm` inside
the container, then `timeout -s INT 2 strace -c -p <key-tid>` for a short sample.
The Docker image includes `strace`. Integration measures the idle key thread and
rejects sustained CPU above 25% of a core, then verifies physical controls normally.

Clean V2.40 and V2.57 integration passed with this shim: idle-key CPU check, physical
single/hold volume, media play/pause, screen sleep/wake, stock library scan, TCP/WS,
and a bit-exact PCM/source comparison. One concurrent V2.40 run timed out waiting
for WS pause before reaching the CPU check; a separate rerun passed without code
or timeout changes. The cause of that intermittent WS timeout is not established.

### Functional checks

Verified live: volume single and repeated hold events; play state **3 → 1 → 2**;
screen flag **1 → 0 → 1** with black viewer frame and HTTP 409 for touch while asleep;
guest power-off and browser-button boot while the container/viewer stay alive.
While paused, volume **115 → 114 → 115** changed the browser output gain
**0.37584 → 0.35481 → 0.37584** in both channels.

Assignments were changed through the app: Single press → Switch track stopped volume
changes; Double press → Adjust volume made a browser double-click change **116 → 115**;
Long press → Switch track stopped held-volume changes. The original **1 / 0 / 1**
assignments were restored and read back after reboot. With a loaded SD queue, the default
double-click next action started a different-rate track (48 kHz → 44.1 kHz), without
changing volume. A complete matrix of every track/position/gesture combination was not tested.

Automated checks:

```sh
python3 -m ci.unit
node --test viewer/tests/test_keys.js viewer/tests/test_audio_browser.js
# Read-only runtime state, inside the container (V2.40 addresses only):
python3 -m research.diagnostics.probe_keys
```

16 Python and 7 JavaScript tests pass, including gesture timing, repeat cancellation,
stale-GPIO reset, unsafe-code rejection, guest shutdown requests, gain/mute conversion
and the browser audio graph.

The final test exposed stock idle-poweroff stopping the container (exit 130, not OOM).
After installing the reboot guard, loader binding diagnostics confirmed BusyBox's
`reboot@GLIBC_2.0` resolves to `fbshim`. Executing guest `/sbin/poweroff -f` then produced
`[fbshim] reboot blocked; guest shutdown requested`, left Docker/viewer alive, and stopped
only the guest. Browser Power successfully started it again. The raw `0x108` viewer API
remains disabled; invoking firmware shutdown is not needed for the manual power control.

## HTTP API

`POST /button`, same-origin `Content-Type: application/json`:

```json
{"name":"volume_down","gesture":"single"}
```

Names: `volume_up`, `volume_down`, `play_pause`, `power`. Gestures: `single`, `double`,
`hold`, `end`, `cancel` (Power supports single/hold/end/cancel). During a volume hold,
send `hold` every 200 ms, then `end`; the watchdog releases it if updates cease.
`GET /device.json` reports running, screen_on, transition and error.
The diagnostic `/key?k=volume_up|volume_down|play_pause|power` sends a single stock event;
`?code=<int>` accepts only the safe known codes, not shutdown. Use POST for power lifecycle.

## Historical audit: old viewer buttons (replaced)

| Viewer label | Sent code | Actual behavior / observed result |
|---|---|---|
| ▲ menu-up | `0x107` | Volume-up hold/repeat gesture, not menu navigation; no volume change in the test because the GPIO gate fails. |
| ▼ menu-down | `0x106` | Volume-down hold/repeat gesture; same missing GPIO support. |
| ▶ play | `0x10c` | Prints `KEY_VALUE_PLAY_KEY_L`; this dispatcher branch has no playback action. |
| ⏯ play/pause | `0x103` | Screen sleep/wake, not media play/pause; missing brightness path prevents sleep. |

The old viewer sent a fixed 120 ms press/release. It had no physical-button
single/double/hold recognizer. The firmware reader forwards the custom event code and
value directly; **waiting longer between the same two events does not turn a single-click
code into a long-press code at this layer**. Those gesture codes must already be classified
when written to `event0`.

## Correct dispatcher mapping

These are firmware-specific codes, not standard Linux `KEY_VOLUMEUP` etc. Injection uses
16-byte MIPS `input_event` records with `EV_KEY`, value 1 then 0, and `SYN_REPORT`.

| Code | Meaning | Setting / prerequisite |
|---|---|---|
| `0xfb` / `0xfc` | Volume-button + / − single press | `KEY_SINGLE_CLICK_SLE` |
| `0x10a` / `0x10b` | Volume-button + / − double press | `KEY_DOUBLE_CLICK_SLE` |
| `0x107` / `0x106` | Volume-button + / − hold/repeat | `KEY_LONG_PRESS_SLE`; GPIO `pb13` / `pb14` must read 0 |
| `0xfa` | Media play/pause | Calls `FUN_00424b2c(0, 0)`; verified live |
| `0x103` / `0x109` | Screen sleep/wake | Brightness and touch-controller support needed |
| `0x108` | Standby/shutdown path, depending on configuration | Static verification only; **do not casually inject** |
| `0x10c` / `0x10d` | Play-button long/double labels | Log-only branches in this dispatcher |

The app's **Custom volume settings** menu configures Single press, Double press and Long
press separately: value **1 = Adjust volume**, value **0 = Switch track**. In the track
branch, the + button selects previous and − selects next. Observed settings were
`single=1, double=0, hold=1` in both the database and live memory. Therefore the viewer
should emit physical-button **gesture codes**, letting the firmware apply these settings,
not translate all presses directly into volume commands.

Settings callbacks are `FUN_004e88c8`, `FUN_004e895c`, `FUN_004e89f0`: they update bytes
`0x0082e9d2`, `0x0082e9d3`, `0x0082e9d4` and persist config indices `0x35`, `0x36`, `0x37`.
The settings path was subsequently exercised through the app as described above.

## Runtime evidence

With `mq_player` running, injection through `tools.stream.key()` produced:

- `0xfc` then `0xfb`: logical volume **119 → 118 → 119**.
- `0xfa` twice: player state **3 → 1 → 2**, starting playback then pausing.
- Current viewer `0x106`, `0x107`: volume stayed 119.
- Current viewer `0x10c`: player state stayed 3.
- Current viewer `0x103`: player state stayed 3 and screen-on stayed 1; the brightness
  open failed in the log.

Readback locations: volume byte `0x0082e98c`, screen-on byte `0x0082e995`, key-enable byte
`0x0082e9c1`, and player-state word at `*(uint32_t *)0x008321f4 + 0x48`. Addresses refer to
the V2.40 guest. When reading `/proc/<qemu-pid>/mem`, derive the guest-base offset from
that process's maps; do not reuse another run's PID or assume a fixed host mapping.
This initial audit tested logical volume only; subsequent DAC/Web Audio checks are above.

Temporary screenshots/probes belong in ignored `shots/`; this document is the persistent
record and does not depend on those files.

## Hardware blockers found in the audit (now addressed)

**Held volume buttons:** `FUN_00407d64` (`gpio_get_value`) calls ioctl `0x2000477a` with
the GPIO name. The old `/dev/gpio` stub opened, but the ioctl failed. The dispatcher
requires `pb13 == 0` for `0x107` and `pb14 == 0` for `0x106`, so it rejects these gestures.
The implementation now provides per-button active-low state, coordinated with press,
hold/repeat and release. Other GPIO requests are not globally forced to succeed.

**Screen sleep/wake:** `FUN_004e0350` first opens
`/sys/bus/platform/drivers/pwm-backlight/backlight/backlight/backlight/brightness`.
Failure returns before sleep helper `FUN_004de1bc`, which handles `/dev/cst816t`, sends
UI state and clears the screen-on flag. Wake helper is `FUN_004dde48`. The emulator
now provides the brightness path, relevant touch/LCD ioctls, and viewer blanking/input
behavior; displaying raw framebuffer bytes alone did not simulate a powered-off screen.

**Power:** the `0x108` branch really does reach standby/shutdown logic. Shutdown helper
`FUN_004de32c` stops services, kills UI processes and invokes `poweroff -f`. Raw `0x108` was
**not executed** during the audit: qemu-user shares the privileged container's kernel.
A safe power control must confine shutdown to the emulated player lifecycle. Turning an
already stopped guest back on requires host orchestration, not another input event.
The earlier claim that event0 has no power event and necessarily needs an MCU stub was wrong.

## Remaining fidelity limits

Physical-driver timing, the complete track-navigation matrix, stock standby/shutdown
policy and MCU behavior remain outside the verified implementation. Viewer power-off
does not execute the stock shutdown helper; its terminal libc reboot call is now guarded,
but the raw event remains disabled to avoid unneeded firmware shutdown side effects.

## Reverse-engineering entry points

`FUN_004d9974` opens the key device; `FUN_004d9840` reads events and calls
`(*DAT_0088cc50)(code, value)`. `FUN_004e3410` registers dispatcher `FUN_004de6fc`.
The existing key-enable patch is described in [RE.md](../../research/docs/methods.md). It gets events past one
gate; it does not emulate the missing GPIO, brightness, gesture or power behavior.
