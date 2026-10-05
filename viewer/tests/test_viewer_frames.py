"""Lossless frame deduplication, buffer selection and real multipart transport."""
import http.client
import threading
import unittest
from unittest.mock import patch

from viewer import server as stream


from emulator.runtime.framebuffer import W, H
from tests.fixtures.framebuffer import pixels, decode_png


class FrameTransportTests(unittest.TestCase):
    def setUp(self):
        self.state = stream.State()
        self.finished = threading.Event()
        finished = self.finished

        class Handler(stream.Handler):
            def _frame_stream(self, **kwargs):
                try:
                    super()._frame_stream(**kwargs)
                finally:
                    finished.set()

        self.patches = [patch.object(stream, 'state', self.state),
                        patch.object(stream, 'FRAME_HEARTBEAT', .1)]
        for p in self.patches:
            p.start()
        self.server = stream.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.clients = []

    def tearDown(self):
        for connection, response in self.clients:
            response.close()
            connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        for p in reversed(self.patches):
            p.stop()

    def connect(self, path='/stream', content_type='multipart/x-mixed-replace; boundary=FRAME'):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        connection.request('GET', path)
        response = connection.getresponse()
        self.clients.append((connection, response))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), content_type)
        return response

    def frame(self, response):
        self.assertEqual(response.readline(), b'--FRAME\r\n')
        self.assertEqual(response.readline(), b'Content-Type: image/png\r\n')
        header = response.readline()
        self.assertTrue(header.startswith(b'Content-Length: '))
        size = int(header.split(b':')[1])
        self.assertEqual(response.readline(), b'\r\n')
        png = response.read(size)
        self.assertEqual(len(png), size)
        # All PNG bytes are available without waiting for the next changed frame.
        self.assertEqual(response.readline(), b'\r\n')
        return png

    def test_initial_idle_refresh_change_and_new_viewer(self):
        response = self.connect()
        self.assertEqual(self.frame(response), self.state.png)
        self.assertEqual(self.frame(response), self.state.png)  # Idle refresh.
        self.state.update_frame(pixels(42) * 2, 1, True)
        expected = bytes((40, 20, 42)) * (W * H)
        self.assertEqual(decode_png(self.frame(response)), expected)
        self.assertEqual(decode_png(self.frame(self.connect())), expected)

    def test_raw_stream_is_the_same_framing_as_plain_bytes(self):
        """frames.js reads the parts itself, so it asks for application/octet-stream:
        WebKit's fetch() never delivers a multipart/x-mixed-replace body to the page."""
        raw = self.connect('/stream?raw=1', 'application/octet-stream; boundary=FRAME')
        multipart = self.connect()
        self.assertEqual(self.frame(raw), self.state.png)
        self.assertEqual(self.frame(multipart), self.state.png)
        self.state.update_frame(pixels(43) * 2, 1, True)
        self.assertEqual(self.frame(multipart), self.frame(raw))
        self.assertEqual(decode_png(self.frame(raw)), bytes((40, 20, 43)) * (W * H))
        self.connect('/stream?raw=0')                       # anything but 1 keeps the browser type

    def test_disconnect_releases_handler(self):
        response = self.connect()
        self.frame(response)
        connection, _ = self.clients.pop()
        response.close()
        connection.close()
        self.assertTrue(self.finished.wait(2), 'Disconnected frame handler leaked')

    def test_new_frame_wakes_client_without_waiting_for_idle_refresh(self):
        with patch.object(stream, 'FRAME_HEARTBEAT', 10):
            response = self.connect()
            self.frame(response)
            self.state.update_frame(pixels(77) * 2, 0, True)
            # HTTP timeout is 2s, much shorter than the idle refresh interval.
            self.assertEqual(decode_png(self.frame(response)),
                             bytes((40, 20, 77)) * (W * H))
            response.close()
        # Wake the old long waiter after restoring the short test heartbeat, so
        # a disconnected handler cannot outlive this test's patched state.
        self.state.update_frame(pixels(78) * 2, 0, True)
        self.assertTrue(self.finished.wait(2))
