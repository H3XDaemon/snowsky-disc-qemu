"""Guest-scoped peripheral validation and readback, without firmware."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from emulator.runtime.keys import Device, BRIGHTNESS
from emulator.runtime.peripherals import Peripherals


class PeripheralTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'rootfs'
        self.root.mkdir()
        self.device = Device(self.root)
        self.controls = Peripherals(self.device)

    def test_brightness_reads_the_hardware_stub_including_sleep(self):
        path = self.root / BRIGHTNESS
        path.parent.mkdir(parents=True)
        for value in (1, 21, 40, 0):
            path.write_bytes(str(value).encode().ljust(4, b'\0'))
            self.assertEqual(self.controls.snapshot()['brightness'], value)
        path.write_bytes(b'')
        self.assertIsNone(self.controls.snapshot()['brightness'])

    def test_usb_changes_only_guest_status_and_survives_controller_restart(self):
        path = self.root / 'sys/class/power_supply/cw221X-bat/status'
        path.parent.mkdir(parents=True)
        path.write_text('Full')
        with patch.object(self.controls, '_event') as event:
            self.controls.set_usb(True)
            self.assertEqual(path.read_text(), 'Charging\n')
            self.assertTrue(Peripherals(self.device).snapshot()['usb_connected'])
            self.controls.set_usb(False)
            self.assertEqual(path.read_text(), 'Discharging\n')
            event.assert_not_called()

    def test_boot_keys_are_armed_for_the_next_power_on_only(self):
        (self.root / 'emu').mkdir()
        self.assertEqual(self.controls.snapshot()['boot_keys'], [])
        self.controls.set_boot_keys(['play', 'volume_up'])
        self.assertEqual(self.controls.snapshot()['boot_keys'], ['play_pause', 'volume_up'])
        self.assertFalse((self.root / 'dev/mem').exists())             # no pin moves before power-on
        for value in ('volume_up', None, [1], ['power']):
            with self.assertRaises(ValueError):
                self.controls.set_boot_keys(value)
        self.assertEqual(self.controls.snapshot()['boot_keys'], ['play_pause', 'volume_up'])
        self.controls.set_boot_keys([])
        self.assertEqual(self.controls.snapshot()['boot_keys'], [])

    def test_jack_model_is_off_until_a_state_is_set(self):
        self.assertIsNone(self.controls.snapshot()['jack'])
        for state, mark in (('3.5', b'3'), ('none', b'n'), ('4.4', b'4')):
            self.controls.set_jack(state)
            self.assertEqual((self.root / 'emu/jack').read_bytes(), mark)
            self.assertEqual(self.controls.snapshot()['jack'], state)
        for value in ('2.5', None, 3.5, [], {}, ['3.5']):
            with self.assertRaises(ValueError):
                self.controls.set_jack(value)
        self.assertEqual(self.controls.jack(), '4.4')
        self.controls.set_jack('off')
        self.assertIsNone(self.controls.jack())

    def test_peripheral_types_and_power_transition_reject_before_mutation(self):
        for value in ('true', 1, None, [], {}):
            with self.assertRaises(ValueError):
                self.controls.set_usb(value)
            with self.assertRaises(ValueError):
                self.controls.set_sd(value)
        self.device.transition = 'starting'
        with self.assertRaises(ValueError):
            self.controls.set_usb(True)
        with self.assertRaises(ValueError):
            self.controls.set_sd(False)
        self.assertFalse((self.root / 'emu').exists())

    def test_invalid_sd_nodes_are_preserved_and_no_mount_is_touched(self):
        (self.root / 'dev').mkdir()
        for name in ('mmcblk0', 'mmcblk0p1'):
            (self.root / 'dev' / name).write_text('not a block device')
        with patch('emulator.runtime.peripherals.subprocess.check_output', return_value=''), \
                patch.object(self.controls, '_unmount_sd') as unmount, \
                patch.object(self.controls, '_event') as event:
            self.controls._sd(False)
            self.assertIn('does not belong', self.controls.error)
            unmount.assert_not_called()
            event.assert_not_called()
        self.assertEqual((self.root / 'dev/mmcblk0p1').read_text(), 'not a block device')
        self.assertIsNone(self.controls.operation)

    def test_foreign_mount_is_never_unmounted(self):
        path = self.root / 'tmp/sdcard'
        path.mkdir(parents=True)
        with patch.object(self.controls, '_mounted', return_value=True), \
                patch('emulator.runtime.peripherals.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'does not belong'):
                self.controls._unmount_sd({path.stat().st_dev + 1})
            run.assert_not_called()

    def test_pair_move_rolls_back_if_second_source_disappears(self):
        first, second = self.root / 'first', self.root / 'missing'
        first.write_text('card')
        targets = [self.root / 'saved-first', self.root / 'saved-second']
        with self.assertRaises(FileNotFoundError):
            self.controls._move_nodes([first, second], targets)
        self.assertEqual(first.read_text(), 'card')
        self.assertFalse(targets[0].exists())

    def test_failed_peripheral_action_message_expires_instead_of_staying(self):
        self.controls.error = 'SD card is busy; stop playback and retry'
        self.controls.error_at = time.monotonic()
        self.assertEqual(self.controls.snapshot()['peripheral_error'],
                         'SD card is busy; stop playback and retry')
        self.controls.error_at = time.monotonic() - Peripherals.ERROR_TTL - 1
        self.assertIsNone(self.controls.snapshot()['peripheral_error'])

    def test_forked_worker_with_inherited_argv_is_not_selected_as_player(self):
        with patch.object(self.controls, '_profile'), \
                patch.object(self.device, 'processes', return_value=[101, 102]), \
                patch.object(Path, 'read_text', side_effect=['mq_player\n', 'echo_powerMG\n']), \
                patch.object(Path, 'read_bytes', return_value=b'qemu\0/usr/bin/mq_player\0'):
            self.assertEqual(self.controls._pid(), 101)
