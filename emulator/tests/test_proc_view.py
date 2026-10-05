"""The rebuilt qemu shows another guest process as the player does (emulator/docker/qemu).

The kernel builds a binfmt-started program's /proc/<pid>/cmdline and exe for the
interpreter; BusyBox pgrep -x then finds by comm what the player's finds by argv[0]
(#57). While the guest marker emu/proc-exe holds 1, qemu reads them as the player:
the argv the caller passed and the program's path. No binfmt here (unprivileged):
the explicit `-0 argv0` and plain layouts are checked, the binfmt one by the
stock-init scenario.
"""
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

GUEST = Path(__file__).resolve().parent / 'guest'


class ProcessViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        version = subprocess.run(['qemu-mipsel-static', '-version'], capture_output=True, text=True).stdout
        assert 'snowsky-disc-devices' in version, f'the image lacks the rebuilt qemu (emulator/docker): {version!r}'
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name).resolve()
        cls.probe = cls.base / 'procprobe'
        subprocess.run(['mipsel-linux-gnu-gcc', '-static', '-O1', '-Wl,-z,execstack', '-o', str(cls.probe),
                        str(GUEST / 'procprobe.c')], check=True)
        (cls.base / 'emu').mkdir()
        cls.marker = cls.base / 'emu/proc-exe'
        cls.sleepers = [subprocess.Popen(['qemu-mipsel-static', '-0', 'mq_ui', str(cls.probe), 'sleep']),
                        subprocess.Popen(['qemu-mipsel-static', str(cls.probe), 'sleep'])]
        time.sleep(.5)

    @classmethod
    def tearDownClass(cls):
        for sleeper in cls.sleepers:
            sleeper.kill()
            sleeper.wait()
        cls.tmp.cleanup()

    def view(self, pid):
        result = subprocess.run(['qemu-mipsel-static', '-L', str(self.base), str(self.probe), str(pid)],
                                capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return dict(line.split(': ', 1) for line in result.stdout.splitlines())

    def test_marker_on_shows_the_program_as_the_player_does(self):
        self.marker.write_text('1')
        named, plain = self.sleepers
        self.assertEqual(self.view(named.pid), {'cmdline': 'mq_ui|sleep', 'exe': str(self.probe)})
        self.assertEqual(self.view(plain.pid), {'cmdline': f'{self.probe}|sleep', 'exe': str(self.probe)})

    def test_marker_off_or_absent_keeps_the_kernel_view(self):
        for text in ('0', None):
            with self.subTest(marker=text):
                self.marker.write_text(text) if text is not None else self.marker.unlink(missing_ok=True)
                view = self.view(self.sleepers[0].pid)
                self.assertTrue(view['cmdline'].endswith(f'|-0|mq_ui|{self.probe}|sleep'), view)
                self.assertTrue(view['exe'].endswith('/qemu-mipsel-static'), view)

    def test_a_process_that_is_not_a_guest_is_untouched(self):
        self.marker.write_text('1')
        native = subprocess.Popen(['sleep', '30'])
        try:
            time.sleep(.2)
            self.assertEqual(self.view(native.pid)['cmdline'], 'sleep|30')
            self.assertTrue(self.view(native.pid)['exe'].endswith('/sleep'))
        finally:
            native.kill()
            native.wait()


if __name__ == '__main__':
    unittest.main()
