# Guest environment presets

What the emulated player "is" before it boots: its battery gauge, serial number,
USB cable, stock settings, and how long it lives. Every preset is opt-in; without
them a guest is prepared exactly as before. Verified on V2.57, 2026-10-02.

Presets are environment variables of the setup and boot scripts. Put them in
`emulator/.env` (Compose passes them to the container) or give them to the
scripts directly (`docker exec -e NAME=value …`).

| Variable | Read by | Meaning | Default |
| --- | --- | --- | --- |
| `GUEST_TTL` | boot | Seconds until the guest is stopped; `0` is no limit | `1800` |
| `POWER_WATCH` | boot (direct) | `1`: serve the stock power-off request without a viewer | `0` |
| `USB_POWER` | setup, boot | `1`/`0`: cable state; empty keeps the stored state | empty |
| `BATTERY_PROFILE` | setup | `legacy` or `device` gauge layout | `legacy` |
| `BATTERY_CAPACITY`, `BATTERY_VOLTAGE_UV`, `BATTERY_TEMP` | setup | percent, microvolts, tenths of °C | `100`, `4200000`, `250` |
| `DEVICE_SN` | setup | 14 letters/digits written to `/usr/data/fiio/sn.txt` | not written |
| `SETTINGS_PROFILE` | setup | Named `SYSCONFIG` preset | `emulator` |
| `SETTINGS` | setup | `COLUMN=INT,…` on top of the profile | empty |
| `JACK` | setup, boot | `3.5`, `4.4` or `none`: [analog-output model](audio.md#analog-output-jack-model); `off` removes it; empty keeps the stored state | off |
| `FPU_GUARD` | every `guest_run` | `reject`, `warn` or `off`: programs that would hit the player's [FPU trap](limits.md#fpu-guard) | `reject` |
| `EMU_CPUS` | Compose | Fraction of one CPU for the whole container, `0` = no limit ([slowing the guest](limits.md#slowing-the-guest)) | `0` |

Card (`SDCARD_MB`, `SDCARD_FS`, `SDCARD_PARTITION`, `SDCARD_KEEP`), `/usr/data`
(`USERDATA_MB`), boot mode (`BOOT_MODE`, `BOOT_KEYS`) and network (`NETWORK`,
`WLAN0…`) have their own pages: [media library](media-library.md#card-image-options),
[stock init](stock-init.md), [network](network.md#emulated-links-isolation-and-shaping).

## Lifetime and explicit stop

`GUEST_TTL` bounds leaked qemu processes. `GUEST_TTL=0` removes the limit in both
boot modes: the guest runs until `./emulator/run.sh stop`, a power event, or its
own power-off. A program started with `guest_run 0 …` has no limit either.
A stock-init guest's limit counts from its power-on and ends as a power cut.

## Power-off without a viewer

Stock idle power-off, the empty-battery shutdown and a long Power press all end in
BusyBox `poweroff -f`. The shim turns that into `emu/power-request`
([idle power](idle-power.md)); something outside the guest must then stop the
guest's processes.

| Boot | Who serves the request |
| --- | --- |
| Stock init | The guest's PID 1, always ([stock init](stock-init.md)). |
| Direct, viewer running | The viewer (`Device.service_requests()`), as before. |
| Direct, `POWER_WATCH=1` | `emulator.runtime.power_watch`, started by `20_boot.sh`. |
| Direct, neither | Nobody: the kernel reboot is blocked but the pair stays half shut down. |

The watcher has no HTTP server and no lifetime: it runs until `99_stop.sh`,
`kill_guest` or the next boot. It can be used on its own:

```sh
python3 -m emulator.runtime.power_watch start    # stop | status | run
```

State is `/work/power-watch.json` (`pid`, `served`, `last`), the log
`/work/power-watch.log` (`Power request: stopping` / `completed`). After a served
request the guest is off; boot it again explicitly. `Device.service_requests()`
keeps its interface for callers that poll it themselves.

## USB cable

`USB_POWER=1` at setup or boot plugs the cable before the first guest instruction,
and the state is stored: later boots keep it until `USB_POWER=0`, the viewer's
USB connector, or `Peripherals.set_usb()` change it. Stock detects it natively
(ADC and sink role, see [idle power](idle-power.md)), so idle power-off is
inhibited from the start. USB data, storage and DAC modes are not modelled.

## Battery

Stock reads `capacity` and `temp` of `/sys/class/power_supply/cw221X-bat`.

| Layout | Attributes |
| --- | --- |
| `legacy` (default) | `type=Battery`, `status`, `online`, `capacity`, `health`, `present`, `technology`, `temp`, `voltage_now` |
| `device` | As a V2.57 player: `type=Mains`, `capacity`, `current_now`, `cycle_count`, `health`, `present`, `technology`, `temp`, `voltage_now`; **no** `status` or `online` |

Values can be changed while the guest runs:

```sh
./emulator/run.sh battery set --capacity 4          # also --voltage (µV), --temp (0.1 °C)
./emulator/run.sh battery show
```

Observed with the `device` layout: the UI shows the new percentage (red at 3 %);
at 0 % with the cable unplugged stock shows its shutdown countdown and requests
power-off about 40 seconds later; with the cable plugged it keeps running.
`current_now` and `cycle_count` are constants; charging curves are not modelled.

## Serial number

A fresh emulated `/usr/data` has no `sn.txt`, and stock reports an empty `SN`.
`DEVICE_SN=25090112345678` writes the file at setup (kept afterwards; remove the
variable to leave an existing file alone). `nb.txt` is not created.

## Stock settings profiles

`10_setup_env.sh` creates `sysconfig.db` by a priming boot, then applies a
profile from `emulator/settings/`:

| Profile | Changes to the stock-created row |
| --- | --- |
| `emulator` (default) | `LOCAL_IMG_ANIM=0`, `BATTERY=100`, `LANGUAGE=$LANG_CODE` — straight to the main menu |
| `factory` | None: the player after a firmware install. `LANGUAGE=100` shows the first-boot language wizard and `LOCAL_IMG_ANIM=1` enables the boot-logo animation. On V2.57 the animation does not hide the screen behind it: the wizard appeared in both boot modes, and with a valid `LANGUAGE` the main menu did ([emulation](emulation.md)). Stock's own "Reset all" writes the same two values ([report](../../research/docs/reports/reset-all.md)) |
| `always-on` | `emulator` plus `LIGTH_ON_TIME=7` (display never times out) |

`SETTINGS="MEMORY_PLAY=1,POWER_SAVE=0"` adds single integer columns. Unknown
columns, non-integers and a running guest are refused; nothing is written then.
A profile is a small JSON file; add one beside the others for a new preset.

```sh
./emulator/run.sh settings list
./emulator/run.sh settings show                     # the current row as JSON
./emulator/run.sh stop && ./emulator/run.sh settings apply --profile always-on
```

Applying a profile later changes only the columns it names; it does not restore
the others to stock. For a true factory state use a new work volume with
`SETTINGS_PROFILE=factory`. Column meanings are in [settings](settings.md).

## Guest clock: not adjustable

The guest's **wall clock** is the host's. (Its uptime is its own: a stock-init
guest runs in a time namespace, so `/proc/uptime`, `CLOCK_BOOTTIME` and
`CLOCK_MONOTONIC` count from its power-on, see [stock init](stock-init.md).)
An offset or an "unsynchronised" wall clock was investigated and is **not** provided:

- qemu-user passes time calls to the shared kernel; there is no guest clock.
  A time namespace offsets only the monotonic clocks, and the container must
  not set the VM's clock.
- A preload shim could shift `time()`/`clock_gettime()` for dynamically linked
  stock programs, but the kernel still compares absolute timeouts
  (`pthread_cond_timedwait`, `sem_timedwait`, `mq_timedreceive`) with the real
  clock, so stock timers would break; and static programs get no shim at all.

To test wrong-time handling, give the program under test its own offset option,
or check the behaviour on a player that has never synchronised (its clock starts
at 2026-01-01 through `S01time_correct`).

## Validation

`CI_SCENARIO=environment bash ci/integration.sh <ota_v257>` checks on a fresh
volume: the `factory` row is exactly what stock created; setup presets (device
gauge, serial, cable, one settings override); `timeout 0` guests; native cable
detection, also on a second boot without the preset; an empty battery powering
the guest off through the headless watcher; and a boot afterwards.
