# DISC platform — new project initialization brief

Prepared on 2026-09-23. This file is intended to be copied into a new repository
and supplied to a coding agent as the initial project brief. It describes a new
product direction, not an already implemented or hardware-validated platform.

## Initial instruction to the implementing agent

Create the first working slice of a standalone DISC web platform in the new
workspace. Inspect the reference implementation before choosing abstractions.
Preserve its reviewed protocol behavior and reuse its interface where practical.
Read this entire brief, write a concise implementation plan and decision log in
the new repository, then implement milestone 1 below. Do not stop at scaffolding
or a proposal: deliver a runnable interface with an explicitly selected demo or
emulator connection, and report exactly what was tested.

Treat subsequent milestones as the roadmap, not permission to flash hardware,
deploy public services, create paid resources or implement every cloud feature
in the first session. Use the new workspace's name as a provisional name; final
branding and a public repository name are undecided. Communicate with the owner
in Russian; keep source documentation in English and product UI in Russian and
English. Do not create another Codex task automatically.

## Product intent

Build a polished browser interface for a FiiO SNOWSKY DISC Hi-Fi player, with a
small companion service running on the player. The end state requires no Python
server installed on the user's computer. The browser renders the interface and
executes its TypeScript client; the device serves/proxies the necessary APIs.

The existing DISC Web is the visual and functional starting point. Preserve its
music-first presentation inspired by Apple Music, Yandex Music and Spotify,
responsive layouts, light/dark/system themes, RU/EN localization, attractive
missing-artwork placeholders, Now Playing side panel, queue and stepped import
and synchronization dialogs. Reuse the current assets and interaction decisions
instead of restarting with a generic dashboard.

Longer-term product direction:

- Local playback control, library browsing, basic search and imports remain
  usable without a cloud account or subscription.
- An optional account links devices and synchronizes catalog metadata across
  browser installations.
- An optional cloud backend provides Typesense search and a premium voice
  assistant. Exact pricing, quotas and feature entitlements are undecided.
- Expose as much of the **reviewed** device capability surface as practical.
  Separate protocol availability, UI coverage and physical validation.

This is primarily a remote control for playback on the DISC. Streaming the
player's audio into the browser or uploading the user's music to the cloud is
not part of the initial product.

## Reference repository and provenance

- Repository: <https://github.com/eudj1n/snowsky-disc-qemu>
- Local checkout on the original host: `/Users/zhek/IdeaProjects/diskos-qemu`
- Reference branch: `codex/disc-web`
- Pinned baseline: `992d156c16746be5a25ab43c7cda5fcef09b8863`
- Active reviewed firmware: SNOWSKY DISC V2.57.
- License: preserve the upstream MIT notice and attribution for reused code.

Use the pinned baseline for reproducibility. If adopting newer upstream work,
record the new revision and relevant changes. Do not assume that a moving branch
still represents the same behavior. The baseline is a reference checkpoint, not
a claim that every hosted or physical acceptance gate passed at that revision.

Keep the reference checkout intact. This project does not move, delete or retire
the existing DISC Web, Python Controller, Library or Assistant. Do not duplicate
the emulator: use its documented external endpoints and independent test stack.
No production dependency on the reference repository's filesystem is intended.

Read these sources from the reference checkout before implementation:

| Source path | Purpose |
| --- | --- |
| `AGENTS.md`, `emulator/docs/emulation.md`, `docs/README.md` | Repository boundaries, operational constraints and documentation index |
| `experiments/disc_web/AGENTS.md`, `README.md`, `docs/architecture.md`, `docs/status.md`, `docs/plan.md` | Existing UI, backend contract, accepted behavior and remaining work; paths after the first entry are relative to that component |
| `controller/docs/api.md`, `controller/session.py` | Public session facade, connection ownership and guarded operations |
| `controller/docs/websocket.md`, `controller/bridge/ws_bridge.py` | Existing WS framing, HTTP proxy, lifecycle and emulator integration |
| `controller/docs/README.md`, `docs/protocol/disc-capabilities.md` | Reviewed compatibility and capability evidence |
| `docs/protocol/protocol.md`, `http-api.md`, `library-browsing.md`, `playlists.md` | Wire contracts and scoped selection; the latter three paths are under `docs/protocol/` |
| `library/AGENTS.md`, `library/README.md` | Snapshots, duplicate preservation, enrichment and optional Typesense indexing |
| `experiments/disc_assistant/AGENTS.md`, `docs/architecture/pipeline.md`, `docs/guides/voice-adapters.md` | Existing interpretation and speech boundaries; documentation paths are relative to the Assistant component |
| `research/docs/reports/2026-09-23-library-metadata.md` | Verified metadata surface and stock lyrics/artwork limitations |
| `research/docs/reports/2026-09-23-fiio-control-runtime-disc.md` | Dedicated DISC Link path versus vendor cloud profiles |
| `research/docs/reports/diskos.md` | Historical custom-runtime findings and installation limits, not V2.57 hardware acceptance |

