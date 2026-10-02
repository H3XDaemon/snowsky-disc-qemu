"""Persistent foreground session: one socket reader, serialized operations, no replay."""
from controller.models import WirePlaybackState
from controller.compatibility import Capability, require_client
from collections import deque
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import random
import socket
import threading
import time
from uuid import uuid4

from controller.fiio_link import Frames, frame
from controller.link_commands import ReviewedCommands
from controller.wire import playback_snapshot
from controller.device import MutationGuard, ObservedSocket, MutationPacer
from controller.events import validate_scan_events, merge_snapshot
from controller.models import DeviceConfig, DeviceSnapshot, CommandResult, PlayMode, QueueItem, Track, PlaybackSource
from controller.contracts import ControlAction, CurrentAction
from typing import Any, Callable, Iterator, Self
from types import TracebackType
from contextlib import AbstractContextManager
from controller.wire import WireState
from controller.sound import SoundCommands, SOUND_READ_TAGS, SOUND_WRITE_TAGS


class LiveSocket(ObservedSocket):
    def sendall(self, data: bytes) -> None:
        mutation = data[:4] in (b'0100', b'0101', b'0102', b'0103', b'0201', b'0104', b'0502')
        mutation = mutation or data == frame('0622', '0000') or data[:4] in SOUND_WRITE_TAGS
        if not mutation and data[:4] not in (b'0599', b'0501', b'0105', b'0202', *SOUND_READ_TAGS):
            raise ValueError('command is outside the reviewed persistent-session surface')
        if self.session.closed.is_set():
            raise ConnectionError('session ended; request was not replayed')
        try:
            super().sendall(data)
        except OSError:
            self.session.close()
            raise


