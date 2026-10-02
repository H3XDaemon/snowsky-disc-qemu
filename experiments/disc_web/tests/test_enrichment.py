from contextlib import nullcontext
from dataclasses import asdict
import hashlib
import http.client
import tempfile
import threading
import unittest

from controller.models import Track
from library.store import Store
from library.tests.helpers import TRACKS
from library.tests.test_enrichment import PNG, STATE, client_fixture, http_fixture
from experiments.disc_web.backend.catalogue import Catalogue
from experiments.disc_web.backend.enrichment import cover_identity
from experiments.disc_web.backend.server import Server
from experiments.disc_web.tests import test_device


class WebEnrichmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.device, self.session, _, _ = test_device.DeviceTests().fixture()
        self.device.http = http_fixture()
        self.client = client_fixture()
        self.session.operation.side_effect = lambda: nullcontext(self.client)
        self.device.catalogue = Catalogue(self.device, threading.Lock(), temporary.name)
        with Store(temporary.name) as store:
            self.head = store.publish(self.device.catalogue.key(), TRACKS, {}, expected_generation=None)

    def test_current_observation_decorates_only_its_track_and_album_and_survives_offline(self):
        expected = cover_identity(Track.from_wire(STATE), 5)
        self.assertEqual(self.device.cover(expected), PNG)
        self.session.snapshot.return_value.to_dict.return_value['connection'] = 'disconnected'
        tracks = self.device.browse('tracks')['items']
        self.assertEqual(tracks[0]['duration'], 123)
        self.assertEqual(tracks[0]['metadata']['sample_rate_hz'], 44100)
        self.assertEqual(tracks[0]['metadata']['genre'], 'Synthetic genre')
        self.assertEqual(tracks[1]['metadata'], {})
        self.assertEqual(tracks[0]['art'], '/api/artwork/' + hashlib.sha256(PNG).hexdigest())
        self.assertIsNone(tracks[1]['duration'])
        albums = self.device.browse('albums')['items']
        self.assertEqual(albums[0]['art'], tracks[0]['art'])
        self.assertIsNone(albums[1]['art'])
        coverage = self.device.catalogue.state()['enrichment']
        self.assertEqual((coverage['count'], coverage['artwork_count'], coverage['duration_count']), (1, 1, 1))
        with Store(self.device.catalogue.directory) as store:
            store.publish(self.device.catalogue.key(), TRACKS, {}, expected_generation=self.head['generation'])
        self.assertIsNone(self.device.browse('tracks')['items'][0]['duration'])
        self.assertEqual(self.device.browse('tracks')['items'][0]['metadata'], {})

    def test_wrong_connection_or_track_cannot_read_or_cache_cover_for_stale_browser(self):
        expected = cover_identity(Track.from_wire(STATE), 4)
        with self.assertRaises(ValueError):
            self.device.cover(expected)
        expected[-1] = 5
        expected[3] = '/tmp/sdcard/changed.flac'
        with self.assertRaises(ValueError):
            self.device.cover(expected)
        self.device.http.cover.assert_not_called()
        self.assertEqual(self.device.catalogue.state()['enrichment']['count'], 0)

    def test_cached_artwork_is_available_while_busy_but_only_for_active_device_snapshot(self):
        self.device.cover()
        url = self.device.browse('tracks')['items'][0]['art']
        with Server(('127.0.0.1', 0), self.device, self.device.catalogue.directory) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with server.imports.gate, self.device.lock:
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    connection.request('GET', url)
                    response = connection.getresponse()
                    self.assertEqual((response.status, response.getheader('Content-Type')), (200, 'image/png'))
                    self.assertEqual(response.read(), PNG)
                    connection.close()
                with Store(self.device.catalogue.directory) as store:
                    store.publish(self.device.catalogue.key(), TRACKS, {}, expected_generation=self.head['generation'])
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                connection.request('GET', url)
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                connection.close()
            finally:
                server.shutdown()
                worker.join(2)

    def test_seek_accepts_extended_public_track_but_rejects_unknown_fields(self):
        track = Track.from_wire(STATE)
        body = dict(action='seek', generation=5, source=1, position_ms=1000, expected=asdict(track))
        self.device.action(body)
        self.session.seek.assert_called_once_with(1000, expected=track, source=1)
        self.session.seek.reset_mock()
        with self.assertRaises(ValueError):
            self.device.action(dict(body, expected=dict(body['expected'], arbitrary='field')))
        self.session.seek.assert_not_called()
