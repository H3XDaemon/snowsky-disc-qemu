#!/bin/sh
# Installed only inside the emulated rootfs by 16_network.sh. Originals are kept
# in /emu/original-commands. This is NOT a security sandbox: guest capabilities
# are also restricted by guest_run() (including direct BusyBox invocations).
name=${0##*/}
case "$name" in
  ip)
    case "$*" in
      # The standalone firmware ip's address dump fails under qemu 7.2 with
      # EOPNOTSUPP; the stock BusyBox applet successfully reads the same kernel.
      'route show default'|'addr show eth1'|'addr show wlan0') exec /bin/busybox ip "$@" ;;
    esac ;;
  ifconfig)
    [ "$#" -eq 0 ] && exec /bin/busybox ifconfig ;;
esac
printf '[emu-network] blocked %s\n' "$name" >&2
exit 1
