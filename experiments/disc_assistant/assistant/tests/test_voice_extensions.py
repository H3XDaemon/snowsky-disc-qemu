"""New voice commands share text interpretation and safe Controller dispatch."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import AsyncMock, Mock, patch

from experiments.disc_assistant.assistant.nlu.intents import ControlIntent, VolumeIntent, Intent
from experiments.disc_assistant.assistant.nlu.interpreter import interpret_request, InterpretationContext, validate_intent
from experiments.disc_assistant.assistant.config import load
from experiments.disc_assistant.assistant.responses import attach_response
from experiments.disc_assistant.assistant.nlu import command_catalog
from experiments.disc_assistant.assistant import context
from experiments.disc_assistant.assistant.controls import execute
from experiments.disc_assistant.assistant.ranking import rank
from library.store import Store
from controller.catalog import CatalogChanged
from controller.tests.test_current import FakeClient
from controller.compatibility import CONTRACTS, Capability


class VoiceExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'config.toml'
        self.base = f'[device]\nkey="test"\nhost="localhost"\n[storage]\ndata_dir="{self.tmp.name}/data"\n'
        self.path.write_text(self.base)
        self.config = load(self.path)

    def interpret(self, text, locale='ru'):
        return asyncio.run(interpret_request(text, InterpretationContext(locale)))

    def test_requested_russian_aliases_and_english_controls(self):
        for text, action in [('Лайк', 'like'), ('Нравится', 'like'), ('Дизлайк', 'dislike'), ('Не нравится', 'dislike'),
                             ('Какой трек сейчас играет', 'now_playing'), ('Какая песня сейчас играет', 'now_playing'),
                             ('Что сейчас играет?', 'now_playing'), ('Что играет', 'now_playing')]:
            self.assertEqual(self.interpret(text), ControlIntent(action))
        for text, action in [('Like', 'like'), ('Unlike', 'dislike'), ('What is playing?', 'now_playing')]:
            self.assertEqual(self.interpret(text, 'en'), ControlIntent(action))

    def test_absolute_spoken_numbers_and_configured_relative_steps(self):
        for text, value, locale in [('Громкость 0', 0, 'ru'), ('Громкость сто двадцать', 120, 'ru'),
                                    ('Громкость сорок пять', 45, 'ru'), ('Volume one hundred and five', 105, 'en'),
                                    ('Volume twenty-five', 25, 'en')]:
            self.assertEqual(self.interpret(text, locale), VolumeIntent(value=value))
        self.path.write_text(self.base+'[volume]\nup_step=7\ndown_step=11\n')
        config = load(self.path)
        for text, expected in [('Сделай тише', 19), ('Тише', 19), ('Сделай громче', 37), ('Громче', 37)]:
            client = FakeClient()
            result = execute(config, self.interpret(text), shared=client)
            self.assertEqual(result['status'], 'confirmed')
            self.assertEqual(client.volume, expected)
        self.assertEqual((self.config.volume_up_step, self.config.volume_down_step), (20, 20))

    def test_bad_numbers_compounds_negations_and_other_locale_never_dispatch(self):
        for text in ('Громкость 121', 'Громкость -1', 'Громкость 20.5', 'Громкость много', 'Не лайк',
                     'Не делай громче', 'Лайк и следующий', 'Громкость 20 и пауза', 'Тише, затем лайк', 'Like'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.interpret(text)
        for intent in (VolumeIntent(value=True), VolumeIntent(value=121), VolumeIntent(value=20, direction='up'),
                       VolumeIntent(direction='sideways')):
            with self.assertRaises(ValueError):
                validate_intent(intent)
        self.assertEqual(self.interpret('Включи «Не нравится»'), Intent('Не нравится'))

    def test_invalid_config_never_silently_uses_default(self):
        for value in ('0', '121', 'true', '"20"', '1.5'):
            self.path.write_text(self.base+'[volume]\nup_step='+value+'\n')
            with self.assertRaises(ValueError):
                load(self.path)

    def test_question_replies_even_in_errors_mode_but_respects_none(self):
        client = FakeClient()
        client.state['song']['song_file_path'] = '/tmp/sdcard/synthetic.flac'
        for state, code in [(0, 'playback.current'), (1, 'playback.current_paused')]:
            client.state['state'] = state
            result = execute(self.config, ControlIntent('now_playing'), shared=client)
            from controller.controls import identity
            self.assertEqual(identity(result['state']), identity(client.state))
            self.assertEqual(result['state']['song']['song_file_path'], '/tmp/sdcard/synthetic.flac')
            reply = attach_response(self.config, result)['response']
            self.assertEqual(reply['code'], code)
            self.assertIn('Track', reply['text'])
            self.assertTrue(reply['speak'])
            self.assertFalse(attach_response(replace(self.config, response_mode='none'), result)['response']['speak'])
        client.state = {}
        reply = attach_response(self.config, execute(self.config, ControlIntent('now_playing'), shared=client))
        self.assertEqual(reply['response']['code'], 'playback.unavailable')
        client.raw.sendall.assert_not_called()

    def test_new_firmware_requires_explicit_reviewed_capability(self):
        client = FakeClient()
        client.settings = Mock(return_value={'soc_version': 260, 'currentVolume': 30})
        self.assertEqual(execute(self.config, ControlIntent('like'), shared=client)['status'], 'not_sent')
        client.raw.sendall.assert_not_called()
        with patch.dict(CONTRACTS, {260: frozenset({Capability.CURRENT_FAVORITE})}):
            self.assertEqual(execute(self.config, ControlIntent('like'), shared=client)['status'], 'confirmed')
        self.assertNotIn(260, CONTRACTS)

    def test_one_shot_context_uses_one_owned_client_through_dispatch(self):
        from contextlib import redirect_stdout
        import io
        from experiments.disc_assistant.assistant import __main__ as cli
        from library.tests.helpers import TRACKS
        from library.search.typesense import signature
        with Store(self.config.data_dir) as store:
            head = store.publish('test', TRACKS, {}, expected_generation=None)
            store.publish_index('test', head['generation'], 'test', signature({}, ['http', '127.0.0.1', 8108]))
        client = FakeClient()
        borrowed = Mock()
        borrowed.__enter__ = Mock(return_value=client)
        borrowed.__exit__ = Mock(return_value=False)
        sdk = Mock()
        sdk.api_call.aclose = AsyncMock()
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'synthetic'}), \
                patch.object(cli, 'create_client', return_value=sdk), \
                patch('experiments.disc_assistant.assistant.device.PlaybackClient', return_value=borrowed) as opened, \
                patch.object(context, 'read', return_value=None) as read, \
                patch.object(cli, 'execute', return_value={'status': 'playing'}) as execute, \
                redirect_stdout(io.StringIO()):
            code = cli.main(['--config', str(self.path), 'ask', 'Включи Numb'])
        self.assertEqual(code, 0)
        opened.assert_called_once()
        read.assert_called_once()
        self.assertIs(read.call_args.args[1], client)
        self.assertIs(execute.call_args.kwargs['shared'], client)
        borrowed.__exit__.assert_called_once()

    def test_volume_shadow_evidence_can_be_exported_and_reviewed(self):
        from dataclasses import asdict
        from experiments.disc_assistant.assistant.nlu.interpretation_sources import LiteralSource
        from experiments.disc_assistant.assistant.nlu.evaluation.shadow_report import source_result
        evidence = asyncio.run(LiteralSource().evaluate('Volume forty', InterpretationContext('en')))
        result = source_result(asdict(evidence), 'Volume forty')
        self.assertEqual(result['intent']['value'], 40)
        self.assertEqual(result['label'], 'volume')

    def test_locale_templates_have_no_training_examples_and_references_are_optional(self):
        for locale in ('ru', 'en'):
            raw = tomllib.loads((command_catalog.DIRECTORY/(locale+'.toml')).read_text())
            self.assertNotIn('examples', raw)
            expected = tomllib.loads((command_catalog.REFERENCES/(locale+'.toml')).read_text())['examples']
            self.assertEqual(command_catalog.source(locale)['examples'], expected)
        with patch.object(command_catalog, 'REFERENCES', Path(self.tmp.name)):
            self.assertEqual(command_catalog.source('en')['examples'], [])
        bad = Path(self.tmp.name)/'en.toml'
        bad.write_text('version=1\nlocale="ru"\nexamples=[]\n')
        with patch.object(command_catalog, 'REFERENCES', bad.parent), self.assertRaises(ValueError):
            command_catalog.source('en')


class ContextRankingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.close)
        # Same titles in distinct albums/artists expose global alphabetical bias.
        tracks = [{'title': title, 'artist': artist, 'album': album, 'path': f'/test/{i}.flac'}
                  for i, (title, artist, album) in enumerate([
                      ('Song', 'A Other', 'A Global'), ('Song', 'Z Artist', 'B Album'),
                      ('Song', 'Z Artist', 'Z Album'), ('Hidden', 'Z Artist', 'B Album'),
                      ('Remote', 'A Other', 'A Global')])]
        # Store accepts the same catalog projection used by the synthetic fixtures.
        from library.catalog import Track
        tracks = [Track(t['title'], t['artist'], t['album'], 0, {'pos': 0, 'name': t['title'], 'author': t['artist']}) for t in tracks]
        head = self.store.publish('test', tracks, {}, expected_generation=None)
        self.store.publish_index('test', head['generation'], 'index', 'sig')
        self.docs = self.store.documents(head['generation'])
        self.config = Mock(device_key='test', aliases={}, locale='en')
        self.search = Mock(signature='sig', search=AsyncMock(return_value={'generation': head['generation'], 'found': 0, 'candidates': []}))
        self.context = self.observation([self.docs[2]], 7)

    def observation(self, docs, source):
        doc = docs[0]
        return {'state': {'state': 0, 'playerflag': source, 'song': {'song_name': doc['title'],
            'song_artist_name': doc['artist'], 'song_album_name': doc['album'], 'pos_id': 1}},
            'items': [{'pos': i, 'name': d['title'], 'author': d['artist']} for i,d in enumerate(docs)],
            'mark': 0, 'playback_known': True}

    async def ranked(self, query, context_value=None):
        return await rank(self.config, self.store, self.search, query,
                          context=self.context if context_value is None else context_value)

    async def test_album_then_artist_then_global_and_explicit_override(self):
        result = await self.ranked(Intent('Song'))
        self.assertEqual(result['candidates'][0]['album'], 'Z Album')
        self.assertEqual(result['retrieval']['scope'], 'album')
        result = await self.ranked(Intent('Hidden'))
        self.assertEqual(result['retrieval']['scope'], 'artist')
        result = await self.ranked(Intent('Remote'))
        self.assertEqual(result['candidates'][0]['artist'], 'A Other')
        self.assertNotIn('playback_context', result)
        result = await self.ranked(Intent('A Other Song'))
        self.assertEqual(result['candidates'][0]['artist'], 'A Other')
        result = await self.ranked(Intent('A Other', 'artist'))
        self.assertEqual(result['candidates'][0]['kind'], 'artist')

    async def test_artist_scope_has_no_current_album_preference(self):
        value = self.observation([d for d in self.docs if d['artist']=='Z Artist'], 7)
        result = await self.ranked(Intent('Song'), value)
        self.assertEqual(result['retrieval']['scope'], 'artist')
        self.assertEqual(result['candidates'][0]['album'], 'B Album')

    async def test_unknown_playlist_or_mismatched_queue_does_not_bias(self):
        for source in (1, 5, 6, 99):
            value = deepcopy(self.context)
            value['state']['playerflag'] = source
            result = await self.ranked(Intent('Song'), value)
            self.assertEqual(result['candidates'][0]['artist'], 'A Other')
        value = deepcopy(self.context)
        value['items'][0]['name']='Changed'
        self.assertEqual(context.scopes(value, self.docs), [])

    async def test_missing_version_does_not_substitute_another_recording(self):
        result = await self.ranked(Intent('Song live'))
        self.assertEqual(result['status'], 'not_found')

    def test_context_read_uses_reviewed_client_and_unknown_playback_falls_back(self):
        client = FakeClient()
        value = {**self.context, 'playback_known': True}
        with patch.object(context, 'snapshot', return_value=value) as snapshot:
            self.assertEqual(context.read(self.config, client), value)
            snapshot.assert_called_once()
            snapshot.reset_mock()
            client.state = {}
            self.assertIsNone(context.read(self.config, client))
            snapshot.assert_not_called()

    def test_stale_context_preflight_rejects_changed_identity_or_membership(self):
        changed = deepcopy(self.context)
        changed['state']['song']['song_name']='Other'
        with patch.object(context, 'read', return_value=changed), self.assertRaises(CatalogChanged):
            context.verify(self.config, Mock(), self.context)
