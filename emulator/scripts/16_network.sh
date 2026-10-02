#!/usr/bin/env bash
# Reproducible wired-network preparation and startup event replay. No guest IP
# patches, fake DHCP, or changes to the Docker-assigned address/default route.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
reannounce(){
  local address
  address="$(ip -4 -o addr show dev eth1 scope global | awk 'NR==1 {print $4}')"
  [ -n "$address" ] || { err 'Docker eth1 has no IPv4 address'; exit 1; }
  ip addr change "$address" dev eth1 valid_lft forever preferred_lft forever
  log "Network: re-announced Docker eth1 $address"
}
wait_listeners(){
  local n
  for ((n=0;n<${NETWORK_WAIT:-30};n++)); do
    if [ "$(ss -H -lnt | grep -Ec ':(12100|12103) ')" -eq 2 ]; then
      log 'Network: stock TCP 12100 and HTTP 12103 are listening'
      return 0
    fi
    sleep 1
  done
  err "Network services did not bind within ${NETWORK_WAIT:-30}s; inspect the player log"
  exit 1
}
case "${1:-prepare}" in
  prepare)
    mkdir -p "$ROOTFS/emu/original-commands"
    if guest_netns >/dev/null; then
      :   # NETWORK=isolated: the guest sees only links made by emulator.runtime.network
    else
      [ -e /sys/class/net/eth1/address ] || {
        err 'eth1 missing: run docker compose up -d (Compose >= 2.36), then setup/boot'; exit 1;
      }
      mkdir -p "$ROOTFS/sys/class/net/eth1"
      cp /sys/class/net/eth1/{address,operstate} "$ROOTFS/sys/class/net/eth1/"
    fi
    # WLAN0=1: an emulated Wi-Fi interface (dummy link + sysfs stub); WLAN0=0 removes it;
    # empty leaves whatever exists. State and address are applied only when given: in a
    # shared guest runtime changes survive the next boot, while an isolated guest gets a
    # new, empty namespace at every boot and needs them again (docs/network.md).
    case "${WLAN0:-}" in
      1)
        wlan=(link wlan0)
        [ -z "${WLAN0_STATE:-}" ] || wlan+=(--state "$WLAN0_STATE")
        [ -z "${WLAN0_ADDR:-}" ] || wlan+=(--addr "$WLAN0_ADDR")
        [ -z "${WLAN0_MAC:-}" ] || wlan+=(--mac "$WLAN0_MAC")
        python3 -B -m emulator.runtime.network "${wlan[@]}" >/dev/null ;;
      0) python3 -B -m emulator.runtime.network unlink wlan0 >/dev/null ;;
      '') ;;
      *) err 'WLAN0 must be 1, 0 or empty'; exit 1 ;;
    esac
    # Preserve originals once, replace paths atomically (never follow BusyBox
    # symlinks with cp: that would overwrite /bin/busybox itself).
    for path in sbin/ip sbin/ifconfig sbin/route sbin/udhcpc sbin/hwclock \
                usr/sbin/ntpd usr/bin/ntpdate usr/bin/curl usr/bin/wget \
                usr/sbin/wpa_supplicant usr/sbin/wpa_cli; do
      name="${path##*/}"
      if [ -e "$ROOTFS/$path" ] || [ -L "$ROOTFS/$path" ]; then
        if [ ! -e "$ROOTFS/emu/original-commands/$name" ]; then
          cp -L "$ROOTFS/$path" "$ROOTFS/emu/original-commands/$name"
        fi
        cp "$REPO/emulator/scripts/guest-command.sh" "$ROOTFS/$path.emu-new"
        chmod 755 "$ROOTFS/$path.emu-new"
        mv -f "$ROOTFS/$path.emu-new" "$ROOTFS/$path"
      fi
    done
    ;;
  announce)
    # Stock network_detect_thread subscribes to NEWADDR, but never requests a
    # dump of addresses which already existed before boot. Re-announce the SAME
    # address after subscription; no down/up, DHCP or default-route edits.
    for ((n=0;n<40;n++)); do
      if grep -q 'Network detect thread started' "$WORK/mq_player.log"; then break; fi
      sleep 1
    done
    grep -q 'Network detect thread started' "$WORK/mq_player.log" || {
      err 'network detector did not start'; exit 1;
    }
    reannounce
    wait_listeners
    ;;
  reannounce) reannounce ;;   # stock-init supervisor: once per mq_player start
  wait) wait_listeners ;;
  *) err 'usage: 16_network.sh [prepare|announce|reannounce|wait]'; exit 2 ;;
esac
