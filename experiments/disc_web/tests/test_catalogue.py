import tempfile
import threading
import unittest
from unittest.mock import Mock
import http.client
import json

from controller import DeviceConfig, QueueItem
from controller.tests.session_fixture import Server as Peer
from library.store import Store
from library.catalog import Track
from library.tests.helpers import Catalog, TRACKS
from experiments.disc_web.backend.catalogue import Catalogue
from experiments.disc_web.backend.device import BusyError, Device
from experiments.disc_web.backend.server import Server
from experiments.disc_web.tests import test_device


class CatalogueTests(unittest.TestCase):
    def test_unconfigured_start_never_connects_or_exposes_a_loopback_snapshot(self):
        peer = Peer()
        self.addCleanup(peer.close)
        config = DeviceConfig('127.0.0.1', peer.server_address[1], timeout=.3)
        with tempfile.TemporaryDirectory() as directory, Device(config, configured=False) as device:
            with Server(('127.0.0.1', 0), device, directory) as server:
                key = json.dumps([config.host, config.tcp_port, config.http_port], separators=(',', ':'))
                with Store(directory) as store:
                    store.publish(key, TRACKS, {}, expected_generation=None)
                self.assertEqual(device.state()['endpoint'], '')
                self.assertFalse(server.catalogue.state()['available'])
                with self.assertRaisesRegex(ValueError, 'Choose a player address'):
                    device.action({'action': 'connect'})
                self.assertEqual(peer.accepts, 0)
                self.assertFalse(device.session.snapshot().enabled)
                device.configure(config, device.state()['generation'])
                self.assertTrue(device.session.wait_ready(3))
                self.assertEqual(device.state()['endpoint'], config.host)
                self.assertTrue(server.catalogue.state()['available'])
                self.assertEqual(peer.accepts, 1)

    def cached_device(self, tracks=TRACKS):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        device, session, _, _ = test_device.DeviceTests().fixture()
        device.catalogue = Catalogue(device, threading.Lock(), temporary.name)
        with Store(temporary.name) as store:
            head = store.publish(device.catalogue.key(), tracks, {}, expected_generation=None)
        return device, session, head

    def test_offline_snapshot_has_album_metadata_and_selects_the_exact_recording(self):
        device, session, head = self.cached_device()
        session.snapshot.return_value.to_dict.return_value['connection'] = 'disconnected'
        albums = device.browse('albums')
        self.assertEqual(albums['snapshot'], head['generation'])
        self.assertEqual(albums['items'][0]['artist'], 'Linkin Park')
        items = device.browse('tracks')['items']
        self.assertEqual([item['album'] for item in items[:2]], ['Meteora', 'Live'])
        session.operation.assert_not_called()
        with self.assertRaises(ValueError):
            device.action({'action': 'track', 'selection': items[1]['selection'], 'generation': 5})
        session.snapshot.return_value.to_dict.return_value['connection'] = 'ready'
        device.action({'action': 'track', 'selection': items[1]['selection'], 'generation': 5})
        session.play_album.assert_called_once_with('Live', index=0,
            expected=(QueueItem(0, 'Numb', 'Linkin Park'),))

    def test_cached_artist_selection_preserves_scope_and_rejects_new_snapshot(self):
        device, session, head = self.cached_device()
        item = device.browse('album', 'Live', 'Linkin Park')['items'][0]
        device.action({'action': 'track', 'selection': item['selection'], 'generation': 5})
        session.play_artist.assert_called_once_with('Linkin Park', album='Live', index=0,
            expected=(QueueItem(0, 'Numb', 'Linkin Park'),))
        with Store(device.catalogue.directory) as store:
            store.publish(device.catalogue.key(), TRACKS, {}, expected_generation=head['generation'])
        with self.assertRaisesRegex(ValueError, 'saved collection changed'):
            device.action({'action': 'track', 'selection': item['selection'], 'generation': 5})
        session.play_artist.assert_called_once()
        device.config = DeviceConfig('127.0.0.2')
        self.assertFalse(device.catalogue.state()['available'])
        with self.assertRaises(ValueError):
            device._selection(item['selection'])

    def test_same_title_artists_stay_separate_in_saved_browse_and_playback(self):
        tracks = [Track('First', 'Artist A', 'Shared', 0, {'pos': 0}),
                  Track('Second', 'Artist B', 'Shared', 1, {'pos': 1})]
        device, session, head = self.cached_device(tracks)
        group = device.browse('albums')['items'][0]
        self.assertEqual(group['artists'], ['Artist A', 'Artist B'])
        self.assertEqual(group['artist'], '')
        self.assertEqual(len(device.browse('album', 'Shared')['items']), 2)
        scoped = device.browse('album', 'Shared', 'Artist B')['items']
        self.assertEqual([row['title'] for row in scoped], ['Second'])
        device.action(dict(action='album', name='Shared', artist='Artist B',
                           snapshot=head['generation'], generation=5))
        session.play_artist.assert_called_once_with('Artist B', album='Shared',
            expected=(QueueItem(0, 'Second', 'Artist B'),))
        session.play_album.assert_not_called()

    def test_whole_saved_album_passes_expected_membership_to_controller(self):
        device, session, head = self.cached_device()
        device.action({'action': 'album', 'name': 'Live', 'snapshot': head['generation'], 'generation': 5})
        session.play_album.assert_called_once_with('Live', expected=(QueueItem(0, 'Numb', 'Linkin Park'),))
        with self.assertRaises(ValueError):
            device.action({'action': 'album', 'name': 'Live', 'snapshot': 'expired', 'generation': 5})
        session.play_album.assert_called_once()

    def test_sync_borrows_one_session_is_read_only_and_retains_snapshot_on_failure(self):
        peer = Peer()
        self.addCleanup(peer.close)
        with tempfile.TemporaryDirectory() as directory, Device(
                DeviceConfig('127.0.0.1', peer.server_address[1], timeout=.3), http=Catalog()) as device:
            device.session.connect()
            self.assertTrue(device.session.wait_ready(3))
            device.catalogue = Catalogue(device, threading.Lock(), directory)
            self.addCleanup(device.catalogue.close)
            catalog = device.http
            attempted = []
            def flaky_read(*args, **kwargs):
                attempted.append(args)
                if len(attempted) == 1:
                    raise TimeoutError('transient read failure')
                return catalog.catalog(*args, **kwargs)
            device.http = Mock()
            device.http.catalog.side_effect = flaky_read
            generation = device.state()['generation']
            device.catalogue.start(generation, 'first-sync')
            device.catalogue.worker.join(4)
            state = device.catalogue.state()
            self.assertEqual(state['phase'], 'done')
            self.assertEqual(state['track_count'], len(TRACKS))
            self.assertFalse(state['stale'])
            self.assertEqual(sum(args == ('all/song',) for args in attempted), 3)
            self.assertEqual((peer.accepts, peer.writes), (1, 0))
            # A broken read cannot replace a complete previous snapshot.
            device.http = Mock()
            device.http.catalog.side_effect = OSError('unavailable')
            device.catalogue.start(generation, 'failed-sync')
            device.catalogue.worker.join(3)
            failed = device.catalogue.state()
            self.assertEqual(failed['phase'], 'failed')
            self.assertEqual(failed['generation'], state['generation'])
            self.assertTrue(failed['stale'])
            device.session.disconnect()
            self.assertEqual(len(device.browse('tracks')['items']), len(TRACKS))
            self.assertEqual(peer.writes, 0)

    def test_http_can_browse_previous_snapshot_while_gate_is_held_and_demo_writes_no_store(self):
        device, session, _ = self.cached_device()
        with Server(('127.0.0.1', 0), device, device.catalogue.directory) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                session.snapshot.return_value.to_dict.return_value['connection'] = 'disconnected'
                with server.imports.gate, device.lock:
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    connection.request('GET', '/api/library?kind=tracks')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(len(json.loads(response.read())['items']), len(TRACKS))
                    connection.close()
                session.operation.assert_not_called()
            finally:
                server.shutdown()
                worker.join(2)
        from pathlib import Path
        from experiments.disc_web.backend.demo import Demo
        path = Path(device.catalogue.directory) / 'demo-must-not-exist'
        with Server(('127.0.0.1', 0), Demo(), path) as server:
            self.assertIsNone(server.catalogue)
        self.assertFalse(path.exists())

    def test_busy_sync_does_not_queue_or_allow_target_switch_and_old_snapshot_is_readable(self):
        device, session, _ = self.cached_device()
        gate = device.catalogue.gate
        with gate:
            with self.assertRaises(BusyError):
                device.catalogue.start(5, 'blocked')
            self.assertIsNone(device.catalogue.worker)
            self.assertEqual(len(device.browse('tracks')['items']), len(TRACKS))
        with self.assertRaises(ValueError):
            device.catalogue.start(4, 'stale')
        self.assertFalse(gate.locked())

    def test_disconnect_during_sync_cannot_publish_partial_data(self):
        peer = Peer()
        self.addCleanup(peer.close)
        with tempfile.TemporaryDirectory() as directory, Device(
                DeviceConfig('127.0.0.1', peer.server_address[1], timeout=.3), http=Catalog()) as device:
            device.session.connect()
            self.assertTrue(device.session.wait_ready(3))
            device.catalogue = Catalogue(device, threading.Lock(), directory)
            device.http.change = lambda *args: device.session.disconnect()
            device.catalogue.start(device.state()['generation'], 'lost-sync')
            device.catalogue.worker.join(3)
            self.assertEqual(device.catalogue.state()['phase'], 'failed')
            self.assertFalse(device.catalogue.state()['available'])
            self.assertFalse(device.catalogue.gate.locked())
            self.assertEqual(peer.writes, 0)


if __name__ == '__main__':
    unittest.main()
