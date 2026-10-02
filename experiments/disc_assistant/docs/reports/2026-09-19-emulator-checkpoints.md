# Emulator acceptance development checkpoints

Historical observations through 2026-09-19, preserved during the documentation
refactor. The [accepted MVP record](2026-09-19-mvp-acceptance.md) owns closure;
the [runner guide](../evaluation/emulator-acceptance.md) owns current commands.

## Validation checkpoint (2026-09-18)

The initial manifest-v2 full run completed 36 cases: **32 passed, 4 failed**.
Both locales exposed the same two behaviors: a member of a semicolon-delimited
artist tag did not retrieve its recording, and a previous-track request after
12 seconds restarted the current recording instead of selecting its predecessor.
The latter remains a product-contract discrepancy, not a transport failure.
The runner exits nonzero and preserves these cases rather than marking them passed.

Manifest v3 added six regression cases for the second credited artist,
artist/title without a dash and fuzzy title retrieval. These are examined regression
cases, not an independent holdout. Multi-artist matching is described in the
[Library metadata policy](../../../../library/README.md#multiple-artist-credits).
Screenshots of playing and paused fixtures were manually inspected on the stock
Now-playing screen; the runner makes no automatic visual-acceptance claim.
Firmware-free infrastructure verification passed 339 Python and 37 JavaScript tests.


Manifest v3 completed **40/42 passing** after multi-artist matching: both original
collaboration cases and all six second-member/prefix/fuzzy cases passed. Only the
two late previous cases remained. The owner then chose explicit predecessor
selection. Assistant now uses the shared Controller `previous_in_queue` helper:
one guarded positional selection, fresh queue/state verification, no mutation
retry. The first queue row is a no-op in every mode; a paused predecessor selection
starts playback. Native `previous_track()` still retains firmware semantics.
Manifest v4 adds paused/first-row cases, bringing the suite to 46 cases. The earlier
36- and 42-case reports remain unchanged as evidence of the measured progression.


Final focused run on manifest v4: **10/10 passed** — early/late previous,
paused previous, first-row no-op, and fuzzy second-artist retrieval in both RU/EN.
The late-selection screenshot was also manually inspected; send evidence contains
one `0100` mutation. The first navigation attempt's false `uncertain` results are
retained separately: it expected source flag 7, while current-queue selection
legitimately reports flag 0. A regression now pins that transition.

Final firmware-free checks: **349 shared Python tests, 37 JavaScript tests and
287 prototype tests passed**. The complete 46-case manifest has not been rerun
after the navigation change; the earlier complete 42-case run and final targeted
10-case run are distinct reports, not a fabricated 46/46 result. Physical
acceptance and numerical MVP thresholds remain pending.

## Full manifest-v4 checkpoint

Candidate `6798da09b692f047449fcc068a4c79db3e73f432` completed **46/46**
(23 RU / 23 EN) on 2026-09-18. The isolated run preserved fresh API/queue
readback, mutation evidence and screenshots for every case. Local report:
`/tmp/disc-review-stage1-46/results/report.json`. The paused-predecessor
screenshot was manually inspected and showed Signal Alpha playing. Other
screenshots are not claimed visually accepted. Earlier failed reports remain
unchanged. This closes the full-rerun gap above, not physical MVP acceptance.

Review stage 2 added eight cases. Initial result: **7/8**. The new `ru-zapusti`
case incorrectly required the Test Album edition of Signal Alpha despite the
existing lexical tie policy selecting Other Edition. Manifest v6 corrects that
new gold to Other Edition; no implementation change or original-report rewrite.
The corrected isolated case passed **1/1**. Reports: `/tmp/disc-review-stage2`
and `/tmp/disc-review-stage2-corrected`. All other new synonyms, compound credits
and sequence rejection passed. Prototype tests: 291. Full 54-case run is pending.

Review stage 3: **10/10 album cases passed** (`/tmp/disc-review-stage3`),
including complete multi-artist compilations, artist-scoped albums, Cyrillic and
absent names. The oracle derives complete membership from fixture metadata, not
the chosen Assistant candidate. Manifest v7 adds two synthetic compilation tracks
and ten cases; original fixtures are retained. 296 prototype and 350 shared Python
plus 37 JS checks passed. An additional focused 12-test run covers the new session
helper and oracle, including two newly added session tests and one new oracle test.
The public helper works over TCP and WS in unit fixtures; this Assistant album
cohort uses TCP. Physical album acceptance is still pending.

Review stage 4: **6/6 focused cases passed** after schema 4 rebuild and
known-artist prefiltering (RU/EN track, fuzzy collaboration member and compilation
album). Report: `/tmp/disc-review-stage4`. Prototype checks: 301. See
[isolated search and speech comparisons](2026-09-18-review-evaluation.md).

## Shared timing guard checkpoint (2026-09-19)

The full current **manifest v7 passed 64/64** after replacing unconditional command
sleeps with remaining-interval pacing. This includes controls, early/late/paused
previous, first-row no-op, compound artist credits, synonyms, single-action
rejection, and complete/scoped/compilation/Cyrillic album selection. Device and
queue readback verify outcomes independently of selected search candidates.

Local evidence: `/tmp/disc-pacing-acceptance-20260919/results/report.json` and its
per-case reports/screenshots. The source revision and working-tree patch are
retained by the harness. Temporary containers, network and volumes were removed.
Example EN/RU pause latencies were 76.794/77.175 ms; track selection took
324.130/293.273 ms. Rapid EN resume after setup pause still took 1999.296 ms;
the firmware interval remains enforced. These individual observations establish
absence of the old unconditional delay, not a controlled hardware speedup.
Screenshots are not claimed visually reviewed; no physical audio/MVP acceptance
is inferred. Earlier failed and focused reports remain unchanged.

Local Controller tests: 192 passed. Prototype tests: 354 passed. The final shared
firmware-free container suite passed 365 Python / 37 JavaScript tests.
