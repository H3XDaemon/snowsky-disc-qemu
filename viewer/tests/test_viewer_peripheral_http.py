import http.client
import json
import threading
import unittest
from unittest.mock import Mock, patch
from viewer import server as stream


class PeripheralHTTPTests(unittest.TestCase):
    def test_validation_and_same_origin_before_mutation(self):
        controls = Mock()
        controls.snapshot.return_value = {'usb_connected': True}
        server = stream.ThreadingHTTPServer(('127.0.0.1', 0), stream.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(stream, 'viewer_controls', controls), \
                    patch.object(stream, 'state', stream.State()):
                def post(body, origin=None):
                    client = http.client.HTTPConnection(*server.server_address, timeout=2)
                    headers = {'Content-Type':'application/json'}
                    if origin:
                        headers['Origin'] = origin
                    client.request('POST', '/peripheral', json.dumps(body), headers)
                    response = client.getresponse()
                    status, data = response.status, response.read()
                    client.close()
                    return status, data
                self.assertEqual(post({'name':'usb', 'connected':True}, 'https://foreign.example')[0], 403)
                controls.set_usb.assert_not_called()
                for data in ([], None, {}, {'name':'unknown'}):
                    self.assertEqual(post(data)[0], 400)
                controls.set_usb.assert_not_called()
                status, data = post({'name':'usb', 'connected':True})
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(data)['usb_connected'])
                controls.set_usb.assert_called_once_with(True)
                self.assertEqual(post({'name':'boot_keys', 'keys':['volume_up']})[0], 200)
                controls.set_boot_keys.assert_called_once_with(['volume_up'])
                self.assertEqual(post({'name':'boot_keys'})[0], 400)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
