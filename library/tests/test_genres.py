"""Genre membership is an independent native scope, including identical recordings."""
import tempfile
import unittest

from controller.catalog import CatalogChanged
from library.catalog import CatalogReader, Track
from library.store import Store
from library.sync import synchronize
from library.tests.helpers import Catalog
from library.tests.test_enrichment import client_fixture

TRACKS = [Track(title, artist, album, pos, dict(pos=pos, name=title, author=artist))
          for title, artist, album, pos in [('Same', 'A', 'Shared', 0), ('Same', 'A', 'Shared', 1),
                                          ('Other', 'B', 'Shared', 2), ('Last', 'A', 'Second', 0)]]
GENRES = ['Rock', 'Jazz', 'Jazz', 'Rock']


class GenreTests(unittest.TestCase):
    def test_stable_facets_keep_duplicates_and_survive_offline_without_schema_change(self):
        with tempfile.TemporaryDirectory() as directory, Store(directory) as store:
            http = Catalog(TRACKS, GENRES)
            result = synchronize(store, 'disc', CatalogReader(http, page_size=1), client_fixture(), http,
                                 include_genres=True)
            head, snapshot = store.snapshot('disc')
            self.assertEqual(head['generation'], result['head']['generation'])
            self.assertEqual(len(snapshot.entries), 4)
            self.assertEqual([r['name'] for r in snapshot.genre_rows('Rock', 'Shared')], ['Same'])
            self.assertEqual([r['name'] for r in snapshot.genre_rows('Jazz', 'Shared')], ['Same', 'Other'])
            self.assertEqual([r['pos'] for r in snapshot.genre_rows('Jazz', 'Shared')], [0, 1])
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 1)
        # A baseline snapshot deliberately has unknown genre coverage, not an empty list.
        with tempfile.TemporaryDirectory() as directory, Store(directory) as store:
            store.publish('disc', TRACKS, {}, expected_generation=None)
            self.assertIsNone(store.snapshot('disc')[1].genres)

    def test_genre_only_change_or_broken_membership_retains_previous_snapshot(self):
        for mode in ('change', 'membership', 'count'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, Store(directory) as store:
                previous = store.publish('disc', TRACKS, {}, expected_generation=None)
                http = Catalog(TRACKS, GENRES)
                calls = 0
                def change(category, offset, page):
                    nonlocal calls
                    if category == 'style':
                        calls += 1
                        if calls == 2 and mode == 'change':
                            http.genres = ['Jazz', 'Jazz', 'Rock', 'Rock']
                    if category == 'style' and mode == 'count':
                        page['items'][0]['count'] += 1
                    if category == 'style/album/song' and mode == 'membership':
                        page['items'] = [dict(r, name='Wrong') for r in page['items']]
                http.change = change
                with self.assertRaises(CatalogChanged):
                    synchronize(store, 'disc', CatalogReader(http), client_fixture(), http, include_genres=True)
                self.assertEqual(store.head('disc')['generation'], previous['generation'])

    def test_unresolved_literal_group_is_retained_without_alias_translation(self):
        http = Catalog(TRACKS, ['unknown_style'] * len(TRACKS))
        reader = CatalogReader(http)
        reader.read_stable(include_genres=True)
        self.assertEqual(reader.genres, [dict(name='unknown_style', count=4, available=False)])
        self.assertFalse(any(category.startswith('style/') for category, *_ in http.calls))
