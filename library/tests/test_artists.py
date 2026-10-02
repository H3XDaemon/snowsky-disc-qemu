import tempfile
import unittest

from library.artists import split_artists
from library.catalog import Track
from library.store import Store


class ArtistTests(unittest.TestCase):
    def test_semicolons_trim_deduplicate_preserve_order_and_unicode(self):
        self.assertEqual(split_artists(' Eminem; Dido ;;EMINEM; Иван Дорн; '),
                         ['Eminem', 'Dido', 'Иван Дорн'])
        self.assertEqual(split_artists('Ё;Е\u0308'), ['Ё'])
        self.assertEqual(split_artists(' ; ; '), [])

    def test_other_punctuation_is_not_a_separator(self):
        for name in ('AC/DC', 'Earth, Wind & Fire', 'Artist feat. Guest'):
            self.assertEqual(split_artists(name), [name])

    def test_existing_snapshot_projects_members_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            track = Track('Song', 'A; B', 'Album', 3, {'name': 'Song', 'author': 'A; B'})
            with Store(directory) as store:
                generation = store.publish('test', [track], {}, expected_generation=None)['generation']
            with Store(directory) as store:
                doc = store.documents(generation)[0]
                self.assertEqual(doc['artists'], ['A', 'B'])
                self.assertEqual(doc['artist'], 'A; B')
                self.assertTrue(store.matches_tracks(generation, [track]))
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 1)
