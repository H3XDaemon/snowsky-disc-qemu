#!/usr/bin/env bash
# Boot the firmware under qemu-user and capture the screen.
#
# Starts mq_ui FIRST (it creates the POSIX mqueue "ui"), then mq_player (the
# backend, which connects to "ui" and pushes state). Waits for input and framebuffer readiness,
# then dumps the framebuffer to PNGs in $SHOTS.
#
# Usage:  emulator/scripts/20_boot.sh [seconds]      (optional extra delay before capture)
#
# Leaves both guest processes RUNNING so you can inject taps with 30_tap.sh, then
# re-capture with `emulator/scripts/capture.sh`. Run `emulator/scripts/99_stop.sh` when done.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
WAIT="${1:-0}"
[ -d "$ROOTFS" ] || { err "no rootfs — run 00/10 first"; exit 1; }
[ -f "$ROOTFS/lib/fbshim.so" ] || { err "shim not installed — run 10_setup_env.sh"; exit 1; }
verify_firmware

apply_ulimits
kill_guest
userdata_attach   # no-op without a USERDATA_MB image (10_setup_env.sh)
# NETWORK=isolated: the guest gets its own network namespace with loopback only; links
# are added with emulator.runtime.network. Default: the container's network, as always.
case "${NETWORK:-shared}" in
  shared) [ ! -e "$ROOTFS/emu/netns" ] || python3 -B -m emulator.runtime.network share >/dev/null ;;
  isolated) python3 -B -m emulator.runtime.network isolate >/dev/null ;;
  *) err "Unknown NETWORK '${NETWORK}' (shared or isolated)"; exit 2 ;;
esac
bash "$REPO/emulator/scripts/16_network.sh" prepare

# Guest lifetime is decoupled from the capture wait so the guests stay alive for the
# interactive viewer (./emulator/run.sh view), not just long enough for one screenshot. Override
# with GUEST_TTL (seconds, 0 = no limit); the timeout only bounds leaked qemu processes.
GUEST_TTL="${GUEST_TTL:-1800}"
case "${BOOT_MODE:-direct}" in
  direct)
    guest_view_direct
    userdata_mount
    board_reset
    # BOOT_KEYS / armed keys are down from before the first guest instruction until boot ends.
    python3 -B -m emulator.runtime.gpio power-on ${BOOT_KEYS:-} >/dev/null
    log "Starting mq_ui (creates 'ui' queue)"
    guest_run "$GUEST_TTL" /usr/bin/mq_ui  >"$WORK/mq_ui.log"     2>&1 &
    sleep 4
    log "Starting mq_player (backend)"
    guest_run "$GUEST_TTL" /usr/bin/mq_player >"$WORK/mq_player.log" 2>&1 &

    # Announce as soon as the stock network detector subscribes, overlapping UI startup.
    # An isolated guest has nothing to announce: stock sees real events when links appear.
    guest_netns >/dev/null || bash "$REPO/emulator/scripts/16_network.sh" announce
    # POWER_WATCH=1: serve the stock idle power-off without a viewer (emulator/docs/environment.md).
    if [ "${POWER_WATCH:-0}" = 1 ]; then python3 -B -m emulator.runtime.power_watch start >/dev/null; fi
    ;;
  init)
    # Stock boot: rcS -> S98FIIO -> fiio_init.sh starts and watches both programs.
    # The supervisor announces the network and remounts the card on every start.
    bash "$REPO/emulator/scripts/17_init_stubs.sh"
    log "Powering on through stock init (console: $WORK/console.log)"
    python3 -B -m emulator.runtime.machine start --ttl "$GUEST_TTL" --keys "${BOOT_KEYS:-}" >/dev/null
    guest_netns >/dev/null || NETWORK_WAIT=120 bash "$REPO/emulator/scripts/16_network.sh" wait
    ;;
  *) err "Unknown BOOT_MODE '${BOOT_MODE}' (direct or init)"; exit 2 ;;
esac
log "Waiting for guest input devices and the first framebuffer flush..."
ROOTFS="$ROOTFS" python3 -m emulator.runtime.boot_ready

# mq_ui umounts /tmp/sdcard during startup (it expects a hotplug remount that never comes
# under emulation). Re-mount the card now, after that umount, so the File Browser — which
# scans /tmp/sdcard live on entry — shows the ./emulator/sdcard content. No-op when there is no card.
if sd_node >/dev/null; then
  if [ "${BOOT_MODE:-direct}" = init ]; then
    # Stock mounts a partitioned card itself; otherwise the supervisor does after a short
    # grace. Wait for either instead of racing the stock mount.
    for ((n=0;n<40;n++)); do mountpoint -q "$ROOTFS/tmp/sdcard" && break; sleep .5; done
  fi
  sd_mount; log "SD re-mounted at /tmp/sdcard (File Browser ready)"
fi
python3 -B -m emulator.runtime.gpio release >/dev/null   # power-on keys are let go

sleep "$WAIT"  # explicit CLI capture delay only; the viewer uses no fixed pause

mkdir -p "$SHOTS"; rm -f "$SHOTS"/*.png "$SHOTS"/*.snap 2>/dev/null || true  # fresh set each boot
cp "$ROOTFS/dev/fb0" "$WORK/fb0.snap"
log "Framebuffer captured. Rendering PNGs:"
python3 -m emulator.runtime.fb2png "$WORK/fb0.snap" "$SHOTS" boot
log "Guests left running. Inject taps: emulator/scripts/30_tap.sh <x> <y>   Stop: emulator/scripts/99_stop.sh"
