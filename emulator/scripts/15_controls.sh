#!/usr/bin/env bash
# Hardware state used by physical controls. No real host sysfs is mounted here.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; source "$HERE/lib.sh"
mkdir -p "$ROOTFS/sys/bus/platform/drivers/pwm-backlight/backlight/backlight/backlight" "$ROOTFS/emu"
printf '20\0\0' > "$ROOTFS/sys/bus/platform/drivers/pwm-backlight/backlight/backlight/backlight/brightness"
printf '11' > "$ROOTFS/emu/volume-buttons"
# Raw pin levels for static guest programs: /dev/mem page of GPIO port B (see keys.md).
python3 -B -m emulator.runtime.gpio reset >/dev/null
printf '\377' > "$ROOTFS/emu/fb-live"
printf '0' > "$ROOTFS/emu/power-request"
# Guest-visible /proc/<pid>/exe names the guest program, not qemu (fbshim): stock-init default.
printf '%s' "${PROC_EXE:-0}" > "$ROOTFS/emu/proc-exe"
: > "$ROOTFS/dev/cst816t"
: > "$ROOTFS/dev/lcd_st77916"
# The output stream as /proc/asound/card0 shows it on the player (pcm3p), kept by tinyshim
# under /emu/asound because a real procfs cannot be extended; and its audible/silent marker.
mkdir -p "$ROOTFS/emu/asound/card0/pcm3p/sub0"
printf 'x2000\n' > "$ROOTFS/emu/asound/card0/id"
printf 'closed\n' > "$ROOTFS/emu/asound/card0/pcm3p/sub0/status"
printf 'closed\n' > "$ROOTFS/emu/asound/card0/pcm3p/sub0/hw_params"
printf 'c' > "$ROOTFS/emu/audio-state"
# CS43131 attenuation registers, initialized muted until firmware configures the DAC.
printf '\377' > "$ROOTFS/emu/dac-left"
printf '\377' > "$ROOTFS/emu/dac-right"

# V2.57's native idle-power gate consumes ADC1 + AW35615 sink-role detection,
# not the battery status string. fbshim implements only this reviewed power ABI.
printf '0' > "$ROOTFS/emu/usb-power-supported"
if firmware_supports usb_power; then
  for d in jz_adc_aux_0 jz_adc_aux_1 jz_adc_aux_2 jz_adc_aux_3 aw35615 sgm41513; do
    : > "$ROOTFS/dev/$d"
  done
  printf '1' > "$ROOTFS/emu/usb-power-supported"
fi
# Keep cable state across guest restarts; no USB gadget/role-switch events.
# USB_POWER=1|0 sets the cable for this and later boots; empty keeps the stored state.
case "${USB_POWER:-}" in
  1|0) printf '%s' "$USB_POWER" > "$ROOTFS/emu/usb-connected" ;;
  '') ;;
  *) err "USB_POWER must be 1, 0 or empty"; exit 1 ;;
esac
# JACK=3.5|4.4|none turns the analog-output model on and sets what is plugged; off removes
# it (stock then sees the original unmodelled pins); empty keeps the stored state.
case "${JACK:-}" in
  3.5) printf '3' > "$ROOTFS/emu/jack" ;;
  4.4) printf '4' > "$ROOTFS/emu/jack" ;;
  none) printf 'n' > "$ROOTFS/emu/jack" ;;
  off) rm -f "$ROOTFS/emu/jack" ;;
  '') ;;
  *) err "JACK must be 3.5, 4.4, none, off or empty"; exit 1 ;;
esac
B="$ROOTFS/sys/class/power_supply/cw221X-bat"
# The player's gauge (BATTERY_PROFILE=device, type Mains) has no status attribute.
if [ -d "$B" ] && [ "$(cat "$B/type" 2>/dev/null)" != Mains ]; then
  if [ "$(cat "$ROOTFS/emu/usb-connected" 2>/dev/null || true)" = 1 ]; then
    printf 'Charging\n' > "$B/status"
  else
    printf 'Discharging\n' > "$B/status"
  fi
fi
