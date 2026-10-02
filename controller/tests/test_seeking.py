"""Synthetic persistent transport seek evidence, identity and no-replay checks."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from controller import DeviceConfig, DiscSession
from controller.models import PlaybackSource
from controller.tests.session_fixture import Server, until


class SeekingTests(unittest.TestCase):
    def setUp(self):
        self.pacer = patch('controller.device.MutationPacer.interval', 0)
        self.pacer.start()
        self.peer = Server()
        self.peer.state['song']['song_duration_time'] = 120000
        self.session = DiscSession(DeviceConfig('127.0.0.1', self.peer.server_address[1], timeout=.4))
        self.session.__enter__()
        self.session.connect()
        self.assertTrue(self.session.wait_ready(3))
        self.track = self.session.snapshot().playback.track

    def tearDown(self):
        self.session.__exit__(None, None, None)
        self.peer.close()
        self.pacer.stop()

    def seek(self, value, expected=None):
        return self.session.seek(value, expected=expected or self.track, source=PlaybackSource.ARTIST_SCOPE)

    def test_playing_seek_rounds_and_confirms_fresh_position(self):
        result = self.seek(31500)
        self.assertEqual(result.status, 'confirmed', result)
        self.assertEqual(result.confirmation['observed_ms'], 31000)
        self.assertEqual(self.peer.tags.count('0103'), 1)

    def test_paused_seek_stays_uncertain_without_resuming_or_replaying(self):
        self.peer.state['state'] = 1
        result = self.seek(31000)
        self.assertEqual(result.status, 'uncertain', result)
        self.assertEqual(result.outcome, 'seek_waiting_for_playback')
        until(lambda: self.peer.tags.count('0103') == 1)
        self.assertNotIn('0201', self.peer.tags)
        self.assertIsNone(self.session.snapshot().playback.position_ms)

    def test_stale_track_and_invalid_bounds_never_write(self):
        for value in [True, -1, 120000, '10']:
            self.assertEqual(self.seek(value).status, 'not_sent')
        self.assertEqual(self.seek(10000, replace(self.track, title='Other')).status, 'not_sent')
        self.assertEqual(self.peer.writes, 0)

    def test_lost_reply_is_uncertain_and_reconnection_does_not_replay(self):
        self.peer.drop_write = True
        result = self.seek(30000)
        self.assertEqual(result.status, 'uncertain')
        self.assertTrue(result.mutation_attempted)
        until(lambda: self.peer.accepts >= 2)
        self.assertEqual(self.peer.tags.count('0103'), 1)

    def test_descriptive_metadata_does_not_change_guarded_seek_identity(self):
        enriched = replace(self.track, sample_rate_hz=44100, bit_depth=16, is_cue=False)
        result = self.seek(10000, enriched)
        self.assertTrue(result.mutation_attempted)
        self.assertEqual(self.peer.tags.count('0103'), 1)
