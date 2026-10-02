"""Duplicate-title selection fixtures remain isolated from device control."""
import unittest
from experiments.disc_web.backend.demo import Demo


class DemoAlbumScopeTests(unittest.TestCase):
    def setUp(self):
        self.demo = Demo()
        self.demo.tracks.append(dict(self.demo.tracks[0], id='other-0', artist='Other Artist'))
        self.demo.albums.append(dict(self.demo.albums[0], id='other', artist='Other Artist', count=1))

    def test_duplicate_album_names_browse_and_play_with_literal_artist_scope(self):
        self.assertEqual(len(self.demo.browse('album', 'Afterglow')['items']), 6)
        for artist, count in [('Northline', 5), ('Other Artist', 1)]:
            with self.subTest(artist=artist):
                card = self.demo.browse('artist', artist)['items'][0]
                self.assertEqual(card['scope_artist'], artist)
                rows = self.demo.browse('album', card['title'], card['scope_artist'])['items']
                self.assertEqual(len(rows), count)
                self.demo.action(dict(action='album', name=card['title'], artist=artist))
                self.assertEqual(self.demo.queue_items, rows)
                self.assertTrue(all(row['artist'] == artist for row in self.demo.queue_items))

    def test_track_selection_keeps_scoped_queue_and_rejects_other_artist(self):
        self.demo.action(dict(action='track', name='0-1', source_view='album',
                              source_name='Afterglow', source_artist='Northline'))
        self.assertEqual(self.demo.selected, 1)
        self.assertEqual(len(self.demo.queue_items), 5)
        before = self.demo.queue()
        with self.assertRaisesRegex(ValueError, 'left displayed source'):
            self.demo.action(dict(action='track', name='other-0', source_view='album',
                                  source_name='Afterglow', source_artist='Northline'))
        self.assertEqual(self.demo.queue(), before)
        with self.assertRaisesRegex(ValueError, 'Selection is empty'):
            self.demo.action(dict(action='album', name='Afterglow', artist='Missing'))
        self.assertEqual(self.demo.queue(), before)
