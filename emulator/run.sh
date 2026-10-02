#!/usr/bin/env bash
# Host-side orchestrator for the Snowsky Disc qemu emulator.
# Works on macOS or Linux with Docker installed. From the repository root:
#
#   ./emulator/run.sh up <ota_dir>       build/start, extract rootfs, set up environment
#   ./emulator/run.sh start              start the existing stopped service
#   ./emulator/run.sh shell              open an interactive container shell
#   ./emulator/run.sh up-image <image>   same, from a rootfs image built on the stock firmware
#   ./emulator/run.sh boot [--init] [--hold KEYS] [seconds]
#                                        boot and capture PNGs into shots/; --init boots through
#                                        stock rcS; KEYS (volume_up,volume_down,play) held at power-on
#   ./emulator/run.sh power <on|reboot|off|cut [--unsynced]|status>
#                                        power events without rebuilding /usr/data or the card
#   ./emulator/run.sh keys <hold|release|arm|show> [KEYS]
#                                        key pin levels; arm = held from the next power-on
#   ./emulator/run.sh tap <x> <y>        inject a tap and capture PNGs
#   ./emulator/run.sh view [port]        start the live viewer (default :8080)
#   ./emulator/run.sh capture [prefix]   capture the current framebuffer
#   ./emulator/run.sh audio              export capture into shots/audio.wav
#   ./emulator/run.sh diag               run touch diagnostics (leaves guests running)
#   ./emulator/run.sh wscheck [--control] compare WS/TCP (control leaves playback paused)
#   ./emulator/run.sh stop               stop guest processes
#   ./emulator/run.sh down               remove containers, keep the work volume
#   ./emulator/run.sh nuke               also delete the work volume
#   ./emulator/run.sh compose [ARGS]     explicit Compose access (profiles, logs, config)
#
# Configure emulator/.env; firmware preparation: firmware/README.md.
set -euo pipefail
EMULATOR_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$EMULATOR_DIR/.." && pwd)"

compose() {
  local env_file=/dev/null
  [[ ! -f "$EMULATOR_DIR/.env" ]] || env_file="$EMULATOR_DIR/.env"
  docker compose --project-directory "$REPO_DIR" --env-file "$env_file" \
    -f "$EMULATOR_DIR/compose.yaml" "$@"
}

need_service() {
  local container
  container="$(compose ps --status running --quiet emulator)"
  [[ -z "$container" ]] || return 0
  container="$(compose ps --all --quiet emulator)"
  if [[ -n "$container" ]]; then
    echo '==> starting stopped emulator service'
    compose start emulator
    return
  fi
  echo 'emulator service missing — run: ./emulator/run.sh up <ota_dir>' >&2
  exit 1
}

