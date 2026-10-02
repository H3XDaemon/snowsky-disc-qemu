"""Read-only current-track observations through the application's existing owner."""
import sqlite3

from controller.models import Track
from library.enrichment import Enrichment
from library.observation import observe_current
from library.store import Store


def cover_identity(track, generation):
    return [track.title, track.artist, track.album, track.path,
            track.queue_position, track.duration_ms, generation]


class Metadata:
    def __init__(self, catalogue):
        self.catalogue = catalogue
        self.device = catalogue.device

    def rows(self, generation):
        try:
            with Enrichment(self.catalogue.directory) as store:
                return store.rows(self.catalogue.key(), generation)
        except (OSError, sqlite3.Error):
            return {}

    def state(self, generation):
        try:
            with Enrichment(self.catalogue.directory) as store:
                return store.state(self.catalogue.key(), generation)
        except (OSError, sqlite3.Error):
            return {'count': 0, 'revision': None, 'unavailable': True}

    def artwork(self, digest):
        with self.device.state_guard:
            try:
                with Store(self.catalogue.directory) as catalogue:
                    head = catalogue.head(self.catalogue.key())
                with Enrichment(self.catalogue.directory) as store:
                    return store.artwork(self.catalogue.key(), head['generation'], digest)
            except (OSError, sqlite3.Error):
                return None

    def capture(self, client, expected=None):
        """Admission belongs to Web; observation and association belong to Library."""
        generation = self.device.state()['generation']
        expected_track = None
        if expected is not None:
            if not isinstance(expected, list) or len(expected) != 7 or expected[-1] != generation:
                raise ValueError('Artwork request belongs to a different connection')
            title, artist, album, path, position, duration, _ = expected
            expected_track = Track(title, artist, album, position, path, duration)
        head, snapshot = self.catalogue.snapshot()
        observation = observe_current(client, self.device.http, snapshot, expected_track=expected_track)
        self.device.protocol_generation(generation)
        try:
            if head['generation'] and self.catalogue.snapshot()[0]['generation'] == head['generation']:
                with Enrichment(self.catalogue.directory) as store:
                    store.record_observation(self.catalogue.key(), head['generation'], observation)
        except (OSError, sqlite3.Error):
            pass
        return observation.cover
