"""Fresh all-tracks, favorites and custom-playlist selection for a session."""
from controller.catalog import CatalogChanged, CatalogReader, verify_expected
from controller.compatibility import require_client
from controller.fiio_http import HTTPClient
from controller.fiio_playlist import playlist_command
from controller.models import PlaybackSource
from controller.playback import GuardedHTTP, verify_playing
from controller.queue import snapshot
from controller.wire import hex_value


def select(config, client, kind, *, index, expected=None, name=None):
    if kind not in ('tracks', 'favorites', 'playlist'):
        raise ValueError('unsupported playback scope')
    if kind == 'playlist':
        playlist_command(0, index, name)
    else:
        hex_value(index)
    require_client(client, 'playlist_playback' if kind == 'playlist' else 'catalog_playback')
    client.wait_for_mutation()
    http = HTTPClient(config.host, config.http_port, config.timeout)
    reader = CatalogReader(http, page_size=config.page_size, max_tracks=config.max_tracks,
                           max_requests=config.max_requests)
    filters = {}
    category = {'tracks': 'all/song', 'favorites': 'love/song', 'playlist': 'custom/song'}[kind]
    lists = None
    if kind == 'playlist':
        lists = reader.rows('custom')
        if lists != reader.rows('custom'):
            raise CatalogChanged('playlist positions are changing')
        matches = [row for row in lists if row['name'] == name]
        if len(matches) != 1:
            raise CatalogChanged('playlist name is missing or ambiguous')
        position = matches[0]['pos']
        filters = {'src_list_id': position}
    rows = reader.rows(category, **filters)
    if not rows or rows != reader.rows(category, **filters):
        raise CatalogChanged('playback source is empty or changing')
    verify_expected(rows, expected)
    target = 0 if index is None else index
    if target >= len(rows):
        raise ValueError('position outside current source')
    source = {'tracks': PlaybackSource.LIBRARY, 'favorites': PlaybackSource.FAVORITES,
              'playlist': PlaybackSource.PLAYLIST}[kind]
    selected = dict(kind='source', artist=None, source=source, selected_index=target,
                    title=rows[target]['name'], target_artist=rows[target]['author'])
    guard = GuardedHTTP(http, category, filters, rows, target, client)
    if kind == 'playlist':
        class PlaylistGuard:
            def catalog(self, requested, offset=0, limit=200, **kwargs):
                if requested == 'custom':
                    if (offset, limit, kwargs) != (position, 1, {}):
                        raise ValueError('unexpected playlist preflight')
                    if reader.rows('custom') != lists or reader.rows(category, **filters) != rows:
                        raise CatalogChanged('playlist changed immediately before playback')
                    client.scan_guard()
                    return {'total': len(lists), 'items': [lists[position]]}
                return guard.catalog(requested, offset, limit, **kwargs)
        client.play_playlist(position, index, http=PlaylistGuard(), expected_name=name)
    else:
        client.play_catalog_track(index, favorites=kind == 'favorites', http=guard)
    state = verify_playing(client, selected, rows, config.timeout, config=config, http=http)
    if not state:
        return {'status': 'uncertain', 'mutation_attempted': True,
                'reason': 'requested source playback not confirmed; no retry'}
    queue = snapshot(config, client, http, expected=rows, selected=selected, selected_position=target)
    return {'status': 'playing', 'mutation_attempted': True, 'state': state, 'queue': queue}
