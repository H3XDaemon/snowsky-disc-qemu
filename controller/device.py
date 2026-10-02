"""Sequential event-preserving client and per-phase mutation guards."""
import time
from controller.fiio_link import Client, frame
from controller.events import validate_scan_events
from controller.sound import SOUND_WRITE_TAGS


class MutationPacer:
    """Respect the stock integer-second gate without delaying idle connections.

    The last command before connection is unknown, so start with a conservative
    interval. Thereafter only actual mutation attempts advance the deadline.
    Call before fresh preflight; the socket also checks it as a final backstop.
    Operations must be serialized by the owning client/session.
    """
    interval = 2.1

    def __init__(self, *, closed=None):
        self.closed = closed
        self.last_attempt = time.monotonic()

    def wait(self):
        while True:
            if self.closed is not None and self.closed.is_set():
                raise ConnectionError('session ended before dispatch')
            remaining = self.last_attempt + self.interval - time.monotonic()
            if remaining <= 0:
                return
            if self.closed is None:
                time.sleep(remaining)
            elif self.closed.wait(remaining):
                raise ConnectionError('session ended before dispatch')

    def attempted(self):
        self.last_attempt = time.monotonic()


class ObservedSocket:
    def __init__(self, socket, session):
        self.socket, self.session = socket, session

    def __getattr__(self, name):
        return getattr(self.socket, name)

    def sendall(self, data):
        if data[:4] in (b'0100', b'0101', b'0102', b'0103', b'0201', b'0104', b'0502', b'0622', *SOUND_WRITE_TAGS):
            kind = 'sound' if data[:4] in SOUND_WRITE_TAGS else {b'0102': 'mode', b'0104': 'favorite', b'0502': 'volume'}.get(data[:4], 'selection')
            if self.session.mutation_phase != kind:
                raise RuntimeError('unexpected mutation in the current phase')
            if self.session.mutation_phase in self.session.attempted_phases:
                raise RuntimeError('playback mutation replay refused')
            self.session.wait_for_mutation()
            self.session.pacer.attempted()
            self.session.attempted_phases.add(self.session.mutation_phase)
            self.session.mutation_attempted = True
        return self.socket.sendall(data)


class MutationGuard:
    pacer: MutationPacer
    attempted_phases: set[str]
    mutation_phase: str

    def wait_for_mutation(self) -> None:
        self.pacer.wait()

    def begin_phase(self, name: str) -> None:
        if (name not in ('mode', 'selection', 'favorite', 'volume', 'sound') or name in self.attempted_phases
                or (name == 'mode' and self.attempted_phases)):
            raise RuntimeError('mutation phase cannot be replayed')
        self.mutation_phase = name


class PlaybackClient(MutationGuard, Client):
    """One synchronous reader; retain unrelated events across Controller queries."""
    def __init__(self, host='127.0.0.1', port=12100, timeout=8):
        # Stock temporarily closes its listener after a client disconnects.
        # Wait only for an INITIAL connection, before handshake or any mutation.
        # Established sessions are never reconnected/replayed.
        deadline = time.monotonic() + timeout
        while True:
            try:
                super().__init__(host, port, max(.01, deadline - time.monotonic()))
                break
            except ConnectionRefusedError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.1)
        self.timeout = timeout
        self.observed = []
        self.mutation_attempted = False
        self.mutation_phase = 'selection'
        self.attempted_phases = set()
        self.pacer = MutationPacer()
        self.socket = ObservedSocket(self.socket, self)



    def retain(self, event):
        if len(self.observed) >= 10000:
            raise ValueError('device event budget exhausted')
        self.observed.append(event)

    def collect(self):
        for _ in range(10000):
            try:
                self.retain(super().event(timeout=.01))
            except TimeoutError:
                return
        raise ValueError('device event budget exhausted')

    def request(self, tag, payload=b'', *, expected=None):
        self.collect()
        self.socket.sendall(frame(tag, payload))
        expected = expected or 'a' + tag[1:].lower()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            event = super().event(timeout=max(.001, deadline - time.monotonic()))
            if event[0] == expected:
                return event[1]
            self.retain(event)
        raise TimeoutError(f'no {expected} reply')

    def take_events(self):
        events, self.observed = self.observed, []
        return events

    def scan_guard(self):
        self.collect()
        validate_scan_events(self.take_events())
