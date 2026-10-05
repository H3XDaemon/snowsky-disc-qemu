"""The audio shim's stream reporting, read back by output_state (no firmware)."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from emulator.runtime.audio import STREAM, output_state, reset_output

REPO = Path(__file__).resolve().parents[2]
RUNNING = 'access: RW_INTERLEAVED\nformat: S32_LE\nsubformat: STD\nchannels: 2\nrate: 44100 (44100/1)\n'


class OutputStreamTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / STREAM).mkdir(parents=True)
        self.files = {name: self.root / STREAM / name for name in ('status', 'hw_params')}
        for path in self.files.values():
            path.write_text('closed\n')
        (self.root / 'emu/audio-state').write_bytes(b'c')

    def probe(self, name):
        """streamprobe.c with the real shim, built for MIPS with a file prefix."""
        probe = self.root / name
        subprocess.run(['mipsel-linux-gnu-gcc', '-static', '-O1', f'-DTINYSHIM_ROOT="{self.root}"',
                        '-DTINYSHIM_NO_FOPEN', '-o', str(probe), str(REPO / 'emulator/tests/guest/streamprobe.c'),
                        str(REPO / 'emulator/shims/tinyshim.c')], check=True)
        return probe

    def test_shim_output_is_what_the_reader_expects(self):
        """The real shim, built for MIPS with a file prefix and run under qemu-user."""
        probe = self.probe('streamprobe')
        steps = {'open': ('PREPARED', 'silence'), 'samples': ('RUNNING', 'samples'),
                 'silence': ('RUNNING', 'silence'), 'close': ('closed', 'closed')}
        for step, (stream, activity) in steps.items():
            with self.subTest(step=step):
                subprocess.run(['qemu-mipsel-static', str(probe), step], check=True, capture_output=True)
                state = output_state(self.root)
                self.assertEqual((state['stream'], state['activity']), (stream, activity))
                if stream != 'closed':
                    self.assertEqual((state['format'], state['rate'], state['channels']), ('S32_LE', 44100, 2))
                    text = self.files['hw_params'].read_text()
                    self.assertEqual(text, RUNNING + 'period_size: 1024\nbuffer_size: 4096\n')
                    status = self.files['status'].read_text()
                    self.assertRegex(status, rf'^state: {stream}\nowner_pid   : \d+\n$')
                else:
                    self.assertEqual({path.read_text() for path in self.files.values()}, {'closed\n'})
        self.assertFalse(list((self.root / STREAM).glob('*.n')))          # no temporary left behind
        self.assertEqual((self.root / 'audio.fmt').read_bytes(), bytes([2, 0, 0, 0, 4, 0, 0, 0, 0x44, 0xac, 0, 0]))

    def test_shim_paces_writes_at_the_sample_rate_not_slower(self):
        """40 periods of 1024 frames at 44.1 kHz are 928 ms of audio (whole ms). With 2 ms
        of the writer's own work per period, a DAC plays while the writer works: the last
        write returns once the 4096-frame buffer (92 ms) is all that is left to play, about
        2 + 928 - 92 = 838 ms in. The window is 10 ms below and 15 ms above that; returning
        a period (23 ms) later, or sleeping after the work (1009 ms), falls outside it."""
        run = subprocess.run(['qemu-mipsel-static', str(self.probe('paceprobe')), 'pace'], check=True,
                             capture_output=True, text=True)
        elapsed = int(run.stdout.split()[-1])
        expected = 2 + 40 * 1024 * 1000 // 44100 - 4096 * 1000 // 44100
        self.assertLessEqual(elapsed, expected + 15, run.stdout)
        self.assertGreaterEqual(elapsed, expected - 10, run.stdout)

    def test_built_shim_needs_no_library_symbols(self):
        """build_shims.sh links with -nostdlib and -shared, which leaves undefined symbols to
        load time. The only one the shim may use is the guest libc's fopen64 (its fopen
        redirect); a helper such as 64-bit division (__udivdi3) has no library there."""
        subprocess.run(['bash', str(REPO / 'emulator/shims/build_shims.sh')], check=True,
                       env={**os.environ, 'WORK': str(self.root)}, capture_output=True)
        undefined = subprocess.run(['mipsel-linux-gnu-nm', '-u', str(self.root / 'tinyshim.so')], check=True,
                                   capture_output=True, text=True).stdout
        self.assertEqual(undefined.split()[1::2], ['fopen64'], undefined)

    def test_half_replaced_pair_is_reported_as_closed_not_an_error(self):
        self.files['status'].write_text('state: RUNNING\nowner_pid   : 7\n')          # hw_params still closed
        self.assertEqual(output_state(self.root)['stream'], 'closed')
        self.files['hw_params'].write_text('format: S32_LE\nrate: broken\nchannels: 2\n')
        self.assertEqual(output_state(self.root)['stream'], 'closed')
        self.files['hw_params'].write_text(RUNNING)
        (self.root / 'emu/audio-state').write_bytes(b'p')
        self.assertEqual(output_state(self.root), dict(stream='RUNNING', activity='samples', format='S32_LE',
                                                       rate=44100, channels=2))

    def test_reader_never_raises_while_the_stream_opens_and_closes(self):
        stop, failures = threading.Event(), []

        def flip():
            while not stop.is_set():
                self.files['hw_params'].write_text(RUNNING)
                self.files['status'].write_text('state: RUNNING\nowner_pid   : 7\n')
                self.files['status'].write_text('closed\n')
                self.files['hw_params'].write_text('closed\n')

        writer = threading.Thread(target=flip)
        writer.start()
        try:
            for _ in range(3000):
                try:
                    self.assertIn(output_state(self.root)['stream'], ('closed', 'RUNNING'))
                except Exception as exc:                                    # noqa: BLE001
                    failures.append(repr(exc))
                    break
        finally:
            stop.set()
            writer.join()
        self.assertEqual(failures, [])

    def test_missing_tree_and_reset_after_a_killed_player(self):
        self.assertEqual(output_state(self.root / 'absent')['stream'], 'closed')
        reset_output(self.root / 'absent')                                  # nothing to reset, no error
        self.files['hw_params'].write_text(RUNNING)
        self.files['status'].write_text('state: RUNNING\nowner_pid   : 7\n')
        (self.root / 'emu/audio-state').write_bytes(b'p')
        reset_output(self.root)
        self.assertEqual(output_state(self.root), dict(stream='closed', activity='closed', format=None,
                                                       rate=None, channels=None))


if __name__ == '__main__':
    unittest.main()
