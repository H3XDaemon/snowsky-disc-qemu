#!/usr/bin/env bash
# Use a prepared rootfs image as the guest rootfs: a squashfs, optionally zero-padded
# to the flash partition (e.g. a 100 MiB review image that adds a boot layer to the
# stock V2.57 rootfs). The six stock binaries must still match the selected profile;
# emulator stubs and patches are applied on top by 10_setup_env.sh as usual.
# Never replaces an existing rootfs: use a separate work volume for each image.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
IMAGE="${1:?usage: 01_image_rootfs.sh <rootfs image: .squashfs or padded .bin>}"
[ -f "$IMAGE" ] || { err "no image file $IMAGE"; exit 1; }
[ ! -e "$ROOTFS" ] && [ ! -L "$ROOTFS" ] || { err "Rootfs already exists; use a new isolated work volume"; exit 1; }
[ "$(head -c 4 "$IMAGE")" = hsqs ] || { err "$IMAGE is not a little-endian squashfs"; exit 1; }
log "Extracting image rootfs -> $ROOTFS"
mkdir -p "$WORK"
rm -rf "$ROOTFS.new"
unsquashfs -no-progress -no-xattrs -d "$ROOTFS.new" "$IMAGE" >/dev/null
# Fail closed on anything but the selected stock build underneath the additions.
python3 -B -m firmware.profile validate "$ROOTFS.new" --version "$FW_VERSION" || {
  rm -rf "$ROOTFS.new"; err "Image is not built on stock V$FW_VERSION"; exit 1;
}
mv "$ROOTFS.new" "$ROOTFS"
printf '{"image": "%s", "sha256": "%s", "bytes": %s}\n' "$(basename "$IMAGE")" \
  "$(sha256sum "$IMAGE" | cut -d' ' -f1)" "$(stat -c %s "$IMAGE")" > "$WORK/rootfs-image.json"
log "Done ($(cat "$WORK/rootfs-image.json")). Next: emulator/scripts/10_setup_env.sh"
