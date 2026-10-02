from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from experiments.disc_assistant.assistant.config import load
from experiments.disc_assistant.assistant.__main__ import main
from experiments.disc_assistant.assistant import session
from library.store import Store
from library.tests.helpers import Catalog, TRACKS


class ConfigSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'config.toml'
        self.base = f'[device]\nkey="test"\nhost="127.0.0.1"\n[storage]\ndata_dir="{self.tmp.name}/data"\n'
        self.path.write_text(self.base)
        self.config = load(self.path)
        self.store = Store(self.config.data_dir)
        self.addCleanup(self.store.close)

    def test_default_ports_and_configuration_validation(self):
        self.assertEqual((self.config.tcp_port, self.config.http_port), (12100, 12103))
        for extra in ('[sync]\npage_size=201', '[sync]\npage_size=true',
                      '[aliases.artists]\nx="bad"', '[typesense]\nprotocol="ftp"',
                      '[typesense]\nprot="http"', '[unknown]\nx=1',
                      '[terminal]\ncolor="yes"', '[terminal]\ninput=12', '[terminal]\nfont="Mono"'):
            self.path.write_text(self.base + extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                load(self.path)

        self.path.write_text(self.base + '[terminal]\ncolor=false\nprompt="#44aaff bold"')
        self.assertEqual(load(self.path).terminal, {'color': False, 'prompt': '#44aaff bold'})

    def test_data_cannot_live_in_checkout(self):
        self.path.write_text(self.base.split('[storage]')[0] + f'[storage]\ndata_dir="{Path.cwd()}"\n')
        with self.assertRaisesRegex(ValueError, 'outside'):
            load(self.path)

    def test_language_defaults_selection_and_validation(self):
        self.assertEqual(self.config.locale, 'ru')
        self.path.write_text(self.base + '[language]\nenabled=["en"]')
        self.assertEqual(load(self.path).locale, 'en')
        for enabled in ('[]', '"ru"', '["ru", "ru"]', '["zz"]'):
            self.path.write_text(self.base + '[language]\nenabled=' + enabled)
            with self.subTest(enabled=enabled), self.assertRaises(ValueError):
                load(self.path)

    def test_continuous_context_requires_explicit_boolean_opt_in(self):
        self.assertFalse(self.config.continuous_context)
        self.path.write_text(self.base + '[playback]\ncontinuous_context=true')
        self.assertTrue(load(self.path).continuous_context)
        for value in ('1', '"true"', '[]'):
            self.path.write_text(self.base + '[playback]\ncontinuous_context=' + value)
            with self.assertRaises(ValueError):
                load(self.path)

    def client(self, version=257):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.handshake.return_value = '0306'
        client.settings.return_value = {'soc_version': version}
        client.event.side_effect = TimeoutError
        return client

    def test_sync_and_failed_refresh_preserve_previous(self):
        http = Catalog()
        with patch.object(session, 'Client', return_value=self.client()), patch.object(session, 'HTTPClient', return_value=http):
            first = session.sync(self.config, self.store)
            self.assertEqual(first['track_count'], len(TRACKS))
            def failure(*args):
                raise OSError('interrupted')
            http.change = failure
            with self.assertRaises(OSError):
                session.sync(self.config, self.store)
            self.assertEqual(self.store.head('test'), first)

    def test_console_sync_reuses_only_an_exact_unchanged_snapshot(self):
        with patch.object(session, 'Client', return_value=self.client()), patch.object(session, 'HTTPClient', return_value=Catalog()):
            first = session.sync(self.config, self.store)
            again = session.sync(self.config, self.store, reuse_unchanged=True)
            self.assertEqual(again['generation'], first['generation'])
            self.assertTrue(again['reused'])
            # One-shot sync preserves its existing publish-new-generation behavior.
            third = session.sync(self.config, self.store)
            self.assertNotEqual(third['generation'], first['generation'])

    def test_unknown_firmware_never_reads_catalog(self):
        with patch.object(session, 'Client', return_value=self.client(999)), patch.object(session, 'HTTPClient') as http:
            with self.assertRaisesRegex(ValueError, 'catalog_snapshot.*999'):
                session.sync(self.config, self.store)
            http.assert_not_called()

    def test_observed_scan_activity_blocks_publication(self):
        client = self.client()
        client.event.side_effect = [TimeoutError(), ('a60a', b'0005')]
        with patch.object(session, 'Client', return_value=client), patch.object(session, 'HTTPClient', return_value=Catalog()):
            with self.assertRaisesRegex(ValueError, 'scan ended during'):
                session.sync(self.config, self.store)
            self.assertIsNone(self.store.head('test')['generation'])

    def test_initialization_and_playback_status_do_not_block_import(self):
        client = self.client()
        client.event.side_effect = [('a60a', b'0010'), ('a60a', b'000D'),
                                   TimeoutError(), ('a60a', b'0010'), TimeoutError()]
        with patch.object(session, 'Client', return_value=client), patch.object(session, 'HTTPClient', return_value=Catalog()):
            self.assertEqual(session.sync(self.config, self.store)['track_count'], len(TRACKS))

    def test_verified_scan_start_and_count_block_before_and_during_read(self):
        for event in (('a60a', b'000F'), ('a60a', b'000f'), ('a622', b'0000'), ('a622', b'01AB')):
            for during in (False, True):
                with self.subTest(event=event, during=during):
                    client = self.client()
                    client.event.side_effect = ([TimeoutError()] if during else []) + [event]
                    with patch.object(session, 'Client', return_value=client), patch.object(session, 'HTTPClient', return_value=Catalog()):
                        with self.assertRaisesRegex(ValueError, 'scan activity'):
                            session.sync(self.config, self.store)
                        self.assertIsNone(self.store.head('test')['generation'])

    def test_scan_ended_before_read_permits_fresh_snapshot(self):
        client = self.client()
        client.event.side_effect = [('a60a', b'0005'), TimeoutError(), TimeoutError()]
        with patch.object(session, 'Client', return_value=client), patch.object(session, 'HTTPClient', return_value=Catalog()):
            self.assertEqual(session.sync(self.config, self.store)['track_count'], len(TRACKS))

    def test_malformed_status_is_not_treated_as_idle(self):
        for event in (('a60a', b'oops'), ('a60a', b'F'), ('a622', b'')):
            with self.subTest(event=event):
                client = self.client()
                client.event.side_effect = [event]
                with self.assertRaisesRegex(ValueError, 'invalid'):
                    session.check_events(client)

    def test_cli_status_offline_and_missing_search_key(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), patch.dict('os.environ', {}, clear=True):
            self.assertEqual(main(['--config', str(self.path), 'status']), 0)
            self.assertEqual(main(['--config', str(self.path), 'search', 'Numb']), 1)
        self.assertIn('"index_current": false', output.getvalue())
        self.assertIn('TYPESENSE_API_KEY', errors.getvalue())
