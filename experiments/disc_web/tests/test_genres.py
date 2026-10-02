"""Offline genre views and source tokens, using synthetic split-genre albums."""
import tempfile
import threading
import unittest
from library.catalog import CatalogReader
from library.store import Store
from library.tests.helpers import Catalog
from library.tests.test_genres import TRACKS, GENRES
from experiments.disc_web.backend.catalogue import Catalogue
from experiments.disc_web.backend.demo import Demo
from experiments.disc_web.tests import test_device


class WebGenreTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        device, session, _, _ = test_device.DeviceTests().fixture()
        device.catalogue = Catalogue(device, threading.Lock(), directory.name)
        reader = CatalogReader(Catalog(TRACKS, GENRES))
        reader.read_stable(include_genres=True)
        with Store(directory.name) as store:
            head = store.publish(device.catalogue.key(), TRACKS, {'genres': reader.genres}, expected_generation=None)
        return device, session, head

    def test_offline_filters_keep_same_album_separate_and_do_not_invent_enrichment(self):
        device, session, _ = self.fixture()
        session.snapshot.return_value.to_dict.return_value['connection'] = 'disconnected'
        albums = device.browse('albums', genre='Rock')
        self.assertEqual([r['title'] for r in albums['items']], ['Shared', 'Second'])
        self.assertEqual(albums['items'][0]['scope_genre'], 'Rock')
        self.assertEqual(albums['items'][0]['count'], 1)
        jazz = device.browse('album', 'Shared', genre='Jazz')
        self.assertEqual([r['title'] for r in jazz['items']], ['Same', 'Other'])
        self.assertTrue(all(r['art'] is None and not r['editable'] for r in jazz['items']))
        session.operation.assert_not_called()
        with self.assertRaises(ValueError):
            device.action(dict(action='track', generation=5, selection=jazz['items'][1]['selection']))
        session.play_genre.assert_not_called()

    def test_scoped_actions_stale_snapshot_and_generation_guards(self):
        device, session, head = self.fixture()
        page = device.browse('album', 'Shared', genre='Jazz')
        device.action(dict(action='track', generation=5, selection=page['items'][1]['selection']))
        call = session.play_genre.call_args
        self.assertEqual((call.args, call.kwargs['album'], call.kwargs['index']), (('Jazz',), 'Shared', 1))
        self.assertEqual([r.title for r in call.kwargs['expected']], ['Same', 'Other'])
        device.action(dict(action='genre', generation=5, selection=page['genre_selection']))
        self.assertNotIn('index', session.play_genre.call_args.kwargs)
        session.play_album.assert_not_called()
        session.play_artist.assert_not_called()
        with self.assertRaises(ValueError):
            device.browse('album', 'Shared', artist='A', genre='Jazz')
        with self.assertRaises(ValueError):
            device.action(dict(action='genre', generation=4, selection=page['genre_selection']))
        with Store(device.catalogue.directory) as store:
            store.publish(device.catalogue.key(), TRACKS, {}, expected_generation=head['generation'])
        with self.assertRaises(ValueError):
            device.action(dict(action='genre', generation=5, selection=page['genre_selection']))
        self.assertIsNone(device.browse('albums')['genres'])
        with self.assertRaises(ValueError):
            device.browse('albums', genre='Jazz')

    def test_demo_obeys_genre_for_navigation_whole_genre_and_tracks(self):
        demo = Demo()
        demo.tracks[1]['metadata']['genre'] = 'Jazz'
        # Demo album filters must be derived from member tracks, just like the device.
        tracks = demo.browse('album', 'Afterglow', genre='Electronic')['items']
        self.assertEqual(len(tracks), 4)
        demo.action(dict(action='genre', genre='Electronic', album='Afterglow'))
        self.assertEqual(len(demo.queue_items), 4)
        demo.action(dict(action='track', name=tracks[-1]['id'], source_view='album',
                         source_name='Afterglow', source_genre='Electronic'))
        self.assertEqual(demo.selected, 3)
