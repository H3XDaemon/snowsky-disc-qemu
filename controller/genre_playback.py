"""Genre selections through the persistent owner; preserve the exact native scope."""
from controller.catalog import CatalogReader, CatalogChanged, verify_expected
from controller.compatibility import require_client
from controller.fiio_http import HTTPClient
from controller.fiio_library import genre_command
from controller.models import PlaybackSource
from controller.playback import GuardedHTTP, verify_playing
from controller.queue import snapshot


def select(config, client, genre, *, album=None, index=None, expected=None):
    genre_command(genre, index, album)
    require_client(client, 'genre_playback')
    client.wait_for_mutation()
    http = HTTPClient(config.host, config.http_port, config.timeout)
    category = 'style/song' if album is None else 'style/album/song'
    filters = {'style': genre, **({'album': album} if album is not None else {})}
    reader = CatalogReader(http, page_size=config.page_size, max_tracks=config.max_tracks,
                           max_requests=config.max_requests)
    rows = reader.rows(category, **filters)
    if not rows or rows != reader.rows(category, **filters):
        raise CatalogChanged('genre source is empty or changing')
    verify_expected(rows, expected)
    position = 0 if index is None else index
    if position >= len(rows):
        raise ValueError('position outside current genre')
    selected = dict(kind='genre', genre=genre, album=album, artist=None,
                    source=PlaybackSource.GENRE_TRACK if index is not None and album is None
                    else PlaybackSource.GENRE_SCOPE)
    if index is not None:
        selected.update(selected_index=index, title=rows[index]['name'], target_artist=rows[index]['author'])
    client.scan_guard()
    guard = GuardedHTTP(http, category, filters, rows, position, client)
    client.play_genre(genre, index, album=album, http=guard)
    state = verify_playing(client, selected, rows, config.timeout, config=config, http=http)
    result = dict(status='playing' if state else 'uncertain', mutation_attempted=True, state=state)
    if state:
        result['queue'] = snapshot(config, client, http, expected=rows, selected=selected,
                                   selected_position=index)
    else:
        result['reason'] = 'genre playback not confirmed; selection was not retried'
    return result
