"""Queue-relative navigation confirms the requested row, not just any change."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from controller.fiio_link import Client, frame
from controller.queue import previous_in_queue, select_queue_index
from controller.models import QueueItem


class QueueNavigationTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(timeout=.01)
        self.before = {'items': [{'pos': i, 'name': name, 'author': 'Artist', 'count': 0}
                                  for i, name in enumerate(('First', 'Second', 'Third'))],
                       'total': 3, 'mark': 1, 'mode': 0,
                       'state': {'state': 0, 'playerflag': 7, 'song': {
                           'song_name': 'Second', 'song_artist_name': 'Artist', 'pos_id': 2}}}
        self.after = deepcopy(self.before)
        self.after['mark'] = 0
        self.after['state']['playerflag'] = 0
        self.after['state']['song'].update(song_name='First', pos_id=1)
        self.client = Mock(mutation_attempted=False)
        self.client.handshake.return_value = '0306'
        self.client.settings.return_value = {'soc_version': 257}
        self.client.play_queue_index = lambda index, **kw: Client.play_queue_index(self.client, index, **kw)
        def send(_):
            self.client.mutation_attempted = True
        self.client.socket.sendall.side_effect = send

    def run_navigation(self, observations):
        with patch('controller.queue.snapshot', side_effect=observations), patch('time.sleep'):
            return previous_in_queue(self.config, self.client, Mock())

    def test_explicit_selection_checks_displayed_queue_before_write(self):
        expected = tuple(QueueItem(r['pos'], r['name'], r['author']) for r in self.before['items'])
        with patch('controller.queue.snapshot', side_effect=[self.before, self.before, self.after]):
            result = select_queue_index(self.config, self.client, Mock(), 0, expected=expected)
        self.assertEqual(result['status'], 'confirmed')
        self.client.socket.sendall.assert_called_once_with(frame('0100', '00000000'))

    def test_explicit_selection_rejects_stale_same_length_source(self):
        expected = tuple(QueueItem(r['pos'], 'Other', r['author']) for r in self.before['items'])
        with patch('controller.queue.snapshot', return_value=self.before):
            result = select_queue_index(self.config, self.client, Mock(), 0, expected=expected)
        self.assertEqual(result['status'], 'not_sent')
        self.client.socket.sendall.assert_not_called()

    def test_explicit_selection_rejects_boolean_and_invalid_bounds(self):
        for index in (True, -1, 65536, '0', 3):
            with patch('controller.queue.snapshot', return_value=self.before):
                result = select_queue_index(self.config, self.client, Mock(), index)
            self.assertEqual(result['status'], 'not_sent')
        self.client.socket.sendall.assert_not_called()

    def test_one_explicit_selection_confirms_exact_predecessor(self):
        result = self.run_navigation([self.before, self.before, self.after])
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['selected_position'], 0)
        self.client.socket.sendall.assert_called_once_with(frame('0100', '00000000'))
        self.client.previous_track.assert_not_called()
        self.client.library.assert_not_called()

    def test_paused_track_and_random_mode_use_displayed_queue(self):
        self.before['state']['state'] = 1
        self.before['mode'] = self.after['mode'] = 1
        self.assertEqual(self.run_navigation([self.before, self.before, self.after])['status'], 'confirmed')

    def test_first_row_does_not_wrap_or_restart_in_any_mode(self):
        for mode in range(5):
            first = deepcopy(self.after)
            first['mode'] = mode
            result = self.run_navigation([first])
            self.assertEqual((result['status'], result['outcome']), ('already_satisfied', 'queue_start'))
        self.client.socket.sendall.assert_not_called()

    def test_unknown_current_state_or_bad_mark_prevents_mutation(self):
        for update in ({'state': {}}, {'mark': -1}, {'mark': 0}, {'state': {'state': 2}}):
            result = self.run_navigation([{**self.before, **update}])
            self.assertEqual(result['status'], 'not_sent')
        self.client.socket.sendall.assert_not_called()

    def test_same_size_queue_replacement_before_send_is_rejected(self):
        changed = deepcopy(self.before)
        changed['items'][0]['name'] = 'Replacement'
        result = self.run_navigation([self.before, changed])
        self.assertEqual(result['status'], 'not_sent')
        self.client.socket.sendall.assert_not_called()

    def test_external_track_change_before_send_is_rejected(self):
        result = self.run_navigation([self.before, self.after])
        self.assertEqual(result['status'], 'not_sent')
        self.client.socket.sendall.assert_not_called()

    def test_wrong_track_at_target_position_is_not_confirmation(self):
        wrong = deepcopy(self.after)
        wrong['state']['song']['song_name'] = 'Wrong'
        with patch('controller.queue.snapshot', side_effect=[self.before, self.before] + [wrong] * 10000), patch('time.sleep'):
            result = previous_in_queue(self.config, self.client, Mock())
        self.assertEqual(result['status'], 'uncertain')
        self.client.socket.sendall.assert_called_once()

    def test_queue_changed_after_send_is_uncertain_without_replay(self):
        changed = deepcopy(self.after)
        changed['items'].pop()
        result = self.run_navigation([self.before, self.before, changed])
        self.assertEqual(result['status'], 'uncertain')
        self.client.socket.sendall.assert_called_once()

    def test_write_loss_is_uncertain_without_replay(self):
        def lost(_):
            self.client.mutation_attempted = True
            raise OSError('lost write')
        self.client.socket.sendall.side_effect = lost
        self.assertEqual(self.run_navigation([self.before, self.before])['status'], 'uncertain')
        self.client.socket.sendall.assert_called_once()

    def test_filename_queue_rows_use_path_and_position_without_song_id(self):
        for observation in (self.before, self.after):
            observation['items'][0].update(name='01 First.flac', author='')
            observation['items'][1].update(name='02 Second.flac', author='')
            observation['state']['song']['song_file_path'] = '/tmp/sdcard/' + (
                '02 Second.flac' if observation['mark'] == 1 else '01 First.flac')
        self.assertEqual(self.run_navigation([self.before, self.before, self.after])['status'], 'confirmed')
