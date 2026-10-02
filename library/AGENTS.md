# Library contributor instructions

Read the root instructions and this component's README. Library owns catalog
observations, SQLite snapshots, offline projections and optional search adapters.
It must not import Assistant, Web, experiments, emulator, viewer or research.
Controller remains independent of Library. Applications provide the owned
connection and choose private storage directories; imports perform no I/O.

Keep literal device metadata and duplicate multiplicities. Snapshot IDs and
positions are observations, not permanent recording identities or ready-to-send
playback commands. Publish complete verified snapshots atomically and preserve
the previous snapshot on failure. Search/enrichment must not mutate a player.
Typesense remains optional. Tests use curated synthetic data and temporary stores;
never commit personal catalogs, artwork or generated databases.

Library owns enrichment association, provenance and the synchronization pipeline;
applications own admission and pass their existing session lease. Keep enrichment
separate from raw tags. Never advance playback to collect metadata, silently
transfer observations across snapshots, or weaken duplicate/scan/identity guards.
