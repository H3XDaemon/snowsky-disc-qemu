"""Album arguments, catalog grouping and full-source verification."""
from dataclasses import replace
import unittest
from unittest.mock import Mock, AsyncMock
from experiments.disc_assistant.assistant.nlu.intents import AlbumIntent
from experiments.disc_assistant.assistant.nlu.interpreter import interpret_request, InterpretationContext, validate_intent
from experiments.disc_assistant.assistant.ranking import rank, score_albums
from experiments.disc_assistant.assistant.tests import test_ranking, test_playback
from controller.playback import matches


class AlbumGrammarTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_album_and_scoped_album(self):
        for locale, prefix in [('en', 'Play album'), ('ru', 'Включи альбом')]:
            for query, album, artist in [('Meteora', 'Meteora', None),
                    ('Linkin Park — Meteora', 'Meteora', 'Linkin Park'),
                    ('"Stop — Then Play"', 'Stop — Then Play', None)]:
                intent = await interpret_request(prefix + ' ' + query, InterpretationContext(locale))
                self.assertIs(type(intent), AlbumIntent)
                self.assertEqual((intent.album, intent.artist), (album, artist))
                validate_intent(intent)

    def test_compilation_scope_and_artist_constraint(self):
        docs = [dict(album='Collection', artist='North'), dict(album='Collection', artist='South'),
                dict(album='Collection Live', artist='North')]
        generic = score_albums(AlbumIntent('Collection', 'Collection'), docs, {})
        self.assertEqual((generic[0]['album'], generic[0]['artist']), ('Collection', None))
        scoped = score_albums(AlbumIntent('South — Collection', 'Collection', 'South'), docs, {})
        self.assertEqual([(c['album'], c['artist']) for c in scoped], [('Collection', 'South')])
        self.assertEqual(score_albums(AlbumIntent('Missing', 'Nonexistent XYZ'), docs, {}), [])

    def test_confirmation_requires_album_scope_source_and_membership(self):
        selected = dict(kind='album', album='Collection', artist=None)
        rows = [dict(name='One', author='North'), dict(name='Two', author='South')]
        state = dict(state=0, playerflag=3, song=dict(song_name='Two', song_artist_name='South', song_album_name='Collection'))
        self.assertTrue(matches(state, selected, rows))
        self.assertFalse(matches({**state, 'playerflag': 7}, selected, rows))
        self.assertFalse(matches(state, {**selected, 'album': 'Other'}, rows))
        self.assertFalse(matches(state, selected, rows[:1]))


class AlbumRankingTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_ranking.RankingTests.setUp
    async def test_album_uses_full_snapshot_without_track_search(self):
        result = await rank(self.config, self.store, self.search, AlbumIntent('Meteora', 'Meteora'))
        self.assertEqual(result['candidates'][0]['album'], 'Meteora')
        self.assertIsNone(result['candidates'][0]['artist'])
        self.search.search.assert_not_called()


class AlbumPlaybackTests(unittest.TestCase):
    setUp = test_playback.PlaybackTests.setUp
    def test_album_changed_membership_blocks_write(self):
        from experiments.disc_assistant.assistant.playback import fresh_selection
        from library.catalog import CatalogChanged
        selected = dict(kind='album', album='Meteora', artist=None)
        category, filters, rows, _, _ = fresh_selection(self.config, self.store, self.head['generation'], selected, self.http)
        self.assertEqual((category, filters), ('album/song', {'album': 'Meteora'}))
        self.http.rows = self.http.rows[:1]
        with self.assertRaises(CatalogChanged):
            fresh_selection(self.config, self.store, self.head['generation'], selected, self.http)
