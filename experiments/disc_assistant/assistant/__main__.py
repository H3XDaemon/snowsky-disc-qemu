"""Desktop prototype: catalog search, ranked text requests and verified playback."""
import argparse
from dataclasses import asdict, replace
import asyncio
import json
import os
import sys

from experiments.disc_assistant.assistant.config import load
from experiments.disc_assistant.assistant.session import sync
from experiments.disc_assistant.assistant.ranking import rank
from experiments.disc_assistant.assistant.playback import execute, device_lock
from experiments.disc_assistant.assistant.nlu.intents import ControlIntent, LanguageIntent, VolumeIntent
from experiments.disc_assistant.assistant.nlu.interpreter import InterpretationContext, interpret_request
from experiments.disc_assistant.assistant.preferences import effective_config, language_command, response_command
from experiments.disc_assistant.assistant.journal import Trace, history_command, outcome, debug_stderr
from experiments.disc_assistant.assistant.responses import Responses, exception_result, validate_locales
from experiments.disc_assistant.assistant.controls import execute as control
from experiments.disc_assistant.assistant.queue import observe as observe_queue
from library.store import Store
from library.search.typesense import Search, create_client, signature
from experiments.disc_assistant.assistant.voice.backends import transcribe_file


def server_identity(config):
    return [config.search_protocol, config.search_host, config.search_port]


def status(config, store):
    head = store.head(config.device_key)
    head['database'] = str(store.path)
    head['index_current'] = bool(head['generation'] and head['generation'] == head['index_generation']
        and head['index_signature'] == signature(config.aliases, server_identity(config)))
    return head


async def search_command(config, store, args, trace, intent=None):
    trace.catalog(store)
    trace.event('search', {'command': args.command, 'query': getattr(args, 'text', getattr(args, 'query', ''))})
    key = os.environ.get(config.api_key_env, '')
    if not key.strip():
        raise ValueError(f'set {config.api_key_env} in the process environment (Compose .env is not auto-loaded)')
    client = create_client(config, key)
    try:
        search = Search(client, config.aliases, server_identity(config))
        if args.command == 'index':
            return await search.build(store, config.device_key)
        if args.command in ('ask', 'rank'):
            from contextlib import ExitStack
            from experiments.disc_assistant.assistant.device import PlaybackClient
            from experiments.disc_assistant.assistant.context import read as read_context
            from experiments.disc_assistant.assistant.nlu.intents import Intent
            with ExitStack() as stack:
                shared = None
                def context():
                    nonlocal shared
                    stack.enter_context(device_lock(config.data_dir))
                    shared = stack.enter_context(PlaybackClient(config.host, config.tcp_port, config.timeout))
                    return read_context(config, shared)
                ranking = await rank(config, store, search, intent, trace=trace,
                                     context=context if args.command == 'ask' else None)
                trace.search(ranking)
                if args.command == 'rank' or not ranking['candidates']:
                    return ranking
                trace.select(ranking)
                trace.event('execution_started', {'action': 'play'})
                result = execute(config, store, ranking, shared=shared)
                trace.event('execution_result', outcome(result))
                return result
        result = await search.search(store, config.device_key, args.query, limit=args.limit)
        trace.search(result, phase='retrieval')
        return result
    finally:
        await client.api_call.aclose()


def shadow_sources(config):
    from experiments.disc_assistant.assistant.nlu.interpretation_sources import default_sources
    return default_sources(config) if config.shadow else None


