import http.client
import json
import threading
import unittest
from uuid import uuid4

from controller import DeviceConfig
from controller.tests.session_fixture import Server as Peer
from experiments.disc_web.backend.device import Device
from experiments.disc_web.backend.server import Server


class WebSoundTests(unittest.TestCase):
    def test_same_owner_read_write_admission_and_stale_generation(self):
        peer = Peer()
        self.addCleanup(peer.close)
        with Device(DeviceConfig('127.0.0.1', peer.server_address[1], timeout=.3)) as device:
            device.session.connect()
            self.assertTrue(device.session.wait_ready(2))
            with Server(('127.0.0.1', 0), device) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                def request(method, path, body=None, **headers):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=4)
                    connection.request(method, path, None if body is None else json.dumps(body),
                        {'Content-Type': 'application/json', 'X-Disc-Token': server.token, **headers})
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read())
                    connection.close()
                    return result
                try:
                    status, read = request('GET', '/api/sound')
                    self.assertEqual((status, read['status']), (200, 'observed'))
                    command = dict(action='sound_setting', name='gain', value=1, expected=0,
                                   generation=read['generation'], request_id=uuid4().hex)
                    self.assertEqual(request('POST', '/api/action', command, Origin='https://example.com')[0], 403)
                    with server.imports.foreground():
                        self.assertEqual(request('GET', '/api/sound')[0], 409)
                        self.assertEqual(request('POST', '/api/action', dict(command, request_id=uuid4().hex))[0], 409)
                    self.assertEqual(peer.writes, 0)
                    status, result = request('POST', '/api/action', command)
                    self.assertEqual((status, result['status']), (200, 'confirmed'))
                    self.assertEqual(request('POST', '/api/action', command)[0], 409)
                    self.assertEqual(request('POST', '/api/action', dict(command, generation=-1, request_id=uuid4().hex))[0], 422)
                    self.assertEqual((peer.accepts, peer.writes), (1, 1))
                finally:
                    server.shutdown()
                    worker.join(2)
