from contextlib import nullcontext
import unittest
from unittest.mock import MagicMock, Mock

from controller import DeviceConfig, QueueItem
from controller.catalog import CatalogChanged
from controller.tests.session_fixture import Server as Peer
from experiments.disc_web.backend.device import BusyError, Device


class DeviceTests(unittest.TestCase):
    def fixture(self):
        session = MagicMock()
        session.snapshot.return_value.to_dict.return_value = {'connection': 'ready', 'generation': 5}
        session.snapshot.return_value.generation = 5
        client = Mock()
        session.operation.side_effect = lambda: nullcontext(client)
        http = Mock()
        device = Device(DeviceConfig('127.0.0.1'), session=session, http=http)
        return device, session, http, client

    def test_no_automatic_connection_and_stale_request_rejected(self):
        device, session, _, _ = self.fixture()
        with device:
            session.connect.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'Connection changed'):
                device.action({'action': 'pause', 'generation': 4})
            session.control.assert_not_called()

    def test_busy_rejection_does_not_queue_mutation(self):
        device, session, _, _ = self.fixture()
        with device.lock:
            with self.assertRaises(BusyError):
                device.action({'action': 'pause', 'generation': 5})
        session.control.assert_not_called()

    def test_artist_scoped_album_does_not_expand_to_generic_album(self):
        device, session, http, client = self.fixture()
        http.catalog.return_value = {'total': 1, 'items': [dict(pos=0, name='Track', author='Artist')]}
        result = device.browse('album', 'Collection', 'Artist')
        self.assertEqual(result['items'][0]['title'], 'Track')
        http.catalog.assert_called_once_with('artist/album/song', offset=0, limit=200, artist='Artist', album='Collection')
        client.scan_guard.assert_called()
        session.play_album.assert_not_called()

    def test_displayed_selection_preserves_artist_scope_and_original_position(self):
        device, session, http, _ = self.fixture()
        http.catalog.return_value = {'total': 2, 'items': [
            dict(pos=0, name='First', author='Artist'), dict(pos=1, name='Second', author='Artist')]}
        item = device.browse('album', 'Collection', 'Artist')['items'][1]
        device.action({'action': 'track', 'selection': item['selection'], 'generation': 5})
        session.play_artist.assert_called_once_with('Artist', album='Collection', index=1,
            expected=(QueueItem(0, 'First', 'Artist'), QueueItem(1, 'Second', 'Artist')))
        session.play_album.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'scope'):
            device.action({'action': 'playlist_add', 'selection': item['selection'], 'generation': 5, 'name': 'List'})
        session.add_playlist_track.assert_not_called()

    def test_selection_cannot_survive_reconnect_or_cache_eviction(self):
        device, session, http, _ = self.fixture()
        http.catalog.return_value = {'total': 1, 'items': [dict(pos=0, name='Track', author='Artist')]}
        item = device.browse('album', 'Collection')['items'][0]
        session.snapshot.return_value.generation = 6
        with self.assertRaisesRegex(ValueError, 'expired'):
            device.action({'action': 'track', 'selection': item['selection'], 'generation': 5})
        session.snapshot.return_value.generation = 5
        for _ in range(32):
            device.browse('album', 'Collection')
        with self.assertRaisesRegex(ValueError, 'expired'):
            device.action({'action': 'track', 'selection': item['selection'], 'generation': 5})
        self.assertEqual(len(device.sources), 32)
        session.play_album.assert_not_called()

    def test_catalog_favorites_and_playlist_selections_use_displayed_scope(self):
        for kind in ('tracks', 'favorites', 'playlist'):
            device, session, http, _ = self.fixture()
            def catalog(category, **kwargs):
                return {'total': 1, 'items': [dict(pos=0, name='Mix' if category == 'custom' else 'Track', author='Artist')]}
            http.catalog.side_effect = catalog
            item = device.browse(kind, 'Mix')['items'][0]
            self.assertTrue(item['playable'])
            device.action({'action': 'track', 'selection': item['selection'], 'generation': 5})
            expected = (QueueItem(0, 'Track', 'Artist'),)
            if kind == 'playlist':
                session.play_playlist.assert_called_once_with('Mix', index=0, expected=expected)
            else:
                session.play_catalog_track.assert_called_once_with(0, favorites=kind == 'favorites', expected=expected)

    def test_missing_page_is_not_reported_as_empty_catalog(self):
        device, _, http, _ = self.fixture()
        http.catalog.return_value = {'total': 1, 'items': []}
        with self.assertRaises(CatalogChanged):
            device.browse('albums')

    def test_album_info_preserves_scope_counts_rows_and_does_not_create_selections(self):
        device, session, http, client = self.fixture()
        http.catalog.return_value = {'total': 3, 'items': [
            dict(pos=0, name='One', author='Artist'),
            dict(pos=1, name='Two', author='Guest'),
            dict(pos=2, name='Three', author='Artist')]}
        result = device.browse('album_info', 'Collection', 'Artist')
        self.assertEqual(result, {'generation': 5, 'count': 3, 'artists': ['Artist', 'Guest']})
        http.catalog.assert_called_once_with('artist/album/song', offset=0, limit=200,
                                            artist='Artist', album='Collection')
        self.assertEqual(device.sources, {})
        self.assertEqual(client.scan_guard.call_count, 2)
        session.play_album.assert_not_called()

    def test_playlist_names_rechecked_after_read(self):
        device, _, http, _ = self.fixture()
        http.catalog.side_effect = [
            {'total': 1, 'items': [dict(pos=0, name='Morning')]},
            {'total': 1, 'items': [dict(pos=0, name='Track', author='Artist')]},
            {'total': 1, 'items': [dict(pos=0, name='Changed')]},
        ]
        with self.assertRaisesRegex(ValueError, 'changed while reading'):
            device.browse('playlist', 'Morning')

    def test_live_tcp_session_pause_volume_and_disconnect_without_replay(self):
        peer = Peer()
        try:
            config = DeviceConfig('127.0.0.1', peer.server_address[1], timeout=.5)
            with Device(config) as device:
                self.assertEqual(peer.accepts, 0)
                device.action({'action': 'connect'})
                self.assertTrue(device.session.wait_ready(3))
                generation = device.state()['generation']
                result = device.action({'action': 'pause', 'generation': generation})
                self.assertEqual(result['status'], 'confirmed')
                writes = peer.writes
                result = device.action({'action': 'pause', 'generation': generation})
                self.assertEqual(result['status'], 'already_satisfied')
                self.assertEqual(peer.writes, writes)
                result = device.action({'action': 'volume', 'value': 37, 'generation': generation})
                self.assertEqual(result['volume'], 37)
                self.assertEqual(peer.volume, 37)
                self.assertEqual(peer.accepts, 1)
                device.action({'action': 'disconnect'})
                writes = peer.writes
                with self.assertRaises(ValueError):
                    device.action({'action': 'resume', 'generation': generation})
                self.assertEqual(peer.writes, writes)
        finally:
            peer.close()
