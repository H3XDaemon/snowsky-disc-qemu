# Local network emulation

The setup/control flow supports V2.40 and V2.57 (default). For version-aware
read-only probes and the V2.57 address map, see [DIAGNOSTICS.md](../../research/docs/diagnostics.md).
Historical function addresses below refer to V2.40.


The stock firmware serves FiiO Link on TCP **12100** and Mongoose HTTP on **12103**.
No network binary patches, hard-coded IP, dummy Wi-Fi or DB flag overrides are needed.
This milestone is local control, not Wi-Fi radio emulation or cloud streaming.
The optional `wsbridge` Compose profile adds a WebSocket → TCP bridge on host
**12103**; direct stock HTTP
is available on host **12113**. See [WEBSOCKET.md](../../controller/docs/websocket.md) for framing, client,
browser inspector and live control results. Guest port numbers remain unchanged.

## Reproduce

Use Docker Engine **28.1+** and Compose **2.36+**. CI pins are in [CI.md](../../docs/development/ci.md).

```sh
./emulator/run.sh compose up -d --build
./emulator/run.sh boot
./emulator/run.sh view
python3 -m controller.fiio_link
python3 -m controller.diagnostics.verify_network
./emulator/run.sh compose --profile wsbridge up -d wsbridge  # optional WS diagnostics
./emulator/run.sh wscheck --control
```

For a new work volume, first use `./emulator/run.sh up /path/to/main_os/ota_v257` as in the README.
Do not delete an existing volume to upgrade. Setup stops the guest before updating
mapped shims or rebuilding its SD. Power-on from the viewer reruns network preparation
and announcement too. The viewer itself must be started again after container recreation.

