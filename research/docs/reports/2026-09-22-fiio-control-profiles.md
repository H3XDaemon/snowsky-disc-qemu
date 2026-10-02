# FiiO Control 4.6.0: device profiles and startup synchronization

Offline Android APK analysis on 2026-09-22, requested by the owner after observing
downloads at app startup. **The APK contains a device/function database and code
that refreshes it from the server.** This establishes an Android implementation,
not the contents of a current server response or identical iOS behavior.

No FiiO cloud endpoint was queried, no app login was performed, and no player was
connected or modified. Controller compatibility is unchanged.

## Inputs and tools

The supplied `FiiOControl V4.6.0.apk` matches the
[previously identified Android input](fiio-control-app.md#android-460-input-2026-09-15):

| Artifact | SHA-256 |
| --- | --- |
| APK | `516c6d882a6723b03d7860f8ab000ce8dc600d9fabe986bfe187ba15d37d110c` |
| ARM64 libapp.so | `c8364937febff7ddd493f3874c38580908433ae9bb42388cc5d79a3785265f6c` |
| ARM64 libflutter.so | `60f8682a4076a781607eb52bc28dc1e2587a03d85e65632dbe561b068639d4b6` |
| Bundled sc_config_default.db | `1791f8a4210282d51ee7e5956f17bda3459b084fca9eaf8ad695aa5a0953fef9` |

[Blutter](https://github.com/worawit/blutter), revision
`4a60ac648bf448c5a7596437243bcd0b9376fdf0`, successfully built and analyzed this input
on macOS ARM64. It identified Dart **3.10.9**, Android ARM64, compressed pointers,
snapshot `1ce86630892e2dca9a8543fdb8ed8e22`. Outputs include symbol-annotated assembly
and object-pool dumps; they are not reconstructed Dart source.

Private outputs live in ignored `work/fiio-control-460/`; tool sources/builds are
in ignored `work/tools/blutter/`. Do not commit the APK, database, assets or dumps.

## Bundled database

The APK entry is
`assets/flutter_assets/assets/database/sc_config_default.db` (770,048 bytes).

| Table | Rows | Role observed in schema/data |
| --- | ---: | --- |
| sc_product_info | 70 | Product records, unique device_type |
| sc_func_info | 78 | Function JSON, unique device_type + device_version |
| sc_update_time | 0 | Update timestamp storage |
| home_save_device | 0 | Saved devices by device_type + address |

Product fields include `device_model`, `device_name`, `connect_mode`,
`command_builder_type`, `form_factor`, `device_version_command`,
`bt_address_range`, `bt_broadcast_code`, `ota_way`, and `server_config_or_not`,
plus photo/manual references and timestamps. These are product records, not
necessarily 70 distinct marketed models: some names have multiple records.

The bundled products have connect_mode 1 (47 rows) or 3 (23 rows), and cover
Bluetooth/USB device families such as BTR, KA, Q, K and UTWS. Numeric transport
values should not be generalized without checking their consuming code.

The `function_msg` JSON describes more than a compatibility list:

- State/audio/settings sections and support flags.
- UI kinds, titles, option labels/values, slider minimum/maximum/step/units.
- Get/set commands, parsing-rule types and polling command lists.
- Optional command pacing (`deviceCommandInterval`).
- Additional feature configuration, including EQ descriptors.

For example, the BTR13 state configuration describes an idle timer with range
0..30, step 1, unit minutes, and a codec choice with explicit bitmask mappings.
These are vendor descriptors for that product, not DISC commands or hardware
acceptance evidence.

The bundled tables are not a complete one-to-one inventory. Function rows exist
without a corresponding product for device_type 48, 51 and 52; six product rows
have no matching function record. Absence must not automatically mean unsupported.

## Startup refresh: recovered call sites

Addresses below are Blutter code addresses in the fingerprinted ARM64 libapp.so,
not live process addresses. Paths are relative to the `flutter_module` package.

| Location | Evidence |
| --- | --- |
| fiio_v2/sc_launcher_page.dart, _startInitialization, 0x8b997c | Calls getAppUpdate; later calls SCConnect.initialize at 0x8b9e1c and RemoteL10n.sync at 0x8b9e2c, on the corresponding startup branch. |
| common/ctrl/sc_connect.dart, onInit, 0xa2f09c | Sets base URL to `https://usersystem.fiio.com/ucenter-api/`. Here and below `common/` is under `fiio_v2/device_control/`. |
| SCConnect.initialize, 0x8ea5b0 | Reads remote update time and local latest timestamp. Missing/older local timestamp enters product refresh, function refresh, then timestamp insertion. |
| requestUpdateTime, 0x8f64a4 | Selects update-time endpoint; HTTP GET and response parsing. |
| updateProductInfos, 0x8f3c3c | HTTP GET, JSON envelope, AESUtil.decryptAes, JSON decoding, SCProductInfo.fromJson, system-type filtering, deleteAll and insertOrUpdate. |
| updateFuncInfos, 0x8ecacc | HTTP GET, JSON envelope, AESUtil.decryptAes, JSON decoding, SCFuncInfo deserialization, deleteAll and insert. |

With the all-data preference disabled, `_resolveEndpoint` (0x8ee108) selects:

- `get-latest-update-time-prod`
- `get-all-device-prod`
- `get-all-device-function-prod`

The alternative all-data branch selects the corresponding names without `-prod`
and has separate header handling. This analysis did not enable it or obtain an
account token. Requests carry a `cipherSign` query parameter. Response data is
decrypted inside the app: a successful HTTPS capture alone may therefore still
contain an encrypted application payload.

App-update metadata (`get-last-supported-version`) and remote localization are
separate startup operations. The owner's visible startup download cannot be
attributed exclusively to product profiles from static evidence alone.

The earlier 18-second PCAP contained ClientHello SNI `usersystem.fiio.com` but no
server TCP payload; the companion HAR had zero entries. This APK now supplies a
concrete use of that host, but cannot establish which request the iPhone attempted.

## How profiles become controls

The universal device path has explicit product resolution, function selection,
UI construction and command dispatch:

1. BluetoothDeviceFactory calls DeviceTypeResolver. Its strategies include
   broadcast-code, database product-name and static mappings.
2. SCUniversalTabPageCtrl queries product metadata and initializes its dispatcher
   through FiiODeviceProtocolType.fromValue (0x9b4e5c).
3. `_loadAndMatchFunctionTable` (0x9b36c4) loads functions by device type, tries an
   exact firmware version, then a closest-lower version; it also has a latest-version
   fallback when no lower match is available or a zero version is encountered.
4. `_initializeFunctionTable` (0x9b38dc) updates support states and initializes page
   controllers. `_initAllPageUI` calls SCUniversalBaseCtrl.initUI.
5. MessageDispatcher calls SCCommandBuilder.buildCommand (0x954ffc).

SCFuncInfoDao also has `_queryWithFallback` (0x9c29b0), which can query the bundled
default database. SCDatabaseManager.defaultDatabase (0x981510) copies the bundled
asset to a local file when needed and opens it. Server data and bundled fallback
are distinct inputs.

The recovered protocol enum contains Bluetooth families, USB families and
`WIFI_V1` (301). Examples: `USB`=101, `BT_UNIVERSAL_1`=6 and
`BT_GAIA_V3_4`=5. Old builder codes and aliases exist; do not assume every raw
database builder number maps directly to an identically numbered current enum.

## DISC boundary

Neither bundled product nor function table contains a DISC or M1 name.
DISC does occur in compiled `DeviceType.castDeviceMaps` (0x9e18e8):
`SNOWSKY DISC` maps to **306**. The machine instruction stores 612 because Dart
tags small integers; 612 is not the device ID. This is an app-internal identifier,
not a claim about a wire handshake value.

The Link scan path uses LinkerBroadcastReceiver. LinkerScanPageController's
connection path calls LinkerController.tryInitController (0x9f41c4), which calls
LinkTcpService.tryConnectAndGetDeviceType (0x9f4a3c). This supports a separate
compiled Wi-Fi Link path alongside universal Bluetooth/USB profiles. The entire
DISC routing graph and any current server-only DISC descriptors remain unverified.

## Consequences for our API

These findings support a future separation between descriptive product metadata,
transport/protocol implementation, and reviewed capabilities. Imported metadata
could help identify models and explain UI controls, but cannot enable commands
by itself. In particular, do not copy the app's permissive firmware-version
fallback into Controller's reviewed compatibility policy.

For DISC, the next useful static targets are LinkTcpService identity handling,
LinkCommandBuilder and model-specific page gates. For updated cloud profiles,
the useful next evidence is a successful normal startup capture plus the app's
post-decryption data or local database. Neither is collected by this report.

## Reproduction

Extract the two ARM64 libraries to an ignored input directory and run, from the
repository root (the local Homebrew ICU path is specific to this host):

```sh
python3 work/tools/blutter/extract_dart_info.py work/fiio-control-460
PKG_CONFIG_PATH=/opt/homebrew/opt/icu4c/lib/pkgconfig python3 work/tools/blutter/blutter.py work/fiio-control-460 work/fiio-control-460/blutter-out
```

Extract the database entry named above with Python zipfile, open SQLite read-only,
and inspect `sqlite_master`, table counts and JSON in `sc_func_info.function_msg`.
Recheck the hashes before reusing these addresses. No firmware or device test is
required to reproduce this offline analysis.
