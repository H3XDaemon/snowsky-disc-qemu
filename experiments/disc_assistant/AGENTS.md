# Disc Assistant contributor instructions

Read root `AGENTS.md`, then [current status](docs/status.md) and
[architecture](docs/architecture/pipeline.md). This file applies to
`experiments/disc_assistant/`. Conversation may be Russian; tracked documentation
and comments remain English. [Documentation ownership](../../docs/decisions/0001-component-and-documentation-ownership.md)
defines where maintained guidance and historical evidence belong.

## Accepted scope and deferred work

The owner accepted software MVP against stock V2.57 on 2026-09-19 using the
existing 64/64 text scenarios (35 RU / 29 EN), including 19 zero-write cases.
[Issue #21](https://github.com/eudj1n/snowsky-disc-qemu/issues/21) is complete in
that scope. Preserve the [acceptance report](docs/reports/2026-09-19-mvp-acceptance.md)
and its candidate/cohort provenance; do not require new hardware/audio runs to
reopen it or relabel later extensions as the accepted run.

Physical acceptance #23 remains unpassed. Preserve the original private 19-RU
observations, failures and disputed expectation; consult the
[physical worksheet](docs/evaluation/physical-baseline.md) before resuming.
Speech/native-Docker/Orange Pi quality/performance #24 is separately deferred.
Historical reports do not authorize fresh physical connections or benchmarks.
Promotion from experiments, repository extraction and publication are separate
owner decisions. NLU already is an ordinary Assistant subsystem.

## Ownership and runtime contracts

- `assistant/application.py` owns the common flow; console and web are adapters.
  `assistant/nlu/` owns executing rules and typed intentions. Optional learned
  sources stay shadow-only and excluded from execution arbitration.
- Root `library/` (shared with DISC Web) owns catalog observations, snapshot storage and retrieval/ranking
  support. Source artist tags remain exact device selectors; derived artist
  membership requires `/index` when its projection changes, not another `/sync`.
- Controller owns persistent device state, guarded operations and compatibility.
  Use its public facade and typed results; do not duplicate wire frames or add
  Controller imports from Assistant, experiments, research, emulator or viewer.
- Preserve one action and one saved input/response locale per request, fresh
  selection/queue checks and rejection across connection generations. Never
  replay uncertain writes or queue disconnected requests for later playback.
- Keep shared `MutationPacer`: wait only for the remaining stock 2.1-second
  interval before fresh preflight. Reads/no-ops do not reset it; mutation attempts
  do. Do not restore unconditional sleeps or remove the firmware guard.
- One foreground application owns the local data-directory lock and stock TCP
  connection. Do not steal a console/FiiO Control connection. Explicit disconnect
  disables reconnect; unexpected loss permits observation recovery only.
- Speech adapters implement `voice/contracts.py` v1 and register through `voice/registry.py`.
  Model/profile settings remain separate from core dispatch. Runtime owns one stable
  event loop and closes owned resources; external model services are operator-owned.
  Keep optional engine dependencies isolated. See `docs/guides/voice-adapters.md`.
- Web stays loopback-only; requests explicitly select Whisper Server or optional
  resident Sherpa RU. Preserve Preview on engine changes and never fall back between
  engines or map unsupported locales silently. Piper replies require saved
  speech policy and explicit browser sound opt-in. Delivery failure is not a
  reason to change or replay a device command. Keep TTS normalization limited to the spoken copy. Identity is the compatibility
  default; explicit Silero profiles select ru_numbers or optional RUNorm. Preserve
  original response/catalog text and normalization provenance; no engine fallback.
- Setup preserves config, keys and installed models unless explicitly replaced.
  Keep private state outside Git and preserve independent device/data namespaces.

## Locales, evaluation and evidence

Command/reply templates live in `assistant/locales`; contributors adding a
language should not need to edit a Python registry. Training examples belong in
`assistant/nlu/data`, not locale templates. Optional NLU tooling lives in
`assistant/nlu/evaluation`; speech/search comparisons live in `evaluation/`.
ML dependencies are not ordinary runtime requirements.

Frozen corpora, labelled references and acceptance payloads must not be silently
edited or trained/calibrated against examined failures. `commands-v2` (manifest
`commands-v2.1`, 609 rows) is examined regression; `slot_acceptance.json` is
implementation acceptance, not an independent holdout. Preserve old study runners
and policy revisions; new comparisons need distinct provenance.

Personal histories, catalogs, annotations, audio, models, reports and credentials
stay outside Git. Commit only curated synthetic fixtures and sanitized aggregates.
Offline shadow reporting consumes explicit exports; it must not open runtime
storage, connect to a player, train, select a model or rerun providers. Disagreement
is not error; gold metrics require reviewed labels. Preserve partial failures,
unknowns and observation/readback distinctions rather than claiming confirmation.

## Validation and handoff

Use `./experiments/disc_assistant/run.sh test`, not `emulator/run.sh`.
Synthetic loopback tests may need sandbox socket permission; they require no
physical device. Browser audio/reply checks live under `assistant/web/test_*.mjs`.
`run.sh check` uses disposable Typesense/synthetic peers; `ci/assistant.sh` owns
stock-firmware acceptance on disposable resources. Choose checks by impact;
documentation changes need link/diff checks, not another device run.

Update current guides/contracts when behavior changes. Put measured evidence,
failures and source hashes in dated reports; current status links to those records.
Keep actionable follow-ups in their existing issues and preserve unrelated work.
