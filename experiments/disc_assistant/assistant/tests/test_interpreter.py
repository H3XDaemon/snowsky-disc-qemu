"""Provider substitution, execution boundaries and interpretation evidence."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from experiments.disc_assistant.assistant import __main__ as cli
from experiments.disc_assistant.assistant.config import load
from experiments.disc_assistant.assistant.console import Application
from experiments.disc_assistant.assistant.nlu.interpreter import (
    Interpretation, InterpretationContext, RuleInterpreter, interpret_request,
)
from experiments.disc_assistant.assistant.nlu.intents import Intent, ControlIntent, LanguageIntent
from experiments.disc_assistant.assistant.journal import Trace, history_command
from experiments.disc_assistant.assistant.providers import ProviderInfo, ProviderUnavailable, InvalidProviderResult
from library.tests.helpers import TRACKS
from library.store import Store
from library.search.typesense import signature


class InterpreterTests(unittest.IsolatedAsyncioTestCase):
    async def test_russian_past_track_alias_preserves_titles_and_guards(self):
        ru = InterpretationContext('ru')
        for phrase in ('прошлый', 'Прошлый трек'):
            self.assertEqual(await interpret_request(phrase, ru), ControlIntent('previous'))
        for phrase in ('не прошлый', 'прошлый и пауза', 'прошлый год'):
            with self.assertRaises(ValueError):
                await interpret_request(phrase, ru)
        with self.assertRaises(ValueError):
            await interpret_request('прошлый', InterpretationContext('en'))
        self.assertEqual(await interpret_request('Включи трек Прошлый', ru), Intent('Прошлый', 'track'))

    async def test_observed_russian_stt_variant_is_a_whole_control_not_a_global_rewrite(self):
        ru = InterpretationContext('ru')
        for phrase in ('следующий трак', 'Следующий   трак'):
            self.assertEqual(await interpret_request(phrase, ru), ControlIntent('next'))
        for phrase in ('не следующий трак', 'следующий трак и пауза', 'следующий трактор'):
            with self.assertRaises(ValueError):
                await interpret_request(phrase, ru)
        with self.assertRaises(ValueError):
            await interpret_request('следующий трак', InterpretationContext('en'))
        self.assertEqual(await interpret_request('Включи трек «Следующий трак»', ru),
                         Intent('Следующий трак', 'track'))

    async def test_single_locale_preserves_music_names_and_rejects_other_command_languages(self):
        ru = InterpretationContext('ru')
        self.assertEqual(await interpret_request('Включи Linkin Park — Numb', ru),
                         Intent('Linkin Park — Numb', 'track', 'Linkin Park', 'Numb'))
        with self.assertRaises(ValueError):
            await interpret_request('Play Numb', ru)
        with self.assertRaises(ValueError):
            await interpret_request('Включи Numb', InterpretationContext('en'))
        self.assertEqual(await interpret_request('Включи трек Пауза', ru), Intent('Пауза', 'track'))
        self.assertEqual(await interpret_request('Включи Numb', ru), Intent('Numb'))

    async def test_local_and_remote_providers_share_validation(self):
        for execution in ('local', 'remote'):
            provider = Mock(info=ProviderInfo('fixture', '1', execution))
            provider.interpret = AsyncMock(return_value=Interpretation('recognized', ControlIntent('pause')))
            context = InterpretationContext('en', 'playing', ('Linkin Park',))
            self.assertEqual(await interpret_request('please pause', context, interpreter=provider), ControlIntent('pause'))
            provider.interpret.assert_awaited_once_with('please pause', context)
            self.assertFalse(hasattr(context, 'session'))

    async def test_invalid_results_never_cross_execution_boundary(self):
        invalid = [None, {'status': 'recognized', 'intent': {'action': 'pause'}},
            Interpretation('recognized', ControlIntent('delete')),
            Interpretation('recognized', LanguageIntent('../en')),
            Interpretation('recognized', Intent('', 'track')),
            Interpretation('recognized', Intent('Numb', 'shell')),
            Interpretation('recognized', Intent('Numb', 'track', 'LP', None)),
            Interpretation('unrecognized', ControlIntent('pause')),
            Interpretation('unknown')]
        for result in invalid:
            with self.subTest(result=result):
                provider = Mock(info=ProviderInfo('fixture', '1', 'remote'),
                                interpret=AsyncMock(return_value=result))
                with self.assertRaises(InvalidProviderResult):
                    await interpret_request('Pause', InterpretationContext('en'), interpreter=provider)

    async def test_provider_unavailable_is_distinct_from_unrecognized_and_no_fallback_occurs(self):
        provider = Mock(info=ProviderInfo('fixture', '1', 'remote'), interpret=AsyncMock(side_effect=TimeoutError))
        with patch.object(RuleInterpreter, 'interpret', side_effect=AssertionError('fallback')):
            with self.assertRaises(ProviderUnavailable):
                await interpret_request('Pause', InterpretationContext('en'), interpreter=provider)
        provider.interpret.assert_awaited_once()
        with self.assertRaises(ValueError):
            await interpret_request('unrelated prose', InterpretationContext('en'))

    async def test_cancellation_is_propagated(self):
        provider = Mock(info=ProviderInfo('fixture', '1', 'remote'),
                        interpret=AsyncMock(side_effect=asyncio.CancelledError))
        with self.assertRaises(asyncio.CancelledError):
            await interpret_request('Pause', InterpretationContext('en'), interpreter=provider)

    async def test_invalid_input_does_not_reach_provider(self):
        provider = Mock(info=ProviderInfo('fixture', '1', 'remote'), interpret=AsyncMock())
        for text in ('', 'x' * 1001, 'Pause\nResume', None):
            with self.assertRaises(ValueError):
                await interpret_request(text, InterpretationContext('en'), interpreter=provider)
        provider.interpret.assert_not_called()


class InterpretationFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.path = root / 'config.toml'
        self.path.write_text(f'[device]\nkey="fixture"\nhost="127.0.0.1"\n[storage]\ndata_dir="{root}/data"\n'
                             '[language]\nlocale="en"\n')
        self.config = load(self.path)

    def provider(self, result=None, error=None):
        return Mock(info=ProviderInfo('fixture', 'v1', 'remote'),
                    interpret=AsyncMock(return_value=result, side_effect=error))

    def invoke(self, provider, *args):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = cli.main(['--config', str(self.path), *args], interpreter=provider)
        return code, json.loads(output.getvalue())

    def test_console_and_cli_music_interpret_once_and_resolve_catalog_separately(self):
        store = Store(self.config.data_dir)
        self.addCleanup(store.close)
        head = store.publish('fixture', TRACKS, {}, expected_generation=None)
        store.publish_index('fixture', head['generation'], 'fixture', signature({}, ['http', '127.0.0.1', 8108]))
        provider = self.provider(Interpretation('recognized', Intent('Linkin Park Numb')))
        sdk = Mock()
        sdk.api_call.aclose = AsyncMock()
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'fixture'}), \
                patch.object(cli, 'create_client', return_value=sdk), \
                patch.object(cli, 'execute', return_value={'status': 'playing'}) as execute:
            code, result = self.invoke(provider, 'ask', 'some external phrasing')
        self.assertEqual(code, 0)
        provider.interpret.assert_awaited_once()
        self.assertEqual(execute.call_args.args[2]['candidates'][0]['title'], 'Numb')
        record = history_command(self.config, ['show', result['request_id']])
        events = [e for e in record['events'] if e['phase'] == 'interpretation_started']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['payload']['provider']['execution'], 'remote')
        self.assertEqual(record['context']['locale'], 'en')
        provider.interpret.reset_mock()
        app = Application(self.config, interpreter=provider)
        app.store = store
        app.session = Mock()
        app.session.status.return_value = {'connection': 'ready', 'generation': 1,
                                           'observation': {'playback': 'playing'}}
        app.device_call = Mock(return_value={'status': 'playing'})
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'fixture'}), \
                patch('experiments.disc_assistant.assistant.application.create_client', return_value=sdk):
            app.request('some external phrasing')
        provider.interpret.assert_awaited_once()
        app.device_call.assert_called_once()

    def test_provider_failures_are_journaled_and_never_execute(self):
        for provider, expected in (
                (self.provider(error=ProviderUnavailable('private-body')), 'interpreter.unavailable'),
                (self.provider(Interpretation('unsupported')), 'command.unsupported'),
                (self.provider(Interpretation('recognized', ControlIntent('delete'))), 'interpreter.invalid')):
            with patch.object(cli, 'control') as control, patch.object(cli, 'execute') as execute:
                code, result = self.invoke(provider, 'ask', 'Pause')
            self.assertEqual(code, 1)
            self.assertEqual(result['response']['code'], expected)
            control.assert_not_called()
            execute.assert_not_called()
            record = history_command(self.config, ['show', result['request_id']])
            self.assertNotIn('private-body', json.dumps(record))

    def test_connection_change_during_interpretation_does_not_dispatch(self):
        provider = self.provider()
        app = Application(self.config, interpreter=provider)
        state = {'connection': 'ready', 'generation': 1}
        app.session = Mock()
        app.session.status.side_effect = lambda: dict(state)
        app.device_call = Mock()
        async def interpret(text, context):
            state['generation'] += 1
            return Interpretation('recognized', ControlIntent('pause'))
        provider.interpret.side_effect = interpret
        result = app.request('Pause')
        self.assertEqual(result['status'], 'not_sent')
        app.device_call.assert_not_called()

    def test_cancelled_interpretation_is_recorded_as_interrupted(self):
        provider = self.provider(error=asyncio.CancelledError())
        app = Application(self.config, interpreter=provider)
        app.device_call = Mock()
        with self.assertRaises(asyncio.CancelledError):
            app.request('Pause')
        row = history_command(self.config)['requests'][0]
        self.assertEqual(row['status'], 'interrupted')
        app.device_call.assert_not_called()

    def test_rank_language_intent_never_mutates_preferences(self):
        provider = self.provider(Interpretation('recognized', LanguageIntent('ru')))
        self.assertEqual(self.invoke(provider, 'rank', 'external language request')[1]['status'], 'planned')
        self.assertEqual(Application(self.config).config.locale, 'en')
