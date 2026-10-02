# Remote connections, idle power and reconnect (V2.57)

Scope: the fingerprinted V2.57 stock player under qemu-user, local TCP 12100 and
our optional WebSocket adapter. This is not a measurement of physical Wi-Fi
suspend, iOS background behavior or wake-on-LAN. Screen-off, transport failure
and a stopped guest are different states.

## Screen sleep is not power-off

With idle power-off disabled (`POWER_SAVE=0`), a paused TCP connection survives
135 seconds without application requests, including the stock two-minute display
timeout (`LIGTH_ON_TIME=3`). Fresh settings and now-playing reads still work on
the same connection. Closing it and opening a new connection with a fresh `0599`
handshake preserves the paused track and HTTP current queue.

The same sequence works over WS. WS ping/pong is adapter-level liveness, not a
FiiO Link command or simulated user interaction. Neither connection/readback nor
remote Play turns the screen on: Play resumes audio with the display still off.
A local short Power gesture wakes the display. A clock lockscreen can remain;
backlight-on is not proof that the UI is unlocked.

This setting is a **disposable test fixture**, not a new emulator default and
not a remotely exposed setting helper. The normal interactive database is never
changed by this test. With idle power-off enabled, playing keeps the idle counter
at zero; pausing with the screen off allows it to grow.

## Static timer contract

Exact V2.57 addresses, selected only after full binary fingerprint validation:

| Field | Player address | Width / meaning |
| --- | --- | --- |
| Screen | `83a755` | byte, 1 on / 0 off |
| Work mode | `83a759` | byte, 8 local |
| Idle limit | `83a75c` | word, `POWER_SAVE`; 0 disables |
| UI inactivity marker | `83a760` | byte, received through local `0807` |
| Native USB detected | `83a768` | byte, 1 inhibits idle power-off |
| Sleep limit | `83a76c` | word, independent sleep timer |
| Connected | `898950` | word, stock TCP client accepted |
| Sleep / idle counters | `899140` / `899142` | unsigned 16-bit |
| Previous inactivity marker | `899147` | byte |

UI `472ed8` reads LVGL inactivity time. At 61 seconds it sends local `0807=1`;
after activity it sends `0807=0`. It separately sends local `0654=0` on display
timeout. Player table entry `838c60` maps `0807` to wrapper `415180`, callback
slot `83a620`, handler `4f19a8`, which stores that marker. Both `0807` and `0654`
are **absent from the TCP allowlist**; they are not remote wake/keepalive APIs.

Power thread `4f44d0` wakes once per second. In the reviewed local-mode path:

- Disabled idle limit, active scan, playing state and several separate hardware
  flags bypass/reset the idle counter. Connected flag `898950` is **not** a gate.
- Screen on **and** marker 0 reset both idle counter and previous marker.
- Otherwise a marker mismatch adds 60 and assigns previous marker **1** (not a
  copy of the new marker); then the loop adds 1. If idle counter is strictly
  greater than the configured limit, it calls shutdown `4e6f0c`.
- A separate sleep counter/limit can also invoke shutdown. It is zero in these
  fixtures and must not be confused with idle power-off.

Consequently, `POWER_SAVE=300` is not a guarantee of five minutes after the last
network operation. Read traffic is not LVGL input. A marker falling to 0 while
the display remains off can also keep the mismatch branch active. Do not derive
a UI countdown from elapsed connection time or treat every silent `0202` as a
network fault. The final-stop case is different again: [TRACK_END.md](../../docs/protocol/track-end.md).

Shutdown `4e6f0c` releases the local player, tears down network components,
stops UI/watchdog and invokes BusyBox `poweroff -f`. The existing shim confines
the libc reboot call to `emu/power-request`. Without a running viewer the kernel
reboot is still blocked, but guest process existence does not establish a healthy
player. The viewer's `Device.service_requests()` consumes that request and stops
only processes chrooted into this guest. It never reboots the Docker VM/host.
In the TCP and WS acceptance runs, a settings read still replied after the intercepted
shutdown request but before supervisor cleanup. That reply did not mean the
released audio engine was usable. The test then required complete guest stop,
failure of the old connection and a fresh refused TCP connection before an
explicit local Power boot. After boot both transports read settings, the
three-track catalog and the retained two-track queue anew. TCP also returned
now-playing metadata; WS did not, and the reboot log reported `get list song idx
fail!`. The repeated TCP recovery also returned no metadata, with internal state
3 and the suppression flag 1, then successfully played and paused a newly
selected album. This is not a transport-dependent distinction.
The final WS run returned full metadata with wire state 2 while the independent
runtime snapshot was already stopped (state 3, suppression flag 1). Messages
and memory reads are not atomic; metadata presence is not evidence of resumed
audio. The explicit new play/pause check passed on both transports.