class LiveClient(MutationGuard, ReviewedCommands, SoundCommands):
    """Only _receive touches recv; request callers wait on a condition variable."""
    def __init__(self, host: str, port: int, timeout: float) -> None:
        raw = socket.create_connection((host, port), timeout)
        raw.settimeout(.25)
        self.timeout = timeout
        self.closed = threading.Event()
        self.condition = threading.Condition()
        self.requests = threading.Lock()
        self.frames = Frames()
        self.events: deque[tuple[str, bytes]] = deque()
        self.waiting: str | None = None
        self.reply: bytes | None = None
        self.active = False
        self.mutation_attempted = False
        self.mutation_phase = 'selection'
        self.attempted_phases: set[str] = set()
        self.pacer = MutationPacer(closed=self.closed)
        self.handshake_value: str | None = None
        self.state: WireState = {}
        self.position: int | None = None
        self.mode: int | None = None
        self.playback = 'unknown'
        self.scan_active = False
        self.observed_at: float | None = None
        self.zero_progress = False
        self.socket: LiveSocket = LiveSocket(raw, self)
        self.reader = threading.Thread(target=self._receive, daemon=True, name='disc-reader')
        self.reader.start()

    def close(self) -> None:
        self.closed.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        with self.condition:
            self.state, self.position, self.playback = {}, None, 'unknown'
            self.condition.notify_all()

    def handshake(self) -> str:
        if self.handshake_value is None:
            self.handshake_value = self.request('0599', '0000').decode('ascii')
        return self.handshake_value

    def now_playing(self) -> WireState:
        update = playback_snapshot(self.request('0202'))
        if not update:
            return {}
        # a202 can be a state-only push even while a query is pending. The reader
        # has already reduced it with the latest metadata, including loading/EOF.
        with self.condition:
            return deepcopy(self.state)

    def _update(self, tag: str, payload: bytes) -> None:
        self.observed_at = time.time()
        if tag == 'a202':
            update = playback_snapshot(payload)
            if not update:
                return
            old_song = self.state.get('song')
            self.state = merge_snapshot(self.state, update)
            if self.state.get('song') != old_song:
                self.position = None
            if update.get('state') == WirePlaybackState.STOPPED:
                self.playback = 'stopped' if not update.get('song') and self.zero_progress else 'loading'
            elif self.state.get('song') and self.state.get('state') in (WirePlaybackState.PLAYING, WirePlaybackState.PAUSED):
                self.playback = 'playing' if self.state['state'] == WirePlaybackState.PLAYING else 'paused'
            else:
                self.playback = 'unknown'
            self.zero_progress = False
        elif tag == 'a103':
            self.position = int(payload, 16)
            self.zero_progress = self.position == 0
        elif tag == 'a102':
            self.mode = int(payload, 16)
        elif tag == 'a622':
            self.scan_active = True
        elif tag == 'a60a':
            value = int(payload, 16)
            if value == 15:
                self.scan_active = True
            elif value == 5:
                self.scan_active = False

    def _receive(self) -> None:
        try:
            while not self.closed.is_set():
                try:
                    data = self.socket.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                for tag, payload in self.frames.feed(data):
                    with self.condition:
                        self._update(tag, payload)
                        if self.waiting == tag and self.reply is None:
                            self.reply = payload
                        elif self.active:
                            if len(self.events) >= 10000:
                                raise ValueError('operation event budget exhausted')
                            self.events.append((tag, payload))
                        self.condition.notify_all()
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            self.close()

    def request(self, tag: str, payload: bytes | str = b'', *, expected: str | None = None) -> bytes:
        expected = expected or 'a' + tag[1:].lower()
        with self.requests:
            with self.condition:
                if self.closed.is_set():
                    raise ConnectionError('device disconnected')
                self.waiting, self.reply = expected, None
                try:
                    self.socket.sendall(frame(tag, payload))
                    deadline = time.monotonic() + self.timeout
                    while self.reply is None and not self.closed.is_set():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            # a202 is also unsolicited and can be silent at final EOF.
                            # Other late replies cannot be safely reused: retire this
                            # connection, then let the owner reconnect for observation.
                            if expected != 'a202':
                                self.close()
                            raise TimeoutError(f'no {expected} reply')
                        self.condition.wait(remaining)
                    if self.closed.is_set():
                        raise ConnectionError('device disconnected during request')
                    assert self.reply is not None
                    return self.reply
                finally:
                    self.waiting, self.reply = None, None

    def begin_operation(self, timeout: float) -> None:
        with self.condition:
            if self.closed.is_set():
                raise ConnectionError('device disconnected before operation')
            self.timeout = timeout
            self.active = True
            self.events.clear()
            # A scan observed while idle must also block later selection/sync.
            if self.scan_active:
                self.events.append(('a60a', b'000F'))
            self.mutation_attempted = False
            self.mutation_phase = 'selection'
            self.attempted_phases = set()

    def end_operation(self) -> None:
        with self.condition:
            self.active = False
            self.events.clear()

    def event(self, timeout: float | None = None) -> tuple[str, bytes]:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        with self.condition:
            while not self.events and not self.closed.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('no event')
                self.condition.wait(remaining)
            if self.closed.is_set():
                raise ConnectionError('device disconnected')
            return self.events.popleft()

    def take_events(self) -> list[tuple[str, bytes]]:
        with self.condition:
            events = list(self.events)
            self.events.clear()
            return events

    def scan_guard(self) -> None:
        with self.condition:
            if self.closed.is_set():
                raise ConnectionError('device disconnected')
            validate_scan_events(self.take_events())
            if self.scan_active:
                raise ValueError('observed library scan activity; wait for completion')

    def view(self) -> dict[str, Any]:
        with self.condition:
            return {'playback': self.playback, 'state': deepcopy(self.state),
                    'position_ms': self.position, 'mode': self.mode,
                    'scan_active': self.scan_active, 'observed_at': self.observed_at}


