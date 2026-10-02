# Assistant interpretation, language and speech boundaries

Implemented in the experimental Assistant on 2026-09-18. This supersedes the earlier
merged-input/separate-response language policy. One locale now governs interaction;
interpreters and speech engines have independent provider contracts.

## Pipeline

[Recognition coordination](recognition-coordination.md) defines proposed
multi-STT assessment/selection boundaries and speculative search constraints.
Those interfaces are not connected to this live, single-STT pipeline.

```text
Typed text ------------------------+
                                   v
WAV file --> Transcriber -> text -> Interpreter(text, context)
Browser microphone ------^
                                   |
                           validated intention
                                   |
              +--------------------+-------------------+
              |                    |                   |
       music reference       playback control    language change
              |                    |                   |
    catalog resolver/ranker        |             Preferences
              |                    |                   |
    fresh guarded selection ------> Controller         |
              |                    |                   |
              +------------ operation result ----------+
                                   |
                          localized response
                                   |
                         speak? -> TextNormalizer -> Synthesizer -> AudioOutput
```

Text, WAV and browser microphone input use the same command pipeline. Web selects
resident Whisper Server or the optional Sherpa RU worker per audio request; CLI
can select CLI or server STT explicitly. Configured TTS (Piper or optional Silero/Vosk)
synthesizes eligible replies for browser playback; macOS `say` remains a file-sample
adapter. [Speech services](../guides/tts.md) are optional and independent of the
Controller. Dialogue remains disabled.

## Interpretation

[`interpreter.py`](../../assistant/nlu/interpreter.py) defines:

```python
async def interpret(text: str, context: InterpretationContext) -> Interpretation:
    ...
```

Context is an immutable value containing the active locale, a cached playback
label (`unknown` when unavailable) and optional music-name hints. It contains no
Controller, socket, database or mutable application session. CLI interpretation
currently receives unknown playback; console interpretation uses cached state,
without a new network query. Hints default to empty; the full library is not sent
to an external provider automatically.

`Interpretation` has status `recognized`, `unrecognized` or `unsupported` and a
validated intention only when recognized:

| Intention | Meaning |
| --- | --- |
| `Intent(query, kind, artist, title)` | Music request; unresolved names remain text, not guessed track IDs |
| `AlbumIntent(query, album, artist, kind="album")` | Explicit whole or artist-scoped album; no catalog IDs from the interpreter |
| `ControlIntent(action)` | Allowlisted pause/resume/stop/next/previous, current-track likes and read-only now-playing |
| `VolumeIntent(value, direction)` | Absolute 0..120 or configured relative up/down; exactly one form |
| `LanguageIntent(locale)` | Set one installed, valid interaction locale |

The `RuleInterpreter` wraps the existing literal grammar. Local-model and remote
implementations can implement the same protocol and be explicitly injected into
`Application`, console `run` or CLI `main` in Python. The executing backend remains rules. An optional loopback structured-model
source contributes only shadow evidence; it is not an executing Interpreter and
there is no automatic local/remote fallback.
Each provider identifies its name, version and `local`/`remote` execution through
`ProviderInfo`. Backend adapters should translate their own transport/model failures
to `ProviderUnavailable`; the boundary also maps unexpected backend exceptions to a sanitized provider error.

`interpret_request` bounds input, validates result types and the intention
allowlist, and records provider identity, locale and interpreted status in the
journal. Invalid output, provider unavailability, unsupported requests and
unrecognized text remain distinct. Cancellation propagates; no provider fallback
or device mutation retry follows it. Future adapters must configure bounded
network/model deadlines and return typed results rather than executable text.

The application interprets a natural request exactly once. The launcher does not
parse commands to decide whether search is needed. It prepares search credentials
when available; absence does not block control or language commands. Maintenance
slash commands remain explicit application commands outside natural interpretation.

[`resolver.py`](../../assistant/resolver.py) resolves an
interpreted music reference against the current catalog. It can infer artist/title
boundaries from known names. `ranking.rank` accepts an `Intent`, not raw command
text; search and ranking cannot reinterpret the command. Search result IDs remain
snapshot-scoped. Controller preflight and observed playback remain the authority
for execution, regardless of which interpreter supplied the intention.

