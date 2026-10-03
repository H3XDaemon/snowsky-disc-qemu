#!/usr/bin/env bash
# Prepare the runtime environment so the MIPS firmware can boot to its main UI
# under qemu-user. Idempotent: safe to re-run (e.g. after a container restart,
# which clears mounts + binfmt).
#
# Encodes every non-obvious fix required to reach the main screen — see emulator/docs/emulation.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
[ -d "$ROOTFS" ] || { err "no rootfs at $ROOTFS — run 00_extract_rootfs.sh first"; exit 1; }
verify_firmware  # reject wrong volume/build before mutations, patching or priming boot
kill_guest  # never overwrite mapped shims or prepare SD while firmware is running
bash "$REPO/emulator/scripts/16_network.sh" prepare

# 1) binfmt_misc: register ONLY the mipsel interpreter, with a mask that ignores
#    ELF bytes 6-15 so it matches every MIPS32 LE guest binary (busybox etc.) but
#    NOTHING else. Do NOT use `qemu-binfmt --reset -p yes`: it registers qemu-aarch64
#    too and hijacks the host's own native binaries -> "exec format error".
log "binfmt_misc: mipsel interpreter"
mountpoint -q /proc/sys/fs/binfmt_misc || mount -t binfmt_misc none /proc/sys/fs/binfmt_misc 2>/dev/null || true
MAGIC='\x7f\x45\x4c\x46\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x08\x00'
MASK='\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xfe\xff\xff\xff'
# Flags: F opens the interpreter at registration (it works inside the chroot); P hands the
# caller's argv[0] to qemu (AT_FLAGS_PRESERVE_ARGV0, Linux 5.12+, honoured by qemu 7.2), as
# the player's kernel keeps it. Without P every guest program saw its file's path as argv[0].
# Older printf used the registration as its FORMAT: embedded NULs truncated the
# magic at byte 6 and accidentally matched i386 as well. Repair only our entry; an entry
# registered without P by an older checkout is replaced too (the entry is shared by every
# container of the Docker VM, so this changes argv[0] for their next execs as well).
if [ -e /proc/sys/fs/binfmt_misc/qemu-mipsel ] && ! python3 -c '
from pathlib import Path
p = Path("/proc/sys/fs/binfmt_misc/qemu-mipsel").read_text().splitlines()
raise SystemExit(not ({"magic 7f454c4601010000000000000000000002000800",
                      "mask ffffffffffff00000000000000000000feffffff", "flags: PF"} <= set(p)))
'; then
  printf '%s\n' -1 > /proc/sys/fs/binfmt_misc/qemu-mipsel
fi
if [ ! -e /proc/sys/fs/binfmt_misc/qemu-mipsel ]; then
  printf '%s' ":qemu-mipsel:M::${MAGIC}:${MASK}:${QEMU}:FP" > /proc/sys/fs/binfmt_misc/register \
    && log "  registered (argv[0] preserved)" || err "  registration failed (already present?)"
fi

# 2) Build + install the framebuffer/input ioctl shim.
log "Building shims"
"$REPO/emulator/shims/build_shims.sh"
cp "$WORK/fbshim.so" "$ROOTFS/lib/fbshim.so"
cp "$WORK/asndshim.so" "$ROOTFS/lib/asndshim.so"      # ALSA interposer  (USB/BT path capture)
cp "$WORK/tinyshim.so" "$ROOTFS/lib/tinyshim.so"      # tinyalsa interposer (LOCAL DAC path -> /audio.pcm)
cp "$REPO/emulator/shims/asound.cards" "$ROOTFS/etc/asound.cards" # x2000 card discovery via tinyshim fopen
printf '/lib/fbshim.so\n/lib/asndshim.so\n/lib/tinyshim.so\n' > "$ROOTFS/etc/ld.so.preload"   # guest ld.so reads this (LD_PRELOAD won't survive popen)

# 2b) Enable physical-key handling: mq_player gates keys on a flag that isn't set headless.
#     Patch the guard so injected event0 keys reach the dispatcher (research/docs/methods.md). KEYS_ENABLE=0 to skip.
"$REPO/emulator/scripts/patch_keys.sh"
bash "$REPO/emulator/scripts/15_controls.sh"

