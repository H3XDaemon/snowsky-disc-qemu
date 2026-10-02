import tempfile
import unittest

from library.store import Store
from library.tests.helpers import TRACKS


class SnapshotTests(unittest.TestCase):
    def test_persisted_views_keep_duplicate_recordings_and_album_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            with Store(directory) as store:
                head = store.publish('player-a', TRACKS, {}, expected_generation=None)
            with Store(directory) as store:
                restored, snapshot = store.snapshot('player-a')
                self.assertEqual(restored['generation'], head['generation'])
                self.assertEqual(len(snapshot.entries), len(TRACKS))
                self.assertEqual([r['album'] for r in snapshot.entries[:2]], ['Meteora', 'Live'])
                for ordinal, album in ((0, 'Meteora'), (1, 'Live'), (6, 'Cue Album')):
                    name, rows, index = snapshot.selection(ordinal)
                    self.assertEqual(name, album)
                    self.assertEqual(index, 1 if ordinal == 6 else 0)
                    self.assertEqual(rows[index]['name'], TRACKS[ordinal].title)
                self.assertIsNone(store.snapshot('player-b')[1])

    def test_artist_scope_remains_literal_and_rejects_other_artists(self):
        with tempfile.TemporaryDirectory() as directory, Store(directory) as store:
            store.publish('device', TRACKS, {}, expected_generation=None)
            _, snapshot = store.snapshot('device')
            self.assertEqual([r['name'] for r in snapshot.groups('album', artist='Linkin Park')],
                             ['Meteora', 'Live', 'Hybrid Theory'])
            with self.assertRaises(ValueError):
                snapshot.selection(2, artist='Linkin Park')
            with self.assertRaises(ValueError):
                snapshot.selection(True)
