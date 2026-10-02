"""Persistent web-facing selections/edits on disposable generated CI media."""
from controller import DeviceConfig, DiscSession, QueueItem
from dataclasses import replace
from controller.catalog import CatalogReader
from controller.fiio_http import HTTPClient


def check():
    http = HTTPClient(port=12103)
    with DiscSession(DeviceConfig('127.0.0.1', http_port=12103)) as session:
        session.connect()
        assert session.wait_ready(35), session.snapshot()
        with session.operation():
            rows = CatalogReader(http).rows('album/song', album='CI Album')
        expected = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in rows)
        assert len(expected) == 2
        result = session.play_album('CI Album', index=1, expected=expected)
        assert result.status == 'playing' and result.queue.selected_position == 1, result
        queue = result.queue.items
        result = session.play_queue_index(0, expected=queue)
        assert result.status == 'confirmed' and result.queue.selected_position == 0, result
        stale = (QueueItem(0, 'Stale synthetic title', 'CI Artist'),) + queue[1:]
        rejected = session.play_queue_index(0, expected=stale)
        assert rejected.status == 'not_sent' and not rejected.mutation_attempted, rejected
        assert session.create_playlist('Web CI').status == 'confirmed'
        assert session.add_playlist_track('Web CI', 1, expected=expected, album='CI Album').status == 'confirmed'
        assert session.rename_playlist('Web CI', 'Web CI renamed').status == 'confirmed'
        with session.operation():
            playlists = CatalogReader(http).rows('custom')
            position = next(r['pos'] for r in playlists if r['name'] == 'Web CI renamed')
            members = CatalogReader(http).rows('custom/song', src_list_id=position)
        selected = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in members)
        result = session.play_playlist('Web CI renamed', expected=selected)
        assert result.status == 'playing' and result.playback.source == 5, result
        result = session.play_playlist('Web CI renamed', index=0, expected=selected)
        assert result.status == 'playing' and result.queue.selected_position == 0, result
        with session.operation():
            tracks = CatalogReader(http).rows('all/song')
        all_expected = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in tracks)
        index = next(i for i, row in enumerate(tracks) if row['name'] == selected[0].title)
        result = session.play_catalog_track(index, expected=all_expected)
        assert result.status == 'playing' and result.playback.source == 1, result
        original_favorite = session.snapshot().playback.favorite
        assert session.set_favorite(True).status in ('confirmed', 'already_satisfied')
        with session.operation():
            favorites = CatalogReader(http).rows('love/song')
        favorite_expected = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in favorites)
        favorite_index = next(i for i, row in enumerate(favorites) if row['name'] == selected[0].title)
        result = session.play_catalog_track(favorite_index, favorites=True, expected=favorite_expected)
        assert result.status == 'playing' and result.playback.source == 6, result
        playback = session.snapshot().playback
        assert playback.track.duration_ms and playback.track.duration_ms > 10000, playback
        rejected = session.seek(2000, expected=replace(playback.track, title='Stale'), source=playback.source)
        assert rejected.status == 'not_sent' and not rejected.mutation_attempted, rejected
        result = session.seek(2500, expected=playback.track, source=playback.source)
        assert result.status == 'confirmed', result
        assert session.pause().status in ('confirmed', 'already_satisfied')
        playback = session.snapshot().playback
        result = session.seek(5500, expected=playback.track, source=playback.source)
        assert result.status == 'uncertain' and result.outcome == 'seek_waiting_for_playback', result
        assert session.snapshot().playback.state == 'paused'
        # Explicit resume belongs to this acceptance scenario, not seek behavior.
        assert session.resume().status == 'confirmed'
        import time
        deadline = time.monotonic() + 5
        while session.snapshot().playback.position_ms is None and time.monotonic() < deadline:
            time.sleep(.1)
        assert 5000 <= session.snapshot().playback.position_ms <= 10000, session.snapshot()
        print('Web playback and playing/paused seek checks passed; restoring fixture state', flush=True)
        # Leave favorites before removing its current member: stock may stop that source.
        restored = session.play_album('CI Album', index=1, expected=expected)
        assert restored.status == 'playing', restored
        paused = session.pause()
        assert paused.status in ('confirmed', 'already_satisfied'), paused
        if original_favorite is False:
            assert session.set_favorite(False).status == 'confirmed'
        result = session.remove_playlist_track('Web CI renamed', 0, expected=selected)
        assert result.status == 'confirmed', result
        # This entire stack is disposable; remove only this generated empty list.
        with session.operation():
            http.delete_playlist(position)
            assert all(r['name'] != 'Web CI renamed' for r in CatalogReader(http).rows('custom'))
        paused = session.pause()
        assert paused.status in ('confirmed', 'already_satisfied'), paused
        from pathlib import Path
        import tempfile
        import wave
        target = '/tmp/sdcard/Web Import Album/Disc 1/Web import — тест.wav'
        with tempfile.NamedTemporaryFile(suffix='.wav') as source:
            with wave.open(source.name, 'wb') as audio:
                audio.setnchannels(2)
                audio.setsampwidth(2)
                audio.setframerate(44100)
                audio.writeframes(b'\0' * 44100 * 4 * 2)
            ticks = []
            result = session.upload_audio(source.name, target, on_progress=lambda sent, total: ticks.append((sent, total)))
            assert result.status == 'confirmed', result
            assert ticks and ticks[-1][0] == Path(source.name).stat().st_size, ticks[-1:]
            assert Path('/work/rootfs' + target).read_bytes() == Path(source.name).read_bytes()
            result = session.upload_audio(source.name, target)
            assert result.status == 'not_sent' and not result.mutation_attempted, result
            counts = []
            result = session.scan_library(timeout=45, on_progress=counts.append)
            assert result.status == 'confirmed' and counts, result
            with session.operation():
                rows = CatalogReader(http).rows('all/song')
                assert any(r['name'] == 'Web import — тест.wav' for r in rows), rows
                http.delete_file(target)
                http.delete_file('/tmp/sdcard/Web Import Album/Disc 1')
                http.delete_file('/tmp/sdcard/Web Import Album')
            result = session.scan_library(timeout=45)
            assert result.status == 'confirmed', result
            with session.operation():
                assert not any(r['name'] == 'Web import — тест.wav' for r in CatalogReader(http).rows('all/song'))
        print('WEB IMPORT ACCEPTANCE PASSED: nested album folder bytes, collision rejection, scan lifecycle and fresh index', flush=True)
        # Borrow the existing owner. Library positions are never dispatched directly.
        import threading
        from experiments.disc_web.backend.device import Device
        from experiments.disc_web.backend.catalogue import Catalogue
        from library.catalog import Track as LibraryTrack
        from library.store import Store
        with tempfile.TemporaryDirectory() as directory:
            device = Device(session.config, session=session, http=http)
            catalogue = device.catalogue = Catalogue(device, threading.Lock(), directory)
            try:
                assert session.play_album('CI Album', index=1, expected=expected).status == 'playing'
                assert session.pause().status in ('confirmed', 'already_satisfied')
                generation = device.state()['generation']
                catalogue.start(generation, 'web-library-acceptance')
                catalogue.worker.join(60)
                assert catalogue.state()['phase'] == 'done', catalogue.state()
                saved = device.browse('tracks')
                observed = session.snapshot().playback.track
                enriched = next(item for item in saved['items'] if item['album'] == 'CI Album'
                                and item['title'] == observed.title)
                assert enriched['duration'] == observed.duration_ms / 1000, enriched
                assert catalogue.state()['enrichment']['count'] >= 1
                selected = next(item for item in saved['items'] if item['album'] == 'CI Album')
                result = device.action({'action': 'track', 'selection': selected['selection'], 'generation': generation})
                assert result['status'] == 'playing', result
                assert session.pause().status in ('confirmed', 'already_satisfied')
                with Store(directory) as store:
                    head, snapshot = store.snapshot(catalogue.key())
                    changed = [LibraryTrack('Stale fixture title' if row['id'] == selected['id'] else row['title'],
                        row['artist'], row['album'], snapshot.selection(row['ordinal'])[2], {}) for row in snapshot.entries]
                    store.publish(catalogue.key(), changed, {}, expected_generation=head['generation'])
                try:
                    device.action({'action': 'track', 'selection': selected['selection'], 'generation': generation})
                except ValueError:
                    pass
                else:
                    raise AssertionError('old snapshot selection survived publication')
                stale = next(item for item in device.browse('tracks')['items'] if item['title'] == 'Stale fixture title')
                rejected = device.action({'action': 'track', 'selection': stale['selection'], 'generation': generation})
                assert rejected['status'] == 'not_sent' and not rejected['mutation_attempted'], rejected
                session.disconnect()
                assert device.browse('albums')['items'], 'saved library disappeared offline'
            finally:
                catalogue.close()
        print('WEB LIBRARY ACCEPTANCE PASSED: stable sync with observed duration, cached album selection, fresh-membership rejection and offline browsing', flush=True)
    print('WEB SESSION ACCEPTANCE PASSED: indexed album, queue, stale-source rejection playlist edits, catalog/favorite/playlist playback and seek', flush=True)


if __name__ == '__main__':
    check()
