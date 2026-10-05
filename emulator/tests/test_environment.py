"""Guest environment presets: battery gauge, settings profiles, power watcher (no firmware)."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from emulator.runtime import battery, power_watch, settings

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        self.root = self.work / 'rootfs'
        (self.root / 'emu').mkdir(parents=True)


class BatteryTests(Base):
    def files(self):
        directory = self.root / battery.DIRECTORY
        return {path.name: path.read_text() for path in directory.iterdir()}

    def test_legacy_layout_is_what_setup_always_wrote(self):
        battery.prepare(self.root)
        self.assertEqual(self.files(), {
            'type': 'Battery', 'capacity': '100', 'status': 'Full', 'health': 'Good', 'present': '1',
            'technology': 'Li-ion', 'voltage_now': '4200000', 'temp': '250', 'online': '1'})

    def test_device_layout_has_the_players_attributes_only(self):
        battery.prepare(self.root)                      # switching layouts removes status/online
        battery.prepare(self.root, 'device', capacity=37, voltage_now=3712000, temp=315)
        self.assertEqual(self.files(), {
            'type': 'Mains\n', 'capacity': '37\n', 'health': 'Good\n', 'present': '1\n', 'technology': 'Li-ion\n',
            'voltage_now': '3712000\n', 'temp': '315\n', 'current_now': '0\n', 'cycle_count': '0\n'})
        self.assertEqual(battery.profile_of(self.root), 'device')

    def test_runtime_update_keeps_layout_and_validates(self):
        battery.prepare(self.root, 'device')
        battery.update(self.root, capacity=4, temp=-50)
        self.assertEqual(self.files()['capacity'], '4\n')
        self.assertEqual(self.files()['temp'], '-50\n')
        self.assertNotIn('status', self.files())
        for bad in (dict(capacity=101), dict(capacity=-1), dict(capacity='5'), dict(voltage_now=6000000)):
            with self.assertRaises(ValueError):
                battery.update(self.root, **bad)
        self.assertEqual(self.files()['capacity'], '4\n')
        with self.assertRaises(ValueError):
            battery.prepare(self.root, 'ideal')

    def test_boot_controls_respect_layout_and_cable_preset(self):
        (self.root / 'dev').mkdir()
        environment = dict(os.environ, ROOTFS=str(self.root), WORK=str(self.work), FW_VERSION='2.57',
                           REPO=str(SCRIPTS.parents[1]))
        controls = lambda **extra: subprocess.run(  # noqa: E731
            ['bash', str(SCRIPTS / '15_controls.sh')], env={**environment, **extra}, capture_output=True)
        battery.prepare(self.root, 'device')
        self.assertEqual(controls(USB_POWER='1').returncode, 0)
        self.assertEqual((self.root / 'emu/usb-connected').read_text(), '1')
        self.assertNotIn('status', self.files())                  # the player's gauge has none
        self.assertEqual(controls().returncode, 0)                # no preset: stored state stays
        self.assertEqual((self.root / 'emu/usb-connected').read_text(), '1')
        battery.prepare(self.root, 'legacy')
        self.assertEqual(controls(USB_POWER='0').returncode, 0)
        self.assertEqual(self.files()['status'], 'Discharging\n')
        self.assertNotEqual(controls(USB_POWER='yes').returncode, 0)
        self.assertEqual((self.root / 'emu/usb-connected').read_text(), '0')
        # The jack model is V2.57 data: other profiles refuse it before writing anything.
        self.assertEqual(controls(JACK='4.4').returncode, 0)
        self.assertEqual((self.root / 'emu/jack').read_bytes(), b'4')
        refused = controls(JACK='3.5', FW_VERSION='2.40')
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(b'V2.57 only', refused.stderr)
        self.assertEqual((self.root / 'emu/jack').read_bytes(), b'4')
        self.assertEqual(controls(JACK='off', FW_VERSION='2.40').returncode, 0)
        self.assertFalse((self.root / 'emu/jack').exists())

    def test_update_needs_a_prepared_gauge(self):
        with self.assertRaises(ValueError):
            battery.update(self.root, capacity=50)


class SettingsTests(Base):
    def setUp(self):
        super().setUp()
        database = self.root / settings.DATABASE
        database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:
            db.execute('CREATE TABLE SYSCONFIG (ID INTEGER PRIMARY KEY autoincrement, LANGUAGE INT, '
                       'LOCAL_IMG_ANIM INT, BATTERY INT, LIGTH_ON_TIME INT, MEMORY_PLAY INT)')
            db.execute('INSERT INTO SYSCONFIG VALUES (1, 100, 1, 87, 3, 0)')

    def row(self):
        with sqlite3.connect(self.root / settings.DATABASE) as db:
            return db.execute('SELECT LANGUAGE, LOCAL_IMG_ANIM, BATTERY, LIGTH_ON_TIME, MEMORY_PLAY '
                              'FROM SYSCONFIG').fetchone()

    def test_default_profile_is_the_original_preset(self):
        self.assertEqual(settings.load('emulator', {}), {'LOCAL_IMG_ANIM': 0, 'BATTERY': 100, 'LANGUAGE': '2'})
        changed = settings.apply(self.root, settings.load('emulator', {'LANG_CODE': '9'}))
        self.assertEqual(self.row(), (9, 0, 100, 3, 0))
        self.assertEqual(changed, {'BATTERY': (87, 100), 'LANGUAGE': (100, 9), 'LOCAL_IMG_ANIM': (1, 0)})

    def test_factory_profile_leaves_stock_defaults(self):
        self.assertEqual(settings.apply(self.root, settings.load('factory')), {})
        self.assertEqual(self.row(), (100, 1, 87, 3, 0))

    def test_overrides_and_always_on(self):
        values = {**settings.load('always-on', {}), **settings.overrides('MEMORY_PLAY=1, LANGUAGE=5')}
        settings.apply(self.root, values)
        self.assertEqual(self.row(), (5, 0, 100, 7, 1))

    def test_bad_input_changes_nothing(self):
        for values in ({'NO_SUCH': 1}, {'LANGUAGE': 'two'}, {'ID': 2}, {'LANGUAGE; DROP TABLE SYSCONFIG': 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                settings.apply(self.root, {'BATTERY': 1, **values})
        with self.assertRaises(ValueError):
            settings.overrides('LANGUAGE')
        with self.assertRaises(ValueError):
            settings.load('nope')
        self.assertEqual(self.row(), (100, 1, 87, 3, 0))

    def test_primed_means_the_table_and_its_row_not_the_file(self):
        """mq_player creates the file before the SYSCONFIG table: a priming boot cut short in
        between left a file setup took for primed, and the settings step then failed (#58)."""
        database = self.root / settings.DATABASE
        self.assertTrue(settings.primed(self.root))
        database.unlink()
        self.assertFalse(settings.primed(self.root))
        database.write_bytes(b'')                                   # the file, nothing in it yet
        self.assertFalse(settings.primed(self.root))
        with self.assertRaisesRegex(ValueError, 'no SYSCONFIG table'):
            settings.apply(self.root, {'BATTERY': 100})
        with sqlite3.connect(database) as db:
            db.execute('CREATE TABLE SYSCONFIG (ID INTEGER PRIMARY KEY autoincrement, BATTERY INT)')
        self.assertFalse(settings.primed(self.root))                # the table, no row yet
        with sqlite3.connect(database) as db:
            db.execute('INSERT INTO SYSCONFIG VALUES (1, 87)')
        self.assertTrue(settings.primed(self.root))
        with sqlite3.connect(database) as db:
            db.execute('INSERT INTO SYSCONFIG VALUES (2, 88)')
        self.assertFalse(settings.primed(self.root))                # never two rows

    def test_every_shipped_profile_loads_and_is_listed(self):
        self.assertEqual(settings.profiles(), ['always-on', 'emulator', 'factory'])
        for name in settings.profiles():
            self.assertIsInstance(settings.load(name, {}), dict)


class PowerWatchTests(Base):
    def test_serves_a_request_and_counts_it(self):
        (self.root / 'emu/power-request').write_bytes(b'1')
        stopped = []

        def power(device):
            stopped.append(device.transition)
            device.transition = None

        with patch('emulator.runtime.keys.Device.processes', return_value=[4242]), \
                patch('emulator.runtime.keys.Device._power', power), \
                patch('emulator.runtime.keys.threading.Thread',
                      lambda target, daemon: type('T', (), {'start': staticmethod(target)})), \
                patch('emulator.runtime.power_watch.signal.signal'):
            power_watch.run(self.root, sleep=lambda _: None, rounds=3)
        self.assertEqual(stopped, ['stopping'])
        self.assertEqual((self.root / 'emu/power-request').read_bytes(), b'0')
        self.assertEqual(power_watch.read(self.root)['pid'], os.getpid())

    def test_start_status_stop_cycle(self):
        environment = dict(os.environ, ROOTFS=str(self.root), PYTHONPATH=str(SCRIPTS.parents[1]))
        run = lambda action: json.loads(subprocess.check_output(  # noqa: E731
            [sys.executable, '-B', '-m', 'emulator.runtime.power_watch', action], env=environment))
        self.assertFalse(run('status')['running'])
        started = run('start')
        self.addCleanup(lambda: power_watch.stop(self.root))
        self.assertTrue(started['running'])
        self.assertEqual(power_watch.running_pid(self.root), started['pid'])
        self.assertFalse(run('stop')['running'])
        self.assertFalse(run('stop')['running'])             # stopping twice is fine


if __name__ == '__main__':
    unittest.main()
