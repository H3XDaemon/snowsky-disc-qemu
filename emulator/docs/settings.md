# Settings reference

This is an emulator/operator reference for the pinned V2.40 and V2.57 firmware.
It separates confirmed values from fields whose names are known but whose enums or
effects still need testing. A database column is not necessarily a live setter.

Verified stock network commands for gain, DRE, filter, SPDIF and user PEQ are in
[REMOTE_SETTINGS.md](../../docs/protocol/remote-settings.md), including the differences between wire
and database enums. Disposable V2.40/V2.57 tests check both network readback and
persisted configuration through TCP and WS.

Setup presets (named settings profiles, single-column overrides, battery, serial
number) are described in [guest environment presets](environment.md).

## Storage and when changes take effect

| Location inside the guest | Purpose | How to change |
|---|---|---|
| `/usr/data/fiio/db/sysconfig.db`, `SYSCONFIG` | Persistent player configuration | Stock UI/protocol; or SQLite while both guests are stopped, then boot |
| `/usr/data/fiio/db/song.db` | Indexed tracks, favorites, playlists and related state | Stock scanner/library operations; do not fabricate rows to simulate a scan |
| `/usr/data/fiio/db/theme.db` | Theme configuration | Stock UI; schema/enums not yet catalogued here |
| `mq_ui` process memory | UI-local state, including Auto update | UI events; not automatically persisted in SQLite |
| `/sys/...`, `/emu/...` | Emulated hardware state: battery, brightness, GPIO, DAC gain | Setup/control scripts and shims; not a replacement for persistent configuration |
| `/usr/project/config/ui/set_menu/*.json` | Localized UI labels and menu resources | Read as documentation; label order alone does not establish a setting's numeric enum |

On the host these files are in the Docker work volume; inside the container prefix
guest paths with `/work/rootfs`. Use a separate work volume for each firmware profile.
The player caches configuration in memory. Editing SQLite during execution can leave
the UI and backend inconsistent, and a subsequent stock save may overwrite the edit.

## Confirmed settings

| Column / setting | Values established so far | Effect and caveats |
|---|---|---|
| `LANGUAGE` | `0` Chinese simplified, `1` Chinese traditional, `2` English, `3` Japanese, `4` Korean, `5` Spanish, `6` Italian, `7` German, `8` Portuguese, `9` Russian | Zero-based firmware mapping. Fresh sentinel `100` opens the language wizard; an in-range value skips it. Setup presets `LANG_CODE` (default `2`) on a database it has just primed, and whenever the value is outside `0..9`; a language chosen in the menu is kept. |
| `VOLUME` | Logical range `0..120`; effective maximum also depends on `MAX_VOL` | Prefer the live FiiO Link volume command. This is not the browser's independent sound-enable switch or captured PCM amplitude. |
| `KEY_SINGLE_CLICK_SLE` | `0` switch track, `1` adjust volume | Single press of the volume buttons. Observed default `1`. |
| `KEY_DOUBLE_CLICK_SLE` | `0` switch track, `1` adjust volume | Double press of the volume buttons. Observed default `0`. |
| `KEY_LONG_PRESS_SLE` | `0` switch track, `1` adjust volume | Held volume buttons. Observed default `1`; GPIO and repeated gesture delivery also matter. |
| `LOCAL_IMG_ANIM` | `0` Static, `1` Rotate | V2.57 Settings > Cover Animation (checked 2026-10-05 by toggling the menu and reading the row). Setup presets `0` only on a database it has just primed; later setups keep the player's choice. A volume set up before this rule keeps `0` until Rotate is chosen once. |
| `BATTERY` | Setup writes `100` | Cached configuration value. The actual emulated battery also needs the sysfs capacity/status stubs from setup. |
| `LIGHT_LEVEL` | Observed boot value `20`; full range not established | Persistent brightness setting. Live screen on/off is read from the brightness sysfs file; a positive configured level does not itself mean the screen is awake. |
| `OUT_DEV` | `6` observed for local `I2S3_OUT` | Runtime route selection depends on card discovery and work mode. Do not force this field as a substitute for emulating the device. Other route values remain unvalidated. |

