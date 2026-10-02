"""Assistant controls, native type-7 queue and natural EOF on disposable V2.57."""
import argparse
import asyncio
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import tempfile
import time

from controller.fiio_link import Client as BaseClient
from controller.fiio_http import HTTPClient
from experiments.disc_assistant.assistant.config import Config
from experiments.disc_assistant.assistant.controls import execute as control
from experiments.disc_assistant.assistant.nlu.intents import ControlIntent
from experiments.disc_assistant.assistant.playback import execute
from experiments.disc_assistant.assistant.queue import observe as queue_observe
from experiments.disc_assistant.assistant.session import sync
from library.store import Store
from tests.fixtures.fixture import generate, NAMES
from tests.integration.scan_cancel_check import scan
from tests.integration.track_end_check import observe
from tests.integration.track_end_trace import validate
from tests.integration.remote_control import flush
from research.diagnostics.player_memory import PlayerMemory

LONG_ALBUM = 'Assistant Confirmation Anniversary Edition'


class Client(BaseClient):
    """Test-only initial connection readiness; never retry an established session."""
    def __init__(self, *args, **kwargs):
        deadline = time.monotonic() + 10
        while True:
            try:
                super().__init__(*args, **kwargs)
                return
            except ConnectionRefusedError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)


def fixtures(directory):
    wav = generate(directory)
    for name in ('A', 'B', 'C'):
        subprocess.run(['sox', str(wav), '--add-comment', 'ARTIST=Assistant CI',
                        '--add-comment', 'ALBUM=Assistant EOF',
                        str(Path(directory) / (name + '.flac')), 'trim', '0', '6'], check=True)
    for name in ('Confirmation A', 'Confirmation B'):
        subprocess.run(['sox', str(wav), '--add-comment', 'ARTIST=Confirmation CI',
                        '--add-comment', 'ALBUM=' + LONG_ALBUM,
                        str(Path(directory) / (name + '.flac'))], check=True)


async def eof():
    with Client(timeout=2) as client:
        assert client.handshake() == '0306'
        assert client.device_setting('gapless') == 0
        assert client.device_setting('folder_jump') == 0
        http = HTTPClient(port=12103)
        rows = http.catalog('artist/album/song', artist='Assistant CI', album='Assistant EOF')['items']
        order = [r['name'] for r in rows]
        assert len(order) == 3
        for mode in range(5):
            client.set_play_mode(mode)
            assert client.play_mode() == mode
            await asyncio.sleep(2.1)
            await flush(client)
            start = 2 if mode == 3 else 1
            client.play_artist('Assistant CI', start, album='Assistant EOF', http=http)
            events = await observe(client, mode)
            positions = validate(events, mode, start, order)
            print(f'PASS: type-7 native EOF mode={mode}, positions={positions}', flush=True)


def persistent(config, store, ranking, short_ranking, long_ranking):
    from experiments.disc_assistant.assistant.live import DeviceSession, LiveSocket
    from unittest.mock import patch
    writes = []
    original = LiveSocket.sendall
    def record(socket, data):
        if data[:4] in (b'0100', b'0101', b'0102', b'0201'):
            writes.append(data[:4])
        return original(socket, data)

    def wait(predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.1)
        raise AssertionError('persistent-session observation timed out')

    with patch.object(LiveSocket, 'sendall', record), DeviceSession(config, health_interval=1) as session:
        session.connect()
        assert session.wait_ready(40), session.status()
        initial = session.client
        with session.operation() as client:
            refreshed = sync(config, store, shared=client, reuse_unchanged=True)
            assert refreshed['generation'] == ranking['generation']
            result = execute(replace(config, continuous_context=True), store, ranking, shared=client)
            assert result['status'] == 'playing', result
        from tests.integration.session_check import check_session
        selected = ranking['candidates'][0]
        check_session(session, artist=selected['artist'], album=selected['album'], index=result['fresh_position'])
        assert session.client is initial
        with session.operation() as client:
            result = execute(config, store, long_ranking, shared=client)
            assert result['status'] == 'playing', result
            assert result['queue']['mark'] == result['fresh_position'], result
        reported_album = result['state']['song']['song_album_name']
        assert reported_album and LONG_ALBUM.startswith(reported_album), result
        selected = long_ranking['candidates'][0]
        from controller.models import OperationStatus
        confirmed = session.play_artist(selected['artist'], album=LONG_ALBUM, index=result['fresh_position'])
        assert confirmed.status == OperationStatus.PLAYING, confirmed
        print(f'PASS: long album selection via Assistant and Controller; observed album={reported_album!r}', flush=True)
        with session.operation() as client:
            result = execute(replace(config, continuous_context=True), store, short_ranking, shared=client)
            assert result['status'] == 'playing', result
        title = result['state']['song']['song_name']
        wait(lambda: session.status()['observation']['state'].get('song', {}).get('song_name') != title)
        assert session.client is initial
        before = len(writes)
        initial.close()  # Test-only transport loss, without a playback mutation.
        wait(lambda: session.status()['connection'] == 'ready' and session.client is not initial, 40)
        assert len(writes) == before, writes
        with session.operation() as client:
            assert queue_observe(config, shared=client)['queue']['total'] == 3
        print('PASS: persistent sync/control/queue share one socket; idle EOF pushes and observation-only reconnect', flush=True)
        with session.operation() as client:
            client.begin_phase('mode')
            client.set_play_mode(4)
            assert client.play_mode() == 4
        with session.operation() as client:
            result = execute(config, store, short_ranking, shared=client)
            assert result['status'] == 'playing', result
        wait(lambda: session.status()['observation']['playback'] == 'stopped')
        final_client = session.client
        with session.operation() as client:
            observed = queue_observe(config, shared=client)
            assert not observed['queue']['playback_known']
        assert session.client is final_client and session.status()['connection'] == 'ready'
        session.disconnect()
        before = len(writes)
        time.sleep(1.5)
        assert session.status()['connection'] == 'disconnected' and len(writes) == before
        print('PASS: final EOF preserves connection despite silent 0202; explicit disconnect stays disconnected', flush=True)


