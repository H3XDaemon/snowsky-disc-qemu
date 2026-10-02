"""Host-side tests of the installed guest command policy (no firmware required)."""
import subprocess
import tempfile
import unittest
from pathlib import Path


class GuardTests(unittest.TestCase):
    def blocked(self, name, *args):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / name
            target.symlink_to(Path(__file__).resolve().parents[2] / 'emulator/scripts/guest-command.sh')
            result = subprocess.run(['sh', str(target), *args], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(f'blocked {name}'.encode(), result.stderr)
            self.assertEqual(result.stdout, b'')

    def test_clock_and_downloads_blocked(self):
        for name in ('hwclock', 'ntpd', 'ntpdate', 'curl', 'wget'):
            with self.subTest(name=name):
                self.blocked(name, '--help')

    def test_guest_network_mutations_blocked(self):
        for name, args in [('ip', ['route', 'del', 'default']),
                           ('ifconfig', ['eth1', 'down']), ('route', ['add', 'default']),
                           ('udhcpc', ['-i', 'eth1']), ('wpa_supplicant', ['-B'])]:
            with self.subTest(name=name):
                self.blocked(name, *args)

    def test_ip_read_allowlist_is_not_prefix_based(self):
        self.blocked('ip', 'addr', 'show', 'eth1', 'extra')
        self.blocked('ip', 'addr', 'show', 'wlan0', 'extra')
        self.blocked('ip', 'addr', 'show', 'wlan1')
        self.blocked('ip', 'route', 'show', 'default', '; touch /tmp/unwanted')


if __name__ == '__main__':
    unittest.main()
