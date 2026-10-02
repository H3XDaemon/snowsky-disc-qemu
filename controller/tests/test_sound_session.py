import unittest
from unittest.mock import patch

from controller import DeviceConfig, DiscSession
from controller.tests.session_fixture import Server, until


class SoundSessionTests(unittest.TestCase):
    def setUp(self):
        self.pacing = patch('controller.device.MutationPacer.interval', .03)
        self.pacing.start()
        self.addCleanup(self.pacing.stop)
        self.peer = Server()
        self.addCleanup(self.peer.close)
        self.session = DiscSession(DeviceConfig('127.0.0.1', self.peer.server_address[1], timeout=.2),
                                   backoff=.02)
        self.session.__enter__()
        self.addCleanup(self.session.__exit__, None, None, None)
        self.session.connect()
        self.assertTrue(self.session.wait_ready(2))

    def test_read_change_and_idempotence_share_owner_and_fresh_readback(self):
        observed = self.session.sound_settings()
        self.assertEqual(observed.status, 'observed')
        self.assertEqual(observed.confirmation['settings'], self.peer.sound)
        for name, value in [('gain', 1), ('balance', -20), ('filter', 5), ('dre', 1)]:
            result = self.session.set_sound_setting(name, value, expected=0)
            self.assertEqual(result.status, 'confirmed', result)
            self.assertEqual(result.confirmation, {'name': name, 'value': value})
            self.assertTrue(result.mutation_attempted)
            self.assertEqual(self.session.set_sound_setting(name, value, expected=value).status, 'already_satisfied')
        self.assertEqual(self.peer.writes, 4)
        self.assertEqual(self.peer.accepts, 1)

    def test_invalid_stale_and_unknown_firmware_never_write(self):
        for name, value in [('gain', True), ('filter', 6), ('balance', -21), ('dre', 2), ('eq_type', 160)]:
            with self.assertRaises(ValueError):
                self.session.set_sound_setting(name, value, expected=0)
        self.peer.sound['gain'] = 1
        result = self.session.set_sound_setting('gain', 0, expected=0)
        self.assertEqual(result.outcome, 'sound_changed')
        self.assertEqual(result.status, 'not_sent')
        result = self.session.set_sound_setting('gain', 0, expected=1, expected_generation=-1)
        self.assertEqual(result.status, 'not_sent')
        self.peer.version = 999
        self.assertEqual(self.session.sound_settings().status, 'not_sent')
        self.assertEqual(self.session.set_sound_setting('gain', 0, expected=1).status, 'not_sent')
        self.assertEqual(self.peer.writes, 0)

    def test_scan_malformed_values_and_missing_confirmation_are_not_success(self):
        self.peer.sound['gain'] = 2
        # Keep the peer response valid hex while exercising unknown value handling.
        with patch('controller.tests.session_fixture.setting_command', return_value=('0649', '0002')):
            self.assertEqual(self.session.sound_settings().status, 'not_sent')
        self.peer.sound['gain'] = 0
        self.peer.push('a60a', '000F')
        until(lambda: self.session.client.scan_active)
        self.assertEqual(self.session.set_sound_setting('gain', 1, expected=0).status, 'not_sent')
        self.peer.push('a60a', '0005')
        until(lambda: not self.session.client.scan_active)
        self.peer.ignore_sound_write = True
        result = self.session.set_sound_setting('gain', 1, expected=0)
        self.assertEqual(result.status, 'uncertain')
        self.assertEqual(self.peer.writes, 1)

    def test_lost_connection_after_write_is_uncertain_and_never_replayed(self):
        generation = self.session.snapshot().generation
        self.peer.drop_write = True
        result = self.session.set_sound_setting('balance', 20, expected=0)
        self.assertEqual(result.status, 'uncertain')
        self.assertTrue(result.mutation_attempted)
        until(lambda: self.session.snapshot().generation > generation and self.session.snapshot().connection == 'ready')
        self.assertEqual(self.peer.writes, 1)
