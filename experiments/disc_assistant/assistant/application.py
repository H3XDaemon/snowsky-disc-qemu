"""Shared synchronous application service for CLI and web adapters."""
import asyncio
from dataclasses import asdict, replace
import os
import shlex
import sys
from uuid import uuid4

from experiments.disc_assistant.assistant.config import Config
from experiments.disc_assistant.assistant.controls import execute as control
from experiments.disc_assistant.assistant.nlu.intents import ControlIntent, LanguageIntent, VolumeIntent
from experiments.disc_assistant.assistant.nlu.languages import load_languages
from experiments.disc_assistant.assistant.nlu.interpreter import InterpretationContext, interpret_request
from experiments.disc_assistant.assistant.live import DeviceSession
from experiments.disc_assistant.assistant.preferences import effective_config, language_command, response_command
from experiments.disc_assistant.assistant.journal import Trace, history_command, debug_stderr
from experiments.disc_assistant.assistant.responses import Responses, validate_locales
from experiments.disc_assistant.assistant.playback import execute as play
from experiments.disc_assistant.assistant.queue import observe as queue
from experiments.disc_assistant.assistant.ranking import rank
from experiments.disc_assistant.assistant.session import sync
from library.search.typesense import Search, create_client, signature
from library.store import Store
from experiments.disc_assistant.assistant.voice.backends import transcribe_file

from experiments.disc_assistant.assistant.console_help import HELP
from experiments.disc_assistant.assistant.voice.backends import transcribe_audio
from experiments.disc_assistant.assistant.voice.files import wav_audio
from experiments.disc_assistant.assistant.voice.runtime import SpeechRuntime