class DiscSession:
    """Own a connection until explicit disconnect/exit; commands never wait for recovery."""
    def __init__(self, config: DeviceConfig, *, ownership: AbstractContextManager[Any] | None = None,
                 client_factory: Callable[[str, int, float], LiveClient] = LiveClient,
                 backoff: float = .5, health_interval: float = 30) -> None:
        self.config, self.client_factory = config, client_factory
        self.ownership = ownership
        self.backoff, self.health_interval = backoff, health_interval
        self.guard = threading.Condition()
        self.operations = threading.Lock()
        self.shutdown = threading.Event()
        self.enabled = False
        self.client: LiveClient | None = None
        self.generation = 0
        self.connection = 'disconnected'
        self.last_error: str | None = None

    def __enter__(self) -> Self:
        self.owner = self.ownership if self.ownership is not None else nullcontext()
        self.owner.__enter__()
        self.worker = threading.Thread(target=self._run, daemon=True, name='disc-session')
        self.worker.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.shutdown.set()
        self.disconnect()
        self.worker.join(self.config.timeout * 4 + 2)
        self.owner.__exit__(exc_type, exc, traceback)

    def connect(self) -> None:
        with self.guard:
            self.enabled = True
            self.guard.notify_all()

    def disconnect(self) -> None:
        with self.guard:
            self.enabled = False
            self.generation += 1
            if self.client:
                self.client.close()
            self.client = None
            self.connection = 'disconnected'
            self.guard.notify_all()

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self.guard:
            while self.connection != 'ready' and self.enabled:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.guard.wait(remaining)
            return self.connection == 'ready'

    def status(self) -> dict[str, Any]:
        with self.guard:
            ready = self.client is not None and not self.client.closed.is_set() and self.connection == 'ready'
            return {'connection': self.connection if ready or self.connection != 'ready' else 'reconnecting',
                    'enabled': self.enabled, 'generation': self.generation, 'last_error': self.last_error,
                    'observation': self.client.view() if ready and self.client is not None else {'playback': 'unknown', 'state': {}}}

    def snapshot(self) -> DeviceSnapshot:
        """Immutable normalized observations; no network request or device mutation."""
        return DeviceSnapshot.from_status(self.status())

    def _perform(self, action: str, callback: Callable[[LiveClient], Any], *, expected_generation: int | None = None) -> CommandResult:
        client = None
        operation_id = uuid4().hex
        try:
            with self.operation(expected_generation=expected_generation) as client:
                result = callback(client)
                if isinstance(result, CommandResult):
                    from dataclasses import replace
                    from controller.models import OperationStatus
                    return (replace(result, status=OperationStatus.UNCERTAIN,
                                    reason='connection lost during operation; no replay')
                            if client.closed.is_set() and result.mutation_attempted else result)
                result.setdefault('operation_id', operation_id)
                if client.closed.is_set() and result.get('mutation_attempted'):
                    result.update(status='uncertain', reason='connection lost during operation; no replay')
        except (OSError, ValueError, RuntimeError) as exc:
            attempted = bool(client and client.mutation_attempted)
            result = {'operation_id': operation_id, 'status': 'uncertain' if attempted else 'not_sent',
                      'mutation_attempted': attempted, 'reason': str(exc)}
            from controller.catalog import CatalogChanged
            if isinstance(exc, CatalogChanged) and exc.diagnostics is not None:
                result['confirmation'] = {'queue': exc.diagnostics}
        return CommandResult.from_result(result, action)

    def control(self, action: ControlAction) -> CommandResult:
        """State-aware pause/resume/next/previous. No native stop is claimed."""
        from controller.operations import playback_control
        if action not in ('pause', 'resume', 'next', 'previous'):
            raise ValueError('unsupported device control action')
        return self._perform(action, lambda client: playback_control(client, action, timeout=self.config.timeout))

    def current_track(self) -> CommandResult:
        return self._current('now_playing')

    def set_favorite(self, favorite: bool) -> CommandResult:
        if type(favorite) is not bool:
            raise ValueError('favorite must be a boolean')
        return self._current('like' if favorite else 'dislike')

    def set_volume(self, value: int) -> CommandResult:
        return self._current('volume', value=value)

    def adjust_volume(self, delta: int) -> CommandResult:
        return self._current('volume', delta=delta)

    def sound_settings(self, *, expected_generation: int | None = None) -> CommandResult:
        """Fresh reviewed sound values. Unknown firmware has no inherited support."""
        from controller.sound import read_settings
        return self._perform('sound_settings', read_settings, expected_generation=expected_generation)

    def set_sound_setting(self, name: str, value: int, *, expected: int,
                          expected_generation: int | None = None) -> CommandResult:
        """One validated setting change, fresh displayed-value check and readback."""
        from controller.sound import validate, change_setting
        validate(name, value)
        validate(name, expected)
        return self._perform('sound_setting', lambda client: change_setting(
            client, name, value, expected, self.config.timeout), expected_generation=expected_generation)

    def _current(self, action: CurrentAction, *, value: int | None = None,
                 delta: int | None = None) -> CommandResult:
        from controller.operations import current_track
        return self._perform(action, lambda client: current_track(client, action,
            value=value, delta=delta, timeout=self.config.timeout))

    def pause(self) -> CommandResult:
        return self.control('pause')

    def resume(self) -> CommandResult:
        return self.control('resume')

    def next_track(self) -> CommandResult:
        return self.control('next')

    def previous_track(self) -> CommandResult:
        return self.control('previous')

    def previous_in_queue(self) -> CommandResult:
        """Select the preceding queue row; never use the native restart shortcut."""
        from controller.fiio_http import HTTPClient
        from controller.queue import previous_in_queue
        return self._perform('previous', lambda client: previous_in_queue(self.config, client,
            HTTPClient(self.config.host, self.config.http_port, self.config.timeout)))

    def set_play_mode(self, mode: PlayMode | str) -> CommandResult:
        from controller.controls import set_mode
        from controller.models import PlayMode
        mode = PlayMode(mode)
        return self._perform('set_play_mode', lambda client: set_mode(client, mode))

    def queue(self) -> CommandResult:
        from controller.fiio_http import HTTPClient
        from controller.queue import snapshot
        def read(client: LiveClient) -> dict[str, Any]:
            http = HTTPClient(self.config.host, self.config.http_port, self.config.timeout)
            return {'status': 'observed', 'queue': snapshot(self.config, client, http)}
        return self._perform('queue', read)

    def play_artist(self, artist: str, *, album: str | None = None, index: int | None = None,
                    expected: tuple[QueueItem, ...] | None = None) -> CommandResult:
        """Fresh named artist/album context or zero-based track; preserve play mode."""
        from controller.fiio_http import HTTPClient
        from controller.fiio_library import artist_command
        from controller.catalog import CatalogReader, CatalogChanged, verify_expected
        from controller.playback import GuardedHTTP, verify_playing
        from controller.queue import snapshot
        def select(client: LiveClient) -> dict[str, Any]:
            artist_command(artist, index, album)
            client.wait_for_mutation()
            http = HTTPClient(self.config.host, self.config.http_port, self.config.timeout)
            reader = CatalogReader(http, page_size=self.config.page_size, max_tracks=self.config.max_tracks,
                                   max_requests=self.config.max_requests)
            category = 'artist/song' if album is None else 'artist/album/song'
            filters = {'artist': artist, **({'album': album} if album is not None else {})}
            rows = reader.rows(category, **filters)
            if not rows or rows != reader.rows(category, **filters):
                raise CatalogChanged('playback source is empty or changing')
            verify_expected(rows, expected)
            position = 0 if index is None else index
            if position >= len(rows):
                raise ValueError('position outside current source')
            selected = {'kind': 'artist' if index is None else 'track', 'artist': artist,
                        'album': album, 'title': rows[position]['name']}
            client.scan_guard()
            guard = GuardedHTTP(http, category, filters, rows, position, client)
            client.play_artist(artist, index, album=album, http=guard)
            state = verify_playing(client, selected, rows, self.config.timeout, config=self.config, http=http)
            result = {'status': 'playing' if state else 'uncertain', 'mutation_attempted': True, 'state': state}
            if state:
                result['queue'] = snapshot(self.config, client, http, expected=rows, selected=selected,
                                           selected_position=index)
            else:
                result['reason'] = 'playback not confirmed; selection was not retried'
            return result
        return self._perform('play_artist', select)

    def play_album(self, album: str, *, index: int | None = None,
                   expected: tuple[QueueItem, ...] | None = None) -> CommandResult:
        """Play all artists in a named native album; verify its complete queue."""
        from controller.fiio_http import HTTPClient
        from controller.fiio_library import album_command
        from controller.catalog import CatalogReader, CatalogChanged, verify_expected
        from controller.playback import GuardedHTTP, verify_playing
        from controller.queue import snapshot
        def select(client: LiveClient) -> dict[str, Any]:
            album_command(album, index)
            client.wait_for_mutation()
            http = HTTPClient(self.config.host, self.config.http_port, self.config.timeout)
            reader = CatalogReader(http, page_size=self.config.page_size, max_tracks=self.config.max_tracks,
                                   max_requests=self.config.max_requests)
            rows = reader.rows('album/song', album=album)
            if not rows or rows != reader.rows('album/song', album=album):
                raise CatalogChanged('album source is empty or changing')
            verify_expected(rows, expected)
            position = 0 if index is None else index
            if position >= len(rows):
                raise ValueError('position outside current album')
            selected: dict[str, Any] = {'kind': 'album', 'artist': None, 'album': album}
            if index is not None:
                selected.update(selected_index=index, title=rows[index]['name'], target_artist=rows[index]['author'])
            client.scan_guard()
            guard = GuardedHTTP(http, 'album/song', {'album': album}, rows, position, client)
            if index is None:
                client.play_album(album, http=guard)
            else:
                client.play_album(album, index, http=guard)
            state = verify_playing(client, selected, rows, self.config.timeout, config=self.config, http=http)
            result = {'status': 'playing' if state else 'uncertain', 'mutation_attempted': True, 'state': state}
            if state:
                result['queue'] = snapshot(self.config, client, http, expected=rows, selected=selected,
                                           selected_position=index)
            else:
                result['reason'] = 'album playback not confirmed; selection was not retried'
            return result
        return self._perform('play_album', select)

    def play_genre(self, genre: str, *, album: str | None = None, index: int | None = None,
                   expected: tuple[QueueItem, ...] | None = None) -> CommandResult:
        """Select only the displayed genre/album membership after fresh checks."""
        from controller.genre_playback import select
        return self._perform('play_genre', lambda client: select(self.config, client, genre,
            album=album, index=index, expected=expected))

    def play_queue_index(self, index: int, *, expected: tuple[QueueItem, ...] | None = None) -> CommandResult:
        """Select a fresh queue row; optional expected rows pin the displayed source."""
        from controller.fiio_http import HTTPClient
        from controller.queue import select_queue_index
        return self._perform('play_queue_index', lambda client: select_queue_index(self.config, client,
            HTTPClient(self.config.host, self.config.http_port, self.config.timeout), index, expected=expected))

    def play_playlist(self, name: str, *, index: int | None = None,
                      expected: tuple[QueueItem, ...] | None = None) -> CommandResult:
        from controller.source_playback import select
        return self._perform('play_playlist', lambda client: select(self.config, client,
            'playlist', index=index, name=name, expected=expected))

    def play_catalog_track(self, index: int, *, favorites: bool = False,
                           expected: tuple[QueueItem, ...] | None = None) -> CommandResult:
        from controller.source_playback import select
        if type(favorites) is not bool:
            raise ValueError('favorites must be a boolean')
        return self._perform('play_catalog_track', lambda client: select(self.config, client,
            'favorites' if favorites else 'tracks', index=index, expected=expected))

    def seek(self, position_ms: int, *, expected: Track, source: PlaybackSource) -> CommandResult:
        from controller.seeking import seek
        return self._perform('seek', lambda client: seek(client, position_ms,
            expected=expected, source=source, timeout=self.config.timeout))

    def create_playlist(self, name: str) -> CommandResult:
        return self._playlist_edit('create', name)

    def upload_audio(self, source: str, destination: str, *,
                     on_progress: Callable[[int, int], None] | None = None,
                     expected_generation: int | None = None) -> CommandResult:
        """Stream one new audio file; verify listing and completed byte count."""
        from controller.importing import upload
        return self._perform('upload_audio', lambda client: upload(
            self.config, client, source, destination, on_progress=on_progress), expected_generation=expected_generation)

    def scan_library(self, *, timeout: float = 300,
                     on_progress: Callable[[int], None] | None = None,
                     expected_generation: int | None = None) -> CommandResult:
        """Start once and observe the scan lifecycle without interleaved queries."""
        from controller.importing import scan
        return self._perform('scan_library', lambda client: scan(
            client, timeout=timeout, on_progress=on_progress), expected_generation=expected_generation)

    def rename_playlist(self, name: str, new_name: str) -> CommandResult:
        return self._playlist_edit('rename', name, new_name=new_name)

    def add_playlist_track(self, name: str, index: int, *, expected: tuple[QueueItem, ...],
                           album: str | None = None) -> CommandResult:
        return self._playlist_edit('add', name, index=index, expected=expected,
                                   category='album/song' if album is not None else 'all/song', album=album)

    def remove_playlist_track(self, name: str, index: int, *, expected: tuple[QueueItem, ...]) -> CommandResult:
        return self._playlist_edit('remove', name, index=index, expected=expected)

    def _playlist_edit(self, action: str, name: str, **kwargs: Any) -> CommandResult:
        from controller.fiio_http import HTTPClient
        from controller.playlist_operations import edit
        return self._perform('playlist_' + action, lambda client: edit(self.config, client,
            HTTPClient(self.config.host, self.config.http_port, self.config.timeout), action, name, **kwargs))

    @contextmanager
    def operation(self, *, expected_generation: int | None = None) -> Iterator[LiveClient]:
        with self.guard:
            requested_generation = self.generation
            if expected_generation is not None and (type(expected_generation) is not int or expected_generation != requested_generation):
                raise ConnectionError('displayed connection expired; no command was sent')
            if self.connection != 'ready' or self.client is None or self.client.closed.is_set():
                raise ConnectionError('device is not ready; command was not queued or replayed')
        with self.operations:
            with self.guard:
                client = self.client
                if (self.connection != 'ready' or client is None or client.closed.is_set()
                        or requested_generation != self.generation):
                    raise ConnectionError('device is not ready; command was not queued or replayed')
                client.begin_operation(self.config.timeout)
            try:
                yield client
            finally:
                client.end_operation()

    def _run(self) -> None:
        delay = self.backoff
        while not self.shutdown.is_set():
            with self.guard:
                while not self.enabled and not self.shutdown.is_set():
                    self.guard.wait(.5)
                if self.shutdown.is_set():
                    return
                generation = self.generation = self.generation + 1
                self.connection = 'connecting' if delay == self.backoff else 'reconnecting'
                self.guard.notify_all()
            client = None
            ready_at = None
            try:
                # Don't swap in a fresh connection while an old operation unwinds.
                with self.operations:
                    client = self.client_factory(self.config.host, self.config.tcp_port, self.config.timeout)
                    with self.guard:
                        if not self.enabled or generation != self.generation:
                            client.close()
                            continue
                        self.client = client
                    require_client(client, Capability.PERSISTENT_SESSION)
                    client.play_mode()
                    try:
                        client.now_playing()
                    except TimeoutError:
                        pass  # Healthy transport may have no now-playing at final EOF.
                    with self.guard:
                        if not self.enabled or generation != self.generation or client.closed.is_set():
                            continue
                        self.connection, self.last_error = 'ready', None
                        ready_at = time.monotonic()
                        self.guard.notify_all()
                health_at = time.monotonic()
                while not self.shutdown.wait(.1) and not client.closed.is_set():
                    with self.guard:
                        if not self.enabled or generation != self.generation:
                            break
                    if time.monotonic() - health_at >= self.health_interval and self.operations.acquire(False):
                        try:
                            client.timeout = self.config.timeout
                            client.play_mode()
                            health_at = time.monotonic()
                        finally:
                            self.operations.release()
            except (OSError, ValueError, RuntimeError) as exc:
                with self.guard:
                    self.last_error = type(exc).__name__ + ': ' + str(exc)
            finally:
                if client:
                    client.close()
                    client.reader.join(1)
                with self.guard:
                    if generation == self.generation:
                        self.client = None
                        self.connection = 'reconnecting' if self.enabled else 'disconnected'
                    self.guard.notify_all()
            if ready_at is not None and time.monotonic() - ready_at >= 30:
                delay = self.backoff
            with self.guard:
                if self.enabled and not self.shutdown.is_set():
                    self.guard.wait(delay * random.uniform(.8, 1.2))
            delay = min(15, delay * 2)