The console pins connection generation before transcription and a potentially slow interpreter and
checks it before dispatch, then retains the existing check after search. A request
spanning a reconnect is not sent on the new connection. Fresh playback/control
checks still handle changes within the same connection.

## One interaction locale

```toml
[language]
locale = "ru"

[response]
mode = "errors"
```

`locale` selects command syntax, user response templates and the context supplied
to speech providers. Device UI language remains independent and unknown
through the supported remote contract. Music titles, artist names and aliases may
use any language. A Russian command can contain `Linkin Park — Numb`.

The first startup persists the effective locale even when command journaling is
disabled. Precedence is explicit `--language CODE`, then the saved preference,
then configuration, then the built-in `ru` default. The startup override is durable:

```sh
./experiments/disc_assistant/run.sh --language en listen
./experiments/disc_assistant/run.sh --language ru ask 'Включи Linkin Park — Numb'
```

```text
/language ru
Переключи язык на английский
Switch language to Russian
/language reset
```

Natural language changes use the current language's command syntax and the same
settings handler as `/language`. A successful change is acknowledged in the new
language. `/rank`/one-shot `rank` can preview a language intent without applying it.
An executed audio transcription passes through this same handler. `/language` with no
arguments reloads the saved value; reset stores the current TOML default.

Open consoles keep their locale until a settings command reloads preferences or
the console restarts. In-flight requests use their captured configuration. There
is no language auto-detection, mixed command-language mode or independent response
language. `/response` controls only `none|errors|all` speech eligibility. Help and
technical diagnostics remain English; localized user feedback is `response.text`.

Metadata version labels are separate from command language. The library's
[`version_markers.toml`](../../../../library/version_markers.toml)
recognizes recording conventions such as `Live` and `Remastered` even when Russian
is active. The locale's version phrases describe requested constraints; they also
extend metadata recognition for localized labels. No sync/reindex is needed for a
locale switch. Lexical version markers remain heuristics, not recording identity. This behavior
is recorded as `lexical-v3`; journal context pins metadata-marker and
transliteration hashes. The search signature also pins spelling projection.

Common recording labels also remain explicit query constraints across locales:
`Включи Linkin Park — Numb live` requires a live edition even in Russian mode.
Locale-specific version phrases extend those shared labels. A missing requested
edition is not silently replaced with a studio recording.

## Migration and storage

The settings table stores `language.locale` and `response.mode`. The current
Assistant database is schema 3; the language refactor itself required no schema
bump. The later [command catalog](../reference/command-catalog.md) migration adds
snapshot tables without rewriting settings/history. Language migration and startup
resolution occur in one SQLite transaction; validation failure preserves old keys.
Existing configuration files are read compatibly and are never rewritten.

For configuration, explicit `[language].locale` is preferred. Without it, the first
entry of legacy `[language].enabled` supplies the locale; legacy `[response].language`
is used only when no input language exists. With neither, use `ru`.

For saved settings, existing `language.locale` wins. Otherwise the first legacy
`language.enabled` entry wins over the old response locale. Without an input list,
use `response.preferences.language`, then the configured locale. Speech mode is
migrated independently. Both canonical keys are written before the legacy keys
are removed. Explicit `--language` takes precedence over legacy locale selection.

Example: saved input `["ru", "en"]` and response `en/all` become locale `ru`, mode
`all`. The policy deliberately preserves the primary input language. `/language en`
is the explicit way to choose English afterwards. Multiple codes in `/language`
and `/response language` now fail with guidance; they do not create divergent settings.
Corrupt locale/mode values can be repaired with `language reset`/`response reset`.

## Speech provider contracts

The [adapter and profile guide](../guides/voice-adapters.md) owns registration,
capabilities, lifecycle, extension examples and the device-free model matrix.
Application-owned speech instances use one stable event loop; Web and CLI do not
select concrete engine classes. Legacy `speech.py` and adapter imports remain compatible.

[`voice/contracts.py`](../../assistant/voice/contracts.py) defines version-1 independent
asynchronous protocols:

| Contract | Input | Output |
| --- | --- | --- |
| `Transcriber.transcribe` | `Audio`, `SpeechContext` | `Transcription(text, locale, no_speech)` |
| `SpeechSynthesizer.synthesize` | `SynthesisRequest(text, context, voice)` | `Audio` |
| `AudioCapture.record` | Maximum recording duration | `Audio` |
| `AudioOutput.play` | `Audio` | Completion or failure |