Do not copy firmware, APKs, extracted vendor binaries, raw app data, credentials,
private catalogs or captures. In particular, the untracked `com.fiio.control`
directory in the reference workspace is not a project asset. Copy only reviewed
code, licensed assets, documentation and curated synthetic/sanitized fixtures.

## Architecture

```text
Browser
  DISC Web UI
  TypeScript Controller: protocol, state, guarded operations
  TypeScript Library: catalog snapshots, local search, IndexedDB cache
       |
       +-- WS ------> device service ----> stock FiiO Link TCP :12100
       +-- HTTP ----> device service ----> stock HTTP :12103
       |
       +-- HTTPS ---> optional cloud backend
                         accounts / device pairing / entitlements
                         catalog synchronization / search / assistant
                              |                   |
                         primary database      Typesense
```

The device service is a small native process compatible with the player's
MIPS/Linux environment. Its implementation language, toolchain, resource budget
and startup packaging must be chosen after inspecting the target. A Node.js
runtime on the player is not a requirement. Serving compiled web assets does
not mean running a browser or rendering the UI on the player.

The service should serve the UI, expose WS control and proxy stock HTTP on one
origin. Stock ports already exist: choose a separate listening port and verify
the usable internal upstream address instead of assuming that loopback works.
The current Python/aiohttp bridge runs outside the guest and has localhost-only
Host/Origin rules; it is a protocol reference, not a binary ready to install.

The current frontend uses backend JSON APIs. Changing its URL to a raw WS bridge
will not replace the backend. Introduce a typed application/device adapter and
migrate behavior deliberately, preserving demo and existing user flows.

Suggested monorepo structure; create directories only when they have content:

```text
apps/web/                 Browser interface
packages/controller/      TypeScript protocol and guarded device operations
packages/library/         Catalog snapshots, projections and browser storage
packages/contracts/       Versioned DTOs shared with cloud/device adapters
device/                   Native service, build and packaging
services/cloud/           Optional accounts/search/assistant API, later stage
tests/conformance/        Curated fixtures and transport parity scenarios
docs/                     Architecture, decisions, milestones and validation
```

Use TypeScript for browser-side Controller and Library. Vite is a reasonable
build default; Vue is optional when its component model helps the migration.
Preserve existing CSS where useful; Tailwind is optional, not a prerequisite.
The cloud assistant may stay in Python to reuse current contracts and tests.
Do not force a whole-stack rewrite for language uniformity.

## Hosting and connection models

Support these as distinct deployment choices, using the same UI and contracts:

1. **Device-hosted web UI:** open the player's address; UI, WS and HTTP share an
   origin. This is the simplest local-control target. An HTTP LAN page is not
   equivalent to an HTTPS secure context: do not promise microphone, installable
   PWA or service-worker functionality without checking browser requirements.
2. **Hosted HTTPS web UI:** suitable for accounts and browser voice capture;
   reaches the local player through its bridge. Validate Local Network Access,
   mixed-content rules, HTTP CORS and WS Origin handling in target browsers.
   Do not claim that HTTPS-to-insecure-WS works universally. TLS and certificate
   provisioning are a design decision if required by the supported browsers.
3. **Chrome extension:** optional later packaging of the same application, with
   explicit host permissions and connection lifecycle handling. It does not
   make stock TCP directly available through ordinary web APIs.

Ordinary browser JS cannot listen for the player's multicast discovery beacons.
Begin with explicit address entry; a known local hostname or paired address can
follow. Cloud device registration alone does not discover the current LAN IP.

A cloud server cannot directly connect to a private LAN address. The first cloud
assistant uses the open browser as the local executor. Remote control without
an open tab would require a separate, authenticated outbound device connection
to the cloud; it is not included in a simple WS-to-TCP proxy.

## Controller invariants to preserve

- One owner of the stock control connection. Do not steal an active FiiO Control
  or console session. A transparent bridge does not create multi-client support;
  initially reject a second controlling client. Do not connect permanently at boot.
