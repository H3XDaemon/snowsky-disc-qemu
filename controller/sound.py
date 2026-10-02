"""Narrow sound settings on the persistent owner; observed values, never retries."""
import time
from typing import Any, TYPE_CHECKING

from controller.compatibility import Capability, require_client
from controller.fiio_settings import setting_command, setting_query, setting_value
from controller.wire import frame
from controller.link_commands import Sender

if TYPE_CHECKING:
    from controller.session import LiveClient

SOUND_SETTINGS = ('gain', 'balance', 'filter', 'dre')
SOUND_READ_TAGS = (b'064a', b'0712', b'0603', b'0813')
SOUND_WRITE_TAGS = (b'0649', b'0713', b'0653', b'0812')


def validate(name: str, value: int) -> None:
    if name not in SOUND_SETTINGS:
        raise ValueError('unsupported sound setting')
    setting_command(name, value)


class SoundCommands:
    socket: Sender

    def request(self, tag: str, payload: bytes | str = b'', *, expected: str | None = None) -> bytes:
        raise NotImplementedError

    def sound_setting(self, name: str) -> int:
        if name not in SOUND_SETTINGS:
            raise ValueError('unsupported sound setting')
        value = setting_value(name, self.request(setting_query(name)))
        validate(name, value)
        return int(value)

    def set_sound_setting(self, name: str, value: int) -> None:
        validate(name, value)
        self.socket.sendall(frame(*setting_command(name, value)))


def read_settings(client: 'LiveClient') -> dict[str, Any]:
    version = require_client(client, Capability.SOUND_SETTINGS)
    client.scan_guard()
    values = {name: client.sound_setting(name) for name in SOUND_SETTINGS}
    client.scan_guard()
    return dict(status='observed', mutation_attempted=False,
                confirmation={'settings': values, 'soc_version': version})


def change_setting(client: 'LiveClient', name: str, value: int, expected: int, timeout: float) -> dict[str, Any]:
    client.wait_for_mutation()
    require_client(client, Capability.SOUND_SETTINGS)
    client.scan_guard()
    before = client.sound_setting(name)
    client.scan_guard()
    if before != expected:
        return dict(status='not_sent', mutation_attempted=False, outcome='sound_changed',
                    confirmation={'name': name, 'value': before})
    if before == value:
        return dict(status='already_satisfied', mutation_attempted=False,
                    confirmation={'name': name, 'value': before})
    client.begin_phase('sound')
    client.set_sound_setting(name, value)
    deadline = time.monotonic() + timeout
    observed = before
    while time.monotonic() < deadline:
        observed = client.sound_setting(name)
        client.scan_guard()
        if observed == value:
            return dict(status='confirmed', mutation_attempted=True,
                        confirmation={'name': name, 'value': observed})
        if client.closed.wait(min(.15, max(0, deadline-time.monotonic()))):
            raise ConnectionError('connection lost after sound change; no replay')
    return dict(status='uncertain', mutation_attempted=True, outcome='sound_unconfirmed',
                confirmation={'name': name, 'value': observed})
