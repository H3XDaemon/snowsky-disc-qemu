"""Synthetic artwork and metadata: no private media, sockets or player writes."""
from contextlib import closing
from copy import deepcopy
import hashlib
import sqlite3
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

from library.catalog import CatalogReader
from library.enrichment import Enrichment
from library.observation import observe_current
from library.store import Store
from library.sync import synchronize
from library.tests.helpers import Catalog, TRACKS
from controller.catalog import CatalogChanged


def chunk(name, body):
    return struct.pack('>I', len(body)) + name + body + struct.pack('>I', zlib.crc32(name + body))


PNG = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(b'\x00\xc0\x40\x30')) + chunk(b'IEND', b''))
STATE = dict(state=1, playerflag=1, song=dict(song_name='Numb', song_artist_name='Linkin Park',
    song_sample_rate=44100, song_encoding_rate=16, song_channel=2, song_bit_rate=1411,
    song_style_name='Synthetic genre', song_track=1, is_dsd=False, is_cue=False,
    song_album_name='Meteora', song_file_path='/tmp/sdcard/fixture.flac', song_duration_time=123000, pos_id=1))


def client_fixture():
    client = Mock()
    client.handshake.return_value = '0306'
    client.settings.return_value = {'soc_version': 257}
    client.now_playing.return_value = deepcopy(STATE)
    client.event.side_effect = TimeoutError
    return client


