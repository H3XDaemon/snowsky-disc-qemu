#!/usr/bin/env bash
# Shared paths + helpers for the Snowsky Disc qemu emulation scripts.
# Sourced by the numbered scripts. Run everything INSIDE the container.
set -euo pipefail

# --- paths -------------------------------------------------------------------
WORK="${WORK:-/work}"                 # persistent state (mount a host dir/volume here)
ROOTFS="${ROOTFS:-$WORK/rootfs}"      # extracted firmware rootfs
REPO="${REPO:-/repo}"                 # this repository (mounted)
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"
SHOTS="${SHOTS:-$WORK/shots}"         # captured PNG framebuffers
# The interpreter: the image's rebuilt qemu (emulator/docker/qemu, answers the device ioctls
# of static programs) when present, else Debian's. QEMU=/usr/bin/qemu-mipsel-static selects
# Debian's explicitly; the binfmt entry follows the choice (10_setup_env.sh).
if [ -z "${QEMU:-}" ] && [ -x /usr/local/bin/qemu-mipsel-static ]; then QEMU=/usr/local/bin/qemu-mipsel-static; fi
QEMU="${QEMU:-/usr/bin/qemu-mipsel-static}"
# What binfmt registers: the rebuilt qemu's own file lives in a directory named after its
# build (/usr/local/lib/qemu-mipsel-<sha256 prefix>/), so a rebuilt image shows a new path
# where the kernel would otherwise keep running the file it opened at the first registration.
QEMU_INTERPRETER="$(readlink -f "$QEMU" 2>/dev/null || printf '%s' "$QEMU")"
# Whether this interpreter can answer /dev/fb0 and /dev/input ioctls for static programs.
qemu_has_devices(){ "$QEMU" -version 2>/dev/null | grep -q snowsky-disc-devices; }

# Explicit runtime selection, defaulting to the reviewed active build. Pins live in firmware/v*.json.
export FW_VERSION="${FW_VERSION:-$(cat "$REPO/firmware/active-version")}"
firmware_supports(){ python3 -B -m firmware.profile supports "$1" --version "$FW_VERSION"; }
verify_firmware(){ python3 -B -m firmware.profile validate "$ROOTFS" --version "$FW_VERSION"; }

# Screen geometry (360x360 round panel, 32bpp; virtual y = 3 sub-buffers).
SCR_W=360; SCR_H=360; SCR_VY=1080

log(){ printf '\033[1;36m[*]\033[0m %s\n' "$*"; }
err(){ printf '\033[1;31m[!]\033[0m %s\n' "$*" >&2; }

# Raise the two limits qemu-user needs, in the current shell.
apply_ulimits(){
  ulimit -q 268435256 2>/dev/null || ulimit -q unlimited 2>/dev/null || true  # RLIMIT_MSGQUEUE
  ulimit -n 65536      2>/dev/null || true                                    # RLIMIT_NOFILE
}

# Stop only processes chrooted into this guest, including its popen children.
# Do not pkill every qemu process: another rootfs may be running in this container.
kill_guest(){
  ROOTFS="$ROOTFS" python3 -m emulator.runtime.power_watch stop >/dev/null   # no-op unless POWER_WATCH started one
  ROOTFS="$ROOTFS" python3 -m emulator.runtime.keys stop
}

# qemu-user shares the Docker VM kernel. Firmware children must not reconfigure
# interfaces, set wall/RTC clocks, reboot the VM, or load modules. Keep SYS_ADMIN
# for the existing guest SD mount workflow; this is not a complete sandbox.
# TTL 0 means no limit (coreutils timeout). A guest booted through stock init
# (BOOT_MODE=init) lives in its own PID/IPC/UTS namespaces: commands join them, so
# guest pgrep/killall, /proc and message queues agree with the running programs.
# With NETWORK=isolated the guest also has its own network namespace (both boot modes).
# The program is first checked for the player's FPU trap, which qemu-user cannot show
# (fpu_guard below).
guest_run(){
  local ttl="$1" init net enter=(); shift
  fpu_guard "$@" || return 126
  local confined=(timeout "$ttl" setpriv
    --bounding-set=-net_admin,-sys_time,-sys_boot,-sys_module,-sys_rawio
    --no-new-privs chroot "$ROOTFS" "$@")
  if net="$(guest_netns)"; then enter+=(--net="/run/netns/$net"); fi
  if init="$(guest_init_pid)"; then enter+=(--target "$init" --pid --ipc --uts --time); fi
  if [ "${#enter[@]}" -gt 0 ]; then
    nsenter "${enter[@]}" -- "${confined[@]}"
  else
    "${confined[@]}"
  fi
}