def main(argv=None, *, interpreter=None, transcriber=None, synthesizer=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='path to a TOML configuration')
    parser.add_argument('--language', help='select and persist one interaction locale at startup')
    parser.add_argument('--debug', action='store_true', help='stream bounded request traces to stderr')
    parser.add_argument('--source', choices=('cli', 'scheduled'), help='request origin; scheduled is explicit for cron')
    sub = parser.add_subparsers(dest='command', required=True)
    browser = sub.add_parser('web', help='local Disc Assistant Web interface')
    browser.add_argument('--port', type=int, default=8090)
    browser.add_argument('--bootstrap', action='store_true', help='sync/index before serving')
    sub.add_parser('listen', help='persistent interactive console; existing catalog/index')
    sub.add_parser('start', help='connect, sync, index and enter the persistent console')
    language = sub.add_parser('language', help='show/set the saved interaction locale, or reset to TOML defaults')
    language.add_argument('languages', nargs='*')
    response = sub.add_parser('response', help='show/set saved speech policy')
    response.add_argument('arguments', nargs='*')
    sub.add_parser('locales', help='validate installed command and response locales')
    sub.add_parser('explain', help='preview intent/arguments without execution').add_argument('text')
    sub.add_parser('commands', help='command snapshots: show, rebuild or import FILE').add_argument('arguments', nargs='*')
    history = sub.add_parser('history', help='inspect/export/prune/clear the local request journal')
    history.add_argument('arguments', nargs=argparse.REMAINDER)
    sub.add_parser('sync', help='read the device catalog twice and publish a SQLite snapshot')
    sub.add_parser('status', help='show locally recorded snapshot/index status; no network calls')
    sub.add_parser('queue', help='read the actual device queue and play mode; no search/index required')
    sub.add_parser('index', help='rebuild Typesense from SQLite; no device connection')
    search = sub.add_parser('search', help='show candidates only; never starts playback')
    search.add_argument('query')
    search.add_argument('--limit', type=int, default=10)
    audio = sub.add_parser('transcribe', help='transcribe PCM WAV without interpretation or device access')
    audio.add_argument('audio')
    synth = sub.add_parser('synthesize', help='synthesize text into a new WAV and metadata sidecar; no playback')
    synth.add_argument('text')
    synth.add_argument('--output', required=True)
    samples = sub.add_parser('speech-samples', help='generate the active locale corpus into a new directory')
    samples.add_argument('directory')
    samples.add_argument('--corpus')
    check = sub.add_parser('speech-check', help='evaluate generated samples without device access or preference changes')
    check.add_argument('directory')
    check.add_argument('--catalog', action='store_true', help='evaluate best matches against the current catalog without execution')
    check.add_argument('--expectations', help='explicit selection targets for saved samples (requires --catalog)')
    for name, help_text in [('rank', 'explain ranked candidates without playback'),
                            ('ask', 'play the best match or control current playback')]:
        command = sub.add_parser(name, help=help_text)
        input_group = command.add_mutually_exclusive_group(required=True)
        input_group.add_argument('text', nargs='?')
        input_group.add_argument('--audio', help='PCM WAV input instead of typed text')
    args = parser.parse_args(argv)
    config = None
    try:
        config = load(args.config)
        base_config = config
        if args.command == 'history':
            config = effective_config(config, language=args.language)
            with Trace(config, 'history', 'history', source=args.source or 'cli', persist=False,
                       event_sink=debug_stderr if args.debug else None) as trace:
                result = trace.finish(history_command(config, args.arguments))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'web':
            from experiments.disc_assistant.assistant.web.server import run
            return run(config, port=args.port, language=args.language, bootstrap=args.bootstrap)
        if args.command in ('listen', 'start'):
            from experiments.disc_assistant.assistant.console import run
            return run(config, bootstrap=args.command == 'start', source=args.source or 'interactive',
                       interpreter=interpreter, language=args.language, debug=args.debug, transcriber=transcriber)
        try:
            config = effective_config(config, language=args.language)
        except ValueError:
            recovery = ((args.command == 'language' and args.languages == ['reset']) or
                        (args.command == 'response' and args.arguments == ['reset']))
            if not recovery:
                raise
        text = getattr(args, 'text', getattr(args, 'query', args.command))
        if getattr(args, 'audio', None) is not None:
            text = '[audio]'
        if args.command == 'language':
            text = 'language ' + ' '.join(args.languages)
        if args.command == 'response':
            text = 'response ' + ' '.join(args.arguments)
        with Trace(config, args.command, text, source=args.source or 'cli',
                   event_sink=debug_stderr if args.debug else None) as trace:
            trace.event('parse', {})
            transcription = None
            if getattr(args, 'audio', None) is not None:
                transcription = asyncio.run(transcribe_file(config, args.audio, trace, provider=transcriber))
                args.text = transcription['command_text']
            intent = (asyncio.run(interpret_request(args.text, InterpretationContext(config.locale),
                        interpreter=interpreter, trace=trace, shadow=shadow_sources(config),
                        shadow_timeout_ms=config.shadow_timeout_ms)) if args.command in ('ask', 'rank') else None)
            if args.command == 'explain':
                from experiments.disc_assistant.assistant.nlu.explain import preview
                result = preview(config, args.text, trace)
            elif args.command == 'commands':
                from experiments.disc_assistant.assistant.nlu.command_catalog import command
                result = command(config, args.arguments)
                trace.event('command_catalog', result)
            elif args.command == 'transcribe':
                result = {'status': 'transcribed'}
            elif args.command in ('synthesize', 'speech-samples', 'speech-check'):
                from experiments.disc_assistant.assistant.voice.samples import speech_command
                result = asyncio.run(speech_command(config, args, trace, transcriber=transcriber,
                                                   synthesizer=synthesizer, interpreter=interpreter))
            elif args.command == 'language' or (isinstance(intent, LanguageIntent) and args.command == 'ask'):
                trace.event('preference', {'name': 'language.locale'})
                result = language_command(base_config, [intent.locale] if isinstance(intent, LanguageIntent) else args.languages)
                config = replace(config, locale=result['locale'])
                trace.responses = Responses(config.locale, config.response_mode)
                trace.event('locale_changed', trace.responses.context())
            elif args.command == 'response':
                trace.event('preference', {'name': 'response.mode'})
                result = response_command(base_config, args.arguments)
                config = replace(config, locale=result['locale'], response_mode=result['mode'])
                trace.responses = Responses(config.locale, config.response_mode)
                trace.event('response_preferences', trace.responses.context())
            elif args.command == 'locales':
                result = validate_locales()
            elif args.command == 'queue':
                trace.event('execution_started', {'action': 'queue', 'read_only': True})
                result = observe_queue(config)
            elif isinstance(intent, (ControlIntent, VolumeIntent, LanguageIntent)):
                if args.command == 'rank':
                    result = {'status': 'planned', 'action': intent.action if isinstance(intent, (ControlIntent, VolumeIntent)) else 'set_language', 'requires_search': False, 'intent': asdict(intent)}
                else:
                    trace.event('execution_started', {'action': intent.action})
                    result = control(config, intent)
            else:
                result = run_catalog_command(config, args, trace, intent)
            if transcription is not None:
                result['transcription'] = transcription
            trace.finish(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('status') in ('not_sent', 'uncertain', 'evaluation_failed') else 0
    except (ValueError, OSError, RuntimeError) as exc:
        if config is not None:
            print(json.dumps(exception_result(config, exc, source=args.source or 'cli'), ensure_ascii=False, indent=2))
        suffix = f' (request {exc.request_id})' if hasattr(exc, 'request_id') else ''
        print(f'Assistant: {exc}{suffix}', file=sys.stderr)
        return 1
    except Exception as exc:
        if config is not None:
            print(json.dumps(exception_result(config, exc, source=args.source or 'cli'), ensure_ascii=False, indent=2))
        # SDK errors can contain server response bodies. Keep personal data and
        # credentials out of accidental terminal logs.
        suffix = f' (request {exc.request_id})' if hasattr(exc, 'request_id') else ''
        print(f'Assistant: {type(exc).__name__}; check the configured service and credentials{suffix}', file=sys.stderr)
        return 1


def run_catalog_command(config, args, trace, intent=None):
    with Store(config.data_dir) as store:
        if args.command == 'sync':
            trace.event('execution_started', {'action': 'sync', 'read_only': True})
            with device_lock(config.data_dir):
                result = sync(config, store)
        elif args.command == 'status':
            result = status(config, store)
        else:
            result = asyncio.run(search_command(config, store, args, trace, intent))
    return result


if __name__ == '__main__':
    sys.exit(main())
