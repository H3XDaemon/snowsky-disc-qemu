#!/usr/bin/env bash
# Power events for a prepared guest. /usr/data and the card image are never rebuilt here.
#
#   25_power.sh on                cold start (BOOT_MODE, BOOT_KEYS as for 20_boot.sh)
#   25_power.sh reboot            stock-init guest only: rcK, then a new power-on through rcS
#   25_power.sh off               clean shutdown (rcK in a stock-init guest); the guest stays off
#   25_power.sh cut [--unsynced]  power loss: every process dies at once, no rcK.
#                                 --unsynced also drops /usr/data writes not yet on its image
#   25_power.sh status            machine state as JSON
#
# See emulator/docs/stock-init.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
machine(){ ROOTFS="$ROOTFS" python3 -B -m emulator.runtime.machine "$@"; }
case "${1:-}" in
  on) shift; exec bash "$HERE/20_boot.sh" "$@" ;;
  reboot)
    guest_init_pid >/dev/null || { err 'reboot needs a running stock-init guest (BOOT_MODE=init)'; exit 1; }
    machine reboot >/dev/null
    NETWORK_WAIT=120 bash "$HERE/16_network.sh" wait
    ROOTFS="$ROOTFS" python3 -B -m emulator.runtime.boot_ready
    ;;
  off)
    if guest_init_pid >/dev/null; then machine poweroff >/dev/null; fi
    kill_guest
    log 'guest is off'
    ;;
  cut)
    case "${2:-}" in
      '') machine cut >/dev/null ;;
      --unsynced) machine cut --unsynced >/dev/null ;;
      *) err 'usage: 25_power.sh cut [--unsynced]'; exit 2 ;;
    esac
    kill_guest
    log "power cut: $(machine status)"
    ;;
  status) machine status ;;
  *) err 'usage: 25_power.sh on|reboot|off|cut [--unsynced]|status'; exit 2 ;;
esac