- Serialize queries and mutations. FiiO Link has unsolicited events and no
  general request IDs; do not equate the next incoming frame with the last query.
- Preserve UTF-8 byte lengths, frame boundaries, split/coalesced records and
  bounded buffers. Follow the bridge's reviewed text/binary framing contract.
- Preserve the stock mutation pacing policy, fresh preflight and confirmation.
  Do not replace the current remaining-interval calculation with arbitrary sleeps.
- Bind pending work to the target and connection generation. Reconnection must
  not silently execute work intended for a previous connection.
- Do not automatically replay a mutation after timeout, disconnect or uncertain
  readback. Distinguish not-sent, confirmed and uncertain outcomes in the API/UI.
- Search results and cached positions are not executable wire selectors. Read
  the fresh scoped source before selecting, retaining duplicate multiplicities.
- Preserve artist-scoped albums, genre-scoped albums and native queue positions.
  Never broaden a scoped request into an identically named generic album.
- Keep TCP and HTTP on the same device. Scan/import/selection admission rules
  must remain coherent across the two transports.
- Gate reviewed capabilities on actual device identity/firmware. Unknown versions
  do not inherit V2.57 support or permissive vendor-profile fallbacks.
- Closing the page, tab suspension and service restart must have explicit
  outcomes. Browser cache does not make an upload a durable background job.

The device service needs explicit Origin/Host validation and a local pairing or
authorization design before LAN distribution. A cloud login by itself does not
authorize access to an unauthenticated local bridge. Do not expose stock device
ports to the public internet or implement a proxy to arbitrary upstream hosts.

## Library and optional cloud data

Library owns stable catalog observations, projections and enrichment. Preserve
the previous published snapshot on interrupted or inconsistent synchronization.
Represent missing duration, cover or audio properties as unknown. Do not cycle
playback to populate metadata and do not merge tracks solely by display labels.

Use browser storage such as IndexedDB for local snapshots and cover caches;
handle storage failure/eviction. Local storage belongs to an origin and browser
profile: a changed player address or another browser is not the same cache.
An optional account-backed catalog can provide cross-browser continuity.

Cloud synchronization is explicit opt-in and initially uploads catalog metadata,
not audio files. Use versioned snapshots and an atomic published-head transition.
Keep the source observations and mappings needed for local execution validation.

Typesense is a rebuildable search index, not the authoritative account database
or device-ownership registry. Isolate records by account/device/snapshot. Enforce
authorization server-side; never trust a browser-supplied owner ID. Either proxy
search through the backend or issue expiring scoped search-only keys with an
embedded access filter. Never ship administrative or indexing credentials.

Registration and pairing should distinguish:

- User identity and account membership.
- Product/model identity and reviewed firmware capabilities.
- A service installation identity with revocable credentials.
- The current network address, which is neither identity nor proof of ownership.

Use an explicit local possession confirmation or one-time pairing flow, and
provide unpair/revoke behavior. Persist the resulting relationship in the primary
database. Provider selection, billing, credential provisioning and account
recovery remain design choices for the cloud milestone.

## Premium voice assistant boundary

Reuse the existing separation between speech recognition, interpretation,
catalog resolution, guarded execution and response synthesis:

```text
Browser microphone or typed request
  -> authenticated cloud API
  -> recognition (for speech)
  -> validated intention
  -> authorized catalog search and resolution
  -> structured proposal returned to the originating browser
  -> local Controller checks connection + fresh source and executes once
  -> observed outcome returned to the backend
  -> localized text / optional spoken reply
```

The selected physical player has no assumed microphone. Voice is captured by
the user's phone/computer. Obtain microphone permission from an eligible browser
context; cloud audio/transcripts have explicit retention and deletion policies.

Do not let an LLM generate executable scripts or raw device commands. Preserve
the existing one-action-per-request contract initially. Clarify ambiguous music
matches; do not claim successful playback before the executor confirms it.
Bind proposals to a request, account, device, snapshot and local connection
context; expire stale proposals and prevent duplicate dispatch. A request ID
does not make a stock mutation safely retryable after an uncertain outcome.

Keep secrets, subscription enforcement, usage accounting and provider quotas on
the backend. Loss of internet or subscription must not disable basic local
playback controls. The current Assistant is a tested reference pipeline, not
an already deployed multi-tenant conversational service.

## Milestones and acceptance

### 1. Runnable browser foundation against the existing emulator bridge

- Record provenance, architecture, initial decisions and the implementation plan.
- Reuse the DISC Web shell with themes, RU/EN and responsive layouts. Make the
  new implementation's supported subset explicit; do not display fake live data.
