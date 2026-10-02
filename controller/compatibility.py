"""Reviewed DISC protocol contracts, selected from fresh device version readback.

No version ranges or implicit inheritance: new firmware needs explicit validation.
This registry describes existing guarded operations, not every raw protocol call.
"""

from enum import Enum
from typing import Any, Protocol


class Capability(str, Enum):
    PERSISTENT_SESSION = 'persistent_session'
    PLAYBACK_CONTROL = 'playback_control'
    QUEUE_READ = 'queue_read'
    QUEUE_NAVIGATION = 'queue_navigation'
    CATALOG_SNAPSHOT = 'catalog_snapshot'
    CURRENT_TRACK = 'current_track'
    CURRENT_FAVORITE = 'current_favorite'
    VOLUME = 'volume'
    SOUND_SETTINGS = 'sound_settings'


DISC_HANDSHAKE = '0306'


class IdentityClient(Protocol):
    def handshake(self) -> str: ...
    def settings(self) -> dict[str, Any]: ...


CONTRACTS = {
    240: frozenset({'network_check'}),
    257: frozenset({'audio_import', 'library_scan', 'favorite_positions', 'playlist_playback', 'playlist_edit', 'catalog_playback', 'seek', 'genre_playback',
                    'artist_playback', 'album_playback', 'folder_playback', 'network_check',
                    Capability.PERSISTENT_SESSION, Capability.PLAYBACK_CONTROL,
                    Capability.QUEUE_READ, Capability.QUEUE_NAVIGATION, Capability.CATALOG_SNAPSHOT,
                    Capability.CURRENT_TRACK, Capability.CURRENT_FAVORITE, Capability.VOLUME, Capability.SOUND_SETTINGS}),
}


def supports(version: object, feature: str) -> bool:
    return type(version) is int and feature in CONTRACTS.get(version, ())


def require(version: object, feature: str) -> None:
    if not supports(version, feature):
        raise ValueError(f'{feature.value if isinstance(feature, Capability) else feature} is not verified for DISC firmware {version!r}')


def require_client(client: IdentityClient, *features: Capability | str) -> int:
    """Read device identity and require explicitly reviewed capabilities."""
    if client.handshake() != DISC_HANDSHAKE:
        raise ValueError('unrecognized DISC handshake')
    version = client.settings().get('soc_version')
    if type(version) is not int:
        raise ValueError('DISC firmware version must be an integer')
    for feature in features:
        require(version, feature)
    return version