# A hard-float program with a non-executable stack runs here and dies on the player
# (emulator/runtime/abi.py). FPU_GUARD=reject (default) refuses to start it, warn only
# says so, off skips the check. Stock programs pass: they have an executable stack.
fpu_guard(){
  local program="$1"
  [ "${FPU_GUARD:-reject}" != off ] || return 0
  if [ "${program##*/}" = qemu-mipsel-static ]; then      # explicit qemu [-0 argv0] PROGRAM
    shift
    while [ "${1:-}" = -0 ] && [ "$#" -ge 2 ]; do shift 2; done   # a lone trailing -0 is left to qemu
    program="${1:-}"
  fi
  case "$program" in /*) ;; *) return 0 ;; esac
  # --root: links are followed inside the guest, as chroot will.
  python3 -B -m emulator.runtime.abi check --root "$ROOTFS" "$program" || [ "${FPU_GUARD:-reject}" = warn ]
}

# Name of the guest's own network namespace (NETWORK=isolated), else failure.
guest_netns(){
  local name
  [ -r "$ROOTFS/emu/netns" ] && read -r name < "$ROOTFS/emu/netns" || return 1
  [ -n "$name" ] && [ -e "/run/netns/$name" ] || return 1
  printf '%s' "$name"
}

# PID (as this container sees it) of a live stock-init guest's PID 1, else failure.
guest_init_pid(){
  local pid
  [ -r "$ROOTFS/emu/init.pid" ] && read -r pid < "$ROOTFS/emu/init.pid" || return 1
  [[ "$pid" =~ ^[0-9]+$ ]] && grep -qa 'emulator.runtime.guest_init' "/proc/$pid/cmdline" 2>/dev/null || return 1
  printf '%s' "$pid"
}

# What a power-on finds: blank framebuffer, no queued input, reset control markers.
board_reset(){
  bash "$REPO/emulator/scripts/15_controls.sh"
  rm -f "$ROOTFS/dev/mqueue/"* 2>/dev/null || true
  head -c $((SCR_W*SCR_VY*4)) /dev/zero > "$ROOTFS/dev/fb0"
  : > "$ROOTFS/dev/input/event1"; : > "$ROOTFS/dev/input/event0"
}

# After a stock-init session the rootfs still carries that guest's dead /proc and
# RAM filesystems; the direct boot expects the container's own proc and mqueue.
guest_view_direct(){
  [ -e "$ROOTFS/emu/machine.json" ] || [ -e "$ROOTFS/emu/init.pid" ] || return 0
  ROOTFS="$ROOTFS" python3 -B -c 'import os; from emulator.runtime import machine
machine.restore_view(os.environ["ROOTFS"]); (machine.Path(os.environ["ROOTFS"]) / machine.STATE).unlink(missing_ok=True)'
}

# Loop devices of THIS container's image file. Loop devices are shared by every
# container of the Docker VM, and `losetup -j` falls back to comparing the path
# text when the file does not exist: on a fresh volume that names other
# containers' /work/*.img loops. Never ask about a file that is not there.
image_loops(){
  [ -f "$1" ] || return 0
  losetup -j "$1" 2>/dev/null | cut -d: -f1
}

# Attach an image to a free loop device and print its path. The container's /dev is a
# snapshot taken when it started: a loop device the VM creates now has no node here.
loop_attach(){
  local loop; loop="$(losetup -f)"
  [ -b "$loop" ] || mknod "$loop" b 7 "${loop##*loop}"
  losetup "$loop" "$1"
  printf '%s\n' "$loop"
}

# --- /usr/data as its own filesystem -------------------------------------------
# With USERDATA_MB, 10_setup_env.sh creates $WORK/userdata.img (ext4, the size of
# the player's userdata partition). Once the image exists it IS /usr/data: a loop
# device behind the guest node /dev/ubi1_0, mounted inside the chroot.
USERDATA_IMG="$WORK/userdata.img"
userdata_attach(){
  [ -f "$USERDATA_IMG" ] || return 0
  local loop
  loop="$(image_loops "$USERDATA_IMG" | head -n1)"
  [ -n "$loop" ] || loop="$(loop_attach "$USERDATA_IMG")"
  if [ "$(stat -c '%t:%T' "$ROOTFS/dev/ubi1_0" 2>/dev/null)" != "$(stat -c '%t:%T' "$loop")" ]; then
    rm -f "$ROOTFS/dev/ubi1_0"
    mknod "$ROOTFS/dev/ubi1_0" b 7 "${loop##*loop}"
  fi
}
userdata_detach(){
  local loop
  if mountpoint -q "$ROOTFS/usr/data"; then umount "$ROOTFS/usr/data"; fi
  for loop in $(image_loops "$USERDATA_IMG"); do losetup -d "$loop"; done
  rm -f "$ROOTFS/dev/ubi1_0"
}
userdata_mount(){
  [ -b "$ROOTFS/dev/ubi1_0" ] || return 0
  mountpoint -q "$ROOTFS/usr/data" || guest_run 20 /bin/mount -t ext4 /dev/ubi1_0 /usr/data
}

# --- SD card -----------------------------------------------------------------
# The firmware's mq_ui (util/src/mount_storage_dev.c) UMOUNTS /tmp/sdcard once at
# startup: on hardware a hotplug handler then remounts the card, but under emulation
# nothing does, so /tmp/sdcard ends up empty and the File Browser shows nothing.
# The File Browser scans /tmp/sdcard *live on entry*, so all we have to do is keep
# the card mounted. sd_mount() (re-)mounts /dev/mmcblk0p1 exactly like the guest would
# (`mount -o iocharset=utf8`) at BOTH the guest rootfs path (content the browser reads)
# and the container's own /tmp/sdcard (so /proc/mounts carries the exact "/tmp/sdcard"
# line FUN_004147ac scans for). Idempotent; a no-op when there is no card. Call it
# after the boot-time umount (end of 20_boot.sh) and before injecting taps (30_tap.sh).
sd_node(){ [ -b "$ROOTFS/dev/mmcblk0p1" ] && printf '%s' "$ROOTFS/dev/mmcblk0p1"; }
sd_mount(){
  local node; node="$(sd_node)" || return 0
  [ -n "$node" ] || return 0
  mkdir -p "$ROOTFS/tmp/sdcard" /tmp/sdcard
  # The scanner checks access(source) for each /proc/mounts entry. A mount made
  # with the container path /work/rootfs/dev/mmcblk0p1 leaves that inaccessible
  # source string in the guest's mount table. Mount INSIDE chroot so the source
  # is /dev/mmcblk0p1, accessible to both the scanner and Browse files.
  if mountpoint -q "$ROOTFS/tmp/sdcard" &&
     [ "$(findmnt -n -o SOURCE --target "$ROOTFS/tmp/sdcard")" = "$node" ]; then
    umount "$ROOTFS/tmp/sdcard" || { err 'SD source migration busy; stop guest first'; return 1; }
  fi
  local type; type="$(blkid -o value -s TYPE "$node" 2>/dev/null)"; type="${type:-vfat}"   # vfat or exfat
  mountpoint -q "$ROOTFS/tmp/sdcard" || \
    guest_run 10 /bin/mount -t "$type" -o iocharset=utf8 /dev/mmcblk0p1 /tmp/sdcard
  mountpoint -q /tmp/sdcard          || mount -t "$type" -o iocharset=utf8 "$node" /tmp/sdcard          2>/dev/null || true
  # Both mmc nodes alias one loop device. Stock blkid enumeration initially
  # caches only mmcblk0, while hotplug runs `blkid | grep /dev/mmcblk0p1`.
  # Probe the partition explicitly so stock remove/add can remount it itself.
  # Keep real filesystem detection and its cache; do not synthesize blkid output.
  sd_probe
}

sd_probe(){
  guest_run 10 /sbin/blkid /dev/mmcblk0p1 >/dev/null || {
    err 'SD filesystem discovery failed'; return 1;
  }
}

# Convert a screen (as-you-see-it) coordinate to the raw touch coordinate.
# The panel + LVGL display are rotated 180deg; the touch path applies no rotation,
# so tap points must be flipped: raw = 359 - displayed.  (see emulator/docs/touch.md)
rot(){ echo $(( (SCR_W-1) - $1 )) $(( (SCR_H-1) - $2 )); }
