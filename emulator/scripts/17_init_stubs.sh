#!/usr/bin/env bash
# Stub the commands stock init scripts call that cannot work in a container
# (kernel modules, mdev, interface setup, UBIFS, NFS/DHCP services). The scripts
# themselves stay stock. Idempotent; used by BOOT_MODE=init (emulator/docs/stock-init.md).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
mkdir -p "$ROOTFS/emu/original-commands"
for path in sbin/insmod sbin/rmmod sbin/mdev usr/bin/mount_ubifs.sh sbin/ifup sbin/ifdown \
            usr/sbin/rpcbind usr/sbin/rpc.statd usr/sbin/rpc.nfsd usr/sbin/rpc.mountd \
            usr/sbin/exportfs usr/sbin/dnsmasq; do
  name="${path##*/}"
  [ -e "$ROOTFS/$path" ] || [ -L "$ROOTFS/$path" ] || continue
  # Keep the stock regular files once; BusyBox applet links are restored with ln.
  if [ ! -L "$ROOTFS/$path" ] && [ ! -e "$ROOTFS/emu/original-commands/$name" ]; then
    cp "$ROOTFS/$path" "$ROOTFS/emu/original-commands/$name"
  fi
  # Replace the path atomically; never write through a BusyBox symlink.
  cp "$REPO/emulator/scripts/guest-init-stub.sh" "$ROOTFS/$path.emu-new"
  chmod 755 "$ROOTFS/$path.emu-new"
  mv -f "$ROOTFS/$path.emu-new" "$ROOTFS/$path"
done