# 3) Kernel filesystems the guest expects.
log "Mounts: /proc, /dev/mqueue in rootfs"
mkdir -p "$ROOTFS/proc" "$ROOTFS/dev/mqueue"
mountpoint -q "$ROOTFS/proc"       || mount -t proc   proc "$ROOTFS/proc"       2>/dev/null || true
mountpoint -q "$ROOTFS/dev/mqueue" || mount -t mqueue none "$ROOTFS/dev/mqueue" 2>/dev/null || true

# 3b) Optional: /usr/data as its own size-limited filesystem, like the player's userdata
#     partition (83 MiB of NAND under UBIFS). USERDATA_MB creates the image once; from then
#     on the image is /usr/data for both boot modes. See emulator/docs/stock-init.md.
if [ -n "${USERDATA_MB:-}" ] && [ ! -f "$USERDATA_IMG" ]; then
  [[ "$USERDATA_MB" =~ ^[0-9]+$ ]] && [ "$USERDATA_MB" -ge 8 ] || { err "USERDATA_MB must be a size in MiB (>= 8)"; exit 1; }
  log "/usr/data: new ${USERDATA_MB} MiB ext4 image $USERDATA_IMG"
  truncate -s "${USERDATA_MB}M" "$USERDATA_IMG.new"
  mkfs.ext4 -q -F -m 0 -L userdata "$USERDATA_IMG.new"
  mv "$USERDATA_IMG.new" "$USERDATA_IMG"
  userdata_attach
  userdata_mount
  rmdir "$ROOTFS/usr/data/lost+found"   # the player's partition starts empty
fi
userdata_attach
userdata_mount

# 4) /dev stubs. fb0 is a plain file (qemu mmaps it fine). event0/event1 are plain
#    files we append input_event structs to; their driver "name" is read from sysfs.
log "/dev stubs: fb0, input/event0 (x2000_key), input/event1 (cst816t)"
head -c $((SCR_W*SCR_VY*4)) /dev/zero > "$ROOTFS/dev/fb0"
mkdir -p "$ROOTFS/dev/input" \
         "$ROOTFS/sys/class/input/event0/device" \
         "$ROOTFS/sys/class/input/event1/device"
: > "$ROOTFS/dev/input/event0"; : > "$ROOTFS/dev/input/event1"
echo x2000_key > "$ROOTFS/sys/class/input/event0/device/name"   # GPIO keys
echo cst816t   > "$ROOTFS/sys/class/input/event1/device/name"   # capacitive touch

# char-device stubs mq_player opens. fbshim handles volume GPIO reads; other missing
# hardware ioctls still fail. Without /dev/gpio, mq_player aborts BEFORE it
# inits the DAC and pushes UI state, so the UI never leaves the splash.
: > "$ROOTFS/dev/gpio"
: > "$ROOTFS/dev/jz_adc_aux_0"
: > "$ROOTFS/dev/jz_watchdog"
: > "$ROOTFS/dev/key_ioctl"   # physical-key handler (echo_key_handler); non-fatal but noisy
# CS43131 DAC control nodes: dac_control.c opens these; open must succeed (like /dev/gpio) so
# playback proceeds to tinyalsa (tinyshim captures). fbshim mirrors DAC volume writes.
for d in cs43131 cs43131b cs43131c cs43131d; do : > "$ROOTFS/dev/$d"; done

# SD card: a REAL FAT block device (not a bind). mq_ui (mount_storage_dev.c) UMOUNTS
# /tmp/sdcard once at startup — on hardware a hotplug handler remounts the card, but under
# emulation nothing does, so a plain bind (or the initial mount here) is torn down and the
# browser ends up empty. The robust fix is to re-mount AFTER that boot-time umount: build a
# FAT image from ./emulator/sdcard, expose it as REAL nodes /dev/mmcblk0[p1] (so `[ -e /dev/mmcblk0 ]`
# passes and the guest can mount the partition), and let sd_mount() (lib.sh, called again at
# the end of 20_boot.sh + in 30_tap.sh) mount /dev/mmcblk0p1 -o iocharset=utf8 at both the
# guest rootfs path (content the browser scans on entry) and the container /tmp/sdcard (so
# /proc/mounts carries the exact "/tmp/sdcard" line FUN_004147ac scans for). The container
# /tmp/sdcard mount survives the guest's chrooted umount, so that line persists across boot.
# Rebuilt each setup so ./emulator/sdcard edits show up on the next boot.
IMG="$WORK/sdcard.img"
# Setup creates a new card; discard handles saved by viewer ejection.
rm -f "$ROOTFS/emu/sd-mmcblk0" "$ROOTFS/emu/sd-mmcblk0p1"
for m in "$ROOTFS/tmp/sdcard" /tmp/sdcard; do mountpoint -q "$m" && umount -l "$m" 2>/dev/null || true; done
for l in $(image_loops "$IMG"); do losetup -d "$l" 2>/dev/null || true; done
SD_CONTENT=""
# SDCARD_KEEP=1 keeps an existing card image (what the guest wrote to it) instead of
# rebuilding it from /sdcard; the first setup still builds it.
SD_KEEP=""
if [ "${SDCARD_KEEP:-0}" = 1 ] && [ -f "$IMG" ]; then SD_KEEP=1; SD_CONTENT=kept; fi
if [ -z "$SD_KEEP" ] && [ -d /sdcard ]; then
  # An empty card is valid. grep exits 1 when only the tracked placeholders exist,
  # which used to abort setup under errexit/pipefail before /usr/data was seeded.
  SD_CONTENT="$(find /sdcard -mindepth 1 -maxdepth 1 ! -name README.md ! -name .gitkeep -print -quit)"
  # An explicit size asks for a card even when the media folder is empty.
  [ -z "${SDCARD_MB:-}" ] || SD_CONTENT="${SD_CONTENT:-empty}"
