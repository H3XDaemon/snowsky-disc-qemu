# Experimental applications

These projects have separate launchers, dependencies and validation boundaries.
Their location does not imply equal maturity or extend firmware support.

| Project | Status and verified scope | Start here |
| --- | --- | --- |
| DISC Web | Independent experimental music remote; responsive UI, isolated demo and bounded live Controller facade. | [README](disc_web/README.md), [status](disc_web/docs/status.md) |
| Disc Assistant | Active text/voice application; software MVP accepted against stock V2.57. Quantified physical/speech acceptance remains separate. | [README](disc_assistant/README.md), [status](disc_assistant/docs/status.md) |
| Browser | Active TinyEMU/WASM prototype; experimental boot/UI evidence, separate from the supported qemu-user runtime. | [README](browser/README.md), [results](browser/docs/overview.md) |
| diskOS preview | Historical, unsupported source-built V2.40 preview; no recurring firmware acceptance gate. | [README](diskos/README.md), [results](diskos/docs/preview.md) |

Shared production-facing libraries remain outside this namespace. In particular,
Controller must never import an experiment. Firmware analysis belongs in
[`research/`](../research/README.md).

## Source-path migration

The former `research/{browser,diskos,disc_assistant}` directories now live here.
Use `experiments.*` for Python modules and `./experiments/disc_assistant/run.sh`
for the Assistant launcher. Its offline speech/search evaluations now live in
`disc_assistant/evaluation/`; working NLU remains in `assistant/nlu/`.

Configuration, application data, Docker project/volume names, service endpoints
and ignored `work/browser-disc` / `work/diskos-preview` outputs are unchanged.
A local Assistant environment moved with the directory can still be used through
`run.sh`, which calls its Python executable directly. Virtualenv activation and
installed console-script shebangs can retain the old absolute path: recreate that
local environment with `run.sh setup` if those entry points are needed. Preserve
existing configuration and external application data when doing so.
