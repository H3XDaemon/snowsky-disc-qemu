# DISC Web implementation plan

Agreed continuation checkpoint, 2026-09-23. Keep this document updated when an
accepted stage is completed; dated validation belongs in [status](status.md).
Issues remain the home for individual actionable follow-ups. DISC Web stays in
`experiments/disc_web`; Controller owns device operations and Library owns catalog
observations and enrichment.

Product direction, confirmed 2026-09-23: expose as much of the reviewed DISC and
Controller capability surface as practical in a coherent music interface. Prefer
stock network capabilities; a completed visual prototype is not the endpoint.
Keep firmware support, API availability and UI coverage explicit.

## 1. Now Playing and queue — complete

Expanded artwork and playback controls, album/artist navigation, adjacent desktop
queue and mobile player/queue switch. Shared queue refresh and guarded selection;
RU/EN and both themes. Implemented in `a9dfda4`, with synthetic and browser checks.
No physical playback acceptance is implied.

## 2. Library synchronization — complete

Make the existing sync understandable: distinguish saved collection, active sync,
offline/stale state and failure. Show the last successful observation separately
from current work, real sync stages and separate artwork/duration coverage.
Explain partial enrichment and preserve the previous snapshot on failure.

Acceptance: RU/EN and light/dark desktop/mobile presentation; synthetic checks for
partial metadata, empty snapshots, interrupted sync and storage failure. No fake
percentage, automatic sync, playback cycling or new physical connection.

Implemented the status badge, separate active/error messages, expandable stages
and saved field coverage. Validation is recorded in [status](status.md).

UI refinement on 2026-09-23 moved sync into a dedicated top-bar dialog and removed
the persistent banner. Album/artist placeholders now use decorative typography;
see [status](status.md#collection-ui-refinement--2026-09-23) for validation.

## 3. Folder import to a browsable collection — complete

Finish the existing folder upload → explicit device scan → Library sync flow.
Retain nested paths, skipped-file reporting and per-file confirmation. Make the
next action and the difference between transferred, indexed and saved metadata
clear. Preserve uncertain results without replaying writes. Folder upload already
exists; verified CUE/artwork sidecar transfer is a separate capability decision.

Acceptance: synthetic end-to-end transitions and narrow-screen review, plus the
relevant disposable firmware scenario if device-operation behavior changes.

Implemented three explicit steps in the import dialog, confirmed-file counts,
same-connection scan-to-sync admission and an open-collection action after a
fresh publication. Partial/uncertain transfers and reload limits remain visible;
demo does not fabricate a saved catalog. Controller operations are unchanged.

## 4. Sound settings — complete

Expose only reviewed Controller capabilities with fresh readback and clear
unsupported states. Start with volume-related settings and supported DAC options;
choose the exact controls against the public facade before implementation.
Unknown firmware must not inherit support. Bluetooth output identity/control and
paused PEQ research are not assumed available.

Implemented gain, L20..R20 balance, six DAC filters and DRE through a narrow
Controller facade with fresh firmware/value checks and one guarded setter.
Web requires explicit Apply and handles unavailable, stale and uncertain results.
Synthetic tests, browser checks, package/type checks and the complete disposable
V2.57 regression passed, including the new persistent settings scenario. See
[status](status.md) for the validation scope; physical audio remains unmeasured.

## Separate decisions

Local-file tags, external enrichment, lyrics, additional file management,
large-catalog improvements, shared Assistant ownership and promotion out of
experiments remain follow-ups. APK/cloud profile research is independent of this
UI sequence and is not a prerequisite for it.

All stages retain one Controller owner, explicit connection, guarded selections,
no replay of uncertain mutations, paired RU/EN and light/dark/system appearance.

## Metadata capability investigation — 2026-09-23

The [stock capability audit](../../../research/docs/reports/2026-09-23-library-metadata.md)
found additional current-track audio properties already retained by raw
Controller clients but omitted from the public Track model. Exposing those is
the proposed next implementation; local-file enrichment belongs in Library sync
for mounted SD/USB Storage/source folders as well as Web imports. Stock local
lyric support does not establish a remote lyric-text API. Full catalog tags,
artwork and lyrics cannot be promised over the verified stock network surface.
The current-track stage below was subsequently approved. Local-file enrichment
and lyrics remain separate follow-ups.

## 5. Current-track metadata through Controller → Library → Web — complete

Expose observed sample rate, bit depth, channels, reported rate, genre, track
number and DSD/SACD/CUE/M3U flags in the public Track. Store them in the existing
snapshot-scoped observation pipeline, with additive migration. Show known source
properties in Now Playing and saved-track menus in RU/EN and both themes. Preserve
selection identity, duplicate and scan guards; do not add device reads or cycle
playback. Implementation and validation are recorded in [status](status.md).

## Local-file enrichment — deferred by owner, 2026-09-23

Optional Library enrichment from mounted SD/USB Storage or an explicit source
folder is deferred, not the next implementation stage. Resume only on an explicit
owner request. Path mapping, duplicate/CUE identity and local-file provenance
remain design considerations for that future work. Existing current-track
enrichment through Controller remains available.

## 6. Native genre browsing and playback — complete

Include stock genre → album → track membership in Web's explicit Library sync,
with two complete equal reads and atomic publication. Keep native genre positions
separate from main catalog identities, preserving mixed-genre albums and duplicate
tracks. Expose filters on Albums and Tracks, offline browsing, deep links and a
whole-genre action. Fresh Controller checks must preserve the exact genre source
for indexed and album playback. Old snapshots require one new sync.

Implemented and validated with synthetic fixtures, responsive browser checks and
the disposable V2.57 library scenario; see [status](status.md).

## Capability coverage candidates

Use the [reviewed protocol matrix](../../../docs/protocol/disc-capabilities.md)
as the source of supported behavior, not APK/cloud descriptors alone. The next
bounded stage will be chosen separately; this list does not authorize destructive
operations against a personal collection.

| Area | Next useful Web work | Boundary |
| --- | --- | --- |
| Folders | Native SD folder browsing and scoped playback | Preserve directory-inclusive positions; Play all is nonrecursive |
| Playlists | Multiple selection, guarded batch additions and list management | Preserve source filters and fresh destination identity |
| Playback | Present all five reviewed play modes clearly | Do not guess root-tab Play all selectors |
| Audio/settings | Expose remaining reviewed settings through the shared owner | No unsupported remote preference setters or invented output identity |
| Device presentation | Reviewed work modes and lock-screen settings | Capability-specific validation; hardware audio is not inferred from readback |

PEQ investigation remains paused. Remote lyrics and Bluetooth device management
need separate evidence. Local SD/USB/source-folder enrichment remains explicitly
deferred above. These boundaries remain in effect while pursuing broader coverage.
