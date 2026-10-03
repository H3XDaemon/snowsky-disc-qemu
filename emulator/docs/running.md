# Running the emulator

The emulator owns its host launcher, base Compose stack and pinned Docker image:
`emulator/run.sh`, `emulator/compose.yaml` and `emulator/docker/`.
The Compose service and its network hostname are both **`emulator`**.

## Setup and daily use

From the repository root:

```sh
cp emulator/.env.example emulator/.env
# Review firmware, media and volume settings before setup.
./emulator/run.sh up /absolute/path/to/main_os/ota_v257
./emulator/run.sh boot
./emulator/run.sh view
```

`up` also works without an env file when given an OTA path; it writes that path
into `emulator/.env` and preserves other existing settings. See
[firmware preparation](../../firmware/README.md) and [settings](settings.md).
The local env file is ignored by Git. Shell variables take precedence over it.

The launcher can be called by absolute path from any working directory. An OTA
argument or shell `OTA_DIR` is relative to the caller. Paths in Compose and a
configured relative `OTA_DIR` are relative to the repository root. Quoted paths
with spaces, dollars and quotes are preserved; paths containing newlines are
rejected. `shots/` remains at repository root, and default media stays under
`emulator/sdcard/`.

`boot --init` starts the guest through the stock init scripts instead of
launching the two programs directly; `boot --hold KEYS` holds keys from power-on.
`power on|reboot|off|cut` are power events that keep `/usr/data` and the card, and
`up-image` prepares a guest from a rootfs image built on the stock firmware. See
[stock init, power events and `/usr/data`](stock-init.md) and [keys](keys.md#keys-held-at-power-on).

`start` starts an existing stopped service without setup. `boot` initializes and
starts guest processes; `stop` stops only those guests. `shell`, `tap`, `capture`,
`audio`, `diag` and `wscheck` retain their documented roles; run `help` for syntax.
`down` removes the stack while retaining the work volume; only explicit `nuke`
requests volume deletion. The launcher addresses Compose services, so a configured
`EMU_CONTAINER_NAME` also works for execution and copying captures.

## Compose and optional services

Use the launcher to provide the correct project directory, env file and base YAML:

```sh
./emulator/run.sh compose config --quiet
./emulator/run.sh compose --profile wsbridge up -d wsbridge
./emulator/run.sh wscheck
./emulator/run.sh compose --profile wsbridge logs --tail 30 wsbridge
./emulator/run.sh compose --profile wsbridge stop wsbridge
```

An equivalent direct invocation from repository root is:

```sh
docker compose --project-directory "$PWD" --env-file emulator/.env \
  -f emulator/compose.yaml config --quiet
```

The launcher passes `/dev/null` as the env file when `emulator/.env` does not
exist. It never falls back to the root `.env` or another directory's config.
Explicit file/project flags also prevent ambient `COMPOSE_FILE` or caller-directory
Compose discovery from selecting a different stack.

The WS bridge connects to `emulator:12100` and stock HTTP on `emulator:12103`.
Its host publications, permissions and opt-in profile remain unchanged.
See [WebSocket usage](../../controller/docs/websocket.md).

## Existing checkouts

There is no root `run.sh` wrapper, root-env fallback or automatic migration.
Prepare `emulator/.env` explicitly; an old root `.env` is left untouched and ignored
by this launcher. Preserve any reviewed firmware, media and volume overrides you
want to retain.

An existing container created under the former Compose service `emu` still has
that service label. Stop/remove its old stack using the previous checkout before
starting the renamed service, keeping its work volume. The new launcher does not
adopt or automatically remove an old-service container. Reuse the intended named
volume with `WORK_VOLUME`; a different firmware requires a separate volume.

Project `snowsky-disc-qemu`, default container/image names and volume
`snowsky-disc-work` are unchanged. Guest `/emu` paths are internal runtime markers,
not Compose service names, and remain unchanged.

The image now carries a rebuilt qemu (`/usr/local/bin/qemu-mipsel-static`,
[static programs](stock-init.md#static-programs-and-the-devices)). After pulling
that change, recreate the container with `./emulator/run.sh compose up -d --build`;
a container from the previous image keeps working and its setup says
`QEMU_DEVICES=1 but … lacks the device patch` until it is rebuilt.

## Build and disposable checks

```sh
docker build -t snowsky-disc-qemu-ci emulator/docker
docker run --rm --network none -v "$PWD:/repo:ro" \
  snowsky-disc-qemu-ci bash /repo/ci/test.sh
bash ci/integration.sh /absolute/path/to/main_os/ota_v257
```

CI and experiment preparation explicitly use repository-root path resolution,
`--env-file /dev/null`, the base `emulator/compose.yaml` and disposable overlays.
They select unique projects/volumes and do not read interactive configuration.
The shared image remains one pinned toolchain; using it from CI does not change
its owner. The [test-selection policy](../../docs/development/ci.md#test-selection-policy)
defines full and optional long-running acceptance.
