"""Disposable desktop acceptance: real controller HTTP/TCP, CLI, SDK and Typesense.

Run with the prototype venv: python -m experiments.disc_assistant.check.
Uses generated metadata servers, random loopback ports and a disposable Compose
project/volume. Never connects to DISC, resets its catalog or touches its files.
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote
from uuid import uuid4

import aiohttp
import typesense

from controller.fiio_link import Frames, frame
from library.tests.helpers import Catalog, TRACKS

ROOT = Path(__file__).resolve().parents[2]


class LinkHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.accepts += 1
        frames = Frames()
        while data := self.request.recv(4096):
            for tag, payload in frames.feed(data):
                if tag == '0599':
                    self.server.handshakes += 1
                    self.request.sendall(frame('a599', '0306'))
                elif tag == '0501':
                    self.request.sendall(frame('a501', '{"soc_version":257}'))
                elif tag == '0105':
                    self.request.sendall(frame('a102', f'{self.server.mode:04X}'))
                elif tag == '0102':
                    self.server.mode = int(payload, 16)
                    self.server.mutations += 1
                elif tag in ('0100', '0101'):
                    prefix = 8 if tag == '0100' else 4
                    assert payload[prefix-4:prefix] == b'0007'
                    selector = json.loads(payload[prefix:])
                    scope = [t for t in TRACKS if t.artist == selector['artist'] and
                             (not selector['album'] or t.album == selector['album'])]
                    index = int(payload[:4], 16) if tag == '0100' else 0
                    self.server.selected = scope[index]
                    self.server.queue, self.server.index, self.server.state = scope, index, 0
                    self.server.mutations += 1
                elif tag == '0201':
                    action = int(payload, 16)
                    self.server.mutations += 1
                    if action == 0:
                        self.server.state = 1 - self.server.state
                    else:
                        self.server.index = (self.server.index + (1 if action == 1 else -1)) % len(self.server.queue)
                        self.server.selected = self.server.queue[self.server.index]
                elif tag == '0202':
                    selected = self.server.selected
                    snapshot = {} if selected is None else {'state': self.server.state, 'playerflag': 7,
                        'song': {'song_name': selected.title, 'song_artist_name': selected.artist,
                                 'song_album_name': selected.album, 'pos_id': self.server.index + 1}}
                    self.request.sendall(frame('a202', json.dumps(snapshot, ensure_ascii=False)))
                else:
                    raise AssertionError(f'Unexpected device command: {tag}')


class CatalogHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != '/song_category_tree/':
            self.send_error(404)
            return
        filters = {key: unquote(self.headers[key]) for key in ('album', 'artist') if key in self.headers}
        offset, limit = int(self.headers['start-pos']), int(self.headers['num-max'])
        if self.headers['type'] == 'curlist/song':
            rows = [dict(pos=i, name=t.title, author=t.artist) for i, t in enumerate(self.server.link.queue)]
            page = {'items': rows[offset:offset+limit], 'total': len(rows), 'mark': self.server.link.index}
        else:
            page = Catalog().catalog(self.headers['type'], offset, limit, **filters)
        body = json.dumps(page['items'], ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('total-num', str(page['total']))
        if 'mark' in page:
            self.send_header('mark-pos', str(page['mark']))
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


async def main():
    project = 'disc-prototype-check-' + uuid4().hex[:10]
    env = {**os.environ, 'TYPESENSE_API_KEY': secrets.token_hex(32), 'TYPESENSE_PORT': '0'}
    compose = ['docker', 'compose', '--env-file', '/dev/null', '-f',
               str(ROOT / 'experiments/disc_assistant/assistant/compose.yaml'), '-p', project]

    def docker(*args):
        return subprocess.run(compose + list(args), env=env, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    sdk = None
    try:
        docker('up', '-d', '--pull', 'never')
        host, port = docker('port', 'typesense', '8108').strip().rsplit(':', 1)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as http:
            deadline = time.monotonic() + 45
            while True:
                try:
                    async with http.get(f'http://{host}:{port}/health') as response:
                        if response.status == 200 and (await response.json()).get('ok'):
                            break
                except (aiohttp.ClientError, TimeoutError):
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError('Typesense readiness timed out')
                await asyncio.sleep(0.5)
        sdk = typesense.AsyncClient({'api_key': env['TYPESENSE_API_KEY'], 'nodes': [
            {'host': host, 'port': int(port), 'protocol': 'http'}], 'num_retries': 0,
            'connection_timeout_seconds': 3})
        with tempfile.TemporaryDirectory(prefix='disc-prototype-') as tmp, \
                socketserver.ThreadingTCPServer(('127.0.0.1', 0), LinkHandler) as link, \
                ThreadingHTTPServer(('127.0.0.1', 0), CatalogHandler) as catalog:
            link.selected, link.mutations = None, 0
            link.accepts, link.handshakes = 0, 0
            link.queue, link.index, link.state = [], 0, 0
            link.mode = 0
            catalog.link = link
            threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (link, catalog)]
            for thread in threads:
                thread.start()
            try:
                config = Path(tmp) / 'config.toml'
                config.write_text(f'''[device]
key = "synthetic"
host = "127.0.0.1"
tcp_port = {link.server_address[1]}
http_port = {catalog.server_address[1]}
[storage]
data_dir = "{tmp}/data"
[typesense]
host = "{host}"
port = {port}
[sync]
page_size = 2
[aliases.artists]
"Linkin Park" = ["линкин парк"]
[aliases.titles]
"Numb" = ["намб"]
''')
                def cli(*args, success=True):
                    result = subprocess.run([sys.executable, '-m', 'experiments.disc_assistant.assistant',
                        '--config', str(config), *args], cwd=ROOT, env=env, text=True, capture_output=True)
                    if success:
                        assert result.returncode == 0, result.stderr
                        return json.loads(result.stdout)
                    assert result.returncode != 0, result.stdout
                    return result.stderr

                snapshot = cli('sync')
                assert snapshot['track_count'] == 7
                assert not cli('status')['index_current']
                cli('search', 'Numb', success=False)
                cli('index')
                assert cli('status')['index_current']
                print('PASS: controller transports -> paginated import -> SQLite -> SDK index', flush=True)
                queries = [('Numb', 3), ('Linkin Park Numb', 2), ('Linkn Park Numb', 2),
                           ('линкин парк намб', 2), ('Meteora Numb', 1), ('Тишина', 1),
                           ('Cue entry', 2), ('tishina', 1), ('albom tishina', 1), ('Linkin Park DefinitelyMissing', 0)]
                for query, expected in queries:
                    found = cli('search', query)
                    assert found['found'] == expected, (query, found)
                    assert all(candidate['match'] for candidate in found['candidates']), found
                    print(f'PASS: {query!r}: {expected} candidates', flush=True)
                ranked = cli('--language', 'ru', 'rank', 'Включи линкин парк намб')
                assert ranked['candidates'][0]['album'] == 'Meteora', ranked
                assert link.mutations == 0
                fuzzy = cli('--language', 'en', 'rank', 'Play Linkin Park - Numbb')
                assert fuzzy['retrieval']['source'] == 'typesense', fuzzy
                assert fuzzy['candidates'][0]['album'] == 'Meteora', fuzzy
                for phrase, kind, album in [
                        ('Включи линкин парк намб', 'track', 'Meteora'),
                        ('Play Linkin Park - Numb live', 'track', 'Live'),
                        ('Включи Linkin Park', 'artist', None),
                        ('Play Cue entry', 'track', 'Cue Album')]:
                    previous = link.mutations
                    playing = cli('--language', 'ru' if phrase.startswith('Включи') else 'en', 'ask', phrase)
                    assert playing['status'] == 'playing', playing
                    assert playing['selected']['kind'] == kind
                    if album:
                        assert playing['state']['song']['song_album_name'] == album
                    if album == 'Cue Album':
                        assert playing['metadata_equivalent_rows'] == 2
                        assert playing['fresh_position'] == 0
                    assert link.mutations == previous + 1
                    assert playing['queue']['total'] >= 1
                    assert playing['queue']['mode'] == 0
                previous = link.mutations
                assert cli('ask', 'Play Linkin Park - DefinitelyMissing')['status'] == 'not_found'
                assert link.mutations == previous
                print('PASS: exact/fuzzy ranking, best-match track/live/artist/CUE playback, missing request sends nothing', flush=True)
                # Controls do not require search credentials or a current index.
                cli('sync')
                key = env.pop('TYPESENSE_API_KEY')
                try:
                    assert cli('--language', 'ru', 'rank', 'Пауза')['status'] == 'planned'
                    assert cli('queue')['queue']['total'] == 2
                    for phrase, expected in [('Пауза', 'confirmed'), ('Pause', 'already_satisfied'),
                                             ('Resume', 'confirmed'), ('Продолжи', 'already_satisfied'),
                                             ('Next track', 'confirmed'), ('Предыдущий трек', 'confirmed'),
                                             ('Stop', 'confirmed'), ('Стоп', 'already_satisfied')]:
                        previous = link.mutations
                        result = cli('--language', 'en' if phrase[0].isascii() else 'ru', 'ask', phrase)
                        assert result['status'] == expected, result
                        assert link.mutations == previous + (expected == 'confirmed')
                    print('PASS: state-aware controls without search key/current index; repeated pause/resume/stop send nothing', flush=True)
                finally:
                    env['TYPESENSE_API_KEY'] = key
                cli('index')
                config.write_text(config.read_text() + '\n[playback]\ncontinuous_context=true\n')
                previous = link.mutations
                continuous = cli('--language', 'en', 'ask', 'Play Linkin Park')
                assert continuous['mode_change']['status'] == 'confirmed', continuous
                assert continuous['queue']['continuation'] == 'wrap_queue'
                assert link.mutations == previous + 2
                again = cli('ask', 'Play Linkin Park')
                assert again['mode_change']['status'] == 'already_satisfied', again
                assert link.mutations == previous + 3
                print('PASS: paginated native queue, preserved default mode and explicit persistent repeat-list mode', flush=True)
                snapshot = cli('status')
                old = cli('status')
                await sdk.collections[old['collection']].delete()
                cli('search', 'Numb', success=False)
                rebuilt = cli('index')
                assert rebuilt['generation'] == snapshot['generation']
                assert rebuilt['collection'] != old['collection']
                assert cli('search', 'Numb')['found'] == 3
                cli('sync')
                assert not cli('status')['index_current']
                cli('search', 'Numb', success=False)
                cli('index')
                assert cli('search', 'Numb')['found'] == 3
                print('PASS: rebuild from SQLite, sync invalidation and explicit reindex', flush=True)
                # The console owns a SINGLE connection across startup and commands.
                # Remove the projection first: bootstrap must rebuild the missing index.
                prior = cli('status')
                await sdk.collections[prior['collection']].delete()
                accepts, handshakes = link.accepts, link.handshakes
                console = subprocess.run([sys.executable, '-m', 'experiments.disc_assistant.assistant',
                    '--config', str(config), 'start'], cwd=ROOT, env=env, text=True, capture_output=True,
                    input='/language en\n/sync\n/rank Play Linkin Park\nPlay Linkin Park\nPause\nResume\n/queue\n/status\n/exit\n', timeout=90)
                assert console.returncode == 0, console.stderr
                assert '"status": "error"' not in console.stdout, console.stdout
                assert '"status": "uncertain"' not in console.stdout, console.stdout
                assert '"status": "not_sent"' not in console.stdout, console.stdout
                assert 'Startup search preparation unavailable' not in console.stdout, console.stdout
                assert '"status": "playing"' in console.stdout, console.stdout
                assert '"status": "confirmed"' in console.stdout, console.stdout
                assert link.accepts == accepts + 1 and link.handshakes == handshakes + 1
                rebuilt = cli('status')
                assert rebuilt['generation'] == prior['generation']
                assert rebuilt['collection'] != prior['collection']
                again = subprocess.run([sys.executable, '-m', 'experiments.disc_assistant.assistant',
                    '--config', str(config), 'start'], cwd=ROOT, env=env, text=True, capture_output=True,
                    input='/exit\n', timeout=60)
                assert again.returncode == 0 and again.stdout.count('"reused": true') == 2, again.stdout
                assert cli('status')['collection'] == rebuilt['collection']
                print('PASS: persistent start -> sync/index -> console uses one handshake/socket; unchanged snapshot/index reused; missing projection rebuilt', flush=True)
                # Journal evidence survives CLI processes and console exit.
                before = link.mutations
                cli('ask', 'unknown natural command', success=False)
                rejected = cli('history')['requests'][0]
                rejection = cli('history', 'show', rejected['id'])
                assert rejection['status'] == 'error'
                assert rejection['events'][-2]['payload']['category'] == 'unrecognized_or_invalid_command'
                scheduled = cli('--source', 'scheduled', 'rank', 'Pause')
                assert cli('history', 'show', scheduled['request_id'])['source'] == 'scheduled'
                fuzzy_log = cli('history', 'show', fuzzy['request_id'])
                assert any(e['phase'] == 'retrieval' for e in fuzzy_log['events'])
                played_log = cli('history', 'show', continuous['request_id'])
                assert played_log['outcome']['operation_id'] == continuous['operation_id']
                assert any(e['phase'] == 'selection' for e in played_log['events'])
                entries = cli('history', '100')['requests']
                assert any(r['source'] == 'interactive' and r['status'] == 'playing' for r in entries)
                assert any(r['source'] == 'startup' and r['command'] == 'index' for r in entries)
                export = Path(tmp) / 'history.jsonl'
                assert cli('history', 'export', str(export))['exported'] == len(entries)
                assert key not in export.read_text()
                assert cli('history', 'clear', '--yes')['removed'] == len(entries)
                assert cli('history')['requests'] == []
                assert link.mutations == before
                print('PASS: persistent request/search/selection/outcome journal, rejected commands, scheduled origin, export and clear', flush=True)
            finally:
                link.shutdown()
                catalog.shutdown()
                for thread in threads:
                    thread.join(timeout=5)
    finally:
        if sdk:
            await sdk.api_call.aclose()
        docker('down', '--volumes', '--timeout', '10')
        print('Disposable services, temporary catalog and index removed', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