The button mappings were checked against both SQLite and guest memory; see
[KEYS.md](keys.md). Full V2.57 assignment combinations still need their own acceptance
matrix. Language mapping and boot prerequisites are documented in [EMULATION.md](emulation.md).

## Auto update is UI-local

In V2.57, the Update media lib page keeps a word at `mq_ui` guest VA `0x83a5d0`,
initialized to `1` in the stock ELF. The callback at `0x4618a8` toggles this word and
the visible indicator; its Auto update branch does not write SQLite or send a
player configuration command. The getter at `0x461c7c` feeds the SD notification path.
These are exact V2.57 UI addresses, not V2.40 addresses or host process pointers.

Live check: tapping the **text/row** at display `(170,141)` changed the word `1 → 0`
and emptied the indicator. Tapping the small circle at `(313,141)` did not change it.
The circle is a child object; its appearance alone is not evidence of a successful
toggle. The default filled circle means enabled. Restarting both guests reset the
word from `0` to `1`: disabling Auto update does **not** survive this restart.

The confirmed trigger is the SD-insertion notification (`aa22`, value `1`), with
additional UI-state guards. In an isolated V2.57 test, insertion with Auto update
off did not scan; with it on, the stock scanner indexed the generated Cyrillic-path
track and returned it over FiiO Link. Merely adding a second file did not update
the index during the observation window. Normal emulator boot remounts the SD but
does not send this notification. Repeated scans work after dismissing the previous
result with OK and unlocking the screen; the discovery-cache fix allows stock
hotplug to remount the card. See [MEDIA_LIBRARY.md](media-library.md) for the exact
conditions, verified add/rename/delete cases and USB limitations.

Do not add an invented `AUTO_UPDATE` column to `SYSCONFIG`, or write this address
into a running process to configure the player. Use the UI until a supported control
path is established. These observations are verified for V2.57 only.

## Read or change settings without navigating the UI

Read-only examples, while the guest is running or stopped:

```sh
docker exec snowsky-disc-qemu sqlite3 -readonly -header -column \
  /work/rootfs/usr/data/fiio/db/sysconfig.db \
  'SELECT LANGUAGE,VOLUME,MAX_VOL,KEY_SINGLE_CLICK_SLE,KEY_DOUBLE_CLICK_SLE,KEY_LONG_PRESS_SLE FROM SYSCONFIG;'
docker exec snowsky-disc-qemu python3 -m research.diagnostics.probe_keys
```

For live volume, use the existing protocol setter, which updates the running player:

```sh
python3 -m controller.fiio_link --volume 80
```

For confirmed persistent settings without a supported live setter, stop only the
guest processes, back up SQLite, edit, and boot without rerunning setup:

```sh
docker exec snowsky-disc-qemu bash -lc 'source /repo/emulator/scripts/lib.sh; verify_firmware; kill_guest'
docker exec snowsky-disc-qemu sqlite3 /work/rootfs/usr/data/fiio/db/sysconfig.db \
  '.backup /work/sysconfig-before-settings.db'
docker exec snowsky-disc-qemu sqlite3 /work/rootfs/usr/data/fiio/db/sysconfig.db \
  'BEGIN IMMEDIATE; UPDATE SYSCONFIG SET LANGUAGE=9,KEY_SINGLE_CLICK_SLE=1,KEY_DOUBLE_CLICK_SLE=0,KEY_LONG_PRESS_SLE=1 WHERE ID=1; COMMIT;'
docker exec snowsky-disc-qemu bash /repo/emulator/scripts/20_boot.sh
```

Check the actual row ID before editing. Keep earlier backups under distinct names.
The viewer stays running during this procedure. Verify the resulting language in
the UI and button assignments with `probe_keys.py`; a changed DB row alone does not
prove that a running process has adopted it.