def exercise(persistent_only=False):
    assert os.environ.get('CI_DISPOSABLE') == '1'
    assert os.environ.get('FW_VERSION') == '2.57'
    with Client() as client, PlayerMemory(Path('/work/rootfs'), '2.57') as memory:
        assert client.handshake() == '0306'
        asyncio.run(scan(client, memory))
    time.sleep(1)  # Stock listener reopens asynchronously after disconnect.
    with tempfile.TemporaryDirectory(prefix='assistant-check-') as tmp, Store(tmp) as store:
        config = Config('generated', '127.0.0.1', 12100, 12103, Path(tmp), 'localhost', 8108, 'http', 'UNUSED', {}, page_size=1)
        from unittest.mock import patch
        # Only test orchestration waits for the stock listener's readiness.
        with patch('experiments.disc_assistant.assistant.session.Client', Client):
            head = sync(config, store)
        time.sleep(1)
        documents = store.documents(head['generation'])
        assert len(documents) == 8
        target = next(d for d in documents if d['title'] == NAMES[2])
        ranking = {'generation': head['generation'], 'candidates': [dict(target, track_id=target['id'], kind='track')]}
        if persistent_only:
            short = next(d for d in documents if d['artist'] == 'Assistant CI')
            short_ranking = {'generation': head['generation'], 'candidates': [dict(short, track_id=short['id'], kind='track')]}
            long = next(d for d in documents if d['album'] == LONG_ALBUM)
            long_ranking = {'generation': head['generation'], 'candidates': [dict(long, track_id=long['id'], kind='track')]}
            persistent(config, store, ranking, short_ranking, long_ranking)
            return
        started = execute(replace(config, continuous_context=True), store, ranking)
        assert started['status'] == 'playing', started
        assert started['queue']['mode'] == 3 and started['queue']['total'] == 2, started
        time.sleep(1)
        for action, status in [('pause', 'confirmed'), ('pause', 'already_satisfied'),
                               ('resume', 'confirmed'), ('resume', 'already_satisfied'),
                               ('stop', 'confirmed'), ('stop', 'already_satisfied'),
                               ('resume', 'confirmed'), ('next', 'confirmed')]:
            time.sleep(1)
            result = control(config, ControlIntent(action))
            assert result['status'] == status, result
        print('PASS: Assistant selection/queue, pause/resume/stop and next on stock firmware', flush=True)
        # Assistant previous selects the preceding row on both sides of the native threshold.
        time.sleep(1)
        started = execute(config, store, ranking)
        assert started['status'] == 'playing', started
        time.sleep(1)
        previous = control(config, ControlIntent('previous'))
        assert previous['status'] == 'confirmed' and previous['outcome'] == 'track_changed', previous
        time.sleep(1)
        started = execute(config, store, ranking)
        assert started['status'] == 'playing', started
        time.sleep(1)
        with Client() as client:
            assert client.handshake() == '0306'
            client.seek(12000)
            time.sleep(1.2)
        time.sleep(1)
        previous = control(config, ControlIntent('previous'))
        assert previous['status'] == 'confirmed' and previous['outcome'] == 'track_changed', previous
        print('PASS: previous selects the preceding queue row before and after twelve seconds', flush=True)
        time.sleep(1)
        observed = queue_observe(config)
        assert observed['queue']['total'] == 2
        # Native playback continues after the Assistant's short-lived connection closes.
        short = next(d for d in documents if d['artist'] == 'Assistant CI')
        short_ranking = {'generation': head['generation'], 'candidates': [dict(short, track_id=short['id'], kind='track')]}
        time.sleep(1)
        initial = execute(replace(config, continuous_context=True), store, short_ranking)
        assert initial['status'] == 'playing', initial
        time.sleep(7)
        after = queue_observe(config)
        assert after['queue']['mode'] == 3
        assert after['queue']['state']['song']['song_name'] != initial['queue']['state']['song']['song_name'], after
        print('PASS: native queue advances while Assistant is disconnected', flush=True)
    time.sleep(1)
    asyncio.run(eof())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures')
    parser.add_argument('--persistent-only', action='store_true')
    args = parser.parse_args()
    fixtures(args.fixtures) if args.fixtures else exercise(args.persistent_only)
