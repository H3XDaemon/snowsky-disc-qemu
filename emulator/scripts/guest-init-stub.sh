#!/bin/sh
# Installed only inside the emulated rootfs by 17_init_stubs.sh for BOOT_MODE=init.
# The stock init scripts run unchanged; these are the commands they call that need
# the player's kernel or radio. Each case is listed in emulator/docs/stock-init.md.
name=${0##*/}
note(){ printf '[emu-init] %s\n' "$*" >&2; }
case "$name" in
  insmod|rmmod)
    note "$name $1: no guest kernel, drivers are emulator stubs"; exit 0 ;;
  mdev)
    note "mdev $*: /dev is prepared by the emulator"
    case "$*" in *-d*) while :; do sleep 3600; done ;; esac
    exit 0 ;;
  mount_ubifs.sh)
    # S21mount_ubifs: `mount_ubifs.sh userdata /usr/data/`. No MTD/UBI here; with
    # USERDATA_MB the partition is a size-limited ext4 image behind /dev/ubi1_0.
    [ -b /dev/ubi1_0 ] || { note "/usr/data is a plain directory (no USERDATA_MB image)"; exit 0; }
    grep -q '^/dev/ubi1_0 /usr/data ' /proc/mounts && exit 0
    exec /bin/mount -t ext4 /dev/ubi1_0 "${2%/}" ;;
  ifup|ifdown)
    note "$name $*: the container owns the interfaces"; exit 0 ;;
  rpcbind|rpc.statd|rpc.nfsd|rpc.mountd|exportfs|dnsmasq)
    note "$name: network service not started in the emulator"; exit 0 ;;
esac
note "unexpected stub $name"
exit 1