The sequence above was exercised on a disposable V2.57 volume: the restarted UI
displayed Russian, SQLite retained `LANGUAGE=9`, and `probe_keys.py` reported the
requested `1/0/1` assignments from guest memory. The interactive volume was not edited.

`./emulator/run.sh boot` runs **setup first**. Setup writes `BATTERY=100` every time. The
player's own choices, `LANGUAGE` (from `LANG_CODE`, default `2`) and `LOCAL_IMG_ANIM=0`, are
preset only on a database that setup has just primed (`settings apply --fresh`), so a language
or Cover Animation chosen in the player's menu, or set by an offline edit, survives later boots.
A `LANGUAGE` outside `0..9` (stock's initial `100`, which the menu cannot set) is no choice yet,
so setup presets `LANG_CODE` then as well.
`SETTINGS` names columns explicitly and is written on every setup:

```sh
docker exec -e SETTINGS=LANGUAGE=9 snowsky-disc-qemu bash /repo/emulator/scripts/10_setup_env.sh
docker exec snowsky-disc-qemu bash /repo/emulator/scripts/20_boot.sh
```

`LANG_CODE` is a setup environment variable used when setup primes a new database, not a
firmware database column.
`GUEST_TTL`, `FW_VERSION`, viewer FPS and browser sound controls are emulator options,
not stock player settings. See [VIEWER.md](../../viewer/docs/usage.md) and [PORTING.md](../../firmware/docs/porting.md).

## Fields awaiting enum/behavior verification

These names exist in the observed V2.57 schema. Their grouping is descriptive; it
does not authorize guessing numeric values from names or localized menu order.
Read the schema on V2.40 before assuming a newer column exists there.

| Area | Columns to map and verify |
|---|---|
| Playback and queue | `PLAY_MODE`, `MEMORY_PLAY`, `FOLDER_JUMP`, `PLAY_GAP`, `SYS_REPLAY_GAIN` |
| Audio paths and processing | `DSD_MODE`, `DSD_DECODE`, `WORK_MODE`, `INPUT_MODE`, `USB_MODE`, `DEVICE_OUTPUT`, `SPDIF`, `EQ_TYPE`, `FILTER_TYPE`, `DRE_STATUS`, `TREBLE`, `BASS` |
| Volume behavior | `MAX_VOL`, `MUTE`, `VOL_MODE`, `VOL_KNOB_MODE`, `BALANCE_VOL`, `PO_PRE_VOL`, `PO_VOL`, `PRE_VOL`, `AUDIO_VOLUME_SET`, `BTSINK_VOLUME`, `BT_SRC_VOLUME`, `UAC_VOLUME`, `AIRPLAY_MEM_VOLUME`, `LO_DISABLE` |
| Display and navigation | `FONT_SIZE`, `LIST_OPER_MODE`, `TRACK_DISPLAY`, `SCREEN_ROT`, `SYS_THEME`, `THEME_MODE`, `LOCK_THEME`, `RGB_LEVEL`, `RGB_STATUS`, `RGB_COLOUR`, `IMG_ANIM_BRIGHTNESS` |
| Power and idle behavior | `LIGTH_ON_TIME` (stock spelling), `POWER_SAVE`, `CHARGE_PROTECT`, `TRIGGER_IN` |
| Network and wireless | `NETWORK_MODE`, `WIFI_STATUS`, `BT_STATUS`, `BT_CODEC`, `AUTO_TIME` |
| Library and online display | `ARTIST_CLASS_TYPE`, `ONLINE_COVER`, `ONLINE_LRC` |
| Internal/version state | `OTA_CFG`, `OS_MODE`, `ARM_VERSION`, `MCU_OTA_FAILED_TIME` |

For each new entry, record firmware fingerprint, UI label, allowed enum/range,
default versus observed value, persistence across guest restart, and observable
effect. Settings such as Wi-Fi status, work mode and hardware/version state may be
maintained by the firmware rather than intended as user-configurable switches.
