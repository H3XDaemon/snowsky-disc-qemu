"""Strict decoding at the Link boundary; absent fields remain absent.

Unknown numeric states/sources are retained for diagnostics, never promoted to
a reviewed enum. Extra firmware fields remain available to raw clients.
"""
import json
from typing import Any, TypedDict, cast


class WireSong(TypedDict, total=False):
    song_name: str
    song_artist_name: str
    song_album_name: str
    song_file_path: str
    pos_id: int
    song_duration_time: int


class WireState(TypedDict, total=False):
    state: int
    playerflag: int
    love: bool
    song: WireSong


def validate_playback(value: object) -> WireState:
    if not isinstance(value, dict):
        raise ValueError('now-playing payload must be an object')
    result = value.copy()
    for key, kind in (('state', int), ('playerflag', int), ('love', bool)):
        if key in result and type(result[key]) is not kind:
            raise ValueError(f'now-playing {key} has an invalid type')
    if 'song' in result:
        song = result['song']
        if isinstance(song, str):
            song = json.loads(song)
        if not isinstance(song, dict):
            raise ValueError('now-playing song must be an object')
        song = song.copy()
        for key in ('song_name', 'song_artist_name', 'song_album_name', 'song_file_path'):
            if key in song and not isinstance(song[key], str):
                raise ValueError(f'now-playing {key} must be a string')
        if 'pos_id' in song and (type(song['pos_id']) is not int or song['pos_id'] < 0):
            raise ValueError('now-playing pos_id must be a nonnegative integer')
        if 'song_duration_time' in song and (type(song['song_duration_time']) is not int or song['song_duration_time'] < 0):
            raise ValueError('song duration must be nonnegative integer milliseconds')
        result['song'] = song
    return cast(WireState, result)


def playback_snapshot(reply: bytes) -> WireState:
    # Empty a202 is observed while loading and at final EOF.
    return validate_playback(json.loads(reply)) if reply else {}


def settings_snapshot(reply: bytes) -> dict[str, Any]:
    value = json.loads(reply)
    if not isinstance(value, dict):
        raise ValueError('settings payload must be an object')
    for key in ('soc_version', 'currentVolume'):
        if key in value and type(value[key]) is not int:
            raise ValueError(f'settings {key} must be an integer')
    if 'currentVolume' in value and not 0 <= value['currentVolume'] <= 120:
        raise ValueError('current volume outside 0..120')
    return value


def volume_command(value: int) -> tuple[str, str]:
    if type(value) is not int or not 0 <= value <= 120:
        raise ValueError('volume outside 0..120')
    return '0502', f'{value:04X}'


def favorite_command(value: bool) -> tuple[str, str]:
    if type(value) is not bool:
        raise ValueError('favorite must be a boolean')
    return '0104', '0001' if value else '0000'


def frame(tag: str, payload: bytes | str = b'') -> bytes:
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    if len(tag) != 4 or any(c not in '0123456789abcdefABCDEF' for c in tag):
        raise ValueError('tag must have four hex digits')
    if len(payload) > 65535 - 8:
        raise ValueError('frame too large')
    return tag.encode('ascii') + f'{8 + len(payload):04X}'.encode() + payload

def hex_value(value: int, maximum: int = 65535, width: int = 4) -> str:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'value outside 0..{maximum}')
    return f'{value:0{width}X}'

def play_mode_value(reply: bytes) -> int:
    if len(reply) != 4 or any(b not in b'0123456789abcdefABCDEF' for b in reply):
        raise ValueError('play mode must be four hex digits')
    value = int(reply, 16)
    if value > 4:
        raise ValueError('unsupported DISC play mode')
    return value
