"""Selection refuses stale sources and checks final playlist name/member reads."""
import unittest
from unittest.mock import Mock, patch
from controller import DeviceConfig, QueueItem
from controller.catalog import CatalogChanged
from controller.link_commands import ReviewedCommands
from controller.source_playback import select


class SourcePlaybackTests(unittest.TestCase):
    def fixture(self):
        client = Mock(mutation_attempted=False)
        client.handshake.return_value = '0306'
        client.settings.return_value = {'soc_version': 257}
        client.play_catalog_track = lambda index, **kw: ReviewedCommands.play_catalog_track(client, index, **kw)
        client.play_playlist = lambda position, index, **kw: ReviewedCommands.play_playlist(client, position, index, **kw)
        rows = [dict(pos=0, name='One', author='A'), dict(pos=1, name='Two', author='B')]
        lists = [dict(pos=0, name='Mix', author='')]
        http = Mock()
        http.catalog.side_effect = lambda category, offset=0, limit=200, **kw: {
            'total': len(lists if category == 'custom' else rows),
            'items': (lists if category == 'custom' else rows)[offset:offset+limit]}
        return client, http, rows, lists

    def test_three_scopes_select_exact_position_and_source(self):
        for kind, wire in [('tracks', b'0100001000010001'), ('favorites', b'0100001000010006'),
                           ('playlist', b'0100001800010005{"id":0}')]:
            client, http, rows, _ = self.fixture()
            with patch('controller.source_playback.HTTPClient', return_value=http), \
                    patch('controller.source_playback.verify_playing', return_value={'state': 0}) as verify, \
                    patch('controller.source_playback.snapshot', return_value={}):
                result = select(DeviceConfig('localhost'), client, kind, name='Mix', index=1,
                    expected=tuple(QueueItem(r['pos'], r['name'], r['author']) for r in rows))
            self.assertEqual(result['status'], 'playing')
            client.socket.sendall.assert_called_once_with(wire)
            self.assertEqual(verify.call_args.args[1]['title'], 'Two')

    def test_stale_source_and_unknown_firmware_never_write(self):
        for version, expected in [(257, (QueueItem(0, 'Stale', 'A'),)), (999, None)]:
            client, http, _, _ = self.fixture()
            client.settings.return_value = {'soc_version': version}
            with patch('controller.source_playback.HTTPClient', return_value=http), self.assertRaises(ValueError):
                select(DeviceConfig('localhost'), client, 'tracks', index=0, expected=expected)
            client.socket.sendall.assert_not_called()

    def test_playlist_shift_during_final_preflight_never_writes(self):
        client, http, _, lists = self.fixture()
        original = client.play_playlist
        def moved(*args, **kwargs):
            lists[0] = dict(pos=0, name='Replacement', author='')
            return original(*args, **kwargs)
        client.play_playlist = moved
        with patch('controller.source_playback.HTTPClient', return_value=http), self.assertRaises(CatalogChanged):
            select(DeviceConfig('localhost'), client, 'playlist', name='Mix', index=0)
        client.socket.sendall.assert_not_called()

    def test_empty_and_out_of_bounds_are_not_sent(self):
        for index in [True, -1, 65536, 2]:
            client, http, _, _ = self.fixture()
            with patch('controller.source_playback.HTTPClient', return_value=http), self.assertRaises(ValueError):
                select(DeviceConfig('localhost'), client, 'favorites', index=index)
            client.socket.sendall.assert_not_called()