Stock resume helper `423ebc` (`comm_play_memory`) can return without selecting
anything when the stored music ID is not positive. A retained HTTP queue does
not guarantee a restored decoder or full `0202` response. As in the EOF path,
`4252ac` suppresses metadata while context offset `+0x50` is nonzero. Recovery
acceptance now checks that gate independently when `0202` times out, requires
fresh successful settings/mode reads, then performs a **new explicit** album
selection and play/pause cycle. It never counts a timeout alone as success or
automatically replays the pre-shutdown command. The controller should show
unavailable current-track state rather than inventing metadata from the queue.

With `POWER_SAVE=300`, Sleep off and display timeout 120, both runs reached idle
counter 301 and released playback about 310–312 seconds after the last explicit
local wake. The confined reboot request followed at about 315–317 seconds. Those
are qemu observations, not a hardware timing guarantee or a count from the last
network request: read-only settings polling continued every five seconds.

## USB power: physical observation and native emulation

Owner's physical DISC report (2026-09-16): Idle poweroff **5 min**, Sleep **off**,
Screen off time **2 min**; with USB power connected, idle power-off does not
occur. This is user-reported hardware evidence, not an emulator measurement.

The earlier viewer cable switch only wrote `emu/usb-connected` and battery sysfs
`status=Charging/Discharging`. Those files alone did **not** drive the native
USB detector. Static `adc_check` (`4f21e0`) first reads OTG role via `4e6820`
from `/dev/aw35615`; in sink role 1 it reads a 32-bit sample from ADC channel 1
(`/dev/jz_adc_aux_1`, opened/enabled by `4e22f4`). A sample >500 sets native
USB flag `83a768=1`; <100 clears it. The charger path additionally accesses
`/dev/sgm41513`. The power loop directly tests the native flag, not the cable
graphic or battery status string.

`emulator/scripts/15_controls.sh` now creates these guest-only nodes for V2.57 and enables
the narrowly scoped `fbshim` ABI with `emu/usb-power-supported=1`. Legacy V2.40
gets marker 0, not an unreviewed enablement. The shim supplies:

- One-byte AW35615 sink role 1, even unplugged, so ADC1 can detect removal.
  Only the sink-role ioctl `20004e26` succeeds; OTG source switching stays unsupported.
- Four-byte little-endian ADC1 samples: 600 plugged / 0 unplugged, derived from
  the existing cable byte. These are threshold fixtures, not calibrated voltage.
- ADC enable ioctl `2000410b` for channels 0–3, allowing sequential stock
  initialization to reach channel 1. Other ADC channel reads fail with ENODEV;
  no invented headphone/balanced-jack readings or uninitialized EOF samples.
- Charger enable ioctl `20004d27` only; unknown requests retain failure behavior.

The firmware itself sets/clears its USB flag and applies the idle-power policy.
No database override, binary patch, direct flag write, real host USB, gadget,
storage/DAC mode or charging curve is added. The viewer updates the cable byte
in place to avoid a transient empty-file disconnect. Cable state persists across
guest/viewer restarts. Connecting and removing power were both observed to wake
the stock display and reset UI inactivity; the display may later time out
normally while the player stays powered.

To use the updated shim in an existing interactive setup, run `./emulator/run.sh boot`
and `./emulator/run.sh view`, then reload the page and click the USB connector at the
bottom of the skin. As with any normal boot/setup, use the intended `emulator/sdcard/`
contents. A page reload alone cannot update the shim in an already running
guest. Clicking USB while the guest is stopped records cable state for the next
explicit Power boot; it does not implement hardware power-on-by-cable.

`CI_SCENARIO=idle-usb` uses the stock idle limit 300, sleep off and display index
3, pauses playback, toggles off/on/off and verifies native flag/counter readback.
The plugged interval lasts 310 seconds with no idle shutdown, including a dark
display. Unplugging must restore idle counting. A short native flag check also
runs in ordinary `full` integration's peripheral stage. Long acceptance status
is recorded below; no hardware current/charging measurement is implied.

### USB storage mode is not modelled

