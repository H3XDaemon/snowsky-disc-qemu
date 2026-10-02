"""Conservative enrichment from the stock current-track and cover endpoints."""
from dataclasses import dataclass
from http.client import HTTPException

from controller.catalog import CatalogReader, CatalogChanged
from controller.compatibility import Capability, require_client
from controller.models import Track
from library.enrichment import image_type


@dataclass(frozen=True)
class Observation:
    track: Track
    ordinal: int | None
    cover: bytes

    @property
    def provenance(self):
        return {'source': 'disc-current-track', 'path': self.track.path,
                'queue_position': self.track.queue_position,
                'association': 'unique-exact-tags-and-two-equal-album-reads',
                'consistency': 'stable-track-around-cover-not-atomic'}


def candidate(snapshot, http, track):
    if snapshot is None or not track.path or not track.album:
        return None
    album = snapshot.tracks(album=track.album)
    matches = [row for row in album if (row['title'], row['artist']) == (track.title, track.artist)]
    # Duplicate recordings and shortened names stay unassociated, including CUE.
    if len(matches) != 1:
        return None
    expected = [(i, row['title'], row['artist']) for i, row in enumerate(album)]
    reader = CatalogReader(http, page_size=100, max_tracks=1000, max_requests=20)
    for _ in range(2):
        rows = reader.rows('album/song', album=track.album)
        if [(row['pos'], row['name'], row['author']) for row in rows] != expected:
            return None
    return matches[0]['ordinal']


def observe_current(client, http, snapshot, *, expected_track=None):
    """Read through a caller-owned session lease; never select or advance a track.

    The endpoint has no atomic artwork identity. Retain this provenance and reject
    any observed track, path, duration, position or source transition around reads.
    """
    require_client(client, Capability.CURRENT_TRACK)
    client.scan_guard()
    before = client.now_playing()
    track = Track.from_wire(before)
    if track is None or before.get('state') not in (0, 1):
        raise ValueError('Current track is unavailable')
    if expected_track is not None and track.identity != expected_track.identity:
        raise ValueError('Current track changed before artwork read')
    # Duration can still be observed if the optional cover endpoint is unavailable.
    try:
        cover = http.cover()
    except (OSError, HTTPException):
        cover = b''
    if not image_type(cover):
        cover = b''
    ordinal = None
    try:
        ordinal = candidate(snapshot, http, track)
    except CatalogChanged:
        raise
    except (OSError, ValueError, RuntimeError, HTTPException):
        pass
    after = client.now_playing()
    client.scan_guard()
    if (Track.from_wire(after) != track or after.get('state') not in (0, 1)
            or before.get('playerflag') != after.get('playerflag')):
        raise ValueError('Current track changed during artwork read')
    return Observation(track, ordinal, cover)
