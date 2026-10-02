# Emulator status

Current on 2026-09-21. **Stock V2.57 is the active supported firmware.** V2.40 is
historical; its remaining legacy profile is not an ongoing compatibility promise.
See the [support policy](../../firmware/docs/porting.md#support-policy--one-active-firmware).

## Current capabilities

| Area | Verified scope | Details |
| --- | --- | --- |
| Boot and UI | Fingerprint-validated stock boot to the English main menu; input/network/framebuffer readiness and touch gestures. | [Emulation](emulation.md), [touch](touch.md) |
| Storage and indexing | FAT SD browsing, manual indexing and V2.57 insertion-triggered scans, including Cyrillic changes. | [Media library](media-library.md) |
| Audio | Stock decoding to PCM capture, source-sample comparisons, WAV export and browser playback. | [Audio](audio.md) |
| Viewer and controls | Live screen/audio, CSS device, assigned volume gestures, play/pause, sleep/wake, guest-only off/on and SD hotplug. | [Viewer](../../viewer/docs/usage.md), [keys](keys.md) |
| Stock init and power events | Opt-in boot through stock `rcS`/`fiio_init.sh` with its watch loop and image hooks; reboot, power-off and power loss; `/usr/data` as a size-limited image; keys held at power-on. | [Stock init](stock-init.md), [keys](keys.md#keys-held-at-power-on) |
| USB power and idle | Stock V2.57 sink/ADC detection, independent display timeout, idle shutdown and explicit local Power/reconnect recovery. | [Power](idle-power.md) |
| Device protocol | Stock TCP/HTTP operations with an optional native WS bridge; explicit per-operation evidence and limits. | [Capabilities](../../docs/protocol/disc-capabilities.md), [Controller](../../controller/docs/README.md) |

Use `./emulator/run.sh` and `emulator/.env`; the base Compose service is
`emulator`. See the [launcher guide](running.md) for explicit path/configuration
rules and existing-installation setup.

## Validation and visual evidence

The [dated development record](reports/2026-09-19-development-checkpoints.md)
preserves boot, audio, viewer, protocol and actual long idle/USB observations,
including unsuccessful earlier investigations. The
[2026-09-21 Controller/Assistant checkpoint](../../experiments/disc_assistant/docs/reports/2026-09-21-development-checkpoints.md#pythoncontroller-review-follow-up-2026-09-21)
records the later successful full V2.57 integration run.
[Repository-refactor validation](../../docs/development/reports/2026-09-21-repository-refactor.md)
is a separate import/path check, not another full or power acceptance run.

| Main menu | Playback | Clock lockscreen |
| --- | --- | --- |
| ![V2.57 menu](../../docs/images/readme-menu.png) | ![V2.57 playback](../../docs/images/readme-playing.png) | ![V2.57 clock](../../docs/images/readme-clock.png) |

These are the preserved 2026-09-15 stock captures, not new screenshots.
[Image provenance](../../docs/images/README.md) and the
[current viewer presentation](../../viewer/docs/usage.md) describe their context.

## Limits and next work

- USB models power detection, not storage/DAC. Bluetooth audio, native DSD/DoP,
  hardware timing, standby and MCU/UART behavior remain outside established scope.
- The framebuffer marker is a selection hint, not an atomic snapshot fence.
  Guest process off/on is not a hardware shutdown/standby model.
- LAN discovery and the bounded phone bridge have explicit evidence; full FiiO
  Control compatibility, physical background/reconnect, Wi-Fi and cloud streaming
  are not implied. Default services remain loopback-only.
- New firmware promotion requires review and validation. OTA monitoring does not
  validate or install a new guest firmware automatically.
- Use the [research checkpoint](../../research/docs/status.md) for protocol
  follow-ups and PEQ pause conditions. Those optional investigations do not reopen
  the accepted local-protocol checkpoint.

[Browser/WASM, diskOS preview and Assistant](../../experiments/README.md) have
separate maturity and acceptance boundaries. Their results do not extend the
qemu-user emulator's support claims. Choose further checks using the
[CI test-selection policy](../../docs/development/ci.md#test-selection-policy).
