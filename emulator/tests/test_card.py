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