Entering stock's USB storage mode unmounts the card and configures a USB gadget
through configfs; leaving it syncs and runs the card remove/add helpers
([media library](media-library.md#usb-mass-storage-hypothesis)). There is no UDC
or gadget under qemu-user, and a guest must not mount the VM's configfs, so the
mode switch cannot be driven here. The card side alone can be approximated with
the viewer's SD removal and insertion, which give stock the same remove/add
events. On a player the card's return was observed to answer `0202` only with
`a60a/0010`; that sequence has not been reproduced in the emulator.

## Three independent transport timers

| Layer | Policy | What it establishes |
| --- | --- | --- |
| Stock TCP | Observed alive after 135 seconds of application silence with idle power-off disabled | No observed 120-second stock Link idle cutoff in that scenario |
| Local WS adapter | 20-second WS heartbeat; no Link-idle read deadline | WS liveness is not a firmware idle-power inhibitor |
| Opt-in host LAN bridge | 120 seconds without bytes **in either individual direction**, plus bounded total service lifetime | An adapter timeout, not stock shutdown; upstream notifications alone do not keep a silent phone's direction alive |

The LAN policy is unchanged. Firmware-free loopback tests shorten only the test
deadline, verify cleanup even with server notifications, then reconnect to the
released control slot. The test exposed a cancellation race in nested `wait_for`
tasks; directly awaited reads/drains inside `asyncio.timeout` now let cleanup
finish reliably. No LAN interface is opened by the automated idle tests.
Real phone background/reconnect behavior remains unvalidated. By owner decision
on 2026-09-16, revisit it only if a concrete error appears; it is not a pending
manual gate for this emulator checkpoint. New LAN exposure still requires fresh,
bounded approval.

## Controller rules

1. Keep one owner of the stock single-client connection. On disconnect, mark
   cached playback/queue state stale; do not reset the UI to an invented stopped
   state or increment/decrement a cached queue index.
2. Reconnect with bounded backoff, a new transport and fresh handshake, then read
   settings, current playback and HTTP queue. A successful socket alone is not
   a completed handshake. A read timeout alone does not prove power-off.
3. Never replay a previous toggle, track selection, seek, reset, file mutation
   or partially acknowledged operation after reconnect. Resolve fresh state and
   await a new user action when the old result is uncertain.
4. Do not use periodic fake touches, writes or playback toggles to defeat the
   user's idle policy. Read-only polling may maintain an adapter connection but
   is not a verified way to prevent firmware shutdown.
5. Once this emulator is stopped, a Link command cannot boot its absent process.
   Offer an **explicit local Power** action through the existing viewer lifecycle,
   then reconnect/read state anew. Do not silently restart a physical device or
   label this host-managed boot as stock remote wake.

## Reproduction and validation

```sh
CI_SCENARIO=idle FW_VERSION=2.57 bash ci/integration.sh "$OTA_257"
CI_SCENARIO=idle-usb FW_VERSION=2.57 bash ci/integration.sh "$OTA_257"
# Optional local evidence only; never upload logs as public CI artifacts:
CI_SCENARIO=idle CI_LOGS="$PWD/work/idle/logs" CI_SHOTS="$PWD/shots/idle" \
  FW_VERSION=2.57 bash ci/integration.sh "$OTA_257"
```

This opt-in scenario runs **instead of** the normal always-awake protocol suite.
It creates its own Compose stack/volume and generated three-track media, with no
published ports; validates the six firmware fingerprints; updates only reviewed
settings while the guest is stopped; scans via stock Link; and performs explicit
local lifecycle actions. It never edits live firmware memory, shortens stock
timers, modifies the interactive volume or requires image-only changes.

The long `idle` scenario is separate from `full`: the latter deliberately keeps
the display awake to isolate its other protocol assertions. Run the idle scenario
explicitly when changing connection/power behavior. Before allowing natural
shutdown, it checks BusyBox's dynamic reboot binding to the existing shim.
USB changes are encoded in the tracked setup/shim, not an ad-hoc image edit.
Existing Dockerfile dependencies suffice; normal Compose defaults, published
ports and security confinement are unchanged.

Local V2.57 validation (2026-09-16): focused `idle` with both phases passed TCP/WS
135-second quiet screen-off, reconnect, screen-off play/pause, natural shutdown,
guest-only stop, explicit local boot and new selection/play/pause. Separate
`idle-usb` passed the 310-second powered interval, off/on/off native detection,
guest-libc read ABI and resumed unplugged counting. Firmware-free checks passed
257 Python and 23 JavaScript tests plus four shim builds. Dedicated library-reset
acceptance and the final full ordinary V2.57 regression passed (exit 0), including
PCM, controls, protocol/settings/formats/EOF, scan/reset/SD and preference checks.
This is local validation, not a hosted release gate. Failure history is preserved in
[the research checkpoint](../../research/docs/reports/2026-09-19-protocol-checkpoints.md#idle-reconnect-and-usb-power-investigation-2026-09-16).
