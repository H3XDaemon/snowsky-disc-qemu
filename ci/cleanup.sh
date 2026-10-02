#!/usr/bin/env bash
# Inside ONLY the disposable CI container, before removing its work volume.
set -euo pipefail
source /repo/emulator/scripts/lib.sh
bash /repo/emulator/scripts/99_stop.sh
for target in "$ROOTFS/tmp/sdcard" /tmp/sdcard; do
  if mountpoint -q "$target"; then umount "$target"; fi
done
for loop in $(image_loops "$WORK/sdcard.img"); do losetup -d "$loop"; done
userdata_detach   # no-op without a USERDATA_MB image
