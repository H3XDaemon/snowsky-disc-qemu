"""Public device models. No wire tags or application configuration/storage paths."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping
from controller.wire import validate_playback
from enum import Enum, IntEnum


@dataclass(frozen=True)
class DeviceConfig:
    host: str
    tcp_port: int = 12100
    http_port: int = 12103
    timeout: float = 8
    page_size: int = 200
    max_tracks: int = 100000
    max_requests: int = 10000

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip() or self.host != self.host.strip():
            raise ValueError('host must be a nonempty trimmed string')
        for name, low, high in (('tcp_port', 1, 65535), ('http_port', 1, 65535),
                                ('page_size', 1, 200), ('max_tracks', 1, 1000000), ('max_requests', 2, 100000)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} outside {low}..{high}')
        if type(self.timeout) not in (int, float) or not 0 < self.timeout <= 120:
            raise ValueError('timeout must be in (0,120] seconds')


class ConnectionState(str, Enum):
    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    READY = 'ready'
    RECONNECTING = 'reconnecting'


class PlaybackState(str, Enum):
    UNKNOWN = 'unknown'
    LOADING = 'loading'
    PLAYING = 'playing'
    PAUSED = 'paused'
    STOPPED = 'stopped'


class WirePlaybackState(IntEnum):
    """Stock Link state values; STOPPED may also mean loading in a snapshot."""
    PLAYING = 0
    PAUSED = 1
    STOPPED = 2


class PlaybackSource(IntEnum):
    """Reviewed stock playerflag values; artist scope may include an album."""
    CURRENT_QUEUE = 0
    LIBRARY = 1
    ARTIST = 2
    ALBUM = 3
    FOLDER = 4
    PLAYLIST = 5
    FAVORITES = 6
    ARTIST_SCOPE = 7
    GENRE_SCOPE = 8
    GENRE_TRACK = 10


class OperationStatus(str, Enum):
    NOT_SENT = 'not_sent'
    UNCERTAIN = 'uncertain'
    CONFIRMED = 'confirmed'
    ALREADY_SATISFIED = 'already_satisfied'
    PLAYING = 'playing'
    OBSERVED = 'observed'
    UNAVAILABLE = 'unavailable'


class PlayMode(str, Enum):
    LIST_ONCE = 'list_once'
    RANDOM = 'random'
    REPEAT_ONE = 'repeat_one'
    REPEAT_LIST = 'repeat_list'
    SINGLE_ONCE = 'single_once'


MODES = tuple(PlayMode)


@dataclass(frozen=True)
class Track:
    title: str
    artist: str | None
    album: str | None
    queue_position: int | None
    path: str | None = None
    duration_ms: int | None = None

    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    reported_bit_rate: int | None = None
    genre: str | None = None
    track_number: int | None = None
    is_dsd: bool | None = None
    is_sacd: bool | None = None
    is_cue: bool | None = None
    is_m3u: bool | None = None

    @property
    def identity(self) -> tuple[object, ...]:
        """Existing selection identity; optional descriptive fields are not selectors."""
        return (self.title, self.artist, self.album, self.queue_position, self.path, self.duration_ms)

    @property
    def metadata(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items()
                if key not in {'title', 'artist', 'album', 'queue_position', 'path', 'duration_ms'}
                and value is not None}

    @classmethod
    def from_wire(cls, state: object) -> Track | None:
        song = validate_playback(state if state is not None else {}).get('song') or {}
        if not isinstance(song, dict) or not song.get('song_name'):
            return None
        position = song.get('pos_id')
        genre = song.get('song_style_name')
        return cls(song['song_name'], song.get('song_artist_name'), song.get('song_album_name'),
                   position - 1 if type(position) is int and position > 0 else None,
                   song.get('song_file_path'), song.get('song_duration_time'),
                   sample_rate_hz=positive_integer(song.get('song_sample_rate')),
                   bit_depth=positive_integer(song.get('song_encoding_rate')),
                   channels=positive_integer(song.get('song_channel')),
                   reported_bit_rate=positive_integer(song.get('song_bit_rate')),
                   genre=genre if isinstance(genre, str) else None,
                   track_number=positive_integer(song.get('song_track')),
                   is_dsd=optional_boolean(song.get('is_dsd')),
                   is_sacd=optional_boolean(song.get('is_sacd')),
                   is_cue=optional_boolean(song.get('is_cue')),
                   is_m3u=optional_boolean(song.get('is_m3u')))


@dataclass(frozen=True)
class PlaybackSnapshot:
    state: PlaybackState
    track: Track | None = None
    position_ms: int | None = None
    mode: PlayMode | None = None
    scan_active: bool | None = None
    observed_at: float | None = None
    favorite: bool | None = None
    source: PlaybackSource | None = None

    @classmethod
    def from_observation(cls, observation: Mapping[str, Any]) -> PlaybackSnapshot:
        state = validate_playback(observation.get('state') or {})
        mode = observation.get('mode')
        return cls(
            state=PlaybackState(observation.get('playback', 'unknown')),
            track=Track.from_wire(state), position_ms=observation.get('position_ms'),
            mode=MODES[mode] if type(mode) is int and 0 <= mode < len(MODES) else None,
            scan_active=observation.get('scan_active'),
            observed_at=observation.get('observed_at'), favorite=state.get('love'),
            source=source_from_wire(state.get('playerflag')),
        )

    @classmethod
    def from_wire(cls, state: object) -> PlaybackSnapshot:
        state = validate_playback(state if state is not None else {})
        track = Track.from_wire(state)
        value = state.get('state')
        label = 'unknown'
        if track and value in (WirePlaybackState.PLAYING, WirePlaybackState.PAUSED):
            label = 'playing' if value == WirePlaybackState.PLAYING else 'paused'
        if value == WirePlaybackState.STOPPED:
            label = 'loading'  # A snapshot alone never proves final stop.
        return cls(PlaybackState(label), track, favorite=state.get('love'),
                   source=source_from_wire(state.get('playerflag')))


@dataclass(frozen=True)
class QueueItem:
    position: int
    title: str
    artist: str


@dataclass(frozen=True)
class QueueSnapshot:
    items: tuple[QueueItem, ...]
    selected_position: int | None
    mode: PlayMode
    continuation: str
    playback: PlaybackSnapshot

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> QueueSnapshot:
        return cls(tuple(QueueItem(row['pos'], row['name'], row['author']) for row in value['items']),
                   value['mark'] if value['mark'] >= 0 else None, MODES[value['mode']],
                   value['continuation'], PlaybackSnapshot.from_wire(value.get('state')))


@dataclass(frozen=True)
class DeviceSnapshot:
    connection: ConnectionState
    enabled: bool
    generation: int
    playback: PlaybackSnapshot
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_status(cls, status: Mapping[str, Any]) -> DeviceSnapshot:
        return cls(ConnectionState(status['connection']), status['enabled'], status['generation'],
                   PlaybackSnapshot.from_observation(status['observation']), status.get('last_error'))


@dataclass(frozen=True)
class CommandResult:
    operation_id: str
    status: OperationStatus
    action: str
    mutation_attempted: bool
    playback: PlaybackSnapshot
    queue: QueueSnapshot | None = None
    outcome: str | None = None
    reason: str | None = None
    requested_mode: PlayMode | None = None
    previous_mode: PlayMode | None = None
    confirmation: dict[str, Any] | None = None
    volume: int | None = None
    previous_volume: int | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_result(cls, result: Mapping[str, Any], action: str) -> CommandResult:
        return cls(
            operation_id=result['operation_id'], status=OperationStatus(result['status']), action=action,
            mutation_attempted=result.get('mutation_attempted', False),
            playback=PlaybackSnapshot.from_wire(result.get('state')),
            queue=QueueSnapshot.from_wire(result['queue']) if 'queue' in result else None,
            outcome=result.get('outcome'), reason=result.get('reason'),
            requested_mode=mode_from_wire(result.get('requested')),
            previous_mode=mode_from_wire(result.get('previous')),
            confirmation=result.get('confirmation'), volume=volume_from_wire(result.get('volume')),
            previous_volume=volume_from_wire(result.get('previous_volume')), error_type=result.get('error_type'),
        )



def mode_from_wire(value: object) -> PlayMode | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value < len(MODES):
        raise ValueError('invalid play mode in operation result')
    return MODES[value]


def volume_from_wire(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 120:
        raise ValueError('invalid volume in operation result')
    return value


def source_from_wire(value: object) -> PlaybackSource | None:
    if type(value) is not int:
        return None
    try:
        return PlaybackSource(value)
    except ValueError:
        return None


def positive_integer(value: object) -> int | None:
    """Optional metadata must not coerce booleans, text or firmware sentinels."""
    return value if type(value) is int and 0 < value <= 2147483647 else None


def optional_boolean(value: object) -> bool | None:
    return value if type(value) is bool else None