class Application:
    def __init__(self, config: Config, *, session_factory=DeviceSession, source='interactive', interpreter=None, language=None,
                 debug=False, debug_output=debug_stderr, transcriber=None):
        self.base_config, self.session_factory = config, session_factory
        self.config = effective_config(config, language=language)
        self.interpreter = interpreter
        self.transcriber = transcriber
        self.voice = SpeechRuntime(self.config)
        self.debug, self.debug_output = debug, debug_output
        self.rules = load_languages((self.config.locale,))
        self.session_id, self.source = uuid4().hex, source

    def __enter__(self):
        self.session = self.session_factory(self.config)
        self.session.__enter__()
        try:
            self.store = Store(self.config.data_dir)
        except BaseException:
            self.session.__exit__(*sys.exc_info())
            raise
        self.session.connect()
        return self

    def __exit__(self, *args):
        try:
            self.voice.close()
        finally:
            self.session.__exit__(*args)
            self.store.close()

    def device_call(self, callback):
        client = None
        operation_id = uuid4().hex
        try:
            with self.session.operation() as client:
                result = callback(client)
                result.setdefault('operation_id', operation_id)
                if client.closed.is_set() and result.get('mutation_attempted'):
                    result.update(status='uncertain', reason='connection lost during operation; no replay')
                return result
        except (OSError, ValueError, RuntimeError) as exc:
            attempted = bool(client and client.mutation_attempted)
            return {'operation_id': operation_id, 'status': 'uncertain' if attempted else 'not_sent',
                    'mutation_attempted': attempted, 'reason': str(exc), 'error_type': type(exc).__name__}

    async def search(self, command, text='', *, intent=None, reuse=False, trace=None, context=None):
        if trace:
            trace.catalog(self.store)
            trace.event('search', {'command': command, 'query': text})
        key = os.environ.get(self.config.api_key_env, '')
        if not key.strip():
            raise ValueError(f'search is unavailable: set {self.config.api_key_env}; controls remain available')
        client = create_client(self.config, key)
        server = [self.config.search_protocol, self.config.search_host, self.config.search_port]
        search = Search(client, self.config.aliases, server)
        try:
            if command == 'index':
                head = self.store.head(self.config.device_key)
                if (reuse and head['collection'] and head['generation'] == head['index_generation']
                        and head['index_signature'] == search.signature):
                    from typesense.exceptions import ObjectNotFound
                    try:
                        info = await client.collections[head['collection']].retrieve()
                        if info.get('num_documents') == head['track_count']:
                            return dict(head, reused=True)
                    except ObjectNotFound:
                        pass
                return await search.build(self.store, self.config.device_key)
            if command == 'rank':
                result = await rank(self.config, self.store, search, intent, trace=trace, context=context)
            else:
                result = await search.search(self.store, self.config.device_key, text)
            if trace:
                trace.search(result, phase='ranking' if command == 'rank' else 'retrieval')
            return result
        finally:
            await client.api_call.aclose()

    def status(self):
        head = self.store.head(self.config.device_key)
        server = [self.config.search_protocol, self.config.search_host, self.config.search_port]
        head['index_current'] = bool(head['generation'] and head['generation'] == head['index_generation']
                                    and head['index_signature'] == signature(self.config.aliases, server))
        return {'session': self.session.status(), 'library': head,
                'language': {'locale': self.config.locale},
                'response_preferences': {'mode': self.config.response_mode},
                'dialogue': {'enabled': False}}

    def device(self):
        state = self.session.status()
        return {'device': {'key': self.config.device_key, 'host': self.config.host,
                           'tcp_port': self.config.tcp_port, 'http_port': self.config.http_port},
                'session': {key: state[key] for key in ('connection', 'enabled', 'generation', 'last_error')}}

    def request(self, line, *, source=None, reuse_index=False):
        if not line.strip():
            return None
        command = line.strip().split(maxsplit=1)[0][1:] if line.strip().startswith('/') else 'ask'
        audio_command = (line.strip().startswith('/') and
                         (command == 'transcribe' or
                          (command in ('ask', 'rank') and line.strip().split()[1:2] == ['--audio'])))
        # History still gets timing, but never persists inspection/export/clear.
        with Trace(self.config, command, '[audio]' if audio_command else line,
                   source=source or self.source, session_id=self.session_id,
                   event_sink=self.trace_event, persist=command != 'history') as trace:
            if command == 'history':
                return trace.finish(history_command(self.config, shlex.split(line.strip())[1:]))
            if hasattr(self, 'session'):
                state = self.session.status()
                trace.event('connection', {k: state[k] for k in ('generation', 'connection')})
            trace.event('parse', {})
            if audio_command:
                args = shlex.split(line.strip())
                expected_count = 2 if command == 'transcribe' else 3
                if command not in ('transcribe', 'ask', 'rank') or len(args) != expected_count:
                    raise ValueError('use /transcribe FILE, /rank --audio FILE or /ask --audio FILE')
                generation = self.session.status()['generation'] if hasattr(self, 'session') else None
                transcription = asyncio.run(transcribe_file(self.config, args[-1], trace, provider=self.speech_provider()))
                result = ({'status': 'transcribed'} if command == 'transcribe' else
                          self.natural_request(transcription['command_text'], trace,
                                               generation=generation, preview=command == 'rank'))
                result['transcription'] = transcription
                return trace.finish(result)
            return trace.finish(self._request(line, trace, reuse_index=reuse_index))

    def speech_provider(self):
        return self.transcriber if self.transcriber is not None else self.voice.get(self.voice.selected['stt'])

    def input_request(self, *, text=None, audio=None, mode='execute', transcriber=None):
        """Transport-neutral natural input; never accepts administrative slash commands."""
        if mode not in ('execute', 'preview', 'transcribe'):
            raise ValueError('invalid input mode')
        if (text is None) == (audio is None):
            raise ValueError('provide either text or WAV bytes')
        if text is not None and (not isinstance(text, str) or len(text) > 1000):
            raise ValueError('text must be a string up to 1000 characters')
        if text is not None and mode == 'transcribe':
            raise ValueError('transcribe requires audio')
        command = {'execute': 'ask', 'preview': 'rank', 'transcribe': 'transcribe'}[mode]
        with Trace(self.config, command, '[audio]' if audio is not None else text,
                   source=self.source, session_id=self.session_id, event_sink=self.trace_event) as trace:
            if text is not None and (not text.strip() or text.lstrip().startswith('/')
                    or any(ord(c) < 32 for c in text)):
                raise ValueError('enter a natural command without control characters')
            generation = self.session.status()['generation']
            transcription = None
            if audio is not None:
                trace.event('audio_input', {'format': 'pcm_wav'})
                value = wav_audio(audio, max_seconds=self.config.speech.get('max_seconds', 30))
                transcription = asyncio.run(transcribe_audio(
                    self.config, value, trace, provider=self.speech_provider() if transcriber is None else transcriber))
                text = transcription['command_text']
            result = ({'status': 'transcribed'} if mode == 'transcribe' else
                      self.natural_request(text, trace, generation=generation, preview=mode == 'preview'))
            if transcription is not None:
                result['transcription'] = transcription
            return trace.finish(result)

    def trace_event(self, event):
        if self.debug:
            self.debug_output(event)

    def shadow_sources(self):
        from experiments.disc_assistant.assistant.nlu.interpretation_sources import default_sources
        return default_sources(self.config) if self.config.shadow else None

    def interpret(self, text, trace):
        playback = 'unknown'
        if hasattr(self, 'session'):
            observed = self.session.status().get('observation', {}).get('playback')
            if observed in ('playing', 'paused', 'stopped'):
                playback = observed
        return asyncio.run(interpret_request(text, InterpretationContext(self.config.locale, playback),
                                            interpreter=self.interpreter, trace=trace,
                                            shadow=self.shadow_sources(), shadow_timeout_ms=self.config.shadow_timeout_ms))

    def language(self, arguments, trace):
        trace.event('preference', {'name': 'language.locale'})
        result = language_command(self.base_config, arguments)
        self.config = replace(self.config, locale=result['locale'])
        self.rules = load_languages((self.config.locale,))
        trace.responses = Responses(self.config.locale, self.config.response_mode)
        trace.event('locale_changed', trace.responses.context())
        return result

    def _request(self, line, trace, *, reuse_index=False):
        line = line.strip()
        if not line:
            return None
        if line.startswith('/'):
            command, _, text = line[1:].partition(' ')
            text = text.strip()
            if command == 'explain':
                from experiments.disc_assistant.assistant.nlu.explain import preview
                return preview(self.config, text, trace)
            if command == 'commands':
                from experiments.disc_assistant.assistant.nlu.command_catalog import command as catalog_command
                result = catalog_command(self.config, shlex.split(text))
                trace.event('command_catalog', result)
                return result
            if command == 'shadow':
                if text not in ('', 'on', 'off'):
                    raise ValueError('/shadow accepts on or off')
                if text:
                    self.config = replace(self.config, shadow=text == 'on')
                return {'shadow': self.config.shadow, 'timeout_ms': self.config.shadow_timeout_ms,
                        'scope': 'console session only', 'execution_source': 'primary_only'}
            if command == 'debug':
                if text not in ('', 'on', 'off'):
                    raise ValueError('/debug accepts on or off')
                if text:
                    self.debug = text == 'on'
                return {'debug': {'enabled': self.debug, 'scope': 'session'}}
            if command == 'language':
                return self.language(text.split(), trace)
            if command == 'response':
                trace.event('preference', {'name': 'response.mode'})
                result = response_command(self.base_config, text.split())
                self.config = replace(self.config, locale=result['locale'], response_mode=result['mode'])
                self.rules = load_languages((self.config.locale,))
                trace.responses = Responses(self.config.locale, self.config.response_mode)
                trace.event('response_preferences', trace.responses.context())
                return result
            if command in ('search', 'rank'):
                if not text:
                    raise ValueError(f'/{command} needs text')
                if command == 'rank':
                    intent = self.interpret(text, trace)
                    if isinstance(intent, (ControlIntent, VolumeIntent, LanguageIntent)):
                        return {'status': 'planned', 'action': intent.action if isinstance(intent, (ControlIntent, VolumeIntent)) else 'set_language',
                                'requires_search': False, 'intent': asdict(intent)}
                    return asyncio.run(self.search(command, text, intent=intent, trace=trace, context=self.playback_context))
                return asyncio.run(self.search(command, text, trace=trace))
            if text:
                raise ValueError(f'/{command} takes no arguments')
            if command == 'locales':
                return validate_locales()
            if command == 'help':
                return {'help': HELP}
            if command == 'exit':
                return {'status': 'exit'}
            if command == 'clear':
                return {'status': 'clear_screen'}
            if command == 'status':
                return self.status()
            if command == 'device':
                return self.device()
            if command == 'disconnect':
                self.session.disconnect()
                return self.session.status()
            if command == 'connect':
                self.session.connect()
                return self.session.status()
            if command == 'queue':
                trace.event('execution_started', {'action': 'queue', 'read_only': True})
                return self.device_call(lambda client: queue(self.config, shared=client))
            if command == 'sync':
                trace.event('execution_started', {'action': 'sync', 'read_only': True})
                return self.device_call(lambda client: sync(self.config, self.store, shared=client, reuse_unchanged=True))
            if command == 'index':
                trace.event('index', {})
                return asyncio.run(self.search('index', reuse=reuse_index, trace=trace))
            raise ValueError('unknown console command; use /help')
        # An online interpreter may take time: pin before interpretation, not after it.
        generation = self.session.status()['generation'] if hasattr(self, 'session') else None
        return self.natural_request(line, trace, generation=generation)

    def playback_context(self):
        from experiments.disc_assistant.assistant.context import read
        with self.session.operation() as client:
            return read(self.config, client)

    def natural_request(self, line, trace, *, generation=None, preview=False):
        # This is natural input only: recognized speech can never enter slash commands.
        intent = self.interpret(line, trace)
        if preview:
            if isinstance(intent, (ControlIntent, VolumeIntent, LanguageIntent)):
                return {'status': 'planned', 'action': intent.action if isinstance(intent, (ControlIntent, VolumeIntent)) else 'set_language',
                        'requires_search': False, 'intent': asdict(intent)}
            return asyncio.run(self.search('rank', line, intent=intent, trace=trace, context=self.playback_context))
        if generation is not None and generation != self.session.status()['generation']:
            return {'status': 'not_sent', 'mutation_attempted': False, 'reason': 'session changed during speech/interpretation'}
        if isinstance(intent, LanguageIntent):
            return self.language([intent.locale], trace)
        if isinstance(intent, (ControlIntent, VolumeIntent)):
            trace.event('execution_started', {'action': intent.action})
            def execute_control(client):
                if generation is not None and generation != self.session.status()['generation']:
                    raise ConnectionError('session changed before control dispatch')
                return control(self.config, intent, shared=client)
            return self.device_call(execute_control)
        # Pin the request to the current connection BEFORE potentially slow search.
        ranking = asyncio.run(self.search('rank', line, intent=intent, trace=trace, context=self.playback_context))
        if not ranking['candidates']:
            return ranking
        trace.select(ranking)
        def execute(client):
            if generation != self.session.status()['generation']:
                raise ConnectionError('session changed during search; request a new selection')
            return play(self.config, self.store, ranking, shared=client)
        trace.event('execution_started', {'action': 'play'})
        return self.device_call(execute)