`Audio` includes bytes, media type, sample rate and channel count. `SpeechContext`
contains locale, request ID and optional music vocabulary. Locale is explicit
context, not a prohibition on foreign artist/title words. A transcription cannot
implicitly switch the application locale. Providers report `no_speech` separately
from failures and preserve cancellation. They share `ProviderInfo` and
`ProviderUnavailable`; capture/output implementations remain independent of engines.

The web response-delivery layer checks `response.speak`, uses the response's locale
and records synthesis and browser-reported playback separately. It cancels obsolete
audio and never changes an execution outcome or retries a command after a delivery
failure. Browser sound requires explicit user opt-in. Native TTS PCM rate is retained;
explicit STT samples use recorded SoXR conversion to 16 kHz. The bounded cache keys
include voice/config hashes and the TTS-only text preparation revision/model digest (identity by default; explicit rule or RUNorm profiles). Search aliases and original response text are unaffected. See
[TTS delivery](../guides/tts.md) and [file evaluation](../guides/voice.md).
Streaming, automatic voice discovery, dialogue and representative human speech
quality/latency evaluation remain future work.

`voice/sherpa.py` owns a lazily loaded subprocess using the separately installed
Sherpa environment. The native recognizer and reviewed hashes live in
`voice/sherpa_model.py`, with no evaluation imports in the runtime. One worker is
reused across the application's per-request event loops. Timeout/cancellation
kills and reaps that worker before releasing the request; no input is replayed.
A later explicit request can start a fresh worker. The web service closes it on
shutdown. Russian is the only supported command locale; catalog hints are explicitly
disabled and journalled as unsupported, without reading the catalog vocabulary.
The common result validation and connection-generation checks remain authoritative.

Dialogue stays disabled: `interactive` is false and `dialogue.enabled=true` is
rejected. These interfaces do not add questions, pending confirmations or choices.

## Pending learned providers

The [NLU comparison plan](../evaluation/nlu-research.md) separates intent classification
and slot extraction from catalog name recovery and descriptive search. Candidate
implementations include a composite Interpreter, Typesense hybrid retrieval and
a validated Natural Language Search adapter. They share existing typed intent,
snapshot and guarded execution boundaries; none is currently enabled.


Read-only implementations now live in
[`assistant/nlu/evaluation`](../../assistant/nlu/evaluation/README.md).
They evaluate class labels and candidate sources without installing a live
Interpreter provider. Label similarity cannot fabricate music/language slots;
prototype vector candidates still pass through the common final ranker. See the
[measured checkpoint](../evaluation/nlu-research.md#first-model-experiment-checkpoint).

## Diagnostic learned interpretation

`/explain TEXT` is an explicit non-executing application command. It compares the
existing parser with extraction templates/guards and an optional portable learned
classifier from a versioned locale snapshot. It does not register a new executing
provider, resolve a music catalog, call Controller or change language from the
text. `/commands` manages that snapshot independently of Library generations.
See [the command catalog](../reference/command-catalog.md) for storage, publication,
training boundaries and the remaining acceptance gates.


## Independent evidence and single-action policy

The [source contract and shadow collector](interpretation-sources.md) now
separate experimental evidence from the executing Interpreter. Sources receive
text/context and return validated intentions or explicit incomplete/rejected/unavailable
results, with source-local scores and hashes. Shadow comparison never overrides
the primary. A future selector is a separate policy/model, not an implicit sum
of incompatible scores. The shared bounded compound-command guard runs before
primary interpretation for both typed and transcribed input. The MVP has one
action per request; no planning, sequencing or dialogue is implemented.


## NLU component organization

The working NLU code is grouped under `assistant/nlu`. Optional offline tools are
in `nlu/evaluation`; corpora/reference examples are in `nlu/data`. Locale resources
remain in `assistant/locales` for contributors. See [component ownership](../../assistant/nlu/README.md).
Learned execution remains disabled. Current-track/favorite/volume commands use
the same typed text/speech interpretation and capability-checked Controller path.
Contextual music ranking reads a fresh native queue, with a second guard before
selection; no interpretation provider receives device handles.