copy_shots() {
  mkdir -p "$REPO_DIR/shots"
  compose cp emulator:/work/shots/. "$REPO_DIR/shots/"
  echo "==> PNGs copied to $REPO_DIR/shots/"
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  up)
    # Arguments and shell OTA_DIR are caller-relative; configured paths are repo-relative.
    OTA="${1:-${OTA_DIR:-}}"
    if [[ -z "$OTA" ]]; then
      [[ -f "$EMULATOR_DIR/.env" ]] || {
        echo 'usage: ./emulator/run.sh up <ota_dir> (or configure emulator/.env)' >&2
        exit 1
      }
      OTA="$(compose config --environment | sed -n 's/^OTA_DIR=//p')"
      [[ -n "$OTA" ]] || { echo 'Set OTA_DIR in emulator/.env' >&2; exit 1; }
      [[ "$OTA" == /* ]] || OTA="$REPO_DIR/$OTA"
    fi
    OTA="$(cd -- "$OTA" && pwd)"
    [[ "$OTA" != *$'\n'* && "$OTA" != *$'\r'* ]] || { echo 'OTA path must fit on one line' >&2; exit 1; }
    ls "$OTA"/rootfs.squashfs.*.enc >/dev/null 2>&1 || {
      echo "no rootfs.squashfs.*.enc in $OTA (point at main_os/ota_v257)" >&2; exit 1;
    }
    # Preserve other settings. Quote dotenv values so spaces, dollars and quotes stay literal.
    escaped="${OTA//\\/\\\\}"
    escaped="${escaped//\"/\\\"}"
    escaped="${escaped//\$/\$\$}"
    ENV_TMP="$(mktemp "$EMULATOR_DIR/.env.XXXXXX")"
    trap 'rm -f -- "$ENV_TMP"' EXIT
    while IFS= read -r line || [[ -n "$line" ]]; do
      case "$line" in OTA_DIR=*) ;; *) printf '%s\n' "$line" ;; esac
    done < <(cat "$EMULATOR_DIR/.env" 2>/dev/null || true) > "$ENV_TMP"
    printf 'OTA_DIR="%s"\n' "$escaped" >> "$ENV_TMP"
    mv -- "$ENV_TMP" "$EMULATOR_DIR/.env"
    trap - EXIT
    echo '==> docker compose up (build)'
    OTA_DIR="$OTA" compose up -d --build
    echo '==> extracting rootfs (first run only takes a minute)'
    compose exec -T emulator bash -lc '[ -e /work/rootfs/usr/bin/mq_ui ] || /repo/emulator/scripts/00_extract_rootfs.sh /ota'
    echo '==> setting up environment'
    compose exec -T emulator bash /repo/emulator/scripts/10_setup_env.sh
    echo '==> ready. Try: ./emulator/run.sh boot'
    ;;
  up-image)
    # A rootfs image (squashfs, possibly padded .bin) built on the selected stock firmware.
    # Its directory is mounted as /ota; use a separate WORK_VOLUME for every image.
    IMAGE="${1:?usage: ./emulator/run.sh up-image <rootfs image>}"
    [[ -f "$IMAGE" ]] || { echo "no image file $IMAGE" >&2; exit 1; }
    IMAGE_DIR="$(cd -- "$(dirname -- "$IMAGE")" && pwd)"
    echo '==> docker compose up (build)'
    OTA_DIR="$IMAGE_DIR" compose up -d --build
    compose exec -T emulator bash -lc '[ -e /work/rootfs/usr/bin/mq_ui ] || /repo/emulator/scripts/01_image_rootfs.sh "/ota/$1"' -- "$(basename -- "$IMAGE")"
    echo '==> setting up environment'
    compose exec -T emulator bash /repo/emulator/scripts/10_setup_env.sh
    echo '==> ready. Try: ./emulator/run.sh boot --init'
    ;;
  start) need_service; echo 'emulator service running';;
  shell) need_service; compose exec emulator bash;;
  boot)
    need_service
    boot_env=()
    while [[ "${1:-}" == --* ]]; do
      case "$1" in
        --init) boot_env+=(-e BOOT_MODE=init); shift;;
        --direct) boot_env+=(-e BOOT_MODE=direct); shift;;
        --hold) boot_env+=(-e "BOOT_KEYS=${2:?--hold needs keys, e.g. volume_up,play}"); shift 2;;
        *) echo "Unknown boot option: $1" >&2; exit 2;;
      esac
    done
    compose exec -T ${boot_env[@]+"${boot_env[@]}"} emulator bash -lc '/repo/emulator/scripts/10_setup_env.sh >/dev/null && /repo/emulator/scripts/20_boot.sh "$1"' -- "${1:-0}"
    copy_shots
    ;;
  power)
    need_service
    compose exec -T emulator bash /repo/emulator/scripts/25_power.sh "$@"
    ;;
  keys)
    need_service
    compose exec -T emulator python3 -B -m emulator.runtime.gpio "$@"
    ;;
  tap)
    need_service
    compose exec -T emulator bash /repo/emulator/scripts/30_tap.sh "${1:?x}" "${2:?y}"
    copy_shots
    ;;
  diag)
    need_service
    compose exec -T emulator bash -lc '/repo/emulator/scripts/10_setup_env.sh >/dev/null 2>&1; /repo/research/diagnostics/diag_tap.sh'
    copy_shots
    ;;
  capture)
    need_service
    compose exec -T emulator bash /repo/emulator/scripts/capture.sh "${1:-cap}"
    copy_shots
    ;;
  audio)
    need_service
    compose exec -T emulator python3 -m emulator.runtime.audio /work/audio.wav
    mkdir -p "$REPO_DIR/shots"
    compose cp emulator:/work/audio.wav "$REPO_DIR/shots/audio.wav"
    echo "==> WAV copied to $REPO_DIR/shots/audio.wav"
    ;;
  view)
    need_service
    PORT="${1:-8080}"
    compose exec -T -d emulator bash -lc '/repo/viewer/scripts/40_stream.sh "$1" >/work/stream.log 2>&1' -- "$PORT"
    sleep 1
    echo "==> live viewer: http://localhost:$PORT (click = tap, drag = swipe)"
    echo '    boot for a live screen; logs: ./emulator/run.sh compose exec emulator cat /work/stream.log'
    ;;
  stop) need_service; compose exec -T emulator bash /repo/emulator/scripts/99_stop.sh;;
  wscheck)
    need_service
    compose --profile wsbridge exec -T wsbridge python3 -B -m controller.diagnostics.verify_websocket --tcp-host emulator "$@"
    ;;
  down) OTA_DIR="${OTA_DIR:-$REPO_DIR}" compose --profile wsbridge down; echo 'containers removed (work volume kept)';;
  nuke) OTA_DIR="${OTA_DIR:-$REPO_DIR}" compose --profile wsbridge down -v; echo 'containers and work volume removed';;
  compose) compose "$@";;
  help|--help|-h) sed -n '2,28p' "$EMULATOR_DIR/run.sh";;
  *) echo "Unknown command: $cmd; see ./emulator/run.sh help" >&2; exit 2;;
esac