fi
if [ -n "$SD_CONTENT" ]; then
  if [ -z "$SD_KEEP" ]; then
    # Default: content + 32 MiB of FAT with no partition table. SDCARD_MB sets the size,
    # SDCARD_FS=exfat the filesystem, SDCARD_PARTITION=1 an MBR with one partition like a
    # real card (emulator/docs/media-library.md). Long names are written as UTF-8.
    card=(--source /sdcard --fs "${SDCARD_FS:-vfat}")
    [ -z "${SDCARD_MB:-}" ] || card+=(--mb "$SDCARD_MB")
    [ "${SDCARD_PARTITION:-0}" != 1 ] || card+=(--partition)
    python3 -B -m emulator.runtime.card build "${card[@]}" >/dev/null
  fi
  # Expose as REAL device nodes (not symlinks): a symlink -> /dev/loop0 can't be resolved from
  # inside the guest's chroot (it has no /dev/loop0), so the guest's own `mount /dev/mmcblk0p1`
  # would fail. mknod with the loop's device numbers lets the guest mount the card directly.
  LOOP="$(python3 -B -m emulator.runtime.card insert)"
  sd_mount   # mount /dev/mmcblk0p1 -o iocharset=utf8 at rootfs + container /tmp/sdcard (lib.sh)
  [ -z "$SD_KEEP" ] || log "SD: kept the existing card image (SDCARD_KEEP=1)"
  log "SD: $(python3 -B -m emulator.runtime.card show) on $LOOP as /dev/mmcblk0p1, mounted at /tmp/sdcard"
else
  rm -f "$ROOTFS/dev/mmcblk0" "$ROOTFS/dev/mmcblk0p1"    # no card
fi

# 5) Battery fuel gauge (cw2215). Without a healthy capacity the UI shows the
#    "battery too low, shutting down" countdown instead of booting.
#    BATTERY_PROFILE=device gives the player's attribute set (type Mains, current_now,
#    cycle_count, no status/online); BATTERY_CAPACITY / BATTERY_VOLTAGE_UV / BATTERY_TEMP
#    choose the values (percent, microvolts, 0.1 degC). See emulator/docs/environment.md.
log "Battery sysfs: cw221X-bat, ${BATTERY_PROFILE:-legacy} layout, ${BATTERY_CAPACITY:-100}%"
python3 -B -m emulator.runtime.battery prepare --profile "${BATTERY_PROFILE:-legacy}" \
  ${BATTERY_CAPACITY:+--capacity "$BATTERY_CAPACITY"} ${BATTERY_VOLTAGE_UV:+--voltage "$BATTERY_VOLTAGE_UV"} \
  ${BATTERY_TEMP:+--temp "$BATTERY_TEMP"} >/dev/null

