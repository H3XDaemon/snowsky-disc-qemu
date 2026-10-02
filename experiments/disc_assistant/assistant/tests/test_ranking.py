import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

from experiments.disc_assistant.assistant.nlu.intents import parse as parse_text, Intent
from experiments.disc_assistant.assistant.nlu.languages import load_languages
from experiments.disc_assistant.assistant.ranking import rank, score_tracks, ordered
from library.tests.helpers import TRACKS, ALIASES
from library.store import Store, StaleSnapshot


def parse(text, rules=None):
    # Low-level grammar comparisons explicitly exercise both dictionaries.
    return parse_text(text, rules or load_languages(('ru', 'en')))


class RankingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.close)
        self.head = self.store.publish('test', TRACKS, {}, expected_generation=None)
        self.store.publish_index('test', self.head['generation'], 'index', 'sig')
        self.config = Mock(device_key='test', aliases=ALIASES, locale='en')
        self.search = Mock(signature='sig')
        self.search.search = AsyncMock(return_value={'generation': self.head['generation'], 'found': 0, 'candidates': []})

    async def ranked(self, text):
        return await rank(self.config, self.store, self.search, parse(text))

    def test_bilingual_grammar_and_explicit_types(self):
        for phrase in ('Включи Linkin Park', 'Play Linkin Park', ' play   Linkin Park '):
            self.assertEqual(parse(phrase), Intent('Linkin Park'))
        self.assertEqual(parse('Включи Linkin Park — Numb').artist, 'Linkin Park')
        self.assertEqual(parse('Play artist AC - DC'), Intent('AC - DC', 'artist'))
        self.assertEqual(parse('Включи трек Numb').kind, 'track')
        for phrase in ('pause Numb', 'удали Numb', 'play ', 'Play Numb\nstop', ''):
            with self.assertRaises(ValueError):
                parse(phrase)

    async def test_exact_artist_and_cyrillic_alias_start_whole_artist(self):
        for phrase in ('Включи Linkin Park', 'Play artist Linkin Park', 'Включи линкин парк'):
            result = await self.ranked(phrase)
            self.assertEqual(result['candidates'][0]['kind'], 'artist')
            self.assertEqual(result['candidates'][0]['artist'], 'Linkin Park')
        self.search.search.assert_not_called()

    async def test_artist_title_constraints_and_default_version_penalty(self):
        for phrase in ('Play Linkin Park - Numb', 'Включи линкин парк намб', 'Play Linkin Park Numb'):
            result = await self.ranked(phrase)
            candidates = result['candidates']
            self.assertEqual(candidates[0]['album'], 'Meteora')
            self.assertEqual({c['artist'] for c in candidates}, {'Linkin Park'})
            self.assertEqual(candidates[1]['evidence']['unrequested_version_penalty'], 12)
            self.assertGreater(candidates[0]['score'], candidates[1]['score'])

    async def test_requested_live_is_mandatory_and_missing_remix_is_not_substituted(self):
        live = await self.ranked('Play Linkin Park - Numb live')
        self.assertEqual([c['album'] for c in live['candidates']], ['Live'])
        missing = await self.ranked('Play Linkin Park - Numb remix')
        self.assertEqual(missing['status'], 'not_found')

    async def test_duplicate_cue_rows_are_preserved_and_tie_break_is_stable(self):
        first = (await self.ranked('Play Cue entry'))['candidates']
        second = (await self.ranked('Play Cue entry'))['candidates']
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertEqual(first[0]['track_id'], self.head['generation'] + ':5')

    async def test_fuzzy_title_uses_typesense_and_can_rank_best_without_confirmation(self):
        docs = self.store.documents(self.head['generation'])[:3]
        self.search.search.return_value = {'generation': self.head['generation'], 'found': 3, 'candidates': docs}
        result = await self.ranked('Play Linkin Park - Nmb')
        self.assertEqual(result['candidates'][0]['album'], 'Meteora')
        self.assertEqual({c['artist'] for c in result['candidates']}, {'Linkin Park'})
        self.assertEqual(result['retrieval']['source'], 'typesense')

    async def test_stale_index_prevents_ranking(self):
        self.store.publish('test', TRACKS, {}, expected_generation=self.head['generation'])
        with self.assertRaises(StaleSnapshot):
            await self.ranked('Play Linkin Park')

    async def test_metadata_versions_are_independent_of_interaction_locale(self):
        self.config.locale = 'ru'
        intent = parse('Включи трек Linkin Park - Numb концертная', load_languages(('ru',)))
        live = await rank(self.config, self.store, self.search, intent)
        self.assertEqual([c['album'] for c in live['candidates']], ['Live'])
        ordinary = await rank(self.config, self.store, self.search, Intent('Linkin Park Numb'))
        self.assertEqual(ordinary['candidates'][0]['album'], 'Meteora')
        with self.assertRaises(TypeError):
            await rank(self.config, self.store, self.search, 'Включи Numb')

    async def test_foreign_edition_labels_remain_hard_constraints_in_russian_requests(self):
        self.config.locale = 'ru'
        for label, expected in [('live', ['Live']), ('remix', [])]:
            intent = parse('Включи Linkin Park - Numb ' + label, load_languages(('ru',)))
            result = await rank(self.config, self.store, self.search, intent)
            self.assertEqual([c['album'] for c in result['candidates']], expected)

    async def test_unmatched_text_never_falls_back_to_artist_only(self):
        result = await self.ranked('Play Linkin Park TotallyMissing')
        self.assertEqual(result['candidates'], [])

    async def test_trace_distinguishes_missing_artist_from_exact_local_match(self):
        trace = Mock()
        result = await rank(self.config, self.store, self.search, Intent('Макс Корж'), trace=trace)
        self.assertEqual(result['status'], 'not_found')
        events = {call.args[0]: call.args[1] for call in trace.event.call_args_list}
        self.assertEqual(events['catalog_loaded']['track_count'], len(TRACKS))
        self.assertEqual(events['local_matches']['exact_artist_count'], 0)
        self.assertEqual(events['local_matches']['artist_candidate_count'], 0)
        self.assertEqual(events['local_track_matches']['exact_track_count'], 0)
        self.assertEqual(events['search_query']['query'], 'maks korzh')
        self.assertEqual(events['retrieval_filtered']['found'], 0)
        trace.reset_mock()
        self.search.search.reset_mock()
        await rank(self.config, self.store, self.search, Intent('Linkin Park'), trace=trace)
        events = {call.args[0]: call.args[1] for call in trace.event.call_args_list}
        self.assertEqual(events['local_matches']['exact_artists'], ['Linkin Park'])
        self.assertFalse(events['local_matches']['track_search_enabled'])
        self.assertNotIn('search_query', events)
        self.search.search.assert_not_called()

    async def test_fuzzy_artist_rank_and_same_name_explicit_track_override(self):
        result = await self.ranked('Play artist Linkn Park')
        self.assertEqual(result['candidates'][0]['artist'], 'Linkin Park')
        extra = self.store.documents(self.head['generation'])[0]
        from experiments.disc_assistant.assistant.ranking import infer
        self.assertEqual(infer(Intent('Numb'), [dict(extra, artist='Numb')], {}).kind, 'artist')
        self.assertEqual(infer(Intent('Numb', 'track'), [dict(extra, artist='Numb')], {}).kind, 'track')

    def test_requested_remaster_and_exact_alias_rank_like_metadata(self):
        docs = [{'id': 's:1', 'title': 'Numb (Remastered)', 'artist': 'Linkin Park', 'album': 'Meteora'},
                {'id': 's:0', 'title': 'Numb', 'artist': 'Linkin Park', 'album': 'Meteora'}]
        ordinary = ordered(score_tracks(Intent('Numb', 'track'), docs, {}))
        self.assertEqual(ordinary[0]['track_id'], 's:0')
        remaster = ordered(score_tracks(Intent('Numb remastered', 'track'), docs, {}, load_languages(('en',))))
        self.assertEqual([c['track_id'] for c in remaster], ['s:1'])

    async def test_projected_names_and_fuzzy_artist_boundary_without_aliases(self):
        self.config.aliases = {}
        for phrase, artist, title in [('Play Линкин Парк', 'Linkin Park', None),
                ('Play Linkn Park Numb', 'Linkin Park', 'Numb'),
                ('Play track Artist E - Tishina', 'Артист Ё', 'Тишина')]:
            result = await self.ranked(phrase)
            self.assertEqual(result['candidates'][0]['artist'], artist)
            self.assertEqual(result['candidates'][0].get('title'), title)
        self.search.search.assert_not_called()

    async def test_fused_names_require_explicit_catalog_backed_suffix(self):
        from experiments.disc_assistant.assistant.resolver import infer
        docs = self.store.documents(self.head['generation'])
        aliases = {'titles': {'Numb': ['намп']}}
        intent = infer(Intent('Линкин Паркнамп'), docs, aliases)
        self.assertEqual((intent.artist, intent.title), ('Linkin Park', 'намп'))
        unknown = Intent('Линкин Паркcompletelyunknown')
        self.assertEqual(infer(unknown, docs, aliases), Intent(unknown.query, 'track'))

    def test_literal_name_beats_alias_collision_and_fuzzy_boundary_tie_abstains(self):
        from experiments.disc_assistant.assistant.ranking import score_artists
        from experiments.disc_assistant.assistant.resolver import infer
        docs = [{'id': 's:0', 'artist': 'Linkin Park', 'title': 'Numb', 'album': 'A'},
                {'id': 's:1', 'artist': 'Lincoln Park', 'title': 'Numb', 'album': 'B'}]
        rows = ordered(score_artists(Intent('Lincoln Park'), docs,
                                     {'artists': {'Linkin Park': ['Lincoln Park']}}))
        self.assertEqual(rows[0]['artist'], 'Lincoln Park')
        docs[1]['artist'] = 'Linken Park'
        intent = Intent('Linkn Park Numb')
        self.assertEqual(infer(intent, docs, {}), intent)

    async def test_alias_cannot_leak_other_artist_into_explicit_canonical_scope(self):
        self.config.aliases = {'artists': {'Other Artist': ['Linkin Park']}}
        result = await self.ranked('Play Linkin Park - Numb')
        self.assertEqual({c['artist'] for c in result['candidates']}, {'Linkin Park'})

    async def test_unresolved_fused_suffix_does_not_launch_whole_artist(self):
        self.config.aliases = {}
        result = await self.ranked('Включи Линкин Паркнамп')
        self.assertEqual(result['candidates'], [])

    async def test_collaboration_matches_each_member_but_keeps_device_credit(self):
        from library.catalog import Track
        tracks = [Track('Stan', 'Eminem;Dido', 'Album', 0, {}),
                  Track('Other', 'Eminem', 'Solo', 0, {}),
                  Track('Stan', 'Someone Else', 'Cover', 0, {})]
        self.head = self.store.publish('test', tracks, {}, expected_generation=self.head['generation'])
        self.store.publish_index('test', self.head['generation'], 'index', 'sig')
        self.config.aliases = {'artists': {'Dido': ['дайдо']}}
        for phrase in ('Play Eminem — Stan', 'Play Dido — Stan', 'Play Dido Stan',
                       'Включи дайдо Stan', 'Play Eminem;Dido — Stan'):
            with self.subTest(phrase=phrase):
                result = await self.ranked(phrase)
                self.assertEqual([c['artist'] for c in result['candidates']], ['Eminem;Dido'])
                self.assertEqual(result['candidates'][0]['title'], 'Stan')
        self.search.search.assert_not_called()
        artist = await self.ranked('Play artist Dido')
        self.assertEqual(artist['candidates'][0]['artist'], 'Eminem;Dido')

    async def test_member_alias_cannot_override_literal_member_and_fuzzy_retrieval_is_scoped(self):
        from library.catalog import Track
        tracks = [Track('Stan', 'Eminem;Dido', 'Album', 0, {}),
                  Track('Stan', 'Wrong;Guest', 'Cover', 0, {})]
        self.head = self.store.publish('test', tracks, {}, expected_generation=self.head['generation'])
        self.store.publish_index('test', self.head['generation'], 'index', 'sig')
        self.config.aliases = {'artists': {'Guest': ['Dido']}}
        docs = self.store.documents(self.head['generation'])
        self.search.search.return_value = {'generation': self.head['generation'], 'found': 2, 'candidates': docs}
        result = await self.ranked('Play Dido — Stann')
        self.assertEqual(result['retrieval']['source'], 'typesense')
        self.assertEqual([c['artist'] for c in result['candidates']], ['Eminem;Dido'])
        self.assertIn('artists', self.search.search.call_args.kwargs['fields'])
