"""Fresh complete-album selection through the session API."""
import unittest
from unittest.mock import Mock, patch
from controller.session import DiscSession
from controller.models import DeviceConfig, QueueItem
from controller.catalog import CatalogChanged


class AlbumSessionTests(unittest.TestCase):
    def test_indexed_album_retains_album_source_and_exact_target(self):
        session = DiscSession(DeviceConfig('127.0.0.1'))
        client = Mock()
        session._perform = lambda action, fn: fn(client)
        rows = [dict(pos=0, name='One', author='A'), dict(pos=1, name='Two', author='B')]
        expected = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in rows)
        with patch('controller.fiio_http.HTTPClient'), patch('controller.catalog.CatalogReader.rows', side_effect=[rows, rows]), \
                patch('controller.playback.verify_playing', return_value={'state': 0}) as verify, \
                patch('controller.queue.snapshot', return_value={}) as queue:
            session.play_album('Collection', index=1, expected=expected)
        self.assertEqual(client.play_album.call_args.args, ('Collection', 1))
        self.assertEqual(verify.call_args.args[1]['target_artist'], 'B')
        self.assertEqual(verify.call_args.args[1]['kind'], 'album')
        self.assertEqual(queue.call_args.kwargs['selected_position'], 1)

    def test_stale_displayed_album_is_rejected_before_selection(self):
        session = DiscSession(DeviceConfig('127.0.0.1'))
        client = Mock()
        session._perform = lambda action, fn: fn(client)
        rows = [dict(pos=0, name='New track', author='A')]
        with patch('controller.fiio_http.HTTPClient'), patch('controller.catalog.CatalogReader.rows', side_effect=[rows, rows]):
            with self.assertRaises(CatalogChanged):
                session.play_album('Collection', index=0, expected=(QueueItem(0, 'Old track', 'A'),))
        client.play_album.assert_not_called()

    def test_complete_source_is_rechecked_and_uncertain_selection_not_replayed(self):
        session = DiscSession(DeviceConfig('127.0.0.1'))
        client = Mock()
        session._perform = lambda action, fn: fn(client)
        rows = [dict(pos=0, name='One', author='A'), dict(pos=1, name='Two', author='B')]
        http = Mock()
        http.catalog.return_value = {'total': 2, 'items': rows[:1]}
        def select(album, *, http):
            from controller.fiio_library import verify_album
            verify_album(http, album)
        client.play_album.side_effect = select
        with patch('controller.session.time.sleep'), patch('controller.fiio_http.HTTPClient', return_value=http), \
                patch('controller.catalog.CatalogReader.rows', side_effect=[rows, rows]), \
                patch('controller.playback.verify_playing', return_value=None):
            result = session.play_album('Collection')
        self.assertEqual(result['status'], 'uncertain')
        self.assertTrue(result['mutation_attempted'])
        client.play_album.assert_called_once()
        http.catalog.assert_called_once_with('album/song', offset=0, limit=1, album='Collection')

    def test_changed_source_never_selects(self):
        session = DiscSession(DeviceConfig('127.0.0.1'))
        client = Mock()
        session._perform = lambda action, fn: fn(client)
        with patch('controller.session.time.sleep'), patch('controller.fiio_http.HTTPClient'), \
                patch('controller.catalog.CatalogReader.rows', side_effect=[[dict(pos=0, name='One', author='A')], []]):
            with self.assertRaises(CatalogChanged):
                session.play_album('Collection')
        client.play_album.assert_not_called()
