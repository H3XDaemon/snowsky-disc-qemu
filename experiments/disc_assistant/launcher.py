"""Local development commands behind run.sh; no shell evaluation of .env values."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

from experiments.disc_assistant.assistant.config import load

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
ENV_FILE = PACKAGE / 'assistant/.env'


def read_env(path):
    result = {}
    if not path.exists():
        return result
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, raw = line.removeprefix('export ').partition('=')
        key = key.strip()
        if not sep or key not in ('TYPESENSE_API_KEY', 'TYPESENSE_PORT') or key in result:
            raise ValueError(f'invalid or duplicate .env setting at line {line_number}')
        try:
            tokens = shlex.split(raw, comments=True)
        except ValueError as exc:
            raise ValueError(f'invalid .env quoting at line {line_number}') from exc
        if len(tokens) > 1:
            raise ValueError(f'quote .env values containing spaces at line {line_number}')
        result[key] = tokens[0] if tokens else ''
    return result


def initialize(config_path):
    # Validate existing environment before changing anything; preserve private keys.
    values = read_env(ENV_FILE)
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'x', encoding='utf-8', opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
            output.write((PACKAGE / 'assistant/config.example.toml').read_text())
    if not values.get('TYPESENSE_API_KEY'):
        key = secrets.token_hex(32)
        old = ENV_FILE.read_text() if ENV_FILE.exists() else ''
        lines = old.splitlines()
        replaced = False
        for index, line in enumerate(lines):
            if line.strip().removeprefix('export ').partition('=')[0].strip() == 'TYPESENSE_API_KEY':
                lines[index] = 'TYPESENSE_API_KEY=' + key
                replaced = True
        if not replaced:
            lines.append('TYPESENSE_API_KEY=' + key)
        # Atomic replace; only a missing/empty key is initialized. Never print it.
        temporary = ENV_FILE.with_name('.env.setup-' + secrets.token_hex(6))
        try:
            with open(temporary, 'x', encoding='utf-8', opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
                output.write('\n'.join(lines) + '\n')
            temporary.replace(ENV_FILE)
        finally:
            temporary.unlink(missing_ok=True)
    print(f'Config: {config_path}\nSearch credentials: {ENV_FILE} (value hidden)')
    print('Edit device.host/key and ports before sync. Physical DISC: TCP 12100, HTTP 12103.')


def environment(config):
    result = dict(os.environ)
    local = read_env(ENV_FILE)
    # The config selects the secret variable. Default local .env takes precedence
    # over a stale exported key, consistently for Compose and the application.
    if config.api_key_env == 'TYPESENSE_API_KEY' and local.get('TYPESENSE_API_KEY'):
        result[config.api_key_env] = local['TYPESENSE_API_KEY']
    key = result.get(config.api_key_env, '')
    if not key.strip():
        raise ValueError('search key missing; run setup or set the configured api_key_env variable')
    result['TYPESENSE_API_KEY'] = key
    # One source for the port with this launcher. Legacy .env port is for manual Compose only.
    result['TYPESENSE_PORT'] = str(config.search_port)
    return result


def compose_command(*args, config=None):
    command = ['docker', 'compose', '--env-file', '/dev/null', '-p', 'disc-assistant',
               '-f', str(PACKAGE / 'assistant/compose.yaml')]
    if config is not None and config.typesense_io_compat:
        command += ['-f', str(PACKAGE / 'assistant/compose.io-compat.yaml')]
    return [*command, *args]


class SearchReadinessError(RuntimeError):
    """Safe diagnostic text, without credentials or provider response bodies."""


def wait_ready(config, timeout=45):
    url = f'{config.search_protocol}://{config.search_host}:{config.search_port}/health'
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200 and json.load(response).get('ok') is True:
                    print(f'Typesense ready: {url}')
                    return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        if time.monotonic() >= deadline:
            raise SearchReadinessError(
                'Typesense readiness timed out; inspect the disc-assistant container logs. '
                'For exit 139 with missing /proc/self/io, see experiments/disc_assistant/docs/guides/typesense.md '
                '(typesense.io_accounting_compat).')
        time.sleep(0.5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.environ.get('DISC_ASSISTANT_CONFIG', '~/disc-assistant.toml'))
    parser.add_argument('--language', help='select and persist one interaction locale')
    parser.add_argument('--debug', action='store_true', help='stream application request traces')
    parser.add_argument('--source', choices=('cli', 'scheduled'))
    parser.add_argument('command', choices=('setup', 'speech-up', 'speech-down', 'speech-benchmark', 'up', 'down', 'start', 'listen', 'web', 'language', 'response', 'locales', 'explain', 'commands', 'history', 'sync', 'status', 'queue', 'index', 'search', 'rank', 'ask', 'transcribe', 'synthesize', 'speech-samples', 'speech-check', 'shadow-report', 'test', 'check'))
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = Path(os.environ.get('DISC_ASSISTANT_CALLER_DIR', os.getcwd())) / config_path
    config_path = config_path.resolve()
    try:
        if args.debug and args.command in ('setup', 'up', 'down', 'test', 'check', 'shadow-report'):
            raise ValueError('--debug applies to application commands, such as start/listen/ask')
        if args.language:
            from experiments.disc_assistant.assistant.responses import validate_locale
            validate_locale(args.language)
            if args.command in ('setup', 'up', 'down', 'test', 'check', 'shadow-report'):
                raise ValueError('--language applies to application commands, such as start/listen/ask')
        if args.command not in ('setup', 'web', 'search', 'rank', 'ask', 'explain', 'commands', 'language', 'response', 'history',
                                'transcribe', 'synthesize', 'speech-samples', 'speech-check', 'speech-benchmark', 'shadow-report') and args.arguments:
            raise ValueError('unexpected arguments; see run.sh help')
        if args.command == 'shadow-report':
            if args.source:
                raise ValueError('--source does not apply to offline shadow reports')
            from experiments.disc_assistant.assistant.nlu.evaluation.shadow_report import main as report_main
            # run.sh changes cwd; resolve all file arguments against its caller.
            caller = Path(os.environ.get('DISC_ASSISTANT_CALLER_DIR', os.getcwd()))
            arguments = list(args.arguments)
            for index, value in enumerate(arguments):
                if index and arguments[index - 1] in ('--history', '--output', '--reviewed'):
                    arguments[index] = str(caller / Path(value).expanduser())
                elif any(value.startswith(flag + '=') for flag in ('--history', '--output', '--reviewed')):
                    flag, path = value.split('=', 1)
                    arguments[index] = flag + '=' + str(caller / Path(path).expanduser())
            return report_main(arguments)
        if args.command == 'setup':
            setup_parser = argparse.ArgumentParser(prog='run.sh setup')
            setup_parser.add_argument('--all', action='store_true')
            setup_parser.add_argument('--whisper-model', choices=('base', 'small'),
                                      help='explicitly replace the STT model; otherwise preserve the configured model')
            setup_args = setup_parser.parse_args(args.arguments)
            if not setup_args.all and setup_args.whisper_model is not None:
                raise ValueError('--whisper-model requires setup --all')
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r',
                            str(PACKAGE / 'assistant/requirements.txt')], check=True, cwd=ROOT)
            initialize(config_path)
            if setup_args.all:
                subprocess.run([sys.executable, '-m', 'pip', 'install', '-r',
                                str(PACKAGE / 'assistant/requirements-speech.txt')], check=True, cwd=ROOT)
                from experiments.disc_assistant.speech_setup import install
                install(config_path, model=setup_args.whisper_model)
            return 0
        if args.command in ('test', 'check'):
            module = (['ci.assistant_unit']
                      if args.command == 'test' else ['experiments.disc_assistant.check'])
            return subprocess.run([sys.executable, '-B', '-m', *module], cwd=ROOT).returncode
        if args.command == 'down':
            # Compose validates interpolation even for down. Stopping this named
            # stack must also work after a config/key has been moved or lost.
            env = {**os.environ, 'TYPESENSE_API_KEY': 'unused-for-stop', 'TYPESENSE_PORT': '8108'}
            return subprocess.run(compose_command('down'), env=env, cwd=ROOT).returncode
        if not config_path.is_file():
            raise ValueError(f'config missing: {config_path}; run setup or pass --config PATH')
        config = load(config_path)
        if args.command == 'speech-benchmark':
            if args.debug or args.language or args.source:
                raise ValueError('speech-benchmark uses its own --locale; --debug/--source/--language do not apply')
            from experiments.disc_assistant.evaluation.speech_benchmark import main as benchmark_main
            return benchmark_main(args.arguments, config)
        if args.command in ('speech-up', 'speech-down'):
            from experiments.disc_assistant.speech_setup import manage
            return manage(config, 'up' if args.command == 'speech-up' else 'down')
        if args.command == 'web' and '--bootstrap' in args.arguments and config.services.get('speech'):
            from experiments.disc_assistant.speech_setup import manage
            try:
                manage(config, 'up')
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                print(f'Speech startup unavailable ({type(exc).__name__}); text input remains available.', file=sys.stderr)
        needs_search = args.command in ('up', 'index', 'search', 'rank', 'ask') or (
            args.command == 'speech-check' and '--catalog' in args.arguments)
        env = dict(os.environ)
        if needs_search:
            try:
                env = environment(config)
            except (OSError, ValueError):
                if args.command == 'up':
                    raise
                # Forward to the application so search-configuration failures are
                # journaled too. Never fall back to a possibly stale exported key.
                env.pop(config.api_key_env, None)
        if args.command in ('start', 'listen', 'web'):
            try:
                env = environment(config)
                if args.command == 'start' or (args.command == 'web' and '--bootstrap' in args.arguments):
                    if config.search_host in ('localhost', '127.0.0.1') and config.search_protocol == 'http':
                        subprocess.run(compose_command('up', '-d', config=config), check=True, env=env, cwd=ROOT,
                                       timeout=600 if config.typesense_io_compat else 60)
                    wait_ready(config)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                env.pop(config.api_key_env, None)
                print(f'Search startup unavailable ({type(exc).__name__}); entering the interface with playback controls.',
                      file=sys.stderr)
                if isinstance(exc, SearchReadinessError):
                    print(str(exc), file=sys.stderr)
        if args.command == 'up':
            if config.search_host not in ('localhost', '127.0.0.1') or config.search_protocol != 'http':
                raise ValueError('up/down manage local HTTP Typesense only; remote search is externally managed')
            subprocess.run(compose_command('up', '-d', config=config), check=True, env=env, cwd=ROOT)
            wait_ready(config)
            return 0
        return subprocess.run([sys.executable, '-m', 'experiments.disc_assistant.assistant',
                               '--config', str(config_path),
                               *(['--source', args.source] if args.source else []),
                               *(['--debug'] if args.debug else []),
                               *(['--language', args.language] if args.language else []), args.command, *args.arguments],
                              cwd=ROOT, env=env).returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Assistant launcher: {exc}', file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print('Assistant launcher: dependency service operation timed out', file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f'Assistant launcher: command failed (exit {exc.returncode})', file=sys.stderr)
        return exc.returncode


if __name__ == '__main__':
    sys.exit(main())
