"""Genre facade and saved facets on disposable generated V2.57 library media."""
import tempfile
from controller import DeviceConfig, DiscSession, QueueItem
from controller.catalog import CatalogReader
from controller.fiio_http import HTTPClient
from library.catalog import CatalogReader as LibraryReader
from library.store import Store
from library.sync import synchronize


def check():
    http = HTTPClient(port=12103)
    with DiscSession(DeviceConfig('127.0.0.1', http_port=12103)) as session:
        session.connect()
        assert session.wait_ready(35), session.snapshot()
        with tempfile.TemporaryDirectory() as directory, Store(directory) as store:
            with session.operation() as client:
                synchronize(store, 'fixture', LibraryReader(http), client, http, include_genres=True)
            _, saved = store.snapshot('fixture')
            assert [r['name'] for r in saved.genre_rows('Genre Ё', 'Shared Album')] == ['Library Alpha', 'Library Beta']
            assert [r['name'] for r in saved.genre_rows('Genre Other', 'Shared Album')] == ['Library Gamma']
        for album, index, source in [(None, None, 8), (None, 2, 10), ('Shared Album', None, 8), ('Shared Album', 1, 8)]:
            category = 'style/song' if album is None else 'style/album/song'
            with session.operation():
                rows = CatalogReader(http).rows(category, style='Genre Ё', **({'album': album} if album else {}))
            expected = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in rows)
            result = session.play_genre('Genre Ё', album=album, index=index, expected=expected)
            assert result.status == 'playing' and result.playback.source == source, result
            assert len(result.queue.items) == len(rows), result
            if index is not None:
                assert result.queue.selected_position == index, result
            print(f'GENRE SESSION: album={album!r} index={index} source={source} queue={len(rows)} PASS', flush=True)
        rejected = session.play_genre('Genre Ё', album='Shared Album', index=0,
                                     expected=(QueueItem(0, 'Stale synthetic row', 'Artist Ё'),))
        assert rejected.status == 'not_sent' and not rejected.mutation_attempted, rejected
        assert session.control('pause').status in ('confirmed', 'already_satisfied')
    print('GENRE SESSION CHECK PASS; persistent facade and offline facets', flush=True)
