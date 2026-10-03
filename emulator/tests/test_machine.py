"""Stock-init guest lifecycle pieces that need no firmware or namespaces."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from emulator.runtime import guest_init, machine
from emulator.runtime.keys import Device

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


class MachineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / 'rootfs'
        (self.root / 'emu').mkdir(parents=True)

    def fake_init(self):
        """A live process whose command line looks like a guest's PID 1."""
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)',
                                    '-m', 'emulator.runtime.guest_init'])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        (self.root / 'emu/init.pid').write_text(f'{process.pid}\n')
        deadline = time.monotonic() + 5                 # its command line appears once it has started
        while machine.init_pid(self.root) != process.pid and time.monotonic() < deadline:
            time.sleep(.05)
        return process

    def test_init_environment_is_busybox_init(self):
        self.assertEqual(guest_init.ENVIRONMENT['PATH'], '/sbin:/usr/sbin:/bin:/usr/bin')
        self.assertEqual(set(guest_init.ENVIRONMENT), {'HOME', 'PATH', 'SHELL', 'USER', 'TERM'})
        self.assertIn('--no-new-privs', guest_init.CONFINE)
        self.assertIn('-sys_boot', guest_init.CONFINE[1])

    def test_reap_collects_orphans_and_reports_the_wanted_child(self):
        init = guest_init.Init(self.root)
        other = subprocess.Popen(['true'])
        wanted = subprocess.Popen(['sh', '-c', 'exit 7'])
        deadline, status = time.monotonic() + 5, None
        while status is None and time.monotonic() < deadline:
            status = init.reap(wanted.pid)
        self.assertEqual(os.waitstatus_to_exitcode(status), 7)
        while time.monotonic() < deadline:
            try:
                os.kill(other.pid, 0)
            except ProcessLookupError:
                break
            init.reap()
        with self.assertRaises(ProcessLookupError):
            os.kill(other.pid, 0)
        other.returncode, wanted.returncode = 0, 7                 # reaped here, not by Popen

    def test_missing_or_stale_state_is_off(self):
        self.assertEqual(machine.state(self.root)['state'], 'off')
        self.assertFalse(machine.active(self.root))
        (self.root / 'emu/machine.json').write_text(json.dumps(dict(state='running', pid=os.getpid(), boots=1)))
        (self.root / 'emu/init.pid').write_text(f'{os.getpid()}\n')   # alive, but not a guest init
        self.assertIsNone(machine.supervisor_pid(self.root))
        self.assertIsNone(machine.init_pid(self.root))

    def test_live_init_is_recognised_and_start_is_refused(self):
        process = self.fake_init()
        self.assertEqual(machine.init_pid(self.root), process.pid)
        with self.assertRaises(RuntimeError):
            machine.start(self.root)

    def test_cut_without_a_guest_is_a_no_op(self):
        with patch('emulator.runtime.machine.restore_view') as restore:
            machine.cut(self.root)
        restore.assert_not_called()

    def test_cut_finishes_an_orphaned_guest(self):
        process = self.fake_init()
        with patch('emulator.runtime.machine.restore_view') as restore, \
                patch('emulator.runtime.machine.guest_processes', return_value=[]):
            machine.cut(self.root)
        self.assertEqual(process.wait(5), -signal.SIGKILL)
        restore.assert_called_once()

    def test_power_request_is_left_to_a_live_guest_init(self):
        (self.root / 'emu/power-request').write_bytes(b'1')
        self.fake_init()
        device = Device(self.root)
        with patch.object(device, 'processes', return_value=[123]):
            device.service_requests()
        self.assertIsNone(device.transition)
        self.assertEqual((self.root / 'emu/power-request').read_bytes(), b'1')

    def test_time_namespace_starts_the_guest_uptime_near_zero(self):
        with patch('emulator.runtime.machine.Path.read_text', return_value='1328973.44 1200.00\n'):
            self.assertEqual(machine.time_namespace(), ['--time', '--boottime=-1328972', '--monotonic=-1328972'])
        with patch('emulator.runtime.machine.Path.read_text', return_value='0.50 0.00\n'):
            self.assertEqual(machine.time_namespace(), ['--time', '--boottime=-0', '--monotonic=-0'])

    def test_supervisor_failure_stops_the_guest_and_restores_the_view(self):
        board = machine.Machine(self.root)
        with patch.object(board, 'power_on', side_effect=RuntimeError('boom')), \
                patch('emulator.runtime.machine.kill_guest_tree') as kill, \
                patch('emulator.runtime.machine.restore_view') as restore, \
                patch('emulator.runtime.machine.gpio.release'), \
                patch('emulator.runtime.machine.signal.signal'), \
                patch('emulator.runtime.machine.traceback.print_exc'):
            board.run()
        kill.assert_called_once()
        restore.assert_called_once()
        state = machine.state(self.root)
        self.assertEqual((state['state'], state['reason']), ('off', 'supervisor error: boom'))

    def test_cut_request_carries_reason_and_unsynced_flag(self):
        board = machine.Machine(self.root)
        board.on_cut(signal.SIGUSR1, None)
        (self.root / 'emu/machine-request').write_text('{"unsynced": true}')
        self.assertEqual(board.cut_request(), ('power cut', True))
        self.assertFalse((self.root / 'emu/machine-request').exists())
        board.cut = 'lifetime limit (GUEST_TTL)'
        self.assertEqual(board.cut_request(), ('lifetime limit (GUEST_TTL)', False))


