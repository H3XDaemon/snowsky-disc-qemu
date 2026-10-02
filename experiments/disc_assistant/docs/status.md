# Disc Assistant status

Current on 2026-09-22. The Assistant is an active experimental application with
an accepted **software MVP against stock V2.57**. Start with the
[command quick guide](guides/quick-guide.md) or [setup](guides/setup.md).

## Shared Library extraction — 2026-09-22

Catalog/store/search modules now live in root [`library/`](../../../library/README.md),
shared with DISC Web. Assistant imports and its test launcher use the shared
component. SQLite schema, stored paths, snapshot IDs, search signatures and the
accepted MVP evidence are unchanged. No automatic data-directory migration or
shared connection daemon is introduced.

## Implemented behavior

- [Vosk RU TTS](guides/tts.md#optional-vosk-tts) adds five explicitly selected voices
  through the same normalization and resident-worker contracts.

- [Silero RU and TTS normalization](guides/tts.md#optional-silero-ru) add resident
  synthesis, explicit integer/percentage rules and optional offline RUNorm.
  Normalization affects only spoken text; RUNorm remains opt-in after observed errors.
- [Speech adapters and profiles](guides/voice-adapters.md) share versioned contracts,
  explicit factories and lifecycle checks. Optional GigaAM code and historical
  pilot evidence are ported; board performance remains unverified.
- CLI, persistent text console and browser text/microphone adapters share one
  application flow. Web selects Whisper Server or optional resident Sherpa RU
  per recording, with Preview on engine changes and optional configured TTS replies.
- Russian/English requests find tracks, artists and albums, control playback and
  queues, like/unlike the current track, report now-playing and set volume.
  Relative volume defaults to ±20 with independently configurable steps.
- Unqualified music searches prioritize verified current album/artist context.
  Explicit scopes are retained; fresh Controller checks precede selection.
- Working rules and typed intentions belong to `assistant/nlu/`. Optional learned
  sources remain shadow-only; locale templates are separate from frozen corpora.
- Controller owns connection state, reviewed firmware compatibility, mutation
  pacing and typed device operations. Assistant owns language, ranking, storage
  and response policy. See [architecture](architecture/pipeline.md).

One action and one saved interaction locale per request remain required. An
uncertain mutation is never automatically replayed. Reconnect recovers observations.

## Acceptance and regression evidence

| Evidence | Result and boundary |
| --- | --- |
| [Vosk TTS](reports/2026-09-21-vosk-tts.md) | 431 tests (4 optional skips); all five voices passed five RU phrases, but each failed on the mixed Latin-name phrase. |
| [Silero/normalization](reports/2026-09-21-silero-normalization.md) | 421 tests (4 optional skips), 18 synthetic comparison WAVs. Pronunciation quality and board performance are not certified. |
| [Speech adapters/profiles](reports/2026-09-21-voice-adapters.md) | 409 tests (4 optional skips), real STT/TTS integration probes and five disposable V2.57 regression cases. No new human-speech/platform acceptance. |
| [Accepted software MVP](reports/2026-09-19-mvp-acceptance.md) | Candidate `48477e8`: 64/64 text cases, 35 RU / 29 EN; 19 no-mutation cases with zero writes. Existing accepted evidence, not a new run. |
| [Voice-command/Controller extension](reports/2026-09-21-development-checkpoints.md#pythoncontroller-review-follow-up-2026-09-21) | Corrected extension run: 30/30, including ten no-write cases; full V2.57 integration also passed. Earlier failed runs remain recorded separately. |
| [Repository reorganization](../../../docs/development/reports/2026-09-21-repository-refactor.md) | Import/path regression checks and one disposable now-playing scenario; no new physical or speech-quality acceptance. |

These are finite regression results. The accepted 64-case cohort uses text input;
owner-reported physical microphone successes do not establish a human-speech error
rate. The [MVP contract](reference/mvp.md) defines the accepted scope.

## Follow-up boundaries

- [Multi-STT coordination and speculative retrieval](architecture/recognition-coordination.md)
  have proposed typed contracts and architectural boundaries only. Runtime remains
  single-STT; no automatic arbitration, search prefetch or phonetic index is enabled.
- [Physical acceptance #23](https://github.com/eudj1n/snowsky-disc-qemu/issues/23)
  remains unpassed. Preserve the original 19-RU observations and disputed gold;
  use the [physical baseline](evaluation/physical-baseline.md) when resumed.
- [Speech/platform work #24](https://github.com/eudj1n/snowsky-disc-qemu/issues/24)
  remains separate and deferred: representative human speech, pronunciation,
  native/Docker/Orange Pi comparisons and latency. No new benchmark is implied.
- Learned execution, semantic retrieval, dialogue/compound planning, wake word/VAD,
  recommendations and dock hardware remain future decisions.
- Controller packaging is implemented; publication and repository extraction have
  not occurred. See the [quality review](../../../docs/development/reports/2026-09-21-python-quality.md).

The [roadmap](roadmap.md) routes future work to its owning issue.
[Development checkpoints](reports/2026-09-21-development-checkpoints.md) preserve
timings, failures and older test counts; [design history](reports/2026-09-21-design-history.md)
preserves superseded implementation plans.
