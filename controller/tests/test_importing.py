from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from controller import DeviceConfig, DiscSession
from controller.fiio_http import HTTPClient, Reply
from controller.fiio_link import frame
from controller.tests.session_fixture import Server, until


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.peer = Server()
        self.addCleanup(self.peer.close)
        self.session = DiscSession(DeviceConfig('127.0.0.1', self.peer.server_address[1], 1, timeout=.3),
                                   health_interval=.05)
        self.session.__enter__()
        self.addCleanup(self.session.__exit__, None, None, None)
        self.session.connect()
        self.assertTrue(self.session.wait_ready(2))
        self.session.client.pacer.interval = 0

    def test_scan_owns_reader_until_end_and_never_runs_health_reads_mid_scan(self):
        self.peer.delay_tag = '0622'
        results, counts = [], []
        worker = threading.Thread(target=lambda: results.append(self.session.scan_library(on_progress=counts.append)))
        worker.start()
        until(lambda: counts == [3])
        tags = list(self.peer.tags)
        time.sleep(.15)
        self.assertEqual(self.peer.tags, tags)
        self.assertTrue(self.session.snapshot().playback.scan_active)
        self.peer.release_reply.set()
        worker.join(3)
        self.assertEqual(results[0].status, 'confirmed')
        self.assertEqual(results[0].confirmation['discovered'], 3)
        self.assertEqual(self.peer.tags.count('0622'), 1)

    def test_lost_scan_reply_is_uncertain_and_not_replayed(self):
        self.peer.drop_write = True
        result = self.session.scan_library(timeout=1)
        self.assertEqual(result.status, 'uncertain')
        self.assertTrue(result.mutation_attempted)
        self.assertEqual(self.peer.tags.count('0622'), 1)

    def test_stale_generation_or_active_scan_never_dispatches(self):
        result = self.session.scan_library(expected_generation=self.session.snapshot().generation + 1)
        self.assertEqual(result.status, 'not_sent')
        self.peer.push('a60a', '000F')
        until(lambda: self.session.snapshot().playback.scan_active)
        self.assertEqual(self.session.scan_library().status, 'not_sent')
        self.assertNotIn('0622', self.peer.tags)

    def test_cancel_and_reset_remain_outside_persistent_socket_surface(self):
        with self.session.operation() as client:
            for tag, body in [('0622', '0001'), ('0621', '0000'), ('0800', '0000')]:
                with self.assertRaises(ValueError):
                    client.socket.sendall(frame(tag, body))
        self.assertEqual(self.peer.writes, 0)

    def transfer(self, *, failure=None, progress=None, listing=True):
        http = Mock()
        def upload(*args, **kwargs):
            kwargs['before_send']()
            if failure:
                raise failure
        http.upload.side_effect = upload
        http.progress.return_value = progress or {'now_size': 4, 'percentage': 1.0}
        http.directory.return_value = {'total': 1, 'items': [{'name': 'New.wav', 'is_dir': False}] if listing else []}
        with tempfile.NamedTemporaryFile() as source:
            source.write(b'RIFF')
            source.flush()
            with patch('controller.importing.HTTPClient', return_value=http):
                result = self.session.upload_audio(source.name, '/tmp/sdcard/New.wav')
        return result, http

    def test_upload_requires_listing_and_completed_size_not_just_http_200(self):
        for kwargs in ({}, {'listing': False}, {'progress': {'now_size': 1, 'percentage': 1}},
                       {'failure': TimeoutError('lost reply')}):
            with self.subTest(kwargs=kwargs):
                result, http = self.transfer(**kwargs)
                self.assertEqual(result.status, 'uncertain' if kwargs else 'confirmed')
                self.assertTrue(result.mutation_attempted)
                http.upload.assert_called_once()

    def test_http_preflight_refuses_collision_before_guard_and_streams_with_byte_progress(self):
        http = HTTPClient()
        http.progress = Mock(return_value=None)
        http.directory = Mock(return_value={'total': 1, 'items': [{'name': 'NEW.wav'}]})
        dispatch, ticks = Mock(), []
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.wav'
            source.write_bytes(b'RIFF12345678')
            with self.assertRaises(FileExistsError):
                http.upload(source, '/tmp/sdcard/New.wav', before_send=dispatch)
            dispatch.assert_not_called()
            http.directory.return_value = {'total': None, 'items': []}
            def request(method, path, body, headers):
                self.assertEqual(headers['Content-Length'], '12')
                data = b''
                while chunk := body.read(5):
                    data += chunk
                self.assertEqual(data, source.read_bytes())
                return Reply(200, {}, b'')
            http.request = request
            http.upload(source, '/tmp/sdcard/New.wav', before_send=dispatch,
                        on_progress=lambda sent, total: ticks.append((sent, total)))
            dispatch.assert_called_once()
            self.assertEqual(ticks[-1], (12, 12))


if __name__ == '__main__':
    unittest.main()
