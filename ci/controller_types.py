"""Static consumer contract; checked by mypy, never connects to a device."""
from typing import assert_type

from controller import CommandResult, DeviceConfig, DeviceSnapshot, DiscSession
from controller.contracts import ControlClient
from controller.session import LiveClient


def consumer(client: LiveClient) -> None:
    guarded: ControlClient = client
    assert_type(guarded.now_playing().get('love'), bool | None)
    player = DiscSession(DeviceConfig('localhost'))
    assert_type(player.snapshot(), DeviceSnapshot)
    assert_type(player.current_track(), CommandResult)
    assert_type(player.set_favorite(True).playback.favorite, bool | None)
    assert_type(player.set_volume(40).volume, int | None)
    assert_type(player.adjust_volume(-20).previous_volume, int | None)
    assert_type(player.sound_settings(expected_generation=1), CommandResult)
    assert_type(player.set_sound_setting('gain', 1, expected=0, expected_generation=1), CommandResult)
    assert_type(player.pause(), CommandResult)
    assert_type(player.play_album('Album'), CommandResult)
