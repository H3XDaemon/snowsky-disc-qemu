"""Persistent genre selections keep scope, expected membership and one write."""
import unittest
from unittest.mock import Mock, patch
from controller.catalog import CatalogChanged
from controller.link_commands import ReviewedCommands
from controller.models import DeviceConfig, QueueItem
from controller.session import DiscSession
from controller.fiio_library import genre_command
from controller.wire import frame

ROWS = [dict(pos=0, name='Same', author='A'), dict(pos=1, name='Other', author='B')]
EXPECTED = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in ROWS)


class GenrePlaybackTests(unittest.TestCase):
    def fixture(self):
        session = DiscSession(DeviceConfig('127.0.0.1'))
        client = Mock()
        client.handshake.return_value = '0306'
        client.settings.return_value = {'soc_version': 257}
        client.play_genre.side_effect = lambda genre, index, **kw: ReviewedCommands.play_genre(client, genre, index, **kw)
        session._perform = lambda action, fn: fn(client)
        http = Mock()
        http.catalog.side_effect = lambda category, offset=0, limit=200, **filters: dict(total=2, items=ROWS[offset:offset+limit])
        return session, client, http

    def test_reviewed_types_complete_preflight_and_exact_indexed_artist(self):
        for album, index, source in [(None, None, 8), (None, 1, 10), ('Shared', None, 8), ('Shared', 1, 8)]:
            with self.subTest(album=album, index=index):
                session, client, http = self.fixture()
                with patch('controller.genre_playback.HTTPClient', return_value=http), \
                        patch('controller.genre_playback.verify_playing', return_value={'state': 0}) as verify, \
                        patch('controller.genre_playback.snapshot', return_value={}) as queue:
                    session.play_genre('Rock', album=album, index=index, expected=EXPECTED)
                client.socket.sendall.assert_called_once_with(frame(*genre_command('Rock', index, album)))
                self.assertEqual(verify.call_args.args[1]['source'], source)
                if index is not None:
                    self.assertEqual(verify.call_args.args[1]['target_artist'], 'B')
                self.assertEqual(queue.call_args.kwargs['selected_position'], index)
                self.assertEqual(http.catalog.call_count, 3)
                self.assertTrue(all(c.kwargs['style'] == 'Rock' for c in http.catalog.call_args_list))

    def test_stale_empty_or_changed_final_preflight_never_writes(self):
        for mode in ('stale', 'empty', 'final'):
            session, client, http = self.fixture()
            if mode == 'empty':
                http.catalog.side_effect = None
                http.catalog.return_value = dict(total=0, items=[])
            if mode == 'final':
                http.catalog.side_effect = [dict(total=2, items=ROWS), dict(total=2, items=ROWS),
                                            dict(total=2, items=[dict(ROWS[0], name='Changed')])]
            with patch('controller.genre_playback.HTTPClient', return_value=http), self.assertRaises(CatalogChanged):
                session.play_genre('Rock', expected=(QueueItem(0, 'Stale', 'A'),) if mode == 'stale' else EXPECTED)
            client.socket.sendall.assert_not_called()

    def test_uncertain_result_is_not_replayed_and_unsupported_version_does_not_read_catalog(self):
        session, client, http = self.fixture()
        with patch('controller.genre_playback.HTTPClient', return_value=http), \
                patch('controller.genre_playback.verify_playing', return_value=None):
            self.assertEqual(session.play_genre('Rock')['status'], 'uncertain')
        client.socket.sendall.assert_called_once()
        client.settings.return_value = {'soc_version': 999}
        with patch('controller.genre_playback.HTTPClient') as factory, self.assertRaises(ValueError):
            session.play_genre('Rock')
        factory.assert_not_called()
