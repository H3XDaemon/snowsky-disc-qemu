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
B="$ROOTFS/sys/class/power_supply/cw221X-bat"
if [ -d "$B" ]; then
  if [ "$(cat "$ROOTFS/emu/usb-connected" 2>/dev/null || true)" = 1 ]; then
    printf 'Charging\n' > "$B/status"
  else
    printf 'Discharging\n' > "$B/status"
  fi
fi
