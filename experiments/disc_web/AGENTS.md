# DISC Web contributor instructions

Read root `AGENTS.md`, this project's [README](README.md),
[architecture](docs/architecture.md) and [status](docs/status.md).

- Keep the application under `experiments/disc_web` until explicit promotion.
  Documentation and source comments remain English. UI strings belong in the
  paired RU/EN dictionaries; never translate device metadata. Appearance and
  language preferences stay browser-local and never change device settings.
- Controller owns protocol behavior and guarded mutations. This app owns HTTP,
  presentation, request admission and UI state. Do not import Assistant, viewer,
  research or emulator runtime into production code, or reverse-import this app
  from Controller. Do not forward arbitrary wire commands from an endpoint.
- One application process owns one `DiscSession`. Do not auto-connect or steal
  another application's stock TCP connection. Shared Assistant runtime is a
  future integration, not achieved by running two independent sessions.
- Preserve same-origin/token validation, connection-generation checks, busy
  rejection and no mutation replay. Demo must never open a device connection.
- Keep demo data clearly labelled and separate from observed device data.
  Never substitute demo metadata, duration or artwork after a live read fails.
- All SVG artwork is original fictional demo content. Do not commit personal
  catalog data, firmware-derived assets, recordings or private screenshots.
- Use `run.sh test` and the repository firmware-free suite; choose additional
  firmware tests by impact. UI updates need browser verification including a
  narrow viewport. Real device use requires explicit session authorization.