- Add browser-side typed transport/application adapters, an explicit demo and
  explicit connection/disconnection. Implement handshake, firmware identity and
  current playback readback as the first real slice.
- Use the existing external WS bridge before writing the native device service.
  Its origin restrictions need an explicit compatible hosting arrangement; do
  not globally disable them for development.
- Add synthetic framing/state/error tests and verify in a real browser. Where a
  disposable emulator is available, verify connection, readback and release of
  the sole TCP channel. Report any unavailable integration prerequisites honestly.
- Document reproducible commands and the next bounded stage. No physical device
  connection, cloud deployment or flashing is part of this initial session.

### 2. TypeScript Controller and Library parity for core workflows

- Port guarded playback/volume/queue and scoped album/artist/genre selections.
- Port snapshots, offline browsing and search, then import/scan/sync and reviewed
  settings. Keep omitted capabilities visible in a parity checklist.
- Compare curated scenarios with the Python reference on disposable V2.57 media.
  Alternate ownership; do not run both clients against stock TCP simultaneously.
- Test stale selection, duplicate labels, interrupted sync, uncertain mutations,
  scan events, reconnection and second-client rejection, not only happy paths.
- Verify light/dark, RU/EN, desktop/mobile and browser console behavior. Preserve
  playback/queue UI, dialog accessibility and actual progress reporting.

### 3. Native service inside the emulated player

- Select and cross-compile a small service for the verified target ABI.
- Serve web assets and implement WS + bounded, streaming HTTP proxy behavior.
- Test startup/shutdown, disconnect cleanup, upload limits, memory use and
  coexistence with stock playback and power/network lifecycle.
- Keep build and packaging here; changes to general emulator infrastructure
  belong upstream. Record compatible upstream revisions and test commands.
- Establish an installation/recovery design before proposing physical flashing.
  Historical diskOS results do not validate a V2.57 installer or cold boot.

### 4. Optional account and cloud catalog

- Implement login, pairing/revocation, ownership checks and catalog opt-in.
- Add a primary database plus isolated Typesense indexing/search.
- Validate supported hosted-site-to-device browser combinations explicitly.
- Prove cross-account isolation and stale-snapshot handling before deployment.

### 5. Premium assistant through the open browser

- Adapt the existing Assistant contracts into an authenticated cloud API.
- Start with typed requests, then microphone/STT and optional TTS.
- Execute only through the local guarded Controller and return confirmed results.
- Test disconnection during recognition, ambiguity, duplicate proposals, provider
  failure and limits. Billing integration follows an explicit provider decision.

### Later, separately scoped

Chrome extension packaging; authenticated outbound device/cloud channel; durable
device-side jobs; local file metadata/lyrics extraction; multi-client arbitration.
Do not implement these implicitly while delivering the earlier milestones.

## Known boundaries and deferred work

- A WS proxy changes transport, not supported stock commands. The current
  artwork endpoint describes the current cover; complete catalog artwork,
  per-file metadata and remote lyric text are not established stock features.
- A native service could later read SD files to add tags/artwork/LRC endpoints,
  but that requires separate implementation, resource and permissions review.
  The owner postponed local-file enrichment; this brief does not resume it.
- Bluetooth device management/output identification is not assumed available.
- PEQ physical research remains paused. No reconnection, writes, preset sweeps
  or restoration attempts are authorized by this project brief.
- Physical flashing, partition changes, boot hooks, cloud publication and paid
  resource creation require a concrete separately authorized step. Routine local
  development and disposable testing should proceed without repeated permission
  questions.
- Firmware images and stock proprietary binaries remain external inputs and
  must not be included in the new source repository or assumed redistributable.

## External design references

These describe browser/service mechanisms, not verified DISC behavior. Recheck
the supported versions when implementing rather than treating this dated brief
as a current browser compatibility matrix.

- [Typesense access control and scoped search keys](https://typesense.org/docs/guide/data-access-control.html)
- [Chrome Local Network Access](https://developer.chrome.com/blog/local-network-access)
- [Chrome extension cross-origin requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)
- [Browser microphone API and secure-context requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)

## Completion report for the first session

Provide the new repository structure, exact run/test commands, implemented live
and demo capabilities, known gaps and the next milestone. Keep a committed plan
and evidence record so subsequent sessions do not rediscover protocol facts or
mistake intended features for verified support. Do not claim firmware installation
or physical acceptance from a browser demo or an emulator-only result.
