from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from experiments.disc_assistant.assistant import __main__ as cli
from experiments.disc_assistant.assistant.config import load
from experiments.disc_assistant.assistant.console import Application
from experiments.disc_assistant.assistant.journal import Journal, Trace, JournalWriteError, history_command
from experiments.disc_assistant.assistant.preferences import language_command
from library.store import Store
from library.search.typesense import signature
from library.tests.helpers import TRACKS


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'config.toml'
        self.path.write_text(f'[device]\nkey="test"\nhost="127.0.0.1"\n'
                             f'[storage]\ndata_dir="{self.root}/data"\n[language]\nlocale="en"\n')
        self.config = load(self.path)

    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = cli.main(['--config', str(self.path), *args])
        return code, json.loads(output.getvalue()) if output.getvalue() else None

    def latest(self):
        request_id = history_command(self.config)['requests'][0]['id']
        return history_command(self.config, ['show', request_id])

    def fixture(self):
        store = Store(self.config.data_dir)
        self.addCleanup(store.close)
        head = store.publish('test', TRACKS, {}, expected_generation=None)
        sig = signature({}, ['http', '127.0.0.1', 8108])
        store.publish_index('test', head['generation'], 'fixture', sig)
        client = Mock()
        client.api_call.aclose = AsyncMock()
        return store, client

    def test_v1_migration_preserves_settings_and_separate_catalog(self):
        self.config.data_dir.mkdir()
        path = self.config.data_dir / 'assistant.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript("CREATE TABLE settings(key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT);"
                             "INSERT INTO settings VALUES('language.enabled','[\"ru\"]','old');"
                             'PRAGMA user_version=1;')
        with Journal(self.config) as journal:
            self.assertEqual(journal.db.execute('PRAGMA user_version').fetchone()[0], 3)
        self.assertEqual(language_command(self.config)['locale'], 'ru')
        self.assertFalse((self.config.data_dir / 'library.sqlite3').exists())

    def test_cli_invalid_command_is_recorded_before_parsing(self):
        self.assertEqual(self.invoke('ask', '  включи что-нибудь?\nnext  ')[0], 1)
        row = self.latest()
        self.assertEqual(row['input'], '  включи что-нибудь?\nnext  ')
        self.assertEqual(row['normalized_input'], 'включи что-нибудь? next')
        self.assertEqual(row['status'], 'error')
        self.assertEqual(row['events'][-2]['payload']['category'], 'unrecognized_or_invalid_command')
        self.assertNotIn('execution_started', [e['phase'] for e in row['events']])

    def test_scheduled_control_result_links_operation_without_search(self):
        with patch.object(cli, 'control', return_value={'status': 'uncertain', 'operation_id': 'op-1',
                          'mutation_attempted': True, 'reason': 'private error body'}) as execute:
            code, result = self.invoke('--source', 'scheduled', 'ask', 'Pause')
        self.assertEqual(code, 1)
        self.assertEqual(execute.call_count, 1)
        row = self.latest()
        self.assertEqual(row['source'], 'scheduled')
        self.assertEqual(row['id'], result['request_id'])
        self.assertEqual(row['outcome']['operation_id'], 'op-1')
        self.assertTrue(row['outcome']['mutation_attempted'])
        self.assertNotIn('private error body', json.dumps(row))

    def test_confirmation_observation_survives_uncertain_result(self):
        observation = {'last_observed': {'state': 0, 'album': 'Fixture Extended Edit'}}
        with patch.object(cli, 'control', return_value={'status': 'uncertain',
                          'mutation_attempted': True, 'confirmation': observation}):
            self.assertEqual(self.invoke('ask', 'Pause')[0], 1)
        self.assertEqual(self.latest()['outcome']['confirmation'], observation)

    def test_cli_music_records_ranking_selection_and_confirmed_result(self):
        store, client = self.fixture()
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'secret-marker'}), \
                patch.object(cli, 'create_client', return_value=client), \
                patch.object(cli, 'execute', return_value={'status': 'playing', 'operation_id': 'op-play',
                                                         'mutation_attempted': True}) as execute:
            self.assertEqual(self.invoke('ask', 'Play Linkin Park - Numb')[0], 0)
        row = self.latest()
        events = {e['phase']: e['payload'] for e in row['events']}
        self.assertEqual(events['parsed']['artist'], 'Linkin Park')
        self.assertEqual(events['ranking']['candidates'][0]['album'], 'Meteora')
        self.assertEqual(events['selection']['method'], 'automatic_best_match')
        self.assertEqual(events['selection']['candidate']['track_id'],
                         execute.call_args.args[2]['candidates'][0]['track_id'])
        self.assertEqual(events['catalog']['generation'], store.head('test')['generation'])
        self.assertNotIn('secret-marker', json.dumps(row))
        self.assertEqual(row['outcome']['operation_id'], 'op-play')

    def test_rank_has_candidates_but_no_selection_or_execution(self):
        store, client = self.fixture()
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'synthetic'}), \
                patch.object(cli, 'create_client', return_value=client), patch.object(cli, 'execute') as execute:
            self.assertEqual(self.invoke('rank', 'Play Cue entry')[0], 0)
        row = self.latest()
        phases = [e['phase'] for e in row['events']]
        self.assertIn('ranking', phases)
        self.assertNotIn('selection', phases)
        self.assertNotIn('execution_started', phases)
        candidates = next(e['payload']['candidates'] for e in row['events'] if e['phase'] == 'ranking')
        self.assertEqual(len(candidates), 2)
        self.assertNotEqual(candidates[0]['track_id'], candidates[1]['track_id'])
        execute.assert_not_called()
        # Exact matches can also exceed the ranker's top ten, without Typesense.
        head = store.publish('test', TRACKS[5:] * 10, {}, expected_generation=store.head('test')['generation'])
        store.publish_index('test', head['generation'], 'fixture', signature({}, ['http', '127.0.0.1', 8108]))
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'synthetic'}), \
                patch.object(cli, 'create_client', return_value=client):
            self.assertEqual(self.invoke('rank', 'Play Cue entry')[0], 0)
        ranked = next(e['payload'] for e in self.latest()['events'] if e['phase'] == 'ranking')
        self.assertEqual(ranked['candidate_count'], 20)
        self.assertEqual(len(ranked['candidates']), 10)
        self.assertTrue(ranked['truncated'])

    def test_search_failures_and_no_matches_are_different(self):
        self.fixture()
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(self.invoke('search', 'Numb')[0], 1)
        failure = self.latest()
        self.assertEqual(failure['events'][-2]['payload']['category'], 'search_unavailable_or_invalid')
        search = Mock()
        search.api_call.aclose = AsyncMock()
        result = {'generation': 'fixture', 'found': 0, 'candidates': [], 'query': 'Missing'}
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'synthetic'}), \
                patch.object(cli, 'create_client', return_value=search), \
                patch.object(cli.Search, 'search', new=AsyncMock(return_value=result)):
            self.assertEqual(self.invoke('search', 'Missing')[0], 0)
        latest = self.latest()
        self.assertEqual(latest['status'], 'completed')
        self.assertEqual(next(e['payload']['found'] for e in latest['events'] if e['phase'] == 'retrieval'), 0)

    def test_console_and_cli_share_journal_and_console_session_id(self):
        app = Application(self.config)
        app.request('/rank Pause')
        with self.assertRaises(ValueError):
            app.request('неизвестная команда')
        rows = history_command(self.config)['requests']
        details = [history_command(self.config, ['show', r['id']]) for r in rows]
        self.assertEqual({r['source'] for r in details}, {'interactive'})
        self.assertEqual({r['session_id'] for r in details}, {app.session_id})
        before = len(rows)
        app.request('/history')
        self.assertEqual(len(history_command(self.config)['requests']), before)
        self.invoke('rank', 'Pause')
        self.assertEqual(self.latest()['source'], 'cli')

    def test_console_music_and_search_errors_keep_decision_evidence(self):
        store, client = self.fixture()
        app = Application(self.config)
        app.store = store
        app.session = Mock()
        app.session.status.return_value = {'generation': 7, 'connection': 'ready'}
        app.device_call = Mock(return_value={'status': 'not_sent', 'operation_id': 'op-no'})
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'synthetic'}), \
                patch('experiments.disc_assistant.assistant.application.create_client', return_value=client):
            app.request('Play Linkin Park - Numb')
        row = self.latest()
        self.assertEqual(row['status'], 'not_sent')
        self.assertIn('selection', [e['phase'] for e in row['events']])
        self.assertEqual(row['events'][0]['payload']['generation'], 7)
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'synthetic'}), \
                patch('experiments.disc_assistant.assistant.application.create_client', side_effect=RuntimeError('secret-body')):
            with self.assertRaises(RuntimeError):
                app.request('Play Numb')
        self.assertNotIn('secret-body', json.dumps(self.latest()))

    def test_candidate_retention_is_bounded_and_reports_truncation(self):
        result = {'found': 100, 'query': 'query', 'generation': 'old',
                  'candidates': [{'id': f'old:{i}', 'title': str(i)} for i in range(50)]}
        with Trace(self.config, 'search', 'query') as trace:
            trace.search(result, phase='retrieval')
            trace.finish(result)
        payload = self.latest()['events'][0]['payload']
        self.assertEqual(len(payload['candidates']), 10)
        self.assertEqual(payload['returned_count'], 50)
        self.assertTrue(payload['truncated'])

    def test_long_invalid_input_is_bounded_and_explicitly_marked(self):
        self.invoke('ask', 'x' * 5000)
        self.assertEqual(len(self.latest()['input']), 4000)
        self.assertTrue(self.latest()['input_truncated'])

    def test_pending_and_interrupted_requests_are_not_reported_as_success(self):
        trace = Trace(self.config, 'ask', 'Pause')
        trace.__enter__()
        trace.event('execution_started', {'action': 'pause'})
        trace.__exit__()  # Simulate a process ending without a final outcome.
        self.assertEqual(self.latest()['status'], 'pending')
        self.assertIsNone(self.latest()['completed_at'])
        with self.assertRaises(KeyboardInterrupt):
            with Trace(self.config, 'ask', 'Pause') as interrupted:
                interrupted.event('execution_started', {'action': 'pause'})
                raise KeyboardInterrupt
        self.assertEqual(self.latest()['status'], 'interrupted')
        self.assertNotIn('mutation_attempted', self.latest()['outcome'])

    def test_journal_disabled_does_not_create_database(self):
        config = replace(self.config, journal_enabled=False)
        with Trace(config, 'ask', 'Pause') as trace:
            result = trace.finish({'status': 'planned'})
        self.assertEqual(result['request_id'], trace.id)
        self.assertFalse(config.data_dir.exists())

    def test_retention_prunes_completed_entries_and_expired_pending_with_cascade(self):
        config = replace(self.config, journal_max_requests=2)
        for i in range(4):
            with Trace(config, 'rank', str(i)) as trace:
                trace.finish({'status': 'planned'})
        self.assertEqual(len(history_command(config)['requests']), 2)
        language_command(config, ['ru'])
        with Journal(config) as journal:
            with journal.db:
                journal.db.execute("UPDATE requests SET started_at='2000-01-01T00:00:00+00:00',completed_at=NULL")
            self.assertEqual(journal.prune(), 2)
            self.assertEqual(journal.db.execute('SELECT count(*) FROM request_events').fetchone()[0], 0)
        self.assertEqual(language_command(config)['locale'], 'ru')

    def test_export_and_clear_preserve_preferences_and_refuse_overwrite(self):
        self.invoke('rank', 'Pause')
        language_command(self.config, ['ru'])
        path = self.root / 'request history.jsonl'
        result = history_command(self.config, ['export', str(path)])
        self.assertEqual(result['exported'], 1)
        self.assertEqual(json.loads(path.read_text())['input'], 'Pause')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            history_command(self.config, ['export', str(path)])
        with self.assertRaises(ValueError):
            history_command(self.config, ['clear'])
        with self.assertRaises(ValueError):
            history_command(self.config, ['export', str(Path.cwd() / 'history.jsonl')])
        self.assertEqual(history_command(self.config, ['clear', '--yes'])['removed'], 1)
        self.assertEqual(history_command(self.config)['requests'], [])
        self.assertEqual(language_command(self.config)['locale'], 'ru')

    def test_write_failure_after_execution_never_reruns_callback(self):
        with self.assertRaisesRegex(JournalWriteError, 'do not replay'):
            with Trace(self.config, 'ask', 'Pause') as trace:
                trace.event('execution_started', {})
                trace.journal.db.execute('PRAGMA query_only=ON')
                trace.finish({'status': 'confirmed', 'mutation_attempted': True})
        self.assertEqual(self.latest()['status'], 'pending')

    def test_journal_config_validation(self):
        base = self.path.read_text()
        for setting in ('enabled="yes"', 'retention_days=0', 'max_requests=true', 'unknown=1'):
            self.path.write_text(base + '\n[journal]\n' + setting)
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                load(self.path)
