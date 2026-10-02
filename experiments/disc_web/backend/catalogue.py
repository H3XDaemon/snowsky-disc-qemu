"""Web ownership of shared Library storage and explicit read-only synchronization."""
from copy import deepcopy
from contextlib import nullcontext
from http.client import HTTPException
import json
import sqlite3
import threading
import time

from library.catalog import CatalogReader
from library.enrichment import Enrichment
from library.store import Store
from library.sync import synchronize
from experiments.disc_web.backend.device import BusyError
from experiments.disc_web.backend.enrichment import Metadata

CACHED_VIEWS = frozenset(('albums', 'artists', 'tracks', 'album', 'artist'))


class Catalogue:
    def __init__(self, device, gate, directory):
        self.device, self.gate, self.directory = device, gate, directory
        self.guard = threading.RLock()
        self.worker = None
        self.stop = threading.Event()
        self.job = None
        self.verified = None
        self.metadata = Metadata(self)
        with Store(directory):
            pass

    def key(self):
        if not self.device.configured:
            return '[null]'
        config = self.device.config
        return json.dumps([config.host, config.tcp_port, config.http_port], separators=(',', ':'))

    def snapshot(self):
        try:
            with Store(self.directory) as store:
                return store.snapshot(self.key())
        except sqlite3.Error as exc:
            raise ValueError('Local library unavailable') from exc

    def state(self):
        try:
            with Store(self.directory) as store:
                head = store.head(self.key())
        except sqlite3.Error:
            return {'available': False, 'phase': 'storage_error'}
        with self.guard:
            status = deepcopy(self.job) if self.job and self.job['device'] == self.key() else {}
            state = self.device.state()
            return {'available': bool(head['generation']), 'generation': head['generation'],
                    'observed_at': head.get('observed_at'), 'track_count': head['track_count'],
                    'stale': self.verified != (self.key(), state['generation']) or state['connection'] != 'ready',
                    'phase': status.get('phase', 'idle'), 'pages': status.get('pages', 0),
                    'enrichment': self.metadata.state(head['generation']),
                    'error': status.get('error'), 'stage': status.get('stage'),
                    'error_type': status.get('error_type'), 'error_detail': status.get('error_detail')}

    def invalidate(self):
        with self.guard:
            self.verified = None

    def update(self, **fields):
        with self.guard:
            self.job.update(fields)

    def start(self, generation, request_id):
        if not self.gate.acquire(False):
            raise BusyError('Another operation is in progress; sync was not queued')
        try:
            self.device.protocol_generation(generation)
            if self.device.state()['connection'] != 'ready':
                raise ValueError('Connect before synchronizing')
            self.invalidate()
            with self.guard:
                self.job = dict(device=self.key(), generation=generation, id=request_id, phase='syncing', pages=0)
            self.worker = threading.Thread(target=self.run, daemon=True, name='disc-library-sync')
            self.worker.start()
            return self.state()
        except Exception:
            self.gate.release()
            raise

    def run(self):
        key, generation = self.job['device'], self.job['generation']
        deadline = time.monotonic() + 300
        owner = self

        class ObservedHTTP:
            requests = 0

            def cover(self):
                if owner.stop.is_set() or time.monotonic() >= deadline or self.requests >= 1000:
                    raise TimeoutError('Synchronization stopped before artwork read')
                owner.device.protocol_generation(generation)
                self.requests += 1
                return owner.device.http.cover()

            def catalog(self, *args, **kwargs):
                # Stock Wi-Fi can drop a read. Repeat only this GET once; both
                # complete catalog observations must still compare equal.
                for attempt in range(2):
                    if owner.stop.is_set() or time.monotonic() >= deadline:
                        raise TimeoutError('Synchronization stopped before publication')
                    if self.requests >= 1000:
                        raise ValueError('catalog request budget exhausted')
                    owner.device.protocol_generation(generation)
                    self.requests += 1
                    try:
                        value = owner.device.http.catalog(*args, **kwargs)
                        break
                    except (OSError, HTTPException):
                        if attempt or owner.stop.wait(.4):
                            raise
                with owner.guard:
                    owner.job['pages'] += 1
                return value

        try:
            with Store(self.directory) as store:
                raw_generation = self.device.protocol_generation(generation)
                with self.device.session.operation(expected_generation=raw_generation) as client:
                    def before_publish():
                        self.device.protocol_generation(generation)
                        if client.closed.is_set() or self.stop.is_set() or time.monotonic() >= deadline:
                            raise ConnectionError('Synchronization interrupted; previous snapshot retained')
                    try:
                        enrichment_context = Enrichment(self.directory)
                    except (OSError, sqlite3.Error):
                        enrichment_context = nullcontext(None)
                    http = ObservedHTTP()
                    with enrichment_context as enrichment:
                        synchronize(store, key,
                            CatalogReader(http, page_size=100, max_tracks=10000, max_requests=1000),
                            client, http, enrichment=enrichment, include_genres=True, before_publish=before_publish,
                            on_stage=lambda stage: self.update(stage=stage))
                with self.guard:
                    self.verified = (key, generation)
                with self.device.lock:
                    self.device.clear_sources()
                self.update(phase='done')
        except (OSError, ValueError, RuntimeError, sqlite3.Error, HTTPException) as exc:
            reasons = {'album membership does not match the complete root catalog': 'membership',
                       'no a501 reply': 'identity_timeout',
                       'catalog changed between full reads; retry once the device is idle': 'changed',
                       'duplicate album selectors cannot be resolved safely': 'ambiguous',
                       'invalid catalog row or non-contiguous positions': 'invalid',
                       'missing or invalid catalog total': 'limit',
                       'catalog request budget exhausted': 'limit'}
            self.update(phase='failed', error=reasons.get(str(exc), 'connection' if isinstance(exc, OSError) else 'unavailable'),
                        error_type=type(exc).__name__, error_detail=str(exc)[:256])
        finally:
            self.gate.release()

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(self.device.config.timeout + 2)
