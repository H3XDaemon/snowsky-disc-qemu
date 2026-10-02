# Repository components

The repository follows the layout agreed in
[issue #7](https://github.com/eudj1n/snowsky-disc-qemu/issues/7). The preceding DISC
protocol checkpoint was committed separately (`f5d0968`, merged by `d4e956c`).
The core components share one repository and Docker toolchain. Firmware analysis
lives in `research/`; independent application prototypes live in `experiments/`
with separate launchers and optional services. See the [experiment index](../../experiments/README.md).
Diagnostic unit tests live in `research/diagnostics/tests/`.

Documentation follows [ADR 0001](../decisions/0001-component-and-documentation-ownership.md);
start with the [documentation index](../README.md). Component manuals travel with
their code; shared protocol and development contracts have repository-wide owners.

## Ownership and dependencies

| Component | Owns | Depends on |
| --- | --- | --- |
| `emulator/scripts/`, `emulator/shims/`, `emulator/runtime/` | Guest setup, boot/stop, SD/network stubs, physical input, framebuffer and PCM | Shared `firmware.profile`; native tools from `emulator/docker/` |
| `viewer/server.py`, `viewer/static/` | HTTP/SSE presentation, browser input/audio, shared device CSS | Emulator runtime adapter; no controller transport |
| `controller/` | Physical-device TCP/HTTP/WS clients, shared session/state/control API, discovery, optional bridges and network diagnostics | Python standard library; `aiohttp` for WS client/bridge; no emulator, firmware, research or experiments imports |
| `library/` | Catalog observations, SQLite snapshots, offline projections and optional search | Controller catalog/transport contracts; optional Typesense; no application imports |
| `firmware/profile.py`, `firmware/v*.json`, `firmware/tools/` | Reviewed profiles/fingerprints, acquisition, extraction, OTA and inventory tools | Native extraction tools where needed |
| `research/ghidra/`, `research/diagnostics/` | Ghidra, ELF tables, GDB and process-memory inspection | Firmware profiles; emulator process helpers for live memory probes |
| `experiments/browser/` | Experimental TinyEMU/WASM runtime, local bundle builder and browser UI | Reviewed firmware preparation/shims; pinned public TinyEMU, Linux and QEMU inputs; separate build image |
| `experiments/disc_assistant/` | Experimental text/voice command flow, console/web adapters, ranking, locale/response policy and request history | Shared Controller and Library APIs; SQLite/Typesense; optional Whisper Server and Piper; separate launcher/services |
| `experiments/disc_web/` | Experimental web music remote, library presentation, local HTTP application and isolated demo | Shared Controller and Library APIs; Python standard library and local browser assets; independent launcher |
| `experiments/diskos/` | Historical, unsupported source-built diskOS UI preview and isolated launcher | Pinned upstream source; legacy V2.40 runtime and emulator helpers; no supported-profile promotion |
| `tests/integration/`, `tests/fixtures/` | Cross-component acceptance and generated media | The components under test |
| `ci/` | Test discovery, disposable Compose orchestration and cleanup | Test implementations under `tests/` |

`firmware/` remains at the root because runtime and research share its reviewed
profiles. `emulator/docker/` owns the pinned QEMU/build environment, reused by CI
and browser preparation. The launcher, base Compose stack and local configuration
live in `emulator/`; CI owns disposable overlays and acceptance orchestration.
See [running the emulator](../../emulator/docs/running.md) and
[ADR 0002](../decisions/0002-emulator-infrastructure.md).

The [shared Controller API](../../controller/docs/api.md) owns persistent device state and
verified playback operations. Assistant owns its language/search/history policy;
the Controller does not import research or select application storage paths.
Its own `pyproject.toml` builds a standalone wheel; the root `pyproject.toml`
configures quality checks only. See [the package README](../../controller/README.md).

The viewer's adapter creates a `Device`, `Buttons`, `Peripherals`, `Touch` and
`Framebuffer` for one rootfs. Emulator runtime owns event bytes, coordinate
rotation, frame selection, PCM reads and guest lifecycle. The viewer owns HTTP
validation, static resources, SSE snapshots and streaming. Integration tests
use emulator primitives directly; they do not import the viewer server to tap
or capture the guest.

## Entry points and resource inventory

Run Python commands **from the repository root** with `python3 -m package.module`.
`__init__.py` files declare ordinary packages and enable recursive unittest
discovery. Controller additionally exports its versioned library models and lazily
loads the session facade; imports perform no network or filesystem writes. There are no per-directory `sys.path`
searches. The Docker image provides the single package root `PYTHONPATH=/repo`;
sourced emulator scripts also support an explicit `REPO` override.

| Previous location | Current entry point / resource |
| --- | --- |
| `scripts/` setup/boot/tap/capture/stop | `emulator/scripts/`; existing `./emulator/run.sh` commands |
| `scripts/40_stream.sh`, `tools/stream.py` | `viewer/scripts/40_stream.sh`, `python3 -m viewer.server` |
| Inline stream page and `tools/*.js` | `viewer/static/index.html` and browser JavaScript; same HTTP URLs |
| `assets/` photo skin | Removed after the CSS device replaced it; historical captures remain in `docs/images/` |
| `shim/` | `emulator/shims/`; all four shims still built |
| `tools/keys.py`, `tools/viewer_controls.py`, `tools/audio.py` | `emulator.runtime.keys`, `emulator.runtime.peripherals`, `emulator.runtime.audio` |
| Stream framebuffer/touch internals | `emulator.runtime.framebuffer`, `emulator.runtime.touch` |
| `tools/fiio_*.py` | `controller.fiio_*`; e.g. `python3 -m controller.fiio_http --help` |
| `tools/ws_bridge.py`, `tools/ws_console.html`, `tools/lan_bridge.py` | `controller/bridge/`; bridge isolation and opt-in LAN rules are unchanged |
| Network/WS checks | `controller/diagnostics/`; `./emulator/run.sh wscheck` remains available |
| Firmware acquisition/inventory utilities | `firmware/tools/`; `python3 -m firmware.tools.check_ota` |
| `tools/firmware_profile.py` | Shared `firmware/profile.py` |
| `ghidra/`, memory/key/network probes, ELF inspection, `uisniff.c`, GDB/tap diagnostic scripts | `research/ghidra/`, `research/diagnostics/` |
| `ci/*_check.py`, other acceptance implementations | `tests/integration/`; orchestrated by `ci/integration.sh` |
| `ci/*fixture.py`, `scripts/media_fixture.sh` | `tests/fixtures/` |
| `tools/test_*`, `tools/fixtures/` | Component `tests/` directories; sanitized captures in `controller/tests/fixtures/` |

The [browser experiment](../../experiments/browser/docs/overview.md) has a separate shell entry point:
`bash experiments/browser/run.sh build /absolute/path/to/main_os/ota_v257`, then
`bash experiments/browser/run.sh serve`. Its tests live in `experiments/browser/tests/`; all
downloaded inputs, generated images and served firmware remain in ignored
`work/browser-disc/`. It is maintained as experimental research on `2.x` and
does not start through the normal `run.sh`, viewer or Compose services.

The [Disc Assistant](../../experiments/disc_assistant/README.md) has its own
`./experiments/disc_assistant/run.sh` launcher: `setup --all` installs its optional
speech runtime, `web --bootstrap` starts the browser interface and `start` opens
the text console. Neither the root launcher nor Viewer starts these services.
Tests live with the prototype; `ci/assistant.sh` orchestrates disposable firmware
acceptance implemented under `tests/integration/`. Its
[software MVP is accepted](../../experiments/disc_assistant/docs/reports/2026-09-19-mvp-acceptance.md), while the implementation
remains experimental and uses the shared Controller without reverse imports.

The [historical diskOS preview](../../experiments/diskos/docs/preview.md) preserves its own Compose file,
`bash experiments/diskos/build.sh /absolute/path/to/diskos` builder, and in-container
`bash /repo/experiments/diskos/boot.sh` launcher. Generated outputs and adapted upstream
sources stay in ignored `work/diskos-preview/`. Its preserved V2.40 results do not
extend the support policy or require recurring firmware integration gates.

The controller can be copied and imported without the emulator, rootfs, Docker,
profiles or memory tooling. `controller.tests.test_isolation` verifies that
boundary in a separate Python process. For direct TCP/HTTP control the standard
library is sufficient; the optional WS client and WS bridge require `aiohttp`.

## Local names and data

Default Compose project/container/image: `snowsky-disc-qemu`; test image:
`snowsky-disc-qemu-ci`; default work volume: `snowsky-disc-work`.
`EMU_IMAGE`, `EMU_CONTAINER_NAME`, `WORK_VOLUME` and `SD_DIR` overrides remain
available. `run.sh` uses the default container name, as before.

User media defaults to ignored `emulator/sdcard/`; the container mount remains
`/sdcard` and the guest mount remains `/tmp/sdcard`. The owner explicitly waived
migration compatibility for the old root SD directory on 2026-09-17: fresh setup
uses the new location, with no migration command or fallback. Existing local
Docker containers are not renamed by moving source files. Stop a previous stack
before starting a fresh default stack if its localhost ports are occupied.

Firmware-derived data, captures and analysis remain ignored. Curated screenshots
stay in `docs/images/`. No firmware profile, binary fingerprint, protocol enum,
UI layout or firmware-support policy changes as part of this reorganization.

## Validation

The firmware-free runner discovers Python tests in every component test directory and fails
if a test module is omitted or a test is skipped. JavaScript and shell discovery
includes the component source/test directories, excluding ignored SD and rootfs data. See [CI](../development/ci.md) for the full V2.57 and long
power scenarios. The full scenario also exercises the viewer's real HTTP page,
JavaScript, frame, PCM, screen sleep/wake and Power stop/boot in its disposable
guest.

Local validation on 2026-09-17:

- Move-only commit `5ad9f4c`: 298 Python tests, 23 JavaScript tests, shell syntax
  checks and all four shim builds passed in the pinned Docker toolchain.
- Final component layout: 299 Python tests and 23 JavaScript tests passed, with
  no skips. All 297 pre-move Python test methods remain covered; the new tests
  check isolated controller imports and guest-specific touch timing/event bytes.
- The runner rejects a test directory missing its package marker. A separate
  synthetic check confirmed that Python-looking files on the ignored SD are not
  imported or executed as tests.
- Full V2.57 integration passed on a fresh disposable Compose stack, including
  the real viewer HTTP/skin/frame/PCM and Power lifecycle acceptance.
- The separate `idle` scenario passed quiet screen timeout, stock idle shutdown
  and explicit Power/reconnect recovery over TCP and WS. `idle-usb` passed its
  actual 310-second observation. All disposable stacks and test volumes were removed.
- Root `run.sh` commands `up`, `boot`, `view`, `capture`, `tap`, `audio`, `wscheck`
  and `stop` were exercised on a fresh local stack with the new names. Browser
  touch navigated the sample SD folders and selected a test track. The previous
  local work volume was retained separately.
- The extracted HTML template, four browser JavaScript files and skin photo are
  byte-identical to the protocol checkpoint. Local Markdown links resolve;
  generated media, firmware and captures are absent from the source diff.

These are local results, not a hosted CI run or a firmware release.


## Assistant NLU ownership

The Assistant's working language-understanding component is now
[`assistant/nlu`](../../experiments/disc_assistant/assistant/nlu/README.md). Executing
rules and typed intent validation live there; optional shadow models remain
non-executing. Offline evaluation/training tools are in `nlu/evaluation`, while
frozen corpora and labelled references are in `nlu/data`. Translator-facing TOML
remains in `assistant/locales`, with no training examples in `locales/commands`.
The Assistant remains an experimental application in `experiments/disc_assistant`;
NLU is its ordinary subsystem. Controller has no reverse dependency on experiments.
