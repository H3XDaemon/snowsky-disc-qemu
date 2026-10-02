"""Card image layout decisions that need no loop device."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from emulator.runtime import card
from emulator.runtime.keys import Device
from emulator.runtime.peripherals import Peripherals


class CardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        self.root = self.work / 'rootfs'
        self.root.mkdir()

    def test_mbr_has_one_partition_to_the_end_of_the_card(self):
        sectors = (64 << 20) // 512
        table = card.mbr(sectors, 'exfat')
        self.assertEqual(len(table), 512)
        self.assertEqual(table[510:], b'\x55\xaa')
        status, kind, start, count = struct.unpack_from('<B3xB3xII', table, 446)
        self.assertEqual((status, kind, start, count), (0, 0x07, 2048, sectors - 2048))
        self.assertEqual(table[462:510], bytes(48))                    # no other partitions
        self.assertEqual(card.mbr(sectors, 'vfat')[450], 0x0c)

    def test_layout_is_read_from_the_image(self):
        path = card.image(self.root)
        self.assertEqual(path, self.work / 'sdcard.img')
        path.write_bytes(card.mbr(131072, 'vfat') + bytes(1024))
        self.assertTrue(card.partitioned(path))
        boot = bytearray(512)                                          # a FAT boot sector: jump + 55AA
        boot[:3], boot[510:] = b'\xeb\x58\x90', b'\x55\xaa'
        path.write_bytes(bytes(boot))
        self.assertFalse(card.partitioned(path))
        path.write_bytes(b'')
        self.assertFalse(card.partitioned(path))

    def test_build_rejects_bad_requests_before_touching_the_image(self):
        path = card.image(self.root)
        path.write_bytes(b'existing card')
        source = self.work / 'media'
        source.mkdir()
        with patch('emulator.runtime.card.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'exfatprogs'):
                card.build(self.root, source, 64, 'exfat')
        for size, filesystem in ((8, 'vfat'), (300000, 'vfat'), ('64', 'vfat'), (64, 'ntfs')):
            with self.subTest(size=size, filesystem=filesystem), self.assertRaises(ValueError):
                card.build(self.root, source, size, filesystem)
        self.assertEqual(path.read_bytes(), b'existing card')

    def test_loops_of_a_missing_image_are_never_looked_up_by_name(self):
        with patch('emulator.runtime.card.subprocess.run') as run:
            self.assertEqual(card.loops(self.work / 'absent.img'), [])   # would name another container's loop
            run.assert_not_called()
            run.return_value.stdout = '/dev/loop7: [0]:1 (/work/sdcard.img)\n'
            (self.work / 'sdcard.img').touch()
            self.assertEqual(card.loops(self.work / 'sdcard.img'), ['/dev/loop7'])

    def build(self, failing):
        """card.build with every external command recorded; `failing` names the one that fails."""
        source = self.work / 'media'
        source.mkdir(exist_ok=True)
        seen = {}

        def run(command, **options):
            seen.setdefault(command[0], []).append(command)
            if command[0] == 'mount':
                (Path(command[-1]) / 'copied.wav').write_text('on the card')   # what a mounted card holds
            if command[0] == failing:
                if options.get('check'):
                    raise subprocess.CalledProcessError(32, command)
                return subprocess.CompletedProcess(command, 1, '', 'cp: No space left on device')
            return subprocess.CompletedProcess(command, 0, '', '')

        with patch('emulator.runtime.card.subprocess.run', side_effect=run), \
                patch('emulator.runtime.card.attach', return_value=('/dev/loop9', 1, 1)), \
                patch('emulator.runtime.card.os.mknod', side_effect=lambda path, *_: Path(path).touch()), \
                patch('emulator.runtime.card.tempfile.mkdtemp', return_value=str(self.work / 'build')), \
                patch('emulator.runtime.card.os.path.ismount', return_value=failing == 'umount'):
            (self.work / 'build').mkdir()
            try:
                card.build(self.root, source, 64)
            except (ValueError, subprocess.CalledProcessError) as exc:
                return seen, exc
            return seen, None

    def test_failed_unmount_never_deletes_what_is_on_the_card(self):
        seen, error = self.build('umount')
        self.assertIsInstance(error, subprocess.CalledProcessError)
        self.assertEqual((self.work / 'build/mount/copied.wav').read_text(), 'on the card')
        self.assertTrue(card.image(self.root).exists())                    # still mounted: left alone
        self.assertEqual(seen['losetup'], [['losetup', '-d', '/dev/loop9']])

    def test_too_small_a_card_is_an_error_not_a_silently_short_card(self):
        seen, error = self.build('cp')
        self.assertIsInstance(error, ValueError)
        self.assertIn('too small', str(error))
        self.assertFalse(card.image(self.root).exists())                   # no half-built card
        self.assertIn(['losetup', '-d', '/dev/loop9'], seen['losetup'])
        self.assertEqual(len(seen['umount']), 1)

    def test_successful_build_leaves_no_workspace(self):
        seen, error = self.build('nothing')
        self.assertIsNone(error)
        self.assertEqual(len(seen['losetup']), 1)
        (self.work / 'build/mount/copied.wav').unlink()                    # the fake card's content

    def test_forced_removal_detaches_a_busy_mount_and_plain_removal_refuses(self):
        controls = Peripherals(Device(self.root))
        mount = self.root / 'tmp/sdcard'
        mount.mkdir(parents=True)
        identity = {mount.stat().st_dev}
        busy = subprocess.CalledProcessError(32, 'umount')
        with patch.object(controls, '_mounted', side_effect=lambda path: path == mount), \
                patch('emulator.runtime.peripherals.subprocess.run', side_effect=[busy]) as run:
            with self.assertRaisesRegex(ValueError, 'busy'):
                controls._unmount_sd(identity)
            self.assertEqual(run.call_count, 1)
        with patch.object(controls, '_mounted', side_effect=lambda path: path == mount), \
                patch('emulator.runtime.peripherals.subprocess.run', side_effect=[busy, None]) as run:
            controls._unmount_sd(identity, force=True)
            self.assertEqual([call.args[0][:2] for call in run.call_args_list],
                             [['umount', str(mount)], ['umount', '-l']])
        for value in ('yes', 1, None):
            with self.assertRaises(ValueError):
                controls.set_sd(False, force=value)


if __name__ == '__main__':
    unittest.main()