# 5b) Seed /usr/data as the device's first boot does. On hardware /usr/data is a blank
#     UBIFS partition that init scripts S98FIIO + fiio_init.sh populate from templates
#     shipped in the rootfs. We don't run init, so replicate the essential parts — above
#     all the zlog configs: without them mq_player's zlog_init() fails ("Error: zlog_init"),
#     the backend never starts, and sysconfig.db is never created (UI stays on the splash).
log "Seeding /usr/data (zlog configs + db templates), like S98FIIO/fiio_init.sh"
mkdir -p "$ROOTFS/usr/data/fiio/log" "$ROOTFS/usr/data/fiio/db" "$ROOTFS/usr/data/fiio/wifi"
cp -f "$ROOTFS/usr/project/config/zlog_player.conf" "$ROOTFS/usr/data/fiio/log/" 2>/dev/null || err "  zlog_player.conf template missing"
cp -f "$ROOTFS/usr/project/config/zlog_ui.conf"     "$ROOTFS/usr/data/fiio/log/" 2>/dev/null || err "  zlog_ui.conf template missing"
cp -f "$ROOTFS"/usr/project/db/*          "$ROOTFS/usr/data/fiio/db/"   2>/dev/null || true  # dic.db etc.
cp -f "$ROOTFS"/usr/project/config/wifi/* "$ROOTFS/usr/data/fiio/wifi/" 2>/dev/null || true
cp -f "$ROOTFS/etc/hostapd.conf"          "$ROOTFS/usr/data/"           2>/dev/null || true

# 6) Config DB: disable the boot logo animation (on V2.40 an infinite-loop overlay drawn on
#    top of the already-built main screen that never cleared under emu; V2.57 shows the
#    screen regardless, see emulator/docs/emulation.md).
#    /usr/data is a SEPARATE UBIFS partition on the device (S21mount_ubifs) and is empty
#    in the squashfs, so on a fresh rootfs sysconfig.db does not exist yet — mq_player
#    creates it on first boot with LOCAL_IMG_ANIM=1. We must prime it (one throwaway boot
#    to create the DB) BEFORE we can set the flag; otherwise the very first real boot is
#    stuck on the splash. Idempotent: skipped once the DB exists.
DB="$ROOTFS/usr/data/fiio/db/sysconfig.db"
if [ ! -f "$DB" ]; then
  log "sysconfig.db absent (fresh /usr/data) — priming boot to create it (~20s)..."
  apply_ulimits
  rm -f "$ROOTFS/dev/mqueue/"* 2>/dev/null || true
  guest_run 45 /usr/bin/mq_ui     >/dev/null 2>&1 &
  sleep 3
  guest_run 42 /usr/bin/mq_player >/dev/null 2>&1 &
  for i in $(seq 1 35); do [ -f "$DB" ] && break; sleep 1; done
  kill_guest
  [ -f "$DB" ] && log "  sysconfig.db created" || err "  DB still absent after priming (see $WORK/*.log)"
  # The priming pair unmounted the card (and may or may not have mounted it again).
  if sd_node >/dev/null; then sd_mount; fi
fi
if [ -f "$DB" ]; then
  # LANGUAGE is a 0-based index (switch in mq_ui FUN_004776e4): 0 zh(简体) 1 tw(繁體) 2 en
  # 3 ja 4 ko 5 es 6 it 7 de 8 pt 9 ru. Any in-range value ALSO skips the first-boot language
  # wizard (the wizard shows only while LANGUAGE is out of range, e.g. the fresh default 100).
  # The default profile sets LOCAL_IMG_ANIM=0, BATTERY=100 and LANGUAGE=$LANG_CODE (default 2 =
  # English). SETTINGS_PROFILE selects another preset from emulator/settings/ (e.g. factory =
  # what stock created, untouched); SETTINGS="COLUMN=INT,..." adds single values.
  export LANG_CODE="${LANG_CODE:-2}"
  SETTINGS_RESULT="$(python3 -B -m emulator.runtime.settings apply)" || { err "  settings were not applied"; exit 1; }
  log "sysconfig.db: $SETTINGS_RESULT"
else
  err "  could not create/find sysconfig.db — first real boot may stay on the splash"
fi

# 7) Serial number. The player keeps a 14-character SN in /usr/data/fiio/sn.txt; a fresh
#    emulated /usr/data has none. DEVICE_SN writes one; empty leaves the file as it is.
if [ -n "${DEVICE_SN:-}" ]; then
  [[ "$DEVICE_SN" =~ ^[0-9A-Za-z]{14}$ ]] || { err "DEVICE_SN must be 14 letters or digits"; exit 1; }
  printf '%s\n' "$DEVICE_SN" > "$ROOTFS/usr/data/fiio/sn.txt"
  log "Serial number: $DEVICE_SN"
fi

log "Environment ready. Next: emulator/scripts/20_boot.sh"
