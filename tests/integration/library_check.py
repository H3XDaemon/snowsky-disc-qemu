"""Artist/genre/folder acceptance with generated media on disposable V2.57 only."""
from tests.integration.profile import (version as firmware_version, require_acceptance)
import asyncio
import hashlib
import os

from tests.integration.queue_check import connection, http_client
from tests.integration.remote_control import call, snapshot, ROOT
from tests.fixtures.library_fixture import generate, TRACKS, FOLDER
from tests.integration.scan_cancel_check import scan
from research.diagnostics.player_memory import PlayerMemory
from tests.integration.track_end_check import sources
from controller.fiio_http import range_body
from controller.fiio_link import frame


async def exercise(transport):
    async with connection(transport) as client:
        http = http_client(transport)
        genres = await call(client.library, 'genres')
        assert {x['name']: x['count'] for x in genres['items']} == {
            'Genre Ё': 3, 'Genre Other': 2, 'Unknown genre': 3}
        print(f'{transport}: genres={genres}', flush=True)
        for category, filters in (
            ('style', {}),
            ('style/song', {'style': 'Genre Ё'}),
            ('style/album', {'style': 'Genre Ё'}),
            ('style/album/song', {'style': 'Genre Ё', 'album': 'Shared Album'}),
            ('album/song', {'album': 'Shared Album'}),
            ('artist/song', {'artist': 'Artist Ё'}),
            ('artist/album', {'artist': 'Artist Ё'}),
            ('artist/album/song', {'artist': 'Artist Ё', 'album': 'Shared Album'}),
        ):
            page = http.catalog(category, **filters)
            print(f'{transport}: {category} {filters}: {page}', flush=True)
            expected = {
                'style': {'Genre Ё', 'Genre Other', 'Unknown genre'},
                'style/song': {'Library Alpha', 'Library Beta', 'Library Delta'},
                'style/album': {'Shared Album', 'Second Album'},
                'style/album/song': {'Library Alpha', 'Library Beta'},
                'album/song': {'Library Alpha', 'Library Beta', 'Library Gamma'},
                'artist/song': {'Library Alpha', 'Library Beta', 'Library Delta'},
                'artist/album': {'Shared Album', 'Second Album'},
                'artist/album/song': {'Library Alpha', 'Library Beta'},
            }[category]
            assert page['total'] == len(expected)
            assert {x['name'] for x in page['items']} == expected
            # Pagination positions are global within the filtered result.
            for offset, row in enumerate(page['items']):
                part = http.catalog(category, offset=offset, limit=1, **filters)
                assert part['total'] == page['total'] and part['items'] == [row]
                assert row['pos'] == offset
        for suffix in ('', '/A', '/A/Nested', '/B', '/Empty'):
            for local in (False, True):
                page = http.directory('/tmp/sdcard/' + FOLDER + suffix, local=local)
                print(f'{transport}: directory {suffix!r} local={local}: {page}', flush=True)
                expected = {'': {'A', 'B', 'Empty'}, '/A': {'Nested', '01.flac', '02.flac'},
                            '/A/Nested': {'04.flac'}, '/B': {'03.flac', '05.flac'},
                            '/Empty': set()}[suffix]
                assert {x['name'] for x in page['items']} == expected
                assert page['total'] == (len(expected) if expected else None)
        mode = await call(client.play_mode)
        await call(client.set_play_mode, 4)

        async def selected(action, expected, index, flag):
            await asyncio.sleep(2.1)
            await call(action)
            state = await snapshot(client, lambda s: s['state'] == 0 and s['playerflag'] == flag
                                   and s['song']['song_name'] == expected[index])
            queue = http.catalog('curlist/song')
            assert [x['name'] for x in queue['items']] == expected, queue
            await asyncio.sleep(2.1)
            await call(client.play_pause)
            await snapshot(client, lambda s: s['state'] == 1)
            print(f'{transport}: selection flag={flag}, index={index}, '
                  f'path={state["song"]["song_file_path"]}, queue={expected}', flush=True)

        for album in (None, 'Shared Album'):
            filters = {'style': 'Genre Ё'}
            if album is not None:
                filters['album'] = album
            expected = [x['name'] for x in http.catalog(
                'style/song' if album is None else 'style/album/song', **filters)['items']]
            for index in (None, len(expected) - 1):
                await selected(lambda: client.play_genre('Genre Ё', index, album=album, http=http),
                               expected, index or 0, 10 if album is None and index is not None else 8)

        # Physical FiiO Control uses type 8 with an empty album for a genre.
        # Compare its queue/order/start against the independently tested type 10.
        expected = [x['name'] for x in http.catalog('style/song', style='Genre Ё')['items']]
        for play_mode in (0, 4):
            await call(client.set_play_mode, play_mode)
            await selected(lambda: client.send('0101', '000AGenre Ё') if transport == 'ws'
                           else client.socket.sendall(frame('0101', '000AGenre Ё')), expected, 0, 10)
            # Select the last track first, so replay-all must reset its position.
            await selected(lambda: client.play_genre('Genre Ё', len(expected) - 1, http=http),
                           expected, len(expected) - 1, 10)
            await selected(lambda: client.play_genre('Genre Ё', http=http), expected, 0, 8)

        # Type 7 preserves the artist restriction when album names overlap.
        # Test an artist spanning two albums; the physical Play-all trace had one.
        for play_mode in (0, 4):
            await call(client.set_play_mode, play_mode)
            expected = [x['name'] for x in http.catalog('artist/song', artist='Artist Ё')['items']]
            await selected(lambda: client.play_all(2, 'Artist Ё'), expected, 0, 2)
            await selected(lambda: client.play_index(len(expected) - 1, 2, 'Artist Ё'),
                           expected, len(expected) - 1, 2)
            await selected(lambda: client.play_artist('Artist Ё', http=http), expected, 0, 7)
            scoped = [x['name'] for x in http.catalog(
                'artist/album/song', artist='Artist Ё', album='Shared Album')['items']]
            await selected(lambda: client.play_artist('Artist Ё', len(scoped) - 1,
                           album='Shared Album', http=http), scoped, len(scoped) - 1, 7)
            await selected(lambda: client.play_artist('Artist Ё', album='Shared Album', http=http),
                           scoped, 0, 7)

        for suffix in ('/A', '/A/Nested', '/B'):
            path = '/tmp/sdcard/' + FOLDER + suffix
            rows = http.directory(path, local=True)['items']
            audio = [x for x in rows if not x['is_dir']]
            titles = {relative.split('/')[-1]: title for relative, title, *_ in TRACKS}
            expected = [titles[x['name']] for x in audio]
            await selected(lambda: client.play_folder(path, http=http), expected, 0, 4)
            row = audio[-1]
            await selected(lambda: client.play_folder(path, row['pos'], http=http,
                                                       expected_name=row['name']),
                           expected, len(expected) - 1, 4)

        # Invalid/stale sources are rejected without sending a playback mutation.
        for action in (
            lambda: client.play_genre('Missing genre', http=http),
            lambda: client.play_genre('Genre Ё', 3, http=http),
            lambda: client.play_genre('Genre Ё', 2, album='Shared Album', http=http),
            lambda: client.play_artist('Missing artist', http=http),
            lambda: client.play_artist('Artist Ё', album='Third Album', http=http),
            lambda: client.play_artist('Artist Ё', 2, album='Shared Album', http=http),
            lambda: client.play_folder('/tmp/sdcard/' + FOLDER + '/Empty', http=http),
            lambda: client.play_folder('/tmp/sdcard/' + FOLDER, http=http),
            lambda: client.play_folder('/tmp/sdcard/' + FOLDER + '/A', 0, http=http,
                                      expected_name='Nested'),
            lambda: client.play_folder('/tmp/sdcard/' + FOLDER + '/B', 0, http=http,
                                      expected_name='stale.flac'),
        ):
            before = await snapshot(client)
            try:
                await call(action)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid source was not rejected')
            after = await snapshot(client)
            assert after['song'] == before['song'] and after['state'] == before['state']

        # Leave fixture context before index mutations and cleanup.
        await asyncio.sleep(2.1)
        await call(client.play_all, 3, 'CI Album')
        await snapshot(client, lambda s: s['state'] == 0 and s['playerflag'] == 3)
        await asyncio.sleep(2.1)
        await call(client.play_pause)
        await snapshot(client, lambda s: s['state'] == 1)
        await call(client.set_play_mode, mode)
        assert http.catalog('custom')['total'] == 0
        cases = (
            # Physical iOS album-track selection: first and third rows, one POST.
            ('album/song', {'album': 'Shared Album'}, [[0, 0], [2, 2]],
             {'Library Alpha', 'Library Gamma'}),
            ('style/album', {'style': 'Genre Ё'}, [[1, 1]], {'Library Alpha', 'Library Beta'}),
            ('style/album', {'style': 'Genre Ё'}, [[0, 1]],
             {'Library Alpha', 'Library Beta', 'Library Delta'}),
            ('style/album/song', {'style': 'Genre Ё', 'album': 'Shared Album'}, [[1, 1]],
             {'Library Beta'}),
            ('style/song', {'style': 'Genre Ё'}, [[0, 0], [2, 2]],
             {'Library Alpha', 'Library Delta'}),
            ('style', {}, [[0, 1]], {t[1] for t in TRACKS}),
        )
        for category, filters, ranges, expected in cases:
            http.create_playlist('Library bulk ' + transport)
            http.add_selection_to_playlist(0, ranges, expected_name='Library bulk ' + transport,
                                            category=category, **filters)
            actual = http.catalog('custom/song', src_list_id=0)
            print(f'{transport}: add {category} {filters} {ranges} -> {actual}', flush=True)
            assert {x['name'] for x in actual['items']} == expected
            assert actual['total'] == len(expected)
            for bad_ranges, bad_name in (([[100, 100]], 'Library bulk ' + transport),
                                          (ranges, 'stale destination')):
                try:
                    http.add_selection_to_playlist(0, bad_ranges, expected_name=bad_name,
                                                    category=category, **filters)
                except ValueError:
                    pass
                else:
                    raise AssertionError('invalid bulk selection was not rejected')
                assert http.catalog('custom/song', src_list_id=0)['items'] == actual['items']
            http.delete_playlist(0)
            assert http.catalog('custom')['total'] == 0

        before = http.catalog()
        # Group rows are accepted for ADD but not DELETE by the stock allowlist.
        # This negative probe and the index-only delete below touch only this
        # disposable generated fixture; never use them on an owner library.
        headers = http._category('style/album', {'style': 'Genre Ё'})
        headers.update(delete_source='0', **{'Content-Type': 'application/json'})
        reply = http.request('DELETE', '/song_category_tree/', range_body([[0, 1]]), headers)
        assert reply.status == 200 and http.catalog() == before
        headers = http._category('style/album/song', {'style': 'Genre Ё', 'album': 'Shared Album'})
        headers.update(delete_source='0', **{'Content-Type': 'application/json'})
        http.request('DELETE', '/song_category_tree/', range_body([[0, 1]]), headers)
        remaining = http.catalog()
        print(f'{transport}: index-only scoped delete -> {remaining}', flush=True)
        assert remaining['total'] == before['total'] - 2
        assert {x['name'] for x in remaining['items']} == (
            {x['name'] for x in before['items']} - {'Library Alpha', 'Library Beta'})
        assert http.catalog('style/album/song', style='Genre Ё', album='Shared Album')['total'] == 0
        for relative, *_ in TRACKS:
            assert (ROOT / 'tmp/sdcard' / FOLDER / relative).is_file()
        with PlayerMemory(ROOT, firmware_version()) as memory:
            await scan(client, memory)
        assert http.catalog()['items'] == before['items']


async def main():
    require_acceptance('library')
    with PlayerMemory(ROOT, firmware_version()):
        pass
    sources()
    folder = generate(ROOT / 'tmp/sdcard')
    hashes = {folder / relative: hashlib.sha256((folder / relative).read_bytes()).hexdigest()
              for relative, *_ in TRACKS}
    async with connection('tcp') as client:
        with PlayerMemory(ROOT, firmware_version()) as memory:
            await scan(client, memory)
    for transport in ('tcp', 'ws'):
        await exercise(transport)
    from tests.integration.genre_session_check import check as check_genre_session
    await asyncio.to_thread(check_genre_session)
    for path, digest in hashes.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        path.unlink()
    for relative in ('A/Nested', 'A', 'B', 'Empty'):
        (folder / relative).rmdir()
    folder.rmdir()
    async with connection('tcp') as client:
        with PlayerMemory(ROOT, firmware_version()) as memory:
            await scan(client, memory)
        assert (await call(client.tracks))['total'] == 3
    sources()
    print(f'LIBRARY CHECK PASS V{firmware_version()} TCP/WS; sources restored', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
