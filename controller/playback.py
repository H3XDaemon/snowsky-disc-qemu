"""Fresh artist selection and verified playback observations, without ranking."""
import time
from controller.models import WirePlaybackState, PlaybackSource
from controller.fiio_link import playback_snapshot
from controller.catalog import CatalogChanged, CatalogReader
from controller.events import merge_snapshot, validate_scan_events


class GuardedHTTP:
    """Recheck identity in the Controller's final HTTP preflight, not just bounds."""
    def __init__(self, http, category, filters, rows, index, client):
        self.http, self.category, self.filters = http, category, filters
        self.rows, self.index, self.client = rows, index, client

    def catalog(self, category, offset=0, limit=200, **filters):
        if (category, filters, offset, limit) != (self.category, self.filters, self.index, 1):
            raise ValueError('unexpected playback preflight scope')
        page = self.http.catalog(category, offset=offset, limit=limit, **filters)
        if page['total'] != len(self.rows) or page['items'] != [self.rows[self.index]]:
            raise CatalogChanged('selection changed immediately before playback; refresh the source')
        # settings() inside Controller retains scan events; check them just before
        # its sendall. No settings query drains away the evidence.
        self.client.scan_guard()
        return page


def album_matches(state, selected, *, config=None, http=None):
    """Resolve a shortened now-playing album only against fresh scoped names.

    No byte/character truncation limit is assumed. A prefix alone is insufficient:
    the artist's album list must be stable and contain exactly one compatible name.
    Callers still verify the native queue and selected position after playback.
    """
    wanted = selected.get('album')
    observed = state.get('song', {}).get('song_album_name')
    if wanted is None or observed == wanted:
        return True
    if (config is None or http is None or not isinstance(observed, str)
            or not observed or not wanted.startswith(observed)):
        return False
    reader = CatalogReader(http, page_size=config.page_size, max_tracks=config.max_tracks,
                           max_requests=config.max_requests)
    category = 'artist/album' if selected.get('artist') is not None else 'album'
    filters = {'artist': selected['artist']} if selected.get('artist') is not None else {}
    if selected.get('genre') is not None:
        category, filters = 'style/album', {'style': selected['genre']}
    albums = reader.rows(category, **filters)
    if albums != reader.rows(category, **filters):
        raise CatalogChanged('artist albums changed during playback confirmation')
    compatible = [row['name'] for row in albums if row['name'].startswith(observed)]
    if compatible != [wanted]:
        raise CatalogChanged('shortened playback album is ambiguous or absent from the fresh artist catalog')
    return True


def matches(state, selected, rows, *, album_verified=False):
    song = state.get('song')
    source = selected.get('source') if selected and selected.get('source') is not None else PlaybackSource.ALBUM if selected['kind'] == 'album' and selected.get('artist') is None else PlaybackSource.ARTIST_SCOPE
    if state.get('state') != WirePlaybackState.PLAYING or state.get('playerflag') != source or not isinstance(song, dict):
        return False
    artist, title = song.get('song_artist_name'), song.get('song_name')
    if selected.get('artist') is not None and artist != selected['artist']:
        return False
    if not album_verified and not album_matches(state, selected):
        return False
    if selected['kind'] == 'track':
        return title == selected['title']
    if selected.get('selected_index') is not None:
        return title == selected['title'] and artist == selected['target_artist']
    return any(r['author'] == artist and r['name'] == title for r in rows)


def verify_playing(client, selected, rows, timeout, *, config=None, http=None, diagnostics=None):
    deadline = time.monotonic() + timeout
    state = {}
    while time.monotonic() < deadline:
        # A fresh read is evidence of the requested playback state, not a wire
        # acknowledgement or proof of audible output. Never repeat selection.
        client.timeout = max(.05, min(2, deadline - time.monotonic()))
        try:
            update = client.now_playing()
        except TimeoutError:
            update = {}
        events = client.take_events()
        validate_scan_events(events)
        for tag, payload in events:
            if tag == 'a202':
                state = merge_snapshot(state, playback_snapshot(payload))
        state = merge_snapshot(state, update)
        if diagnostics is not None:
            song = state.get('song') or {}
            diagnostics['last_observed'] = {
                'state': state.get('state'), 'playerflag': state.get('playerflag'),
                'title': song.get('song_name'), 'artist': song.get('song_artist_name'),
                'album': song.get('song_album_name'), 'pos_id': song.get('pos_id')}
        if matches(state, selected, rows):
            return state
        # Only the album may differ; title, artist, source and playing state
        # remain exact. Queue confirmation is mandatory in both public callers.
        if (matches(state, selected, rows, album_verified=True)
                and album_matches(state, selected, config=config, http=http)):
            return state
        time.sleep(.15)
    return None