def http_fixture():
    http = Catalog()
    http.cover = Mock(return_value=PNG)
    return http


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.store = Store(self.directory)
        self.addCleanup(self.store.close)
        self.head = self.store.publish('device', TRACKS, {}, expected_generation=None)
        self.snapshot = self.store.snapshot('device')[1]

    def test_sync_publishes_catalog_and_available_enrichment_through_one_pipeline(self):
        stages = []
        http, client = http_fixture(), client_fixture()
        with Enrichment(self.directory) as enrichment:
            result = synchronize(self.store, 'device', CatalogReader(http), client, http,
                                 enrichment=enrichment, on_stage=stages.append)
            generation = result['head']['generation']
            rows = enrichment.rows('device', generation)
            self.assertTrue(result['enriched'])
            self.assertEqual(stages, ['identity', 'catalog', 'enrichment', 'verification'])
            self.assertEqual(rows[generation + ':0']['duration_ms'], 123000)
            self.assertEqual(enrichment.artwork('device', generation, hashlib.sha256(PNG).hexdigest()),
                             (PNG, 'image/png'))
        with Enrichment(self.directory) as reopened:
            self.assertEqual(reopened.state('device', generation)['count'], 1)
            self.assertEqual(reopened.rows('device', generation)[generation + ':0']['metadata']['sample_rate_hz'], 44100)
            self.assertEqual(reopened.rows('other-device', generation), {})
            self.assertEqual(reopened.rows('device', self.head['generation']), {})
            self.assertIsNone(reopened.artwork('other-device', generation, hashlib.sha256(PNG).hexdigest()))
        self.assertNotIn('duration_ms', self.store.snapshot('device')[1].entries[0])
        self.assertEqual(self.store.db.execute('PRAGMA user_version').fetchone()[0], 1)
        client.play_album.assert_not_called()
        client.set_state.assert_not_called()

    def test_duplicate_shortened_or_stale_album_metadata_is_never_associated(self):
        for fields in (
            dict(song_name='Cue entry', song_artist_name='Cue Artist', song_album_name='Cue Album'),
            dict(song_album_name='Mete'), dict(song_artist_name='Linkin'),
        ):
            client = client_fixture()
            client.now_playing.return_value['song'].update(fields)
            self.assertIsNone(observe_current(client, http_fixture(), self.snapshot).ordinal)
        http = http_fixture()
        http.tracks = TRACKS[1:]
        self.assertIsNone(observe_current(client_fixture(), http, self.snapshot).ordinal)

    def test_track_path_position_duration_and_source_changes_reject_the_observation(self):
        for fields in ({'song_file_path': '/tmp/sdcard/other.flac'}, {'pos_id': 2},
                       {'song_duration_time': 124000}, {'song_sample_rate': 96000}, {'song_name': 'Other'}):
            client = client_fixture()
            after = deepcopy(STATE)
            after['song'].update(fields)
            client.now_playing.side_effect = [deepcopy(STATE), after]
            with self.assertRaisesRegex(ValueError, 'changed during'):
                observe_current(client, http_fixture(), self.snapshot)
        client = client_fixture()
        client.now_playing.side_effect = [deepcopy(STATE), dict(deepcopy(STATE), playerflag=3)]
        with self.assertRaises(ValueError):
            observe_current(client, http_fixture(), self.snapshot)

    def test_optional_artwork_failure_does_not_suppress_duration_or_complete_catalog(self):
        http = http_fixture()
        http.cover.side_effect = TimeoutError
        with Enrichment(self.directory) as enrichment:
            result = synchronize(self.store, 'device', CatalogReader(http), client_fixture(), http,
                                 enrichment=enrichment)
            row = next(iter(enrichment.rows('device', result['head']['generation']).values()))
            self.assertEqual(row['duration_ms'], 123000)
            self.assertIsNone(row['artwork'])
            client = client_fixture()
            client.now_playing.side_effect = TimeoutError
            result = synchronize(self.store, 'device', CatalogReader(http), client, http, enrichment=enrichment)
            self.assertEqual(result['head']['track_count'], len(TRACKS))
            self.assertFalse(result['enriched'])

    def test_cancelled_publication_retains_previous_head_and_does_not_save_draft_observations(self):
        def cancel():
            raise ConnectionError('disconnected')
        http = http_fixture()
        with Enrichment(self.directory) as enrichment:
            with self.assertRaises(ConnectionError):
                synchronize(self.store, 'device', CatalogReader(http), client_fixture(), http,
                            enrichment=enrichment, before_publish=cancel)
            self.assertEqual(self.store.head('device')['generation'], self.head['generation'])
            self.assertEqual(enrichment.db.execute('SELECT count(*) FROM observations').fetchone()[0], 0)

    def test_scan_during_optional_enrichment_still_blocks_catalog_publication(self):
        client, http = client_fixture(), http_fixture()
        client.scan_guard.side_effect = [None, None, CatalogChanged('scan ended during observation')]
        with Enrichment(self.directory) as enrichment:
            with self.assertRaises(CatalogChanged):
                synchronize(self.store, 'device', CatalogReader(http), client, http, enrichment=enrichment)
        self.assertEqual(self.store.head('device')['generation'], self.head['generation'])

    def test_artwork_budget_invalid_images_and_duration_bounds(self):
        with Enrichment(self.directory) as enrichment:
            generation = self.head['generation']
            with patch('library.enrichment.MAX_ARTWORK', 1):
                enrichment.record('device', generation, 'row', duration_ms=1000, cover=PNG, provenance={})
            self.assertIsNone(enrichment.rows('device', generation)['row']['artwork'])
            for duration in (True, -1, 0, 7 * 86400000 + 1):
                self.assertFalse(enrichment.record('device', generation, 'invalid',
                    duration_ms=duration, cover=b'<svg/>', provenance={}))
            self.assertIsNone(enrichment.artwork('device', generation, '../../file'))

    def test_coverage_counts_fields_per_track_with_snapshot_and_device_isolation(self):
        with Enrichment(self.directory) as enrichment:
            generation = self.head['generation']
            self.assertEqual(enrichment.state('device', generation)['count'], 0)
            for track, duration, cover in [('duration', 1000, None),
                                           ('artwork', None, PNG), ('both', 2000, PNG)]:
                enrichment.record('device', generation, track,
                                  duration_ms=duration, cover=cover, provenance={})
            # Two tracks sharing one image still each have observed artwork.
            state = enrichment.state('device', generation)
            self.assertEqual((state['count'], state['artwork_count'], state['duration_count']), (3, 2, 2))
            for device, snapshot in [('other-device', generation), ('device', 'new-snapshot')]:
                empty = enrichment.state(device, snapshot)
                self.assertEqual((empty['count'], empty['artwork_count'], empty['duration_count']), (0, 0, 0))
            # An absent cover on a fresh observation must lower coverage too.
            enrichment.record('device', generation, 'both', duration_ms=2000, cover=None, provenance={})
            updated = enrichment.state('device', generation)
            self.assertEqual(updated['artwork_count'], 1)
            self.assertNotEqual(updated['revision'], state['revision'])

    def test_migration_preserves_existing_artwork_duration_and_provenance(self):
        with closing(sqlite3.connect(Path(self.directory) / 'observations.sqlite3')) as db, db:
            db.execute("CREATE TABLE observations (device TEXT, generation TEXT, track TEXT, duration_ms INTEGER, artwork TEXT, provenance TEXT, observed_at TEXT, revision TEXT, PRIMARY KEY(device,generation,track))")
            db.execute("CREATE TABLE artwork (digest TEXT PRIMARY KEY, mime TEXT NOT NULL, body BLOB NOT NULL)")
            digest = hashlib.sha256(PNG).hexdigest()
            db.execute("INSERT INTO artwork VALUES (?, 'image/png', ?)", (digest, PNG))
            db.execute("INSERT INTO observations VALUES ('device','old','old:0',123000,NULL,'{}','then','revision')")
            db.execute("UPDATE observations SET artwork=? WHERE generation='old'", (digest,))
        with Enrichment(self.directory) as store:
            self.assertEqual(store.artwork('device', 'old', digest), (PNG, 'image/png'))
            row = store.rows('device', 'old')['old:0']
            self.assertEqual((row['duration_ms'], row['metadata'], row['revision']), (123000, {}, 'revision'))
        with Enrichment(self.directory) as store:
            self.assertEqual(store.rows('device', 'old')['old:0']['observed_at'], 'then')

    def test_metadata_can_be_saved_without_duration_or_cover_and_missing_values_are_not_retained(self):
        client, http = client_fixture(), http_fixture()
        client.now_playing.return_value['song'].pop('song_duration_time')
        http.cover.side_effect = TimeoutError
        with Enrichment(self.directory) as store:
            observation = observe_current(client, http, self.snapshot)
            generation = self.head['generation']
            self.assertTrue(store.record_observation('device', generation, observation))
            row = store.rows('device', generation)[generation + ':0']
            self.assertIsNone(row['duration_ms'])
            self.assertIsNone(row['artwork'])
            self.assertEqual(row['metadata']['reported_bit_rate'], 1411)
            client.now_playing.return_value['song'].pop('song_sample_rate')
            store.record_observation('device', generation, observe_current(client, http, self.snapshot))
            self.assertNotIn('sample_rate_hz', store.rows('device', generation)[generation + ':0']['metadata'])
