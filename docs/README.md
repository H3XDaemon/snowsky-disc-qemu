# Documentation

Component manuals live beside their code. This index connects them with the
shared protocol, architecture and development documentation.

| Area | Read first | Contents |
| --- | --- | --- |
| Emulator | [Current status](../emulator/docs/status.md) | [Boot, audio, controls, network and settings](../emulator/docs/README.md) |
| Viewer | [Usage](../viewer/docs/usage.md) | [Browser interaction](../viewer/docs/README.md) |
| Library | [Shared catalog and storage](../library/README.md) | Offline projections, snapshot identity and optional search |
| Controller | [Package setup](../controller/README.md) | [Session API, discovery and bridges](../controller/docs/README.md) |
| Firmware | [Preparation](../firmware/README.md) | [Profiles, porting and version reports](../firmware/docs/README.md) |
| Disc Assistant | [Quick command guide](../experiments/disc_assistant/docs/guides/quick-guide.md) | [Guides, contracts, evaluation and reports](../experiments/disc_assistant/docs/README.md) |
| DISC Web | [Run the music remote](../experiments/disc_web/README.md) | [Architecture](../experiments/disc_web/docs/architecture.md), [status](../experiments/disc_web/docs/status.md) |
| Browser experiment | [Project setup](../experiments/browser/README.md) | [Results and limitations](../experiments/browser/docs/README.md) |
| diskOS preview | [Historical project](../experiments/diskos/README.md) | [Preserved preview evidence](../experiments/diskos/docs/README.md) |
| Firmware research | [Current checkpoint and pause conditions](../research/docs/status.md) | [Methods, diagnostics and investigation reports](../research/docs/README.md) |
| DISC protocol | [Capabilities](protocol/disc-capabilities.md) | [Wire contracts and library behavior](protocol/README.md) |
| Architecture | [Component boundaries](architecture/repository.md) | [Repository architecture](architecture/README.md) |
| Decisions | [Ownership policy](decisions/0001-component-and-documentation-ownership.md) | [Accepted architecture decisions](decisions/README.md) |
| Development | [CI and test selection](development/ci.md) | [Quality checks and releases](development/README.md) |

[Curated screenshots](images/README.md) remain shared assets under `docs/images/`.
Private recordings, catalogs, firmware and raw captures do not belong in documentation.

## Finding moved pages

Former uppercase pages under `docs/` now have descriptive lowercase names beneath
their owner. For example, `CONTROLLER_API.md` is now
[`controller/docs/api.md`](../controller/docs/api.md); Assistant pages are grouped
under [`experiments/disc_assistant/docs/`](../experiments/disc_assistant/docs/README.md).
Git history preserves the former paths. Maintained repository links point to the
canonical page; there are no duplicate copies of the manuals.

Run `python3 -m ci.docs` from the repository root to check local Markdown targets.
The hosted firmware-free workflow runs the same check without firmware or services.
