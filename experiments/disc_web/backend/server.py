"""Dependency-free HTTP adapter, loopback by default. A browser never owns a device socket."""
import argparse
from collections import OrderedDict
import json
import mimetypes
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import parse_qs, urlsplit

from controller import DeviceConfig
from experiments.disc_web.backend.demo import Demo
from experiments.disc_web.backend.device import BusyError, Device
from experiments.disc_web.backend.imports import Imports
from experiments.disc_web.backend.connections import Discovery, connection_config, interfaces, local_address
from experiments.disc_web.backend.catalogue import Catalogue, CACHED_VIEWS

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, device, data_dir=None, *, emulator=False):
        self.device = device
        self.emulator = emulator
        self.imports = Imports(device)
        self.catalogue = Catalogue(device, self.imports.gate, data_dir) if data_dir and not device.demo else None
        if self.catalogue:
            device.catalogue = self.catalogue
        self.discovery = Discovery()
        self.token = secrets.token_urlsafe(32)
        self.requests = OrderedDict()
        self.request_lock = threading.Lock()
        super().__init__(address, Handler)

    def server_close(self):
        if self.catalogue:
            self.catalogue.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'DiscWeb/0.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        # Device names, queries and private catalog data do not belong in logs.
        pass

    def reply(self, value, status=200, content_type='application/json; charset=utf-8'):
        body = json.dumps(value, ensure_ascii=False).encode() if not isinstance(value, bytes) else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def same_origin(self):
        # The accepted socket supplies the actual local destination, including
        # for a wildcard listener. Never trust arbitrary Host/forwarded headers.
        address = self.connection.getsockname()[0]
        names = {address}
        if address.startswith('127.'):
            names.add('localhost')
        allowed = {f'{name}:{self.server.server_port}' for name in names}
        if self.server.server_port == 80:
            allowed.update(names)
        host = self.headers.get('Host')
        origin = self.headers.get('Origin')
        return (len(self.headers.get_all('Host', [])) == 1
                and len(self.headers.get_all('Origin', [])) <= 1
                and host in allowed and (origin is None or origin == f'http://{host}')
                and self.headers.get('Sec-Fetch-Site') not in ('cross-site',))

    def do_GET(self):
        if not self.same_origin():
            return self.reply({'error': 'Local same-origin access required'}, 403)
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        try:
            if url.path == '/api/state':
                job = self.server.imports.state()
                return self.reply({**self.server.device.state(), 'token': self.server.token,
                                   'emulator': self.server.emulator,
                                   'busy': self.server.imports.gate.locked(), 'job': job,
                                   'catalogue': self.server.catalogue.state() if self.server.catalogue else None})
            if url.path == '/api/interfaces':
                return self.reply({'interfaces': [] if self.server.device.demo else interfaces()})
            if url.path.startswith('/api/artwork/') and self.server.catalogue:
                art = self.server.catalogue.metadata.artwork(url.path.removeprefix('/api/artwork/'))
                return self.reply(art[0], content_type=art[1]) if art else self.reply({'error': 'Artwork unavailable'}, 404)
            if (url.path == '/api/library' and self.server.catalogue
                    and query.get('kind', ['albums'])[0] in CACHED_VIEWS
                    and self.server.catalogue.state()['available']):
                return self.get_content(url, query)
            if url.path.startswith('/api/'):
                with self.server.imports.foreground():
                    return self.get_content(url, query)
            return self.get_content(url, query)
        except BusyError as exc:
            return self.reply({'error': str(exc)}, 409)
        except (ValueError, OSError, RuntimeError) as exc:
            return self.reply({'error': str(exc)}, 422)

    def get_content(self, url, query):
        try:
            if url.path == '/api/sound' and not self.server.device.demo:
                return self.reply(self.server.device.sound_settings())
            if url.path == '/api/library':
                return self.reply(self.server.device.browse(query.get('kind', ['albums'])[0],
                    query.get('name', [''])[0], query.get('artist', [''])[0], query.get('genre', [''])[0]))
            if url.path == '/api/queue':
                return self.reply(self.server.device.queue())
            if url.path == '/api/cover' and not self.server.device.demo:
                expected = json.loads(query['v'][0]) if 'v' in query else None
                data = self.server.device.cover(expected)
                if data.startswith(b'\xff\xd8\xff'):
                    return self.reply(data, content_type='image/jpeg')
                if data.startswith(b'\x89PNG\r\n\x1a\n'):
                    return self.reply(data, content_type='image/png')
                return self.reply({'error': 'No current cover'}, 404)
            relative = 'index.html' if url.path == '/' else url.path.removeprefix('/')
            path = (FRONTEND / relative).resolve()
            if not path.is_relative_to(FRONTEND) or not path.is_file():
                return self.reply({'error': 'Not found'}, 404)
            return self.reply(path.read_bytes(), content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        except BusyError as exc:
            return self.reply({'error': str(exc)}, 409)
        except (ValueError, OSError, RuntimeError) as exc:
            return self.reply({'error': str(exc)}, 422)

    def do_POST(self):
        if (not self.same_origin() or not secrets.compare_digest(self.headers.get('X-Disc-Token', ''), self.server.token)):
            return self.reply({'error': 'Local session token required'}, 403)
        url = urlsplit(self.path)
        if url.path == '/api/upload':
            try:
                if self.headers.get('Content-Type') != 'application/octet-stream' or self.headers.get('Transfer-Encoding'):
                    return self.reply({'error': 'A raw file with Content-Length is required'}, 415)
                query = parse_qs(url.query)
                request_id = self.headers.get('X-Request-ID')
                self.claim(request_id)
                return self.reply(self.server.imports.upload(self.rfile,
                    int(self.headers.get('Content-Length', '0')), query.get('name', [''])[0],
                    int(self.headers.get('X-Disc-Generation', '0')), request_id), 202)
            except BusyError as exc:
                return self.reply({'error': str(exc)}, 409)
            except (ValueError, OSError, RuntimeError) as exc:
                return self.reply({'error': str(exc)}, 422)
        if self.path not in ('/api/action', '/api/scan', '/api/connection', '/api/discover', '/api/sync'):
            return self.reply({'error': 'Not found'}, 404)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply({'error': 'JSON required'}, 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                return self.reply({'error': 'Request size outside limit'}, 413)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            request_id = body.get('request_id')
            self.claim(request_id)
            if self.path == '/api/sync':
                if not self.server.catalogue:
                    raise ValueError('Local library is unavailable in this mode')
                return self.reply(self.server.catalogue.start(body.get('generation'), request_id), 202)
            if self.path in ('/api/connection', '/api/discover') and self.server.device.demo:
                raise ValueError('Demo mode never connects or discovers devices')
            if self.path == '/api/discover':
                return self.reply(self.server.discovery.search(body.get('interface')))
            if self.path == '/api/scan':
                return self.reply(self.server.imports.scan(body.get('generation'), request_id), 202)
            with self.server.imports.foreground():
                if self.path == '/api/connection':
                    config = connection_config(body)
                    result = self.server.device.configure(config, body.get('generation'))
                    with self.server.imports.guard:
                        self.server.imports.job = None
                    return self.reply(result)
                return self.reply(self.server.device.action(body))
        except BusyError as exc:
            return self.reply({'error': str(exc)}, 409)
        except (ValueError, OSError, RuntimeError) as exc:
            return self.reply({'error': str(exc)}, 422)

    def claim(self, request_id):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
            raise ValueError('A request ID is required')
        with self.server.request_lock:
            if request_id in self.server.requests:
                raise BusyError('Duplicate request was not replayed')
            if len(self.server.requests) >= 4096:
                raise BusyError('Request budget exhausted; restart the local server')
            self.server.requests[request_id] = None


def bind_address(value):
    if value == '0.0.0.0':
        return value
    try:
        return local_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Use a local IPv4 address or 0.0.0.0') from exc


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true', help='Isolated fictional collection, no device connection')
    mode.add_argument('--emulator', action='store_true', help='Developer mode: show emulator preset, default to 127.0.0.1 / HTTP 12113')
    parser.add_argument('--port', type=int, default=8091)
    parser.add_argument('--host', type=bind_address, default='127.0.0.1',
                        help='Web bind IPv4 (default: 127.0.0.1); 0.0.0.0 exposes control to the trusted LAN')
    parser.add_argument('--device', type=local_address, help='Initial player IPv4; otherwise enter its address in the browser')
    parser.add_argument('--tcp-port', type=int, default=12100)
    parser.add_argument('--http-port', type=int, help='Override device HTTP port (default: 12103, or 12113 with --emulator)')
    parser.add_argument('--data-dir', type=Path, default=Path.home() / '.local/share/disc-web',
                        help='Private local Library directory, separate from Assistant storage')
    args = parser.parse_args(argv)
    if args.emulator and args.device is None:
        args.device = '127.0.0.1'
    if args.http_port is None:
        args.http_port = 12113 if args.emulator else 12103
    return args


def main():
    args = parse_args()
    device = Demo() if args.demo else Device(DeviceConfig(args.device or '127.0.0.1', args.tcp_port, args.http_port),
                                           configured=args.device is not None)
    with device, Server((args.host, args.port), device, args.data_dir.expanduser(), emulator=args.emulator) as server:
        display_host = '127.0.0.1' if args.host == '0.0.0.0' else args.host
        print(f'DISC Web: http://{display_host}:{server.server_port} · {"isolated demo" if args.demo else "disconnected; connect in browser"}', flush=True)
        if args.host != '127.0.0.1':
            print(f'Listening on {args.host}:{server.server_port}. Trusted network only: no user authentication.', flush=True)
        if args.host == '0.0.0.0':
            for address in sorted({row['address'] for row in interfaces()}):
                print(f'LAN: http://{address}:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
