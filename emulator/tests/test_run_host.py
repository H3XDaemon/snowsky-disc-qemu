"""Exercise the host launcher without touching a Docker daemon or user state."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class HostSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'checkout with spaces'
        self.component = self.root / 'emulator'
        self.component.mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'run.sh', self.component / 'run.sh')
        self.caller = Path(self.temp.name).resolve() / 'caller elsewhere'
        self.caller.mkdir()
        self.ota = self.caller / 'firmware chunks'
        self.ota.mkdir()
        (self.ota / 'rootfs.squashfs.0000.test.enc').touch()
        self.log = self.root / 'docker.jsonl'
        commands = self.root / 'commands'
        commands.mkdir()
        docker = commands / 'docker'
        docker.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
assert args[0] == 'compose', args
assert args[1] == '--project-directory', args
assert args[3] == '--env-file', args
assert args[5] == '-f', args
args = args[7:]
if args[0] == '--profile':
    args = args[2:]
if args[0] == os.environ.get('FAKE_FAIL'):
    sys.exit(19)
if args[0] == 'ps':
    state = os.environ.get('FAKE_STATE', 'running')
    if state == 'running' or (state == 'stopped' and '--all' in args):
        print('custom-container-id')
if args == ['config', '--environment']:
    print('OTA_DIR=' + os.environ.get('FAKE_CONFIG_OTA', ''))
''')
        docker.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ('OTA_DIR', 'COMPOSE_FILE', 'COMPOSE_PROJECT_NAME', 'COMPOSE_ENV_FILES')}
        self.env.update(PATH=str(commands) + ':' + os.environ['PATH'], FAKE_LOG=str(self.log))

    def run_launcher(self, *args, check=True, **environment):
        return subprocess.run(['bash', str(self.component / 'run.sh'), *args],
                              cwd=self.caller, env={**self.env, **environment},
                              check=check, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_up_preserves_other_env_entries_and_ignores_root_env(self):
        original = '# custom settings\nFW_VERSION=2.40\nWORK_VOLUME=legacy-work\nOTA_DIR=/old\nSTREAM_FPS=18'
        (self.component / '.env').write_text(original)
        (self.root / '.env').write_text('OTA_DIR=/must-not-use\nWORK_VOLUME=unrelated\n')
        self.run_launcher('up', self.ota.name)
        rows = (self.component / '.env').read_text().splitlines()
        self.assertEqual([r for r in rows if r.startswith('OTA_DIR=')], [f'OTA_DIR="{self.ota}"'])
        for value in ('# custom settings', 'FW_VERSION=2.40', 'WORK_VOLUME=legacy-work', 'STREAM_FPS=18'):
            self.assertIn(value, rows)
        self.assertEqual((self.root / '.env').read_text(), 'OTA_DIR=/must-not-use\nWORK_VOLUME=unrelated\n')
        for call in self.calls():
            self.assertEqual(call[:7], ['compose', '--project-directory', str(self.root),
                                       '--env-file', str(self.component / '.env'),
                                       '-f', str(self.component / 'compose.yaml')])
        self.assertIn(['up', '-d', '--build'], [c[7:] for c in self.calls()])
        self.assertTrue(all(c[9] == 'emulator' for c in self.calls() if c[7] == 'exec'))

    def test_up_escapes_dotenv_characters_without_executing_them(self):
        ota = self.caller / 'firmware $literal "quote" \\backtick`'
        ota.mkdir()
        (ota / 'rootfs.squashfs.0000.test.enc').touch()
        self.run_launcher('up', ota.name)
        escaped = str(ota).replace('\\', '\\\\').replace('"', '\\"').replace('$', '$$')
        self.assertEqual((self.component / '.env').read_text(), f'OTA_DIR="{escaped}"\n')

    def test_up_uses_compose_to_resolve_configured_ota_from_repository(self):
        (self.component / '.env').write_text('OTA_DIR="./firmware chunks"\n')
        destination = self.root / 'firmware chunks'
        shutil.copytree(self.ota, destination)
        self.run_launcher('up', FAKE_CONFIG_OTA='./firmware chunks')
        self.assertIn(f'OTA_DIR="{destination}"', (self.component / '.env').read_text())
        self.assertEqual(self.calls()[0][7:], ['config', '--environment'])

    def test_up_shell_ota_is_caller_relative(self):
        self.run_launcher('up', OTA_DIR=self.ota.name)
        self.assertEqual((self.component / '.env').read_text(), f'OTA_DIR="{self.ota}"\n')

    def test_root_env_is_never_migrated_or_used_as_fallback(self):
        (self.root / '.env').write_text(f'OTA_DIR={self.ota}\n')
        result = self.run_launcher('up', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('emulator/.env', result.stderr)
        self.assertFalse((self.component / '.env').exists())
        self.assertFalse(self.log.exists())

    def test_help_is_read_only_and_needs_no_docker(self):
        result = self.run_launcher('help')
        self.assertIn('./emulator/run.sh', result.stdout)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.component / '.env').exists())

    def test_existing_stopped_service_starts_without_creating_or_building(self):
        self.run_launcher('start', FAKE_STATE='stopped')
        self.assertEqual([c[7:] for c in self.calls()], [
            ['ps', '--status', 'running', '--quiet', 'emulator'],
            ['ps', '--all', '--quiet', 'emulator'], ['start', 'emulator']])
        self.assertTrue(all(c[4] == '/dev/null' for c in self.calls()))

    def test_missing_service_and_docker_failure_do_not_start_or_create(self):
        for settings in ({'FAKE_STATE': 'missing'}, {'FAKE_FAIL': 'ps'}):
            with self.subTest(settings=settings):
                self.log.unlink(missing_ok=True)
                result = self.run_launcher('start', check=False, **settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(all(c[7] == 'ps' for c in self.calls()))

    def test_capture_passes_literal_arguments_and_uses_repository_shots(self):
        prefix = 'snapshot $(touch UNEXPECTED)'
        self.run_launcher('capture', prefix, EMU_CONTAINER_NAME='custom-device')
        self.assertIn(['exec', '-T', 'emulator', 'bash', '/repo/emulator/scripts/capture.sh', prefix],
                      [c[7:] for c in self.calls()])
        self.assertIn(['cp', 'emulator:/work/shots/.', str(self.root / 'shots') + '/'],
                      [c[7:] for c in self.calls()])
        self.assertFalse((self.caller / 'UNEXPECTED').exists())

    def test_boot_options_reach_the_guest_scripts_as_environment(self):
        self.run_launcher('boot', '--init', '--hold', 'volume_up,play', '5')
        boot = [c[7:] for c in self.calls() if c[7] == 'exec'][0]
        self.assertEqual(boot[:7], ['exec', '-T', '-e', 'BOOT_MODE=init', '-e', 'BOOT_KEYS=volume_up,play', 'emulator'])
        self.assertEqual(boot[-2:], ['--', '5'])
        self.log.unlink()
        self.run_launcher('boot')
        self.assertEqual([c[7:] for c in self.calls() if c[7] == 'exec'][0][:3], ['exec', '-T', 'emulator'])
        result = self.run_launcher('boot', '--fast', check=False)
        self.assertEqual(result.returncode, 2)

    def test_power_and_keys_pass_arguments_to_the_container(self):
        self.run_launcher('power', 'cut', '--unsynced')
        self.assertEqual(self.calls()[-1][7:], ['exec', '-T', 'emulator', 'bash',
                                               '/repo/emulator/scripts/25_power.sh', 'cut', '--unsynced'])
        self.run_launcher('keys', 'arm', 'play')
        self.assertEqual(self.calls()[-1][7:], ['exec', '-T', 'emulator', 'python3', '-B', '-m',
                                               'emulator.runtime.gpio', 'arm', 'play'])

    def test_up_image_mounts_the_image_folder_and_never_edits_env(self):
        image = self.caller / 'candidate image.bin'
        image.write_bytes(b'hsqs')
        self.run_launcher('up-image', image.name)
        calls = [c[7:] for c in self.calls()]
        self.assertEqual(calls[0], ['up', '-d', '--build'])
        self.assertEqual(calls[1][-2:], ['--', 'candidate image.bin'])
        self.assertIn('01_image_rootfs.sh', calls[1][-3])
        self.assertFalse((self.component / '.env').exists())
        self.assertNotEqual(self.run_launcher('up-image', 'missing.bin', check=False).returncode, 0)

    def test_capture_copy_failure_is_not_reported_as_success(self):
        result = self.run_launcher('capture', check=False, FAKE_FAIL='cp')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('PNGs copied', result.stdout)

    def test_down_preserves_volume_and_nuke_is_explicit(self):
        for command, args in (('down', ['down']), ('nuke', ['down', '-v'])):
            with self.subTest(command=command):
                self.log.unlink(missing_ok=True)
                self.run_launcher(command)
                self.assertEqual(self.calls()[0][7:], ['--profile', 'wsbridge', *args])

    def test_wscheck_uses_new_service_dns_and_passes_control_flag(self):
        self.run_launcher('wscheck', '--control')
        self.assertEqual(self.calls()[-1][7:], [
            '--profile', 'wsbridge', 'exec', '-T', 'wsbridge', 'python3', '-B', '-m',
            'controller.diagnostics.verify_websocket', '--tcp-host', 'emulator', '--control'])

    def test_compose_passthrough_keeps_paths_and_arguments(self):
        self.run_launcher('compose', '--profile', 'wsbridge', 'config', '--quiet')
        self.assertEqual(self.calls()[0][7:], ['--profile', 'wsbridge', 'config', '--quiet'])

    def test_unknown_command_fails_without_docker(self):
        result = self.run_launcher('not-a-command', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())
