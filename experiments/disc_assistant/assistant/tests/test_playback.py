from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from controller.fiio_link import frame
from experiments.disc_assistant.assistant import playback
from experiments.disc_assistant.assistant.config import Config
from library.store import Store
from library.tests.helpers import TRACKS


class ScopedHTTP:
    def __init__(self):
        self.rows = [dict(pos=0, name='Earlier', author='Linkin Park'),
                     dict(pos=1, name='Numb', author='Linkin Park')]
        self.calls = []

    def catalog(self, category, offset=0, limit=200, **filters):
        self.calls.append((category, offset, limit, filters))
        return {'total': len(self.rows), 'items': self.rows[offset:offset+limit], 'mark': 1}


class FakeClient:
    def __init__(self):
        self.mutation_attempted = False
        self.observed = []
        self.calls = 0
        self.error = None
        self.snapshot = {'state': 0, 'playerflag': 7, 'song': {'song_name': 'Numb',
                         'song_artist_name': 'Linkin Park', 'song_album_name': 'Meteora', 'pos_id': 2}}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin_phase(self, name):
        pass

    def wait_for_mutation(self):
        pass

    def handshake(self):
        return '0306'

    def settings(self):
        return {'soc_version': 257}

    def play_mode(self):
        return 0

    def take_events(self):
        events, self.observed = self.observed, []
        return events

    def scan_guard(self):
        pass

    def play_artist(self, artist, index=None, *, album=None, http):
        from controller.fiio_library import verify_artist
        verify_artist(http, artist, index, album)
        self.calls += 1
        self.selected_index = index
        self.mutation_attempted = True
        if self.error:
            raise self.error

    def now_playing(self):
        return self.snapshot


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        directory = Path(self.tmp.name)
        self.store = Store(directory)
        self.addCleanup(self.store.close)
        tracks = [TRACKS[0], replace(TRACKS[0], title='Earlier', position=1,
                                   raw={'pos': 1, 'name': 'Earlier', 'author': 'Linkin Park'})]
        self.head = self.store.publish('test', tracks, {}, expected_generation=None)
        self.config = Config('test', 'localhost', 12100, 12103, directory, 'localhost', 8108, 'http', 'KEY', {})
        self.target = {'kind': 'track', 'track_id': self.head['generation'] + ':0',
                       'artist': 'Linkin Park', 'album': 'Meteora', 'title': 'Numb'}
        self.ranking = {'generation': self.head['generation'], 'candidates': [self.target]}
        self.http, self.client = ScopedHTTP(), FakeClient()

    def execute(self):
        with patch.object(playback, 'HTTPClient', return_value=self.http), \
                patch.object(playback, 'PlaybackClient', return_value=self.client), \
                patch.object(playback.time, 'sleep'):
            return playback.execute(self.config, self.store, self.ranking)

    def test_reordered_tracks_use_fresh_scoped_position(self):
        result = self.execute()
        self.assertEqual(result['status'], 'playing')
        self.assertEqual(self.client.selected_index, 1)
        self.assertEqual(self.client.calls, 1)
        self.assertIn(('artist/album/song', 1, 1, {'artist': 'Linkin Park', 'album': 'Meteora'}), self.http.calls)

    def test_changed_membership_and_generation_do_not_send(self):
        self.http.rows[1] = dict(pos=1, name='Replaced', author='Linkin Park')
        self.assertEqual(self.execute()['status'], 'not_sent')
        self.assertEqual(self.client.calls, 0)
        self.store.publish('test', [], {}, expected_generation=self.head['generation'])
        self.assertEqual(self.execute()['status'], 'not_sent')
        self.assertEqual(self.client.calls, 0)

    def test_final_preflight_identity_change_blocks_dispatch(self):
        original = self.http.catalog
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get('limit') == 1:
                result['items'] = [dict(pos=1, name='Replacement', author='Linkin Park')]
            return result
        self.http.catalog = changed
        self.assertEqual(self.execute()['status'], 'not_sent')
        self.assertEqual(self.client.calls, 0)

    def test_uncertain_write_is_never_replayed(self):
        self.client.error = ConnectionError('lost during write')
        result = self.execute()
        self.assertEqual(result['status'], 'uncertain')
        self.assertTrue(result['mutation_attempted'])
        self.assertEqual(self.client.calls, 1)

    def test_unconfirmed_playback_is_uncertain_without_retry(self):
        with patch.object(playback, 'verify_playing', return_value=None):
            self.assertEqual(self.execute()['status'], 'uncertain')
        self.assertEqual(self.client.calls, 1)

    def test_queue_failure_keeps_fresh_evidence_and_does_not_replay(self):
        from experiments.disc_assistant.assistant.journal import outcome
        playing = self.client.snapshot
        self.client.now_playing = Mock(side_effect=[playing, {}])
        result = self.execute()
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(self.client.calls, 1)
        self.assertEqual(result['confirmation']['last_observed']['title'], 'Numb')
        queue = result['confirmation']['queue']
        self.assertEqual(queue['code'], 'state_mismatch')
        self.assertIsNone(queue['observed']['state'])
        self.assertEqual(queue['expected']['pos_id'], 2)
        self.assertEqual(outcome(result)['confirmation']['queue'], queue)

    def test_shortened_album_is_confirmed_with_fresh_catalog_and_queue(self):
        original = self.http.catalog
        def catalog(category, **kwargs):
            if category == 'artist/album':
                return {'total': 1, 'items': [{'pos': 0, 'name': 'Meteora'}]}
            return original(category, **kwargs)
        self.http.catalog = catalog
        self.client.snapshot['song']['song_album_name'] = 'Meteor'
        result = self.execute()
        self.assertEqual(result['status'], 'playing')
        self.assertEqual(result['confirmation']['last_observed']['album'], 'Meteor')
        self.assertEqual(result['queue']['mark'], 1)
        self.assertEqual(self.client.calls, 1)

    def test_artist_play_all_uses_no_index(self):
        self.ranking['candidates'] = [{'kind': 'artist', 'artist': 'Linkin Park'}]
        self.assertEqual(self.execute()['status'], 'playing')
        self.assertIsNone(self.client.selected_index)

    def test_state_only_delta_keeps_metadata_but_loading_drops_old_song(self):
        state = playback.merge_snapshot({}, dict(self.client.snapshot, state=2))
        state = playback.merge_snapshot(state, {'state': 0})
        self.assertTrue(playback.matches(state, self.target, self.http.rows))
        state = playback.merge_snapshot(state, {'state': 2})
        state = playback.merge_snapshot(state, {'state': 0})
        self.assertFalse(playback.matches(state, self.target, self.http.rows))

    def test_scan_after_dispatch_does_not_confirm_playback(self):
        self.client.observed = [('a60a', b'000F')]
        with self.assertRaisesRegex(ValueError, 'scan activity'):
            playback.verify_playing(self.client, self.target, self.http.rows, 1)

    def test_wrong_artist_or_paused_state_is_not_confirmation(self):
        for update in ({'state': 1}, {'playerflag': 3},
                       {'song': {'song_name': 'Numb', 'song_artist_name': 'Other', 'song_album_name': 'Meteora'}}):
            with self.subTest(update=update):
                state = {**self.client.snapshot, **update}
                self.assertFalse(playback.matches(state, self.target, self.http.rows))

    def test_same_data_directory_serializes_device_operations(self):
        with playback.device_lock(self.config.data_dir):
            with self.assertRaisesRegex(ValueError, 'another assistant'):
                with playback.device_lock(self.config.data_dir):
                    pass

    def test_socket_marks_uncertain_attempt_before_transport_error(self):
        raw = Mock()
        raw.sendall.side_effect = OSError('broken')
        session = Mock(mutation_attempted=False, mutation_phase='selection', attempted_phases=set())
        socket = playback.ObservedSocket(raw, session)
        with self.assertRaises(OSError):
            socket.sendall(frame('0100', '00000007'))
        self.assertTrue(session.mutation_attempted)
        with self.assertRaisesRegex(RuntimeError, 'replay'):
            socket.sendall(frame('0100', '00000007'))
        self.assertEqual(raw.sendall.call_count, 1)

    def test_request_retains_interleaved_scan_notifications(self):
        client = playback.PlaybackClient.__new__(playback.PlaybackClient)
        client.socket = Mock()
        client.observed, client.timeout = [], 1
        with patch.object(client, 'collect'), patch('controller.fiio_link.Client.event', side_effect=[
                ('a60a', b'000F'), ('a501', b'{"soc_version":257}')]):
            self.assertEqual(client.settings()['soc_version'], 257)
        self.assertEqual(client.observed, [('a60a', b'000F')])
        with patch.object(client, 'collect'), self.assertRaisesRegex(ValueError, 'scan activity'):
            client.scan_guard()

    def test_member_match_preserves_literal_credit_in_fresh_device_scope(self):
        from library.catalog import Track
        from library.tests.helpers import Catalog
        tracks = [Track('Stan', 'Eminem;Dido', 'Album', 0,
                        {'pos': 0, 'name': 'Stan', 'author': 'Eminem;Dido'})]
        head = self.store.publish('test', tracks, {}, expected_generation=self.head['generation'])
        selected = {'kind': 'track', 'track_id': head['generation'] + ':0',
                    'artist': 'Eminem;Dido', 'title': 'Stan', 'album': 'Album'}
        http = Catalog(tracks)
        category, filters, rows, index, count = playback.fresh_selection(
            self.config, self.store, head['generation'], selected, http)
        self.assertEqual(filters, {'artist': 'Eminem;Dido', 'album': 'Album'})
        self.assertEqual((index, count), (0, 1))
        self.assertEqual(rows[0]['author'], 'Eminem;Dido')
