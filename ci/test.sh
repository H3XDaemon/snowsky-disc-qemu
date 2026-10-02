#!/usr/bin/env bash
# Firmware-free checks, run inside the same image as the emulator.
set -euo pipefail
cd /repo
while IFS= read -r -d '' script; do bash -n "$script"; done < <(
  find emulator viewer controller library firmware research experiments tests ci -type d \
    \( -name sdcard -o -name rootfs -o -name work -o -name .venv -o -name __pycache__ \) -prune -o \
    -type f -name '*.sh' -print0
)
python3 -B -m ci.unit
mapfile -d '' js_tests < <(find emulator/tests viewer/tests controller/tests firmware/tests research/diagnostics/tests experiments/browser/tests experiments/disc_web/tests tests -type f -name 'test_*.js' -print0 | sort -z)
[ "${#js_tests[@]}" -gt 0 ]
node --test "${js_tests[@]}"
bash emulator/shims/build_shims.sh
