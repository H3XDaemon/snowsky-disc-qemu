"""Key pin levels shared by the stock GPIO ioctl path and raw /dev/mem readers."""
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock

from emulator.runtime import gpio
from emulator.runtime.keys import Buttons


class GpioTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'dev/input').mkdir(parents=True)
        (self.root / 'emu').mkdir()
        (self.root / 'dev/input/event0').touch()

    def word(self):
        with (self.root / 'dev/mem').open('rb') as memory:
            return struct.unpack('<I', os.pread(memory.fileno(), 4, 0x10010100))[0]

    def test_released_and_held_words_match_the_device_reads(self):
        self.assertEqual(gpio.word(()), 0xF6EFE127)
        self.assertEqual(gpio.word({'volume_up'}), 0xF6EFC127)       # bit 13 low
        self.assertEqual(gpio.word({'volume_down'}), 0xF6EFA127)     # bit 14 low
        self.assertEqual(gpio.word({'play_pause'}), 0xF6EF6127)      # bit 15 low
        self.assertEqual(gpio.word(gpio.BITS), 0xF6EF0127)

    def test_page_is_mappable_at_the_pinctrl_base_and_sparse(self):
        gpio.release(self.root)
        info = (self.root / 'dev/mem').stat()
        self.assertEqual(info.st_size, 0x10011000)
        self.assertLess(info.st_blocks * 512, 1 << 20)
        self.assertEqual(self.word(), 0xF6EFE127)
        self.assertEqual(gpio.read(self.root), 0xF6EFE127)
        self.assertEqual((self.root / 'emu/volume-buttons').read_bytes(), b'11')

    def test_hold_and_release_keep_both_views_consistent(self):
        gpio.hold(self.root, 'volume_up,play')
        self.assertEqual(self.word(), 0xF6EF4127)
        self.assertEqual((self.root / 'emu/volume-buttons').read_bytes(), b'01')
        gpio.hold(self.root, ['volume_down'])
        self.assertEqual((self.root / 'emu/volume-buttons').read_bytes(), b'00')
        gpio.release(self.root, ['volume_up'])
        self.assertEqual(self.word(), 0xF6EF2127)
        gpio.release(self.root)
        self.assertEqual(self.word(), 0xF6EFE127)
        self.assertEqual(gpio.snapshot(self.root), dict(word='0xF6EFE127', held=[], armed=[]))

    def test_armed_keys_apply_to_exactly_one_power_on(self):
        gpio.arm(self.root, ['play_pause'])
        self.assertIsNone(gpio.read(self.root))                       # arming changes no level
        gpio.power_on(self.root)
        self.assertEqual(self.word(), 0xF6EF6127)
        self.assertEqual(gpio.armed(self.root), set())
        gpio.release(self.root)
        gpio.power_on(self.root, ['volume_up'])
        self.assertEqual(self.word(), 0xF6EFC127)
        gpio.power_on(self.root)
        self.assertEqual(self.word(), 0xF6EFE127)

    def test_unknown_key_changes_nothing(self):
        gpio.hold(self.root, ['volume_up'])
        for call in (gpio.hold, gpio.arm, gpio.power_on):
            with self.assertRaises(ValueError):
                call(self.root, ['menu'])
        self.assertEqual(gpio.held(self.root), {'volume_up'})
        self.assertEqual(self.word(), 0xF6EFC127)

    def test_viewer_hold_is_visible_in_memory_and_keeps_power_on_holds(self):
        device = Mock(transition=None)
        device.running.return_value = True
        buttons = Buttons(self.root, device, sleep=lambda _: None, clock=lambda: 0)
        gpio.hold(self.root, ['play_pause'])
        buttons.gesture('volume_down', 'hold')
        self.assertEqual(self.word(), 0xF6EF2127)
        self.assertEqual((self.root / 'emu/volume-buttons').read_bytes(), b'10')
        buttons.gesture('volume_down', 'end')
        self.assertEqual(self.word(), 0xF6EF6127)
        buttons.reset()                                               # a new viewer is not a key release
        self.assertEqual(self.word(), 0xF6EF6127)


if __name__ == '__main__':
    unittest.main()
