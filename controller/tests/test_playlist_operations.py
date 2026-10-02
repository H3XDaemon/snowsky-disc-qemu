from contextlib import nullcontext
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from controller import DeviceConfig, DiscSession, QueueItem


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.names = ['Morning']
        self.songs = []
        self.source = [dict(pos=0, name='One', author='Artist')]
        self.http = Mock()
        def catalog(category, offset=0, limit=200, **filters):
            if category == 'custom':
                rows = [dict(pos=i, name=name) for i, name in enumerate(self.names)]
            elif category == 'custom/song':
                rows = self.songs
            else:
                rows = self.source
            return {'total': len(rows), 'items': deepcopy(rows[offset:offset+limit])}
        self.http.catalog.side_effect = catalog
        self.http.create_playlist.side_effect = self.names.append
        self.http.rename_playlist.side_effect = lambda position, name: self.names.__setitem__(position, name)
        self.http.add_selection_to_playlist.side_effect = lambda *a, **k: self.songs.extend(deepcopy(self.source))
        self.http.remove_from_playlist.side_effect = lambda *a, **k: self.songs.clear()
        self.client = Mock(mutation_attempted=False, attempted_phases=set())
        self.client.handshake.return_value = '0306'
        self.client.settings.return_value = {'soc_version': 257}
        self.client.closed.is_set.return_value = False
        self.session = DiscSession(DeviceConfig('127.0.0.1'))
        self.session.operation = lambda **kwargs: nullcontext(self.client)
        self.expected = (QueueItem(0, 'One', 'Artist'),)

    def call(self, name, *args, **kwargs):
        self.client.mutation_attempted = False
        self.client.attempted_phases.clear()
        with patch('controller.fiio_http.HTTPClient', return_value=self.http):
            return getattr(self.session, name)(*args, **kwargs)

    def test_create_rename_add_remove_verify_actual_rows(self):
        self.assertEqual(self.call('create_playlist', 'Evening').status, 'confirmed')
        self.assertEqual(self.call('rename_playlist', 'Evening', 'Night').status, 'confirmed')
        self.assertEqual(self.call('add_playlist_track', 'Morning', 0, expected=self.expected).status, 'confirmed')
        self.assertEqual(self.call('remove_playlist_track', 'Morning', 0, expected=self.expected).status, 'confirmed')
        self.http.remove_from_playlist.assert_called_once_with(0, [[0, 0]])

    def test_empty_200_is_uncertain_and_not_replayed(self):
        self.http.create_playlist.side_effect = None
        result = self.call('create_playlist', 'Evening')
        self.assertEqual(result.status, 'uncertain')
        self.assertTrue(result.mutation_attempted)
        self.http.create_playlist.assert_called_once()

    def test_lost_response_is_uncertain_without_replay(self):
        self.http.create_playlist.side_effect = OSError('response lost')
        result = self.call('create_playlist', 'Evening')
        self.assertEqual(result.status, 'uncertain')
        self.http.create_playlist.assert_called_once()

    def test_stale_track_or_ambiguous_playlist_never_writes(self):
        result = self.call('add_playlist_track', 'Morning', 0, expected=(QueueItem(0, 'Other', 'Artist'),))
        self.assertEqual(result.status, 'not_sent')
        self.names.append('Morning')
        self.assertEqual(self.call('rename_playlist', 'Morning', 'Night').status, 'not_sent')
        self.http.add_selection_to_playlist.assert_not_called()
        self.http.rename_playlist.assert_not_called()

    def test_unsupported_version_and_duplicate_name_do_not_write(self):
        self.client.settings.return_value = {'soc_version': 999}
        self.assertEqual(self.call('create_playlist', 'New').status, 'not_sent')
        self.client.settings.return_value = {'soc_version': 257}
        self.assertEqual(self.call('create_playlist', 'Morning').status, 'not_sent')
        self.http.create_playlist.assert_not_called()
