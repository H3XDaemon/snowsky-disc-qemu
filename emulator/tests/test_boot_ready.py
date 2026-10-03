from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from emulator.runtime.boot_ready import flusher, holders, own_pid, ready, wait_ready


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