The Compose configuration is `emulator/compose.yaml`.
Its [`interface_name`](https://docs.docker.com/reference/compose-file/services/#interface_name)
setting gives Docker's normal bridged interface the firmware-supported name **eth1**.
Docker assigns the address and default route. Published ports bind **127.0.0.1**:
12100, direct HTTP 12113, UDP 12101 and viewer 8080; the optional bridge adds 12103. Auth-free controls must not be
accidentally exposed to the LAN.

## Emulated links, isolation and shaping

Verified on V2.57, 2026-10-02. All opt-in; the default is the Docker `eth1` above.

```sh
python3 -m emulator.runtime.network status
python3 -m emulator.runtime.network link wlan0 --state up --addr 10.203.0.7/24
python3 -m emulator.runtime.network link wlan0 --state down --addr none
python3 -m emulator.runtime.network shape --rate 800kbit --delay 60ms --loss 1%
python3 -m emulator.runtime.network shape off
```

- **`WLAN0=1`** (setup/boot variable, with optional `WLAN0_STATE`, `WLAN0_ADDR`,
  `WLAN0_MAC`) creates an emulated `wlan0`: a dummy kernel link, so netlink and
  `ifconfig` see it, plus the `/sys/class/net/wlan0/{address,operstate}` stub that
  stock and services read. State and address are controlled with `link`; the
  stub's `operstate` follows the requested state (`up`/`down`). In a
  [stock-init](stock-init.md) guest `S43wifi_bcm_init_config` then runs as on the
  player and writes `/usr/data/wpa_supplicant.conf` and `macaddr.txt`, which is
  what the stock ["Reset all"](../../research/docs/reports/reset-all.md) needs.
  No radio is emulated: `wpa_supplicant`, `udhcpc` and interface changes from the
  guest stay blocked. Only dummy links can be changed; the Docker `eth1` cannot.
- **`NETWORK=isolated`** boots the guest (either boot mode) in its own network
  namespace with nothing but loopback: a player with no network. Nothing is
  announced and the boot does not wait for the stock listeners. A link added
  later is a real kernel event that stock handles by itself:

  ```sh
  python3 -m emulator.runtime.network link wlan0 --state up --addr 192.0.2.2/24 --gateway 192.0.2.1
  ip netns exec disc-guest python3 -m controller.fiio_link   # clients must run inside
  ```

  With `wlan0` (or `eth1`) as the only link, stock logged `Interface wlan0: IP
  Address added` and bound 12100 and 12103 three seconds later; the FiiO Link
  handshake answered on that address. In a shared guest that already serves on
  the Docker `eth1`, stock takes no notice of a second address on `wlan0`. The
  published host ports do not reach an isolated guest; `guest_run` enters the
  namespace automatically. `NETWORK=shared` (default) returns to the container's network.
- **`shape`** limits what the guest sends on the Docker `eth1` (token bucket plus
  optional delay and loss), which is what a client downloads, also through the
  published host ports. Measured between two containers with a 3 MB file:
  unlimited 280 MB/s; `--rate 800kbit --delay 60ms` 95 kB/s over 31.5 s. Uploads
  to the guest are not limited. It is a constant-rate link, not a Wi-Fi model.

### mDNS and the host LAN

- The guest's own `avahi-daemon` starts under qemu-user, registers
  `ingenic.local` on `eth1`, and then aborts on its first received packet
  (`avahi_recv_dns_packet_ipv4: Assertion '!(msg.msg_flags & MSG_TRUNC)'`): the
  pinned qemu 7.2 truncates that socket's control messages. Stock mDNS is
  therefore not served.
- A Docker Desktop container is not on the host's LAN and receives no multicast
  from it, so a guest cannot be reached by a LAN address or answer LAN mDNS by
  itself. What works is a host-side stand-in, opt-in and subject to the
  [LAN bridge rules](../../controller/docs/discovery.md): run the bounded
  `controller/bridge/lan_bridge.py` on the host's LAN address and publish the
  name from the host, for example on macOS
  `dns-sd -P ingenic _http._tcp local 12103 ingenic.local <host LAN IPv4>`.
  A browser then reaches `http://ingenic.local:12103` as a private-network
  address. This was not run in this work; it needs the owner's approval of LAN
  exposure.

## Why it was blocked

Three independent gates were observed:

1. `FUN_004b89a0` subscribes to NETLINK_ROUTE groups `0x11` (link + IPv4 address),
   but does **not** request a dump of addresses that existed before player startup.
2. `FUN_004b7e00` handles `RTM_NEWADDR`, saves the IP at `0x0086c020`, and sets
   `0x0086c030 = 1`. `FUN_004e99d0` checks this flag every second and starts HTTP
   (`004b9914`) and FiiO Link (`004d344c`). Merely setting WIFI_STATUS is insufficient.
3. FiiO Link's `FUN_004c7408` independently reads the default route and supports only
   `wlan0` or `eth1`. The standalone firmware `/sbin/ip addr show eth1` fails under
   this QEMU 7.2 with **Operation not supported**; the stock BusyBox `ip` applet works.

`emulator/scripts/16_network.sh prepare` mirrors eth1's actual MAC/operstate into guest sysfs
and installs command wrappers. `announce` waits for the detector's startup log and
re-announces the **same** Docker IPv4 address with `ip addr change … valid_lft forever
preferred_lft forever`, then waits for both listeners. No interface down/up, new
address, DHCP exchange, host route or firmware-memory mutation is involved.
The `ip` wrapper delegates the two read-only queries to `/bin/busybox ip`.

## Confinement and reproducibility

This is still a **privileged development container**, not a security boundary for
untrusted firmware. `guest_run()` in `emulator/scripts/lib.sh` uses the Dockerfile's
`util-linux`/`setpriv` to remove NET_ADMIN, SYS_TIME, SYS_BOOT, SYS_MODULE and SYS_RAWIO
from the guest bounding/effective capability sets and enables no-new-privileges.
This applies to the normal boot, first-boot priming, GDB and touch diagnostic launchers,
including child commands. SYS_ADMIN remains for the existing SD mount workflow.

The stock network-up path launches OTA helpers/NTP and executes `hwclock -w` every
21 seconds. `emulator/scripts/guest-command.sh` blocks those commands and guest network
configuration tools; original executables are preserved at `/emu/original-commands/`.
Wrappers are installed atomically without following BusyBox symlinks. No utilities
were installed ad hoc in the image. Dockerfile checks `setpriv` and `ip` availability.
These wrappers are an accident-prevention measure, **not an outbound firewall**;
library-level connections and direct syscalls are not comprehensively sandboxed.
The separate host-side [OTA monitor](../../firmware/docs/ota.md) reads the vendor catalog and creates
release tracking issues; it does not enable the guest OTA installer.

Read-only live state/capability check (never writes `/proc/PID/mem`):

```sh
docker exec snowsky-disc-qemu python3 -m research.diagnostics.probe_network
docker exec snowsky-disc-qemu python3 -m research.diagnostics.probe_keys
docker exec snowsky-disc-qemu ip route
```

## Wire checks and controls

The extended remote-control contract and repeatable TCP/WS acceptance are in
[REMOTE_CONTROL.md](../../docs/protocol/remote-control.md): position selection, next/previous, seek,
local modes, named albums/artists and built-in favorites. That report also records
physical V2.57 comparisons and the stock navigation rate limit.

The library scanner has a separate storage gate from Browse files. It checks
`access(source)` for entries in `/proc/mounts` (`004bc890`, called by `004269e0`).
The old source `/work/rootfs/dev/mmcblk0p1` was inaccessible inside chroot: Update now
stayed on **0 songs**, and its worker returned early. `sd_mount()` now mounts from
inside the guest, recording `/dev/mmcblk0p1 /tmp/sdcard`. The stock scanner then
finished with **4 songs**, and TCP 0401 returned the same four records. No synthetic
database rows were inserted. Use Settings → Update media lib → Update now after
placing files on the SD. Screenshots are in [STATUS.md](status.md).

Temporary Auto update fixture, generated with the Dockerfile's SoX dependency:

```sh
docker exec snowsky-disc-qemu bash /repo/tests/fixtures/media_fixture.sh add
./emulator/run.sh boot
# Inspect the app and run controller/fiio_link.py; do not press Update now for the auto test.
docker exec snowsky-disc-qemu bash /repo/tests/fixtures/media_fixture.sh remove
./emulator/run.sh boot
```

The fixture generator refuses to overwrite existing media; removal verifies its
recorded SHA-256. The second boot rebuilds the SD without the generated file.
In the 2026-09-11 test the fifth file was present on the rebuilt SD, but no startup
scan ran and the index stayed at four records. Clicking Auto update gave no confirmed
effective-state change. The generated file was removed and the original SD restored.
The V2.57 follow-up established a volatile UI flag and an SD-insertion trigger.
Repeated scans and Cyrillic add/rename/delete work after dismissing the result and
unlocking the screen. `sd_mount()` now primes stock blkid's partition discovery,
allowing the firmware's hotplug handler to remount the emulated card.
See [SETTINGS.md](settings.md) and the [media-library investigation](media-library.md)
before relying on Auto update in the emulator.

`controller/fiio_link.py` uses only Python's standard library, defaults to localhost and
handles fragmented/coalesced frames. Lengths count UTF-8 **bytes**. It decodes the
nested JSON string in `now_playing.song`. Stock firmware sometimes sends no 0202
reply before a track is selected or after its state is cleared; the CLI reports
that timeout separately instead of claiming playback metadata exists.

```sh
python3 -m controller.fiio_link --volume 118  # absolute logical volume, 0..120
python3 -m controller.fiio_link --play-pause # selected track only
python3 -m controller.fiio_link --play-all   # start all indexed local songs
# Open a test track first. This writes volume (then restores it) and toggles twice:
python3 -m controller.diagnostics.verify_network --control
# Or select the indexed library over TCP; final test state is paused:
python3 -m controller.diagnostics.verify_network --control --start-library
```

Confirmed command routing, without sweeping arbitrary setters:

| Request | Stock route |
|---|---|
| `0599000C0000` | handshake, `a599000C0306` |
| `05010008` | settings JSON including volume and firmware 240 |
| `0401000C0000` | indexed library page, not a live SD directory listing |
| `02020008` | now-playing JSON, including actual `/tmp/sdcard/…` path |
| `0502000C0076` | volume 118: table 82d520 → 41c640 → 4e4744 → callback 88cc44 → 4e0fdc |
| `0201000C0000` | play/pause: table 82d528 → 41c660 → 4e477c → 424b2c(0, 0) |
| `0101000C0001` | start all indexed songs: 4e4cb4 → 423e94, list type **1**; type 0 reuses the current queue |

Live verification after repeated setup/boot: volume **119 → 118 → 119**; wire play
state **0 → 1 → 0** for the same indexed track (playing → paused → playing), then
left paused. Independent guest memory readback showed player state **2** (paused)
and volume **119**. Wire state numbers are different from the internal player enum.
The client drains old asynchronous notifications before new queries: a queued `a202`
must not be mistaken for a response to a later play/pause action. The protocol has no
request IDs; the client is sequential and intentionally does not support concurrent requests.

Direct stock Mongoose (host 12113) `/api/hi` and `/api/websocket` return the generic empty HTTP 200 fallback,
not an API reply or WebSocket upgrade. See the investigation below.
Publishing UDP 12101 is not a multicast relay. Normal Compose remains localhost-only.
Stock V2.57 announcement/lifecycle probes and an opt-in, allowlisted **host**
LAN bridge are described in [DISCOVERY.md](../../controller/docs/discovery.md); the bridge is separate
from wsbridge and must be explicitly enabled for a bounded phone test.
OTA installation, NTP, internet services and actual Wi-Fi association are out of scope.

## WebSocket investigation

V2.40's active HTTP server does **not register WebSocket**. This is not an emulation
network-readiness or password problem:

1. `004b9720` starts port 12103 with callback `004b9d38`.
2. The callback dispatches HTTP events 10/11 through the 16-entry table at `006c7a50`.
   It handles connection cleanup/poll events, but has no WebSocket-message dispatch.
3. The table has no `/api/*` or WebSocket route. Unmatched requests call `0048f8f8`,
   which directly returns HTTP 200 with no body.
4. `/api/hi`, `/api/websocket` with valid Upgrade headers and `/__unmapped_probe__`
   all produced the same HTTP 200 with Content-Length 0 in the running emulator.

Bundled dashboard code near `004b2820` references `/api/websocket` and
`mg_dash_authenticate`, but this listener does not delegate to it. Earlier notes about
vendor credentials causing the empty 200 were incorrect. A WebSocket implementation
in the phone app is not proof of DISC server support. No firmware patches or ad-hoc
image changes were made in this investigation.

Reproduce the **read-only** inspection and wire probe:

```sh
docker exec snowsky-disc-qemu python3 -m research.diagnostics.inspect_http_routes
python3 -m controller.diagnostics.probe_websocket --port 12113
python3 -m controller.diagnostics.probe_websocket --port 12113 --path /__unmapped_probe__
# Intentionally exits 1 for stock V2.40, which returns 200 instead of upgrading:
python3 -m controller.diagnostics.probe_websocket --port 12113 --require-upgrade
```

The route inspector uses ELF PT_LOAD mappings, not a guessed address offset; its
addresses are specific to V2.40. The probe requires HTTP 101, Upgrade/Connection
headers and the matching Sec-WebSocket-Accept digest. Neither HTTP 200 nor an
arbitrary 101 counts as a successful upgrade. These read-only inspection/probe tools
use only the Python standard library. The subsequently implemented bridge has its
own declared aiohttp dependency and Compose port mapping, documented separately.

**Now implemented:** a separately identified local WebSocket → TCP 12100 bridge.
Host 12103 reaches it; guest 12103 is unchanged, with direct access on host 12113.
This is not stock WS support; see [WEBSOCKET.md](../../controller/docs/websocket.md).
Follow-up investigation verified `POST /audio/` file transfer, directory operations,
custom playlists and remote scanning: see [HTTP_API.md](../../docs/protocol/http-api.md).

## Re-run the reverse engineering

On an analyzed stock V2.40 `mq_player` Ghidra project, use the committed scripts:

```sh
analyzeHeadless /path/to/project mqproj -process mq_player -noanalysis -readOnly \
  -scriptPath /path/to/snowsky-disc-qemu/research/ghidra \
  -postScript DecFuncs.java 0x4b89a0 0x4b7e00 0x4e99d0 0x4c7408 0x4b6a60 \
  -postScript DecFuncs.java 0x4e4744 0x4e477c
```

Scanner gate: `-postScript DecFuncs.java 0x4269e0 0x4bc890 0x462488`.
Active HTTP dispatch/fallback: `-postScript DecFuncs.java 0x4b9720 0x4b9d38 0x48f8f8`.
The `mq_ui` function `0043ed1c` (`ui_set_media.c`) is **AirPlay settings**, not
Update media lib; do not follow that misleading "media" string when investigating Auto update.

The pointer tables and trampolines can also be inspected inside the image with
`mipsel-linux-gnu-objdump -s/-d --start-address=… --stop-address=…
/work/rootfs/usr/bin/mq_player`. Data virtual addresses are **not** uniformly
`file offset + 0x400000`; use ELF-aware tools rather than raw-offset guesses.
