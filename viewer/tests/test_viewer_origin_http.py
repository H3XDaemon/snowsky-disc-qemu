import http.client
import threading
import unittest
from unittest.mock import Mock, patch
from viewer import server as stream


class BrowserOriginTests(unittest.TestCase):
    """Requests a browser makes for another site must not reach the guest."""

    def setUp(self):
        self.server = stream.ThreadingHTTPServer(('127.0.0.1', 0), stream.Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        for name, value in (('viewer_controls', Mock()), ('state', stream.State()), ('buttons', Mock()),
                            ('touch', Mock())):
            patcher = patch.object(stream, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, path, host=None, **headers):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        client.putrequest('GET', path, skip_host=True)
        client.putheader('Host', host or f'127.0.0.1:{self.port}')
        for name, value in headers.items():
            client.putheader(name.replace('_', '-'), value)
        client.endheaders()
        response = client.getresponse()
        response.read()
        client.close()
        return response

    def test_cross_site_requests_are_refused(self):
        cross = {'Sec-Fetch-Site': 'cross-site'}
        self.assertEqual(self.get('/tap?x=1&y=1', **cross).status, 403)
        self.assertEqual(self.get('/key?k=power', **cross).status, 403)
        self.assertEqual(self.get('/tap?x=1&y=1', **{'Sec-Fetch-Site': 'same-site'}).status, 403)
        self.assertEqual(self.get('/key?k=power', Origin='http://example.com').status, 403)
        self.assertEqual(self.get('/device.json', host=f'attacker.example:{self.port}').status, 403)
        navigate = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'}
        self.assertEqual(self.get('/', **navigate, **{'Sec-Fetch-Dest': 'iframe'}).status, 403)
        self.assertEqual(self.get('/device.json', **navigate, **{'Sec-Fetch-Dest': 'document'}).status, 403)
        self.assertEqual(stream.buttons.method_calls, [])
        self.assertEqual(stream.touch.method_calls, [])

    def test_own_page_and_tools_still_work(self):
        self.assertEqual(self.get('/device.json').status, 200)                       # curl, scripts
        self.assertEqual(self.get('/device.json', host=f'localhost:{self.port}').status, 200)
        self.assertEqual(self.get('/device.json', **{'Sec-Fetch-Site': 'same-origin'},
                                  Origin=f'http://127.0.0.1:{self.port}').status, 200)
        self.assertEqual(self.get('/device.json', **{'Sec-Fetch-Site': 'none'}).status, 200)  # typed URL
        # Opened from another app, Chrome marks the navigation cross-site.
        page = self.get('/', **{'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                                'Sec-Fetch-Dest': 'document'})
        self.assertEqual(page.status, 200)
        self.assertEqual(page.getheader('X-Frame-Options'), 'DENY')
        self.assertEqual(page.getheader('Content-Security-Policy'), "frame-ancestors 'none'")


if __name__ == '__main__':
    unittest.main()
