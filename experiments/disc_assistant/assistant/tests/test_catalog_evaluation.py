"""Selection evaluation is a preview; recognition agreement is a separate metric."""
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from experiments.disc_assistant.assistant.voice.catalog_evaluation import CatalogEvaluation, validate_targets
from experiments.disc_assistant.assistant.tests import test_voice_files as fixtures
from experiments.disc_assistant.assistant.speech import Transcription
from experiments.disc_assistant.assistant.voice import catalog_evaluation
from library.store import Store, StaleSnapshot
from library.search.typesense import signature
from library.tests.helpers import TRACKS


class CatalogVoiceTests(unittest.TestCase):
    setUp = fixtures.VoiceFileTests.setUp
    invoke = fixtures.VoiceFileTests.invoke

    def test_catalog_selection_can_pass_while_reference_text_differs(self):
        directory = self.root / 'corpus'
        corpus = self.root / 'corpus.json'
        case = {'id': 'artist', 'text': 'Play Linkin Park', 'expected': {
            'status': 'recognized', 'intent': {'query': 'Linkin Park', 'kind': 'auto', 'artist': None, 'title': None}},
            'selection': {'kind': 'artist', 'artist': 'Linkin Park'}}
        corpus.write_text(json.dumps({'version': 1, 'locale': 'en', 'cases': [case]}))
        self.assertEqual(self.invoke('speech-samples', directory, '--corpus', corpus)[0], 0)
        with Store(self.config.data_dir) as store:
            head = store.publish('test', TRACKS, {}, expected_generation=None)
            store.publish_index('test', head['generation'], 'fixture', signature({}, ['http', '127.0.0.1', 8108]))
        self.provider.transcribe.return_value = Transcription('Play Линкин Парк.', 'en')
        client = Mock()
        client.api_call.aclose = AsyncMock()
        from experiments.disc_assistant.assistant import __main__ as cli
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'fixture'}), \
                patch.object(catalog_evaluation, 'create_client', return_value=client), \
                patch.object(cli, 'control') as control, patch.object(cli, 'execute') as play:
            code, result = self.invoke('speech-check', directory, '--catalog')
        self.assertEqual(code, 0, result)
        self.assertEqual((result['selection_passed'], result['selection_total']), (1, 1))
        self.assertEqual(result['interpretation_passed'], 0)
        self.assertFalse(result['cases'][0]['transcription_match'])
        self.assertIsNone(result['cases'][0]['failed_stage'])
        control.assert_not_called()
        play.assert_not_called()
        client.api_call.aclose.assert_awaited_once()

    def test_targets_are_explicit_and_locale_scoped(self):
        case = {'id': 'track', 'expected': {'status': 'recognized', 'intent': {'query': 'Missing'}}}
        for overlay in ([], {}, {'version': 1, 'locale': 'ru', 'selections': {'track': None}},
                        {'version': 1, 'locale': 'en', 'selections': {}},
                        {'version': 1, 'locale': 'en', 'selections': {'track': {'kind': 'track', 'title': 'X'}}}):
            with self.assertRaises(ValueError):
                validate_targets([case], overlay, 'en')
        self.assertEqual(validate_targets([case], {'version': 1, 'locale': 'en',
                                                 'selections': {'track': None}}, 'en'), {'track': None})


class CatalogStageTests(unittest.IsolatedAsyncioTestCase):
    async def test_stage_attribution_absence_and_stale_abort(self):
        evaluator = CatalogEvaluation(Mock(), {'track': {'kind': 'track', 'artist': 'A', 'title': 'T', 'album': 'B'}}, Mock())
        evaluator.verify = Mock()
        evaluator.store = Mock()
        evaluator.search = Mock()
        case = {'id': 'track'}
        actual = {'status': 'recognized', 'intent': {'query': 'T'}}
        self.assertEqual((await evaluator.evaluate(case, {'status': 'unrecognized'}))['failed_stage'], 'interpretation')
        result = {'candidates': [], 'retrieval': {'found': 0}, 'candidate_count': 0, 'ranking_policy': 'fixture'}
        with patch.object(catalog_evaluation, 'rank', AsyncMock(return_value=result)) as rank:
            self.assertEqual((await evaluator.evaluate(case, actual))['failed_stage'], 'retrieval')
            result['retrieval']['found'] = 3
            self.assertEqual((await evaluator.evaluate(case, actual))['failed_stage'], 'ranking')
            evaluator.targets['track'] = None
            self.assertTrue((await evaluator.evaluate(case, actual))['passed'])
            rank.side_effect = OSError('private endpoint')
            error = await evaluator.evaluate(case, actual)
            self.assertEqual(error['failed_stage'], 'search')
            self.assertNotIn('private endpoint', json.dumps(error))
            rank.side_effect = StaleSnapshot('changed')
            with self.assertRaises(StaleSnapshot):
                await evaluator.evaluate(case, actual)
