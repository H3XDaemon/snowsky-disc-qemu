from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from emulator.runtime.boot_ready import argv0, flusher, holders, own_pid, ready, wait_ready, watched


class BootReadyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / 'rootfs'
        (self.root / 'emu').mkdir(parents=True)
        (self.root / 'dev/input').mkdir(parents=True)
        # The marker names the flusher by the PID it has in ITS namespace: the stock-init
        # guest's UI is 1 here (container PID 1) but 37 inside the guest.
        self.marker = self.root / 'emu/fb-flush'
        self.marker.write_text('37\n')
        self.proc = self.base / 'proc'
        for pid, program, event, inner in ((1, 'mq_ui', 'event1', 37), (2, 'mq_player', 'event0', 52)):
            entry = self.proc / str(pid)
            (entry / 'fd').mkdir(parents=True)
            (entry / 'cmdline').write_bytes(f'qemu\0/usr/bin/{program}\0'.encode())
            (entry / 'comm').write_text(program + '\n')
            (entry / 'status').write_text(f'Name:\t{program}\nPid:\t{pid}\nNSpid:\t{pid}\t{inner}\n')
            (self.root / 'dev/input' / event).touch()
            (entry / 'fd/3').symlink_to('anon_inode:[eventpoll]')
            (entry / 'fd/4').symlink_to(self.root / 'dev/input' / event)
        self.device = Mock(root=self.root)
        self.device.processes.return_value = [1, 2]

    def test_requires_both_input_consumers_and_a_frame_from_this_ui(self):
        self.assertTrue(ready(self.device, self.proc))
        for marker in ('', '36\n', '52\n', '1\n', 'x'):          # nobody, a predecessor, the player, a probe
            self.marker.write_text(marker)
            self.assertFalse(ready(self.device, self.proc))
        self.marker.write_text('        37\n')                    # the fixed-width record as written
        self.assertTrue(ready(self.device, self.proc))
        self.device.processes.return_value = [1]
        self.assertFalse(ready(self.device, self.proc))
        self.device.processes.return_value = [1, 2]
        (self.proc / '2/fd/4').unlink()
        self.assertFalse(ready(self.device, self.proc))

    def test_direct_boot_has_no_nested_namespace(self):
        (self.proc / '1/status').write_text('Name:\tmq_ui\nPid:\t1\nNSpid:\t1\n')
        self.assertEqual(own_pid(1, self.proc), 1)
        self.assertFalse(ready(self.device, self.proc))     # 37 was the guest-namespace PID
        self.marker.write_text('1\n')
        self.assertTrue(ready(self.device, self.proc))
        (self.proc / '1/status').write_text('Name:\tmq_ui\n')   # no NSpid line (older kernels)
        self.assertEqual(own_pid(1, self.proc), 1)
        self.assertTrue(ready(self.device, self.proc))

    def process(self, pid, cmdline, comm, preserved=None):
        """A guest process as the container sees it: qemu's cmdline, the program's comm."""
        entry = self.proc / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / 'cmdline').write_bytes(b''.join(part.encode() + b'\0' for part in cmdline))
        (entry / 'comm').write_text(comm + '\n')
        if preserved is not None:                       # AT_FLAGS (8) with bit 0 = argv[0] preserved
            (entry / 'auxv').write_bytes((8).to_bytes(8, 'little') + int(preserved).to_bytes(8, 'little') + bytes(16))

    def test_argv0_follows_the_three_qemu_layouts(self):
        qemu = '/usr/local/lib/qemu-mipsel-abc/qemu-mipsel-static'
        self.process(10, [qemu, '/usr/bin/mq_ui', 'mq_ui'], 'mq_ui', preserved=True)        # binfmt P: exec mq_ui
        self.process(11, [qemu, '/usr/bin/mq_ui', '/usr/bin/mq_ui'], 'mq_ui', preserved=True)   # exec /usr/bin/mq_ui
        self.process(12, [qemu, '-0', 'mq_ui', '/usr/data/mq_ui', '-v'], 'mq_ui')                # explicit -0
        self.process(13, [qemu, '/usr/data/mq_ui', '-v'], 'mq_ui', preserved=False)              # explicit plain
        self.process(14, [qemu, '-g', '1234', '/usr/bin/mq_player'], 'mq_player', preserved=False)   # unknown options
        self.process(15, ['python3', '-m', 'emulator.runtime.guest_init'], 'init')                 # not a guest
        self.assertEqual([argv0(pid, self.proc) for pid in range(10, 16)],
                         ['mq_ui', '/usr/bin/mq_ui', 'mq_ui', '/usr/data/mq_ui', None, None])

    def test_watched_is_busybox_pgrep_x_on_the_player(self):
        qemu = '/usr/bin/qemu-mipsel-static'
        self.process(20, [qemu, '/usr/bin/mq_ui', 'mq_ui'], 'mq_ui', preserved=True)
        self.process(21, [qemu, '/usr/bin/mq_ui', '/usr/bin/mq_ui'], 'mq_ui', preserved=True)
        self.process(22, [qemu, '/usr/bin/mq_ui', '/sbin/mq_ui'], 'mq_ui', preserved=True)
        self.process(23, [qemu, '/bin/busybox', 'sh', '/sbin/mq_ui'], 'sh', preserved=True)     # a wrapper script
        self.process(24, [qemu, '/usr/data/ui', 'disc-ui'], 'mq_ui', preserved=True)           # name only in comm
        self.assertTrue(watched('mq_ui', 20, self.proc))        # argv[0] is the name
        self.assertFalse(watched('mq_ui', 21, self.proc))       # the name occurs in a path: no fallback to comm
        self.assertFalse(watched('mq_ui', 22, self.proc))
        self.assertFalse(watched('mq_ui', 23, self.proc))
        self.assertTrue(watched('mq_ui', 24, self.proc))        # not in argv[0] at all: comm decides
        self.assertFalse(watched('mq_ui', 999, self.proc))      # gone
        # The pair stock's own fiio_init.sh starts (`mq_ui &`, `mq_player &`) is watched.
        self.assertTrue(watched('mq_ui', 1, self.proc) and watched('mq_player', 2, self.proc))

    def test_flusher_reads_the_marker_or_nothing(self):
        self.assertEqual(flusher(self.device), 37)
        self.marker.write_text('')
        self.assertIsNone(flusher(self.device))
        self.marker.unlink()
        self.assertIsNone(flusher(self.device))

    def test_other_root_and_similar_command_do_not_count(self):
        (self.proc / '2/fd/4').unlink()
        (self.proc / '2/fd/4').symlink_to(self.base / 'other/dev/input/event0')
        self.assertFalse(ready(self.device, self.proc))
        (self.proc / '2/fd/4').unlink()
        (self.proc / '2/fd/4').symlink_to(self.root / 'dev/input/event0')
        (self.proc / '1/comm').write_text('mq_ui_old\n')
        self.assertFalse(ready(self.device, self.proc))

    def test_a_ui_from_another_path_counts_and_a_launcher_with_the_name_does_not(self):
        """A boot layer starts its ui package through /sbin/mq_ui: same name, another file."""
        (self.proc / '1/cmdline').write_bytes(b'qemu\0/usr/data/disc-boot/ui/a/mq_ui\0')
        self.assertTrue(ready(self.device, self.proc))
        watcher = self.proc / '0'                           # the launcher keeps the name, holds no device
        (watcher / 'fd').mkdir(parents=True)
        (watcher / 'comm').write_text('mq_ui\n')
        (watcher / 'cmdline').write_bytes(b'/opt/disc-boot/disc-boot\0')
        self.device.processes.return_value = [0, 1, 2]
        self.assertEqual(holders(self.device, self.proc), {'mq_ui': [1], 'mq_player': [2]})
        self.assertTrue(ready(self.device, self.proc))
        (self.proc / '1/fd/4').unlink()
        self.assertEqual(holders(self.device, self.proc)['mq_ui'], [])
        self.assertFalse(ready(self.device, self.proc))

    def test_exit_or_missing_marker_is_not_ready(self):
        self.device.processes.return_value = [1, 999]
        self.assertFalse(ready(self.device, self.proc))
        self.marker.unlink()
        self.assertFalse(ready(self.device, self.proc))

    def test_ready_has_no_minimum_wait_and_failure_is_bounded(self):
        sleep = Mock()
        with patch('emulator.runtime.boot_ready.ready', return_value=True):
            wait_ready(self.device, sleep=sleep)
        sleep.assert_not_called()
        with patch('emulator.runtime.boot_ready.ready', return_value=False):
            with self.assertRaisesRegex(TimeoutError, 'not ready'):
                wait_ready(self.device, timeout=1, clock=Mock(side_effect=[0, 0, 1]), sleep=sleep)
        sleep.assert_called_once_with(.2)
