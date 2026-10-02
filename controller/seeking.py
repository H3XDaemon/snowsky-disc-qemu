"""Seek once on the displayed track; confirm only fresh position observations."""
import time
from controller.compatibility import require_client
from controller.controls import observe, UnknownPlayback
from controller.models import Track, PlaybackSource, WirePlaybackState
from controller.wire import hex_value


def seek(client, position_ms, *, expected, source, timeout):
    hex_value(position_ms, 0x7fffffff, 8)
    if not isinstance(expected, Track) or not isinstance(source, PlaybackSource):
        raise ValueError('the displayed track and source are required')
    require_client(client, 'seek')
    client.wait_for_mutation()
    before, _ = observe(client)
    track = Track.from_wire(before)
    if (track is None or track.identity != expected.identity) or before.get('playerflag') != source:
        raise ValueError('displayed track changed; no seek sent')
    if track.duration_ms is None or not 0 <= position_ms < track.duration_ms:
        raise ValueError('seek requires a known duration and a position before the end')
    # Consume preflight events before send, and retain only subsequent observations.
    client.scan_guard()
    with client.condition:
        if not same_track(client.state, expected) or client.state.get('playerflag') != source:
            raise ValueError('track changed immediately before seek')
        client.seek(position_ms)
        client.position = None
    target = position_ms // 1000 * 1000
    confirmation = {'requested_ms': position_ms, 'rounded_ms': target}
    if before['state'] == WirePlaybackState.PAUSED:
        return {'status': 'uncertain', 'mutation_attempted': True, 'state': before,
                'outcome': 'seek_waiting_for_playback', 'confirmation': confirmation,
                'reason': 'paused seek has no position acknowledgement; playback was not resumed'}
    sent = time.monotonic()
    deadline = sent + timeout
    while time.monotonic() < deadline:
        client.timeout = max(.05, min(2, deadline - time.monotonic()))
        try:
            state, position = observe(client)
        except (TimeoutError, UnknownPlayback):
            continue
        if not same_track(state, expected) or state.get('playerflag') != source:
            break
        elapsed = (time.monotonic() - sent) * 1000
        if position is not None and target <= position <= target + elapsed + 1000:
            return {'status': 'confirmed', 'mutation_attempted': True, 'state': state,
                    'outcome': 'seek_observed', 'confirmation': dict(confirmation, observed_ms=position)}
        time.sleep(.1)
    return {'status': 'uncertain', 'mutation_attempted': True, 'confirmation': confirmation,
            'reason': 'seek position not observed on the same track; command was not retried'}


def same_track(state, expected):
    track = Track.from_wire(state)
    return track is not None and track.identity == expected.identity
