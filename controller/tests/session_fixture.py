"""Synthetic wire peer for Controller session tests; no firmware/application imports."""
import json
import socket
import socketserver
import threading
import time
from controller.fiio_link import Frames, frame
from controller.fiio_settings import SETTINGS, setting_command, setting_value


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        with server.lock:
            server.accepts += 1
            server.connections.add(self.request)
        decoder = Frames()
        try:
            while data := self.request.recv(65536):
                for tag, payload in decoder.feed(data):
                    server.tags.append(tag)
                    if tag == '0599':
                        result, body = 'a599', b'0306'
                    elif tag == '0501':
                        result, body = 'a501', json.dumps({'soc_version': server.version, 'currentVolume': server.volume}).encode()
                    elif tag in ('064a', '0712', '0603', '0813'):
                        name = next(name for name in server.sound if SETTINGS[name][0] == tag)
                        result, body = 'a' + tag[1:], setting_command(name, server.sound[name])[1].encode()
                    elif tag in ('0649', '0713', '0653', '0812'):
                        server.writes += 1
                        if server.drop_write:
                            self.request.shutdown(socket.SHUT_RDWR)
                            return
                        name = next(name for name in server.sound if SETTINGS[name][1] == tag)
                        if not server.ignore_sound_write:
                            server.sound[name] = setting_value(name, payload)
                        continue
                    elif tag == '0105':
                        result, body = 'a102', f'{server.mode:04X}'.encode()
                    elif tag == '0102':
                        server.mode = int(payload, 16)
                        server.writes += 1
                        result, body = 'a102', payload
                    elif tag == '0622':
                        server.writes += 1
                        if server.drop_write:
                            self.request.shutdown(socket.SHUT_RDWR)
                            return
                        self.request.sendall(frame('a60a', '000F'))
                        self.request.sendall(frame('a622', '0003'))
                        if server.delay_tag == '0622':
                            server.release_reply.wait(2)
                        result, body = 'a60a', b'0005'
                    elif tag == '0202':
                        if server.silent_now:
                            continue
                        result, body = 'a202', json.dumps(server.state).encode()
                    elif tag == '0103':
                        server.writes += 1
                        if server.drop_write:
                            self.request.shutdown(socket.SHUT_RDWR)
                            return
                        if server.state['state'] == 1:
                            continue
                        result, body = 'a103', f'{int(payload, 16) // 1000 * 1000:08X}'.encode()
                    elif tag in ('0104', '0502'):
                        server.writes += 1
                        if server.drop_write:
                            self.request.shutdown(socket.SHUT_RDWR)
                            return
                        if tag == '0104':
                            server.state['love'] = bool(int(payload, 16))
                            result, body = 'a202', json.dumps(server.state).encode()
                        else:
                            server.volume = int(payload, 16)
                            continue
                    elif tag == '0201':
                        server.writes += 1
                        if server.drop_write:
                            self.request.shutdown(socket.SHUT_RDWR)
                            return
                        server.state['state'] = 1 - server.state['state']
                        result, body = 'a202', json.dumps({'state': server.state['state']}).encode()
                    else:
                        raise AssertionError(tag)
                    if tag == server.delay_tag:
                        server.release_reply.wait(2)
                    self.request.sendall(frame(result, body))
        except (OSError, ConnectionError):
            pass
        finally:
            with server.lock:
                server.connections.discard(self.request)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.lock = threading.Lock()
        self.connections = set()
        self.accepts, self.writes = 0, 0
        self.mode = 0
        self.volume = 30
        self.version = 257
        self.sound = {'gain': 0, 'balance': 0, 'filter': 0, 'dre': 0}
        self.ignore_sound_write = False
        self.tags = []
        self.state = {'love': False, 'state': 0, 'playerflag': 7, 'song': {'song_name': 'Track',
                      'song_artist_name': 'Artist', 'song_album_name': 'Album', 'pos_id': 1}}
        self.drop_write, self.silent_now, self.delay_tag = False, False, None
        self.release_reply = threading.Event()
        self.worker = threading.Thread(target=self.serve_forever, daemon=True)
        self.worker.start()

    def push(self, tag, payload):
        with self.lock:
            for connection in list(self.connections):
                connection.sendall(frame(tag, payload))

    def disconnect(self):
        with self.lock:
            for connection in list(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        self.release_reply.set()
        self.disconnect()
        self.shutdown()
        self.server_close()
        self.worker.join(1)


def until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('condition did not become true')
