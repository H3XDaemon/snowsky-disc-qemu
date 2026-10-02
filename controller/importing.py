"""One-shot audio transfer and observed scan lifecycle on a persistent owner."""
from pathlib import Path, PurePosixPath
import time

from controller.compatibility import require_client
from controller.fiio_http import HTTPClient, sd_path
from controller.fiio_link import frame

AUDIO_EXTENSIONS = frozenset({'.flac', '.wav', '.mp3', '.m4a', '.aac', '.ogg', '.ape', '.wma', '.dsf', '.dff'})


def upload(config, client, source, destination, *, on_progress=None):
    sd_path(destination, child=True)
    if PurePosixPath(destination).suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError('unsupported audio filename extension')
    size = Path(source).stat().st_size
    require_client(client, 'audio_import')
    client.wait_for_mutation()
    http = HTTPClient(config.host, config.http_port, config.timeout)

    def dispatch():
        client.scan_guard()
        if client.mutation_attempted:
            raise RuntimeError('upload replay refused')
        client.pacer.attempted()
        client.mutation_attempted = True
        client.attempted_phases.add('selection')

    try:
        http.upload(source, destination, before_send=dispatch, on_progress=on_progress)
    except FileExistsError:
        if client.mutation_attempted:
            raise
        return {'status': 'not_sent', 'mutation_attempted': False, 'outcome': 'destination_exists'}
    progress = http.progress(destination)
    if (not isinstance(progress, dict) or progress.get('now_size') != size
            or progress.get('percentage') != 1):
        raise ValueError('completed byte count not confirmed; upload was not retried')
    parent, name = str(PurePosixPath(destination).parent), PurePosixPath(destination).name
    offset = 0
    for _ in range(100):
        page = http.directory(parent, offset)
        if any(row.get('name') == name and row.get('is_dir') is False for row in page['items']):
            client.scan_guard()
            return {'status': 'confirmed', 'mutation_attempted': True, 'outcome': 'audio_uploaded',
                    'confirmation': {'bytes': size, 'destination': destination}}
        offset += len(page['items'])
        if not page['items'] or page['total'] is None or offset >= page['total']:
            break
    raise ValueError('uploaded file not observed in directory; upload was not retried')


def scan(client, *, timeout=300, on_progress=None):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 1800:
        raise ValueError('scan timeout must be in 1..1800 seconds')
    require_client(client, 'library_scan')
    client.wait_for_mutation()
    client.scan_guard()
    client.socket.sendall(frame('0622', '0000'))
    deadline, started, count = time.monotonic() + timeout, False, 0
    while time.monotonic() < deadline:
        try:
            tag, payload = client.event(timeout=max(.001, deadline - time.monotonic()))
        except TimeoutError:
            break
        if tag == 'a60a' and int(payload, 16) == 15:
            started = True
        elif tag == 'a622' and started:
            count = int(payload, 16)
            if on_progress:
                on_progress(count)
        elif tag == 'a60a' and int(payload, 16) == 5 and started:
            return {'status': 'confirmed', 'mutation_attempted': True, 'outcome': 'scan_ended',
                    'confirmation': {'discovered': count}}
    raise TimeoutError('scan completion not observed; scan was not restarted')
