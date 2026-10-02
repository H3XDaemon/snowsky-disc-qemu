# "Reset all" and the MCU (V2.57)

Static analysis of the pinned V2.57 `mq_ui` and `mq_player`, 2026-10-02, with a
runtime confirmation on a disposable stock-init guest the same day. Addresses are
guest virtual addresses of those exact builds. **read** marks facts read from the
binaries, **run** what was observed in the emulator, **inferred** the rest.

## Result

- Reset all has **no MCU step**. Nothing in `mq_player` or `mq_ui` can reach an
  MCU: the SPI layer in `mq_player` is dead code (read).
- Under emulation it did nothing because its first statement fails:
  `open("/usr/data/wpa_supplicant.conf", O_RDWR|O_TRUNC)` without `O_CREAT`
  (read). On the player `S43wifi_bcm_init_config` creates that file once `wlan0`
  exists; the emulator had no `wlan0`, so the file never existed.
- With an emulated `wlan0` in a [stock-init](../../../emulator/docs/stock-init.md)
  guest the file exists and Reset all runs to its `reboot` (run). No MCU model is
  needed, for this or for work-mode switching.

## What Reset all does

UI (`mq_ui`, read): Settings item "Reset all" → dialog `465260` → confirm handler
`46512c` shows "Please wait..." and sends the local frame `0800000C0003` to the
`player` queue. It starts no timer and waits for no reply; on a player the dialog
ends with the reboot.

Player (`mq_player`, read): local table entry `0800` → handler `4f05d8`, in order:

1. Open `/usr/data/wpa_supplicant.conf` for rewrite; on failure print
   `open /usr/data/wpa_supplicant.conf failed!` and **return**. This is the only
   gate; every later result is ignored.
2. Rewrite that file: `ctrl_interface=/var/run/wpa_supplicant`, `update_config=1`,
   `country=NZL`.
3. `rm -rf /usr/data/fiio/wifi`.
4. Drop the library tables (SONG, MY_LOVE, custom playlists, queue lists).
5. Bluetooth cleanup over D-Bus (bounded 3 s calls), `killall -9 bluetoothd bluealsa`,
   `rm -rf /usr/data/storebluetooth`, `rm /usr/data/bluetooth.db`.
6. Remove `/usr/data/fiio/db/theme.db` and `/usr/data/fiio/db/song.db`.
7. `4ea368`: 42 `UPDATE SYSCONFIG` statements, close the player, power the DAC
   down, stop the watchdog, `hciconfig hci0 down`, notify the UI (`aa03`),
   `sleep(2)`, backlight 0, `system("reboot")`.

`/usr/data` afterwards:

| Path | Effect |
| --- | --- |
| `wpa_supplicant.conf` | rewritten (three lines, country `NZL`) |
| `fiio/wifi/`, `storebluetooth/`, `bluetooth.db` | removed |
| `fiio/db/song.db`, `fiio/db/theme.db` | removed; stock recreates them on the next boot |
| `fiio/db/sysconfig.db` | kept; row reset to stock values, among them `LANGUAGE=100` (first-boot wizard), `LOCAL_IMG_ANIM=1`, `VOLUME=40`, `POWER_SAVE=300`, `LIGTH_ON_TIME=3` |
| `fiio/db/dic.db`, `fiio/sn.txt`, logs, everything else | untouched |

The final `reboot` is BusyBox `reboot` without `-f`: it signals PID 1, so `rcK`
runs. In a stock-init guest the guest reboots and shows the language wizard (run).
In a direct-boot guest there is no init to signal, so the pair would be left shut
down (inferred, not run).

The remote `0800` (TCP) is the same broad reset. Do not use it in place of the
library reset `0621` ([library reset](../../../docs/protocol/library-reset.md)).

## The MCU code that is never called

`mq_player` contains `spi_handler.c` (read): `/dev/spidev0.0`, a frame of
`FC FE`, length, two command bytes, payload, an 8-bit additive checksum, `FE FC`,
and a command-name table (`GET_FIRMWARE_VERSION`, `SET_FACTORY`, `SET_MCU_POWER`,
`SET_POWER_DOWN_TO_MCU`, …). No call, branch or data pointer in a loaded section
reaches its entry points; `mq_ui` has no MCU, spidev or tty strings. The
`SYSCONFIG` columns `MCU_OTA_FAILED_TIME` and `ARM_VERSION` appear only in the
schema. `/usr/bin/cmd_mcu` exists but neither program nor any init script uses it.

Work-mode switching (`0657` → `4f1110`) saves the volume, closes and reopens the
player with the mapped input mode, stores `INPUT_MODE`/`WORK_MODE` and replies
`a607`: no MCU exchange (read). Standby is `killall -9 mq_ui` plus `poweroff -f`.

## Reproduce

Disposable guest only: this is a factory reset of that guest's `/usr/data`.

```sh
CI_SCENARIO=card-network bash ci/integration.sh /absolute/path/to/main_os/ota_v257
```

The scenario boots a stock-init guest with `WLAN0=1`, sends the UI's own frame on
the guest's `player` queue, and checks the reboot, the reset settings row, the
rewritten `wpa_supplicant.conf` and the recreated `song.db`.
