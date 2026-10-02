import http.client
from email.message import Message
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4

from experiments.disc_web.backend.demo import Demo
from experiments.disc_web.backend.server import Handler, Server, bind_address, parse_args


class WebTests(unittest.TestCase):
    def setUp(self):
        self.demo = Demo()
        self.server = Server(('127.0.0.1', 0), self.demo)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        base = {'Content-Type': 'application/json', 'X-Disc-Token': self.server.token}
        base.update(headers or {})
        connection.request(method, path, json.dumps(body) if body is not None else None, base)
        response = connection.getresponse()
        status, content, response_headers = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return status, content, response_headers

    def test_page_assets_and_synthetic_catalog(self):
        self.assertFalse(json.loads(self.request('GET', '/api/state')[1])['emulator'])
        self.server.emulator = True
        self.assertTrue(json.loads(self.request('GET', '/api/state')[1])['emulator'])
        status, body, headers = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('frame-ancestors', headers['Content-Security-Policy'])
        self.assertIn('Плеер'.encode(), body)
        status, body, _ = self.request('GET', '/api/library?kind=albums')
        self.assertEqual(len(json.loads(body)['items']), 8)
        status, _, headers = self.request('GET', '/art/cover-4.svg')
        self.assertEqual((status, headers['Content-Type']), (200, 'image/svg+xml'))

    def test_no_token_cross_origin_and_rebinding_are_rejected(self):
        command = {'action': 'resume', 'request_id': uuid4().hex}
        for headers in ({'X-Disc-Token': ''}, {'Origin': 'https://untrusted.example'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'Host': 'untrusted.example'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('POST', '/api/action', command, headers)[0], 403)
        self.assertFalse(self.demo.playing)
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': 'evil.example'})[0], 403)

    def test_origin_uses_local_socket_destination_not_arbitrary_lan_or_forwarded_host(self):
        def accepts(host, origin=None, address='192.168.2.10', port=8091, extra=()):
            headers = Message()
            headers['Host'] = host
            if origin is not None:
                headers['Origin'] = origin
            for key, value in extra:
                headers[key] = value
            handler = SimpleNamespace(headers=headers, server=SimpleNamespace(server_port=port),
                                      connection=Mock(getsockname=Mock(return_value=(address, port))))
            return Handler.same_origin(handler)

        authority = '192.168.2.10:8091'
        self.assertTrue(accepts(authority))
        self.assertTrue(accepts(authority, f'http://{authority}'))
        self.assertTrue(accepts('localhost:8091', 'http://localhost:8091', address='127.0.0.1'))
        self.assertTrue(accepts('192.168.2.10', 'http://192.168.2.10', port=80))
        for host in ['192.168.2.11:8091', '0.0.0.0:8091', 'evil.example:8091',
                     '127.0.0.1:8091', '192.168.2.10:8092']:
            self.assertFalse(accepts(host), host)
        self.assertFalse(accepts(authority, 'http://192.168.2.11:8091'))
        self.assertFalse(accepts(authority, extra=[('Sec-Fetch-Site', 'cross-site')]))
        self.assertFalse(accepts(authority, extra=[('Host', authority)]))
        self.assertFalse(accepts(authority, f'http://{authority}', extra=[('Origin', f'http://{authority}')]))
        self.assertFalse(accepts('evil.example', extra=[('X-Forwarded-Host', authority)]))
        self.assertEqual(self.request('GET', '/api/state', headers={'Host': authority})[0], 403)

    def test_wildcard_listener_keeps_token_and_origin_guards(self):
        with Server(('0.0.0.0', 0), Demo()) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                authority = f'127.0.0.1:{server.server_port}'
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                connection.request('GET', '/api/state', headers={'Origin': f'http://{authority}'})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                token = json.loads(response.read())['token']
                for supplied, origin, expected in [('', f'http://{authority}', 403),
                    (token, 'http://evil.example', 403), (token, f'http://{authority}', 200)]:
                    connection.request('POST', '/api/action', json.dumps({'action':'next', 'request_id':uuid4().hex}),
                        {'Content-Type':'application/json', 'X-Disc-Token':supplied, 'Origin':origin})
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    response.read()
                connection.close()
            finally:
                server.shutdown()
                worker.join(2)

    def test_bind_option_accepts_wildcard_or_local_ipv4(self):
        import argparse
        for value in ['127.0.0.1', '192.168.2.10', '0.0.0.0']:
            self.assertEqual(bind_address(value), value)
        self.assertEqual(bind_address('localhost'), '127.0.0.1')
        for value in ['evil.example', 'https://127.0.0.1', '8.8.8.8', '::', '224.0.0.1']:
            with self.assertRaises(argparse.ArgumentTypeError):
                bind_address(value)

    def test_emulator_is_an_explicit_launch_mode_with_physical_defaults_otherwise(self):
        from contextlib import redirect_stderr
        import io
        normal = parse_args([])
        self.assertEqual((normal.device, normal.http_port, normal.tcp_port, normal.emulator),
                         (None, 12103, 12100, False))
        physical = parse_args(['--device', '192.168.2.10', '--host', '0.0.0.0'])
        self.assertEqual((physical.device, physical.http_port, physical.emulator), ('192.168.2.10', 12103, False))
        emulator = parse_args(['--emulator'])
        self.assertEqual((emulator.device, emulator.http_port, emulator.emulator), ('127.0.0.1', 12113, True))
        override = parse_args(['--emulator', '--device', '192.168.2.10', '--http-port', '12103'])
        self.assertEqual((override.device, override.http_port), ('192.168.2.10', 12103))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(['--demo', '--emulator'])

    def test_duplicate_request_never_changes_state_twice(self):
        command = {'action': 'next', 'request_id': uuid4().hex}
        self.assertEqual(self.request('POST', '/api/action', command)[0], 200)
        selected = self.demo.selected
        self.assertEqual(self.request('POST', '/api/action', command)[0], 409)
        self.assertEqual(self.demo.selected, selected)

    def test_mutations_are_not_get_routes_and_unknown_commands_fail(self):
        self.assertEqual(self.request('GET', '/api/action?action=resume')[0], 404)
        self.assertEqual(self.request('POST', '/api/action', {'action': 'raw', 'request_id': uuid4().hex})[0], 422)
        self.assertEqual(self.request('GET', '/../../AGENTS.md')[0], 404)
        self.assertFalse(self.demo.playing)

    def test_demo_isolation_and_current_favorite(self):
        self.assertEqual(self.request('POST', '/api/action', {'action': 'connect', 'request_id': uuid4().hex})[0], 422)
        command = {'action': 'favorite', 'value': False, 'request_id': uuid4().hex}
        self.assertEqual(self.request('POST', '/api/action', command)[0], 200)
        favorites = json.loads(self.request('GET', '/api/library?kind=favorites')[1])['items']
        self.assertNotIn('0-1', [t['id'] for t in favorites])
        self.assertFalse(self.demo.state()['playback']['favorite'])

    def test_invalid_json_shape_and_scalar_types(self):
        self.assertEqual(self.request('POST', '/api/action', [1, 2])[0], 422)
        self.assertEqual(self.request('POST', '/api/action', {'action': 'volume', 'value': True, 'request_id': uuid4().hex})[0], 422)
        self.assertEqual(self.request('POST', '/api/action', {'action': 'queue', 'index': -1, 'request_id': uuid4().hex})[0], 422)

    def test_upload_auth_framing_duplicates_and_static_assets_during_scan(self):
        body = {'generation': 1, 'request_id': uuid4().hex}
        self.assertEqual(self.request('POST', '/api/scan', body, {'X-Disc-Token': ''})[0], 403)
        self.assertEqual(self.request('POST', '/api/scan', body)[0], 202)
        self.assertEqual(self.request('POST', '/api/scan', body)[0], 409)
        self.assertEqual(self.request('POST', '/api/action', {'action': 'next', 'request_id': uuid4().hex})[0], 409)
        state = json.loads(self.request('GET', '/api/state')[1])
        self.assertTrue(state['busy'])
        self.assertEqual(state['job']['id'], body['request_id'])
        self.assertEqual(self.request('GET', '/imports.mjs')[0], 200)
        self.assertEqual(self.request('POST', '/api/upload?name=Test.wav')[0], 415)

    def test_demo_never_connects_or_discovers_and_connection_routes_require_token(self):
        self.assertEqual(json.loads(self.request('GET', '/api/interfaces')[1]), {'interfaces': []})
        for route in ('/api/connection', '/api/discover', '/api/sync'):
            body = {'host': '192.168.2.10', 'tcp_port': 12100, 'http_port': 12103,
                    'interface': '192.168.2.11', 'request_id': uuid4().hex, 'generation': 1}
            self.assertEqual(self.request('POST', route, body, {'X-Disc-Token': ''})[0], 403)
            self.assertEqual(self.request('POST', route, body)[0], 422)


if __name__ == '__main__':
    unittest.main()
