import asyncio
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

from experiments.disc_assistant.assistant import __main__ as cli
from experiments.disc_assistant.assistant.config import load
from experiments.disc_assistant.assistant.console import Application
from experiments.disc_assistant.assistant.journal import Trace, history_command
from experiments.disc_assistant.assistant.preferences import effective_config
from experiments.disc_assistant.assistant.providers import ProviderInfo
from experiments.disc_assistant.assistant.speech import Audio, InvalidSpeech, NoSpeech, SpeechUnavailable, Transcription
from experiments.disc_assistant.assistant.voice import backends, samples
from experiments.disc_assistant.assistant.voice.files import load_audio, wav_audio
from library.store import Store
from library.search.typesense import signature
from library.tests.helpers import TRACKS


def wav(*, rate=16000, width=2, channels=1, frames=1600, silent=False):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes((b'\x00' if silent else b'\x01') * width * channels * frames)
    return buffer.getvalue()


class VoiceFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'config.toml'
        self.path.write_text(f'[device]\nkey="test"\nhost="127.0.0.1"\n'
                             f'[storage]\ndata_dir="{self.root}/data"\n[language]\nlocale="en"\n')
        self.config = load(self.path)
        self.audio = self.root / 'input with spaces.wav'
        self.audio.write_bytes(wav())
        self.provider = Mock(info=ProviderInfo('fixture-stt', '1', 'local'))
        self.provider.transcribe = AsyncMock(return_value=Transcription('Pause.', 'en'))
        self.synthesizer = Mock(info=ProviderInfo('fixture-tts', '1', 'local'))
        self.synthesizer.synthesize = AsyncMock(return_value=Audio(wav(), 'audio/wav', 16000, 1))

    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = cli.main(['--config', str(self.path), *map(str, args)],
                            transcriber=self.provider, synthesizer=self.synthesizer)
        return code, json.loads(output.getvalue())

    def test_transcribe_and_rank_do_not_execute_and_audio_history_omits_path(self):
        with patch.object(cli, 'control') as control, patch.object(cli, 'execute') as play:
            for args in [('transcribe', self.audio), ('rank', '--audio', self.audio)]:
                code, result = self.invoke(*args)
                self.assertEqual(code, 0)
                self.assertEqual(result['transcription']['text'], 'Pause.')
                self.assertEqual(result['transcription']['command_text'], 'Pause')
                record = history_command(self.config, ['show', result['request_id']])
                self.assertEqual(record['input'], '[audio]')
                self.assertNotIn(str(self.audio), json.dumps(record))
                self.assertIn('transcription', [e['phase'] for e in record['events']])
                self.assertIn('timing', result)
            control.assert_not_called()
            play.assert_not_called()

    def test_audio_ask_uses_existing_control_once(self):
        with patch.object(cli, 'control', return_value={'status': 'confirmed', 'action': 'pause'}) as control:
            code, result = self.invoke('ask', '--audio', self.audio)
        self.assertEqual(code, 0)
        control.assert_called_once()
        self.provider.transcribe.assert_awaited_once()
        self.assertEqual(result['response']['code'], 'playback.paused')

    def test_new_voice_controls_use_one_shared_typed_dispatch(self):
        for text, action in [('Like.', 'like'), ('What is playing?', 'now_playing'), ('Volume forty.', 'volume')]:
            self.provider.transcribe.return_value = Transcription(text, 'en')
            with patch.object(cli, 'control', return_value={'status': 'confirmed'}) as control:
                code, result = self.invoke('ask', '--audio', self.audio)
            self.assertEqual(code, 0)
            control.assert_called_once()
            self.assertEqual(control.call_args.args[1].action, action)
            self.assertEqual(result['transcription']['text'], text)

    def test_observed_russian_next_variant_dispatches_once_and_preserves_transcript(self):
        self.provider.transcribe.return_value = Transcription('Следующий трак.', 'ru')
        with patch.object(cli, 'control', return_value={'status': 'confirmed', 'action': 'next'}) as control:
            code, result = self.invoke('--language', 'ru', 'ask', '--audio', self.audio)
        self.assertEqual(code, 0)
        control.assert_called_once()
        self.assertEqual(control.call_args.args[1].action, 'next')
        self.assertEqual(result['action'], 'next')
        self.assertEqual(result['transcription']['text'], 'Следующий трак.')
        self.assertEqual(result['transcription']['command_text'], 'Следующий трак')
        record = history_command(self.config, ['show', result['request_id']])
        transcript = next(e['payload']['text'] for e in record['events'] if e['phase'] == 'transcription')
        self.assertEqual(transcript, 'Следующий трак.')

    def test_audio_music_passes_through_catalog_ranking_before_single_dispatch(self):
        with Store(self.config.data_dir) as store:
            head = store.publish('test', TRACKS, {}, expected_generation=None)
            store.publish_index('test', head['generation'], 'fixture', signature({}, ['http', '127.0.0.1', 8108]))
        self.provider.transcribe.return_value = Transcription('Play Linkin Park Numb.', 'en')
        client = Mock()
        client.api_call.aclose = AsyncMock()
        with patch.dict('os.environ', {'TYPESENSE_API_KEY': 'fixture'}), \
                patch.object(cli, 'create_client', return_value=client), \
                patch.object(cli, 'execute', return_value={'status': 'playing'}) as play:
            code, result = self.invoke('ask', '--audio', self.audio)
        self.assertEqual(code, 0)
        play.assert_called_once()
        self.provider.transcribe.assert_awaited_once()
        selected = play.call_args.args[2]['candidates'][0]
        self.assertEqual((selected['artist'], selected['title']), ('Linkin Park', 'Numb'))
        record = history_command(self.config, ['show', result['request_id']])
        phases = [e['phase'] for e in record['events']]
        self.assertEqual(phases.count('interpretation_started'), 1)
        self.assertLess(phases.index('transcription'), phases.index('selection'))

    def test_transcription_failure_never_dispatches_and_does_not_expose_provider_body(self):
        for value, code in [(Transcription('', 'en', True), 'speech.no_speech'),
                            (Transcription('Pause', 'ru'), 'speech.invalid'),
                            (Transcription('Pause\nNext', 'en'), 'speech.invalid'),
                            (Transcription('Pause', 'en', True), 'speech.invalid')]:
            self.provider.transcribe.return_value = value
            with patch.object(cli, 'control') as control:
                status, result = self.invoke('ask', '--audio', self.audio)
                self.assertEqual(status, 1)
                self.assertEqual(result['response']['code'], code)
                control.assert_not_called()
        self.provider.transcribe.side_effect = RuntimeError('SECRET-BODY')
        _, result = self.invoke('ask', '--audio', self.audio)
        self.assertEqual(result['response']['code'], 'speech.unavailable')
        record = history_command(self.config, ['show', result['request_id']])
        self.assertNotIn('SECRET-BODY', json.dumps(record))

    def test_silence_and_bad_files_are_rejected_before_provider(self):
        for data, code in [(wav(silent=True), 'speech.no_speech'), (b'not wav', 'speech.invalid'),
                           (wav(rate=44100), 'speech.invalid'), (wav(channels=2), 'speech.invalid'),
                           (wav()[:-8], 'speech.invalid'), (wav(frames=0), 'speech.invalid'),
                           (wav(frames=16000 * 31), 'speech.invalid')]:
            self.audio.write_bytes(data)
            _, result = self.invoke('transcribe', self.audio)
            self.assertEqual(result['response']['code'], code)
        self.provider.transcribe.assert_not_called()

    def test_console_pins_connection_before_stt_and_never_dispatches_slash_commands(self):
        app = Application(self.config, transcriber=self.provider)
        app.session = Mock()
        state = {'generation': 1, 'connection': 'ready', 'observation': {'playback': 'playing'}}
        app.session.status.side_effect = lambda: dict(state)
        app.device_call = Mock(return_value={'status': 'confirmed', 'action': 'pause'})
        async def reconnect(audio, context):
            state['generation'] = 2
            return Transcription('Pause.', 'en')
        self.provider.transcribe.side_effect = reconnect
        result = app.request(f'/ask --audio "{self.audio}"')
        self.assertEqual(result['status'], 'not_sent')
        app.device_call.assert_not_called()
        self.provider.transcribe.side_effect = None
        self.provider.transcribe.return_value = Transcription('/language ru', 'en')
        with self.assertRaises(ValueError):
            app.request(f'/ask --audio "{self.audio}"')
        self.assertEqual(app.config.locale, 'en')
        self.provider.transcribe.return_value = Transcription('Pause.', 'en')
        self.assertEqual(app.request(f'/rank --audio "{self.audio}"')['status'], 'planned')
        app.device_call.assert_not_called()
        self.assertEqual(app.request(f'/ask --audio "{self.audio}"')['status'], 'confirmed')
        app.device_call.assert_called_once()

    def test_natural_language_change_preview_and_execution_share_existing_preferences(self):
        self.provider.transcribe.return_value = Transcription('Switch language to Russian.', 'en')
        self.assertEqual(self.invoke('rank', '--audio', self.audio)[0], 0)
        self.assertEqual(effective_config(self.config).locale, 'en')
        _, result = self.invoke('ask', '--audio', self.audio)
        self.assertEqual(effective_config(self.config).locale, 'ru')
        self.assertEqual(result['response']['language'], 'ru')
        self.assertEqual(result['transcription']['locale'], 'en')

    def test_synthesis_writes_audio_and_provenance_without_overwrite(self):
        target = self.root / 'sample.wav'
        code, result = self.invoke('synthesize', 'Pause', '--output', target)
        self.assertEqual(code, 0)
        self.assertEqual(target.read_bytes(), wav())
        metadata = json.loads(target.with_suffix('.wav.json').read_text())
        self.assertEqual(metadata['text'], 'Pause')
        self.assertEqual(metadata['provider']['name'], 'fixture-tts')
        self.assertEqual(metadata['sha256'], result['synthesis']['sha256'])
        self.assertEqual(self.invoke('synthesize', 'Next track', '--output', target)[0], 1)
        self.synthesizer.synthesize.assert_awaited_once()

    def test_corpus_evaluation_is_read_only_and_reports_mismatches(self):
        directory = self.root / 'samples'
        self.assertEqual(self.invoke('speech-samples', directory)[0], 0)
        manifest = json.loads((directory / 'manifest.json').read_text())
        self.provider.transcribe.side_effect = [Transcription(case['text'] + '.', 'en') for case in manifest['cases']]
        with patch.object(cli, 'control') as control:
            code, result = self.invoke('speech-check', directory)
        self.assertEqual(code, 0)
        self.assertEqual(result['passed'], result['total'])
        self.assertEqual(effective_config(self.config).locale, 'en')
        control.assert_not_called()
        self.provider.transcribe.side_effect = None
        self.provider.transcribe.return_value = Transcription('Pause.', 'en')
        code, result = self.invoke('speech-check', directory)
        self.assertEqual(code, 1)
        self.assertEqual(result['passed'], 1)
        (directory / 'pause.wav').write_bytes(wav(frames=3200))
        self.assertEqual(self.invoke('speech-check', directory)[0], 1)

    def test_corpus_rejects_wrong_locale_and_path_traversal(self):
        for locale in ('ru', 'en'):
            corpus = samples.read_json(samples.CORPORA / f'{locale}.json')
            self.assertEqual(len(samples.validate_cases(corpus, locale)), 6)
        with self.assertRaises(ValueError):
            samples.validate_cases(corpus, 'ru')
        corpus['cases'][0]['id'] = '../outside'
        with self.assertRaises(ValueError):
            samples.validate_cases(corpus, 'en')

    def test_speech_config_and_missing_model_fail_explicitly(self):
        base = self.path.read_text()
        for value in ('unknown=1', 'timeout=0', 'model="relative.bin"',
                      'voices="bad"', 'stt_languages={en="auto"}'):
            self.path.write_text(base + '\n[speech]\n' + value)
            with self.assertRaises(ValueError):
                load(self.path)
        self.path.write_text(base)
        self.path.write_text(base + '\n[speech.voices]\nru="Milena"\n')
        self.assertEqual(load(self.path).locale, 'en')
        self.path.write_text(base)
        with Trace(self.config, 'transcribe', '[audio]') as trace:
            with self.assertRaises(SpeechUnavailable):
                asyncio.run(backends.transcribe_file(self.config, self.audio, trace))

    def test_audio_syntax_is_explicit_and_empty_paths_fail_before_stt(self):
        for arguments in [('transcribe', ''), ('ask', '--audio', '')]:
            code, result = self.invoke(*arguments)
            self.assertEqual(code, 1)
            self.assertEqual(result['response']['code'], 'speech.invalid')
        self.provider.transcribe.assert_not_called()
        app = Application(self.config, transcriber=self.provider)
        with patch.object(app, '_request', return_value={'status': 'planned'}) as typed:
            app.request('Play --audio imaginary.wav')
            typed.assert_called_once()
        self.provider.transcribe.assert_not_called()


class VoiceProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_and_cancellation_kill_and_reap_process(self):
        for error in (TimeoutError(), asyncio.CancelledError()):
            process = Mock(returncode=None)
            process.wait = AsyncMock(side_effect=[error, 0])
            with patch.object(asyncio, 'create_subprocess_exec', new=AsyncMock(return_value=process)):
                with self.assertRaises(SpeechUnavailable if isinstance(error, TimeoutError) else asyncio.CancelledError):
                    await backends.run_process(['fixture'], timeout=1)
            process.kill.assert_called_once()
            self.assertEqual(process.wait.await_count, 2)

    async def test_whisper_arguments_json_and_wrong_language_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'model.bin'
            model.write_bytes(b'fixture model')
            backend = backends.WhisperCpp({'model': str(model), 'whisper_executable': '/fake/whisper'})
            language = ['en']
            async def process(args, **kwargs):
                self.assertEqual(args[0], '/fake/whisper')
                self.assertEqual(args[args.index('-l') + 1], 'en')
                self.assertNotIn('--prompt', args)
                Path(args[args.index('-of') + 1] + '.json').write_text(json.dumps({
                    'result': {'language': language[0]}, 'transcription': [{'text': ' Pause.'}]}))
            with patch('experiments.disc_assistant.assistant.voice.adapters.stt.whisper_cpp.run_process', side_effect=process):
                result = await backend.transcribe(wav_audio(wav()), backends.SpeechContext('en', 'fixture'))
                self.assertEqual(result.text, 'Pause.')
                language[0] = 'ru'
                with self.assertRaises(InvalidSpeech):
                    await backend.transcribe(wav_audio(wav()), backends.SpeechContext('en', 'fixture'))
