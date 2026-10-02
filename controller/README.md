# SNOWSKY DISC Controller

Local TCP/HTTP control with fresh preflight, bounded confirmation and no replay
of uncertain mutations. Python 3.11 or newer; the core uses only the standard
library. This is an unofficial client, not firmware.

Build from this directory with `python -m build`. Install the wheel, or use
`pip install ./controller` from the integration repository. The distribution name
is `snowsky-disc-controller`; Python imports remain `controller`. Optional
`[websocket]` and `[bridge]` extras install aiohttp. Importing the core does not
load these extras.

```python
from controller import DeviceConfig, DiscSession, OperationStatus

with DiscSession(DeviceConfig("127.0.0.1")) as player:
    player.connect()
    if player.wait_ready(8):
        result = player.current_track()  # Fresh observation, no mutation.
        if result.status is OperationStatus.OBSERVED:
            print(result.playback.track)
```

`snapshot()` is cached; `current_track()` performs a fresh read. `pause()`,
`resume()`, `next_track()`, `previous_track()`, `previous_in_queue()`,
`set_favorite(bool)`, `set_volume(int)` and `adjust_volume(int)` return the same
typed `CommandResult`. Volume is 0..120; relative adjustments clamp at the limits.
Unknown/unavailable observations, unsent operations and uncertain mutations are
distinct. Never retry an uncertain result automatically.

`sound_settings()` observes gain, channel balance, DAC filter and DRE.
`set_sound_setting(name, value, expected=current_value)` changes one reviewed
parameter with fresh preflight and readback. Both accept `expected_generation`
for displayed-connection guards; see the [sound API](docs/api.md#sound-settings).

`DiscSession` serializes commands and owns one connection. Explicit disconnect
prevents reconnection; unexpected disconnect permits observation recovery but
never mutation replay. Only explicitly reviewed firmware capabilities are
enabled. The active guarded contract is DISC V2.57; new firmware requires review.

The versioned public exports are listed in `controller.__all__`. The 0.x API may
change between minor releases; patch releases preserve the public contract.
Wire clients (`fiio_link`, `fiio_ws`) and operation borrowing are advanced APIs,
separate from the session facade. Borrowing requires exclusive ownership and
fresh device/catalog guards. Private transport implementation is not a public
compatibility promise. No package is published by the build or test scripts.

Synthetic tests live under `tests/` in the source tree; they are not distributed
in the wheel. Emulator/firmware acceptance belongs to the integration repository.
The wheel includes the bridge inspector HTML and PEP 561 type marker. Before a
repository split, copy this component with its tests and license, then keep the
installed-wheel check in the consuming repository.

See the [Controller documentation](docs/README.md) for the API and optional bridges.