class ShellTests(unittest.TestCase):
    """lib.sh and the installed stubs, with host commands replaced by recorders."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / 'rootfs'
        (self.root / 'emu').mkdir(parents=True)
        commands = self.base / 'commands'
        commands.mkdir()
        for name in ('nsenter', 'timeout'):
            (commands / name).write_text(f'#!/bin/sh\necho {name} "$@"\n')
            (commands / name).chmod(0o755)
        self.env = dict(os.environ, PATH=f'{commands}:{os.environ["PATH"]}', ROOTFS=str(self.root),
                        WORK=str(self.base), REPO=str(SCRIPTS.parents[1]), FW_VERSION='2.57')

    def guest_run(self, *command):
        return subprocess.check_output(['bash', '-c', f'source {SCRIPTS}/lib.sh; guest_run "$@"', '-', *command],
                                       env=self.env, text=True).split()

    def test_guest_run_is_unchanged_without_a_stock_init_guest(self):
        words = self.guest_run('0', '/bin/true')
        self.assertEqual(words[:3], ['timeout', '0', 'setpriv'])
        self.assertEqual(words[-3:], ['chroot', str(self.root), '/bin/true'])

    def test_guest_run_joins_a_live_guests_namespaces(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)',
                                    '-m', 'emulator.runtime.guest_init'])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        (self.root / 'emu/init.pid').write_text(f'{process.pid}\n')
        words = self.guest_run('15', '/bin/ps')
        self.assertEqual(words[:9], ['nsenter', '--target', str(process.pid), '--pid', '--ipc', '--uts', '--time',
                                     '--', 'timeout'])
        (self.root / 'emu/init.pid').write_text('1\n')                # some other live process
        self.assertEqual(self.guest_run('15', '/bin/ps')[0], 'timeout')

    def test_loops_of_a_missing_image_are_never_looked_up_by_name(self):
        (self.base / 'commands/losetup').write_text('#!/bin/sh\necho "/dev/loop7: [0]:1 ($2)"\n')
        (self.base / 'commands/losetup').chmod(0o755)
        loops = lambda path: subprocess.check_output(  # noqa: E731
            ['bash', '-c', f'source {SCRIPTS}/lib.sh; image_loops "$1"', '-', str(path)], env=self.env, text=True)
        self.assertEqual(loops(self.base / 'absent.img'), '')     # would name another container's loop
        (self.base / 'present.img').touch()
        self.assertEqual(loops(self.base / 'present.img'), '/dev/loop7\n')

    def test_loop_attach_creates_the_node_the_container_lacks(self):
        node = self.base / 'loop42'
        (self.base / 'commands/losetup').write_text(
            f'#!/bin/sh\n[ "$1" = -f ] && echo {node} || echo "attach $@" >> {self.base}/losetup.log\n')
        (self.base / 'commands/losetup').chmod(0o755)
        (self.base / 'commands/mknod').write_text(f'#!/bin/sh\necho "$@" >> {self.base}/mknod.log\n')
        (self.base / 'commands/mknod').chmod(0o755)
        output = subprocess.check_output(['bash', '-c', f'source {SCRIPTS}/lib.sh; loop_attach /work/card.img'],
                                         env=self.env, text=True)
        self.assertEqual(output, f'{node}\n')
        self.assertEqual((self.base / 'mknod.log').read_text(), f'{node} b 7 42\n')
        self.assertEqual((self.base / 'losetup.log').read_text(), f'attach {node} /work/card.img\n')

    def stub(self, name, *args):
        target = self.base / name
        target.unlink(missing_ok=True)
        target.symlink_to(SCRIPTS / 'guest-init-stub.sh')
        return subprocess.run(['sh', str(target), *args], capture_output=True, text=True)

    def test_init_stubs_succeed_loudly_and_unknown_names_fail(self):
        for name, args in (('insmod', ['soc_gpio.ko']), ('ifup', ['-a']), ('dnsmasq', []),
                           ('rpc.nfsd', ['2']), ('mdev', ['-s']), ('mount_ubifs.sh', ['userdata', '/usr/data/'])):
            with self.subTest(name=name):
                result = self.stub(name, *args)
                self.assertEqual(result.returncode, 0)
                self.assertIn('[emu-init]', result.stderr)
                self.assertEqual(result.stdout, '')
        self.assertEqual(self.stub('reboot').returncode, 1)

    def test_power_script_rejects_unknown_actions_before_touching_a_guest(self):
        for args in ([], ['explode'], ['cut', '--now']):
            with self.subTest(args=args):
                result = subprocess.run(['bash', str(SCRIPTS / '25_power.sh'), *args],
                                        env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('usage', result.stderr)


if __name__ == '__main__':
    unittest.main()
