"""The rebuilt qemu answers the device ioctls of a STATIC guest program (emulator/docker/qemu).

A dynamically linked program gets them from the preloaded fbshim; a static one only
reaches the kernel, which says ENOTTY for the regular files behind /dev/fb0 and
/dev/input/event*. The patched interpreter answers them itself while the guest's
/emu/qemu-devices marker holds 1. No chroot here: qemu's -L sysroot stands in for
the guest root, as it does for the guest's own open().
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

GUEST = Path(__file__).resolve().parent / 'guest'
FB_BYTES = 360 * 1080 * 4
EXPECTED = '''fb: 360x360 virtual 360x1080 bpp 32 offsets r16 g8 b0 a24
fix: ingenicfb smem 1555200 line 1440 visual 2
mmap: ok
pan: yoffset 360
blank: ok
touch name: cst816t
touch version: 0x10001
touch bus: 0x18
ev: 0 0x1 0x3
keys: 0x14a
abs 0: 0..359
abs 0x36: 0..359
abs 0x39: 0..65535
touch grab: ok
keys name: x2000_key
keys version: 0x10001
keys bus: 0x19
ev: 0 0x1
keys: 0xfa 0xfb 0xfc 0x103 0x106 0x107 0x108 0x109 0x10a 0x10b 0x10c 0x10d
abs 0: Invalid argument
abs 0x36: Invalid argument
abs 0x39: Invalid argument
keys grab: ok
'''


class StaticDeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        version = subprocess.run(['qemu-mipsel-static', '-version'], capture_output=True, text=True).stdout
        assert 'snowsky-disc-devices' in version, f'the image lacks the rebuilt qemu (emulator/docker): {version!r}'
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name).resolve()
        cls.probe = cls.base / 'devprobe'
        subprocess.run(['mipsel-linux-gnu-gcc', '-static', '-O1', '-Wl,-z,execstack', '-o', str(cls.probe),
                        str(GUEST / 'devprobe.c')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def sysroot(self, marker):
        """A guest root as 10_setup_env.sh and 15_controls.sh lay it out."""
        root = self.base / f'root-{marker}'
        for name, text in (('sys/class/input/event0/device/name', 'x2000_key\n'),
                           ('sys/class/input/event1/device/name', 'cst816t\n'),
                           ('dev/input/event0', ''), ('dev/input/event1', ''), ('emu/fb-live', '\xff'),
                           ('emu/fb-flush', '')):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding='latin-1')
        (root / 'dev/fb0').write_bytes(bytes(FB_BYTES))
        if marker is not None:
            (root / 'emu/qemu-devices').write_text(marker)
        return root

    def run_probe(self, root):
        return subprocess.run(['qemu-mipsel-static', '-L', str(root), str(self.probe)],
                              capture_output=True, text=True)

    def test_static_program_sees_the_stock_devices(self):
        root = self.sysroot('1')
        result = self.run_probe(root)
        pid, output = result.stdout.split('\n', 1)
        self.assertEqual((result.returncode, result.stderr, output), (0, '', EXPECTED))
        # The pan to the second sub-buffer reached the viewer's marker, as fbshim's flush does,
        # and named this process as the one that flushed (boot_ready matches it to the UI).
        self.assertEqual((root / 'emu/fb-live').read_bytes(), b'\x01')
        self.assertEqual((root / 'emu/fb-flush').read_text(), f"{int(pid.removeprefix('pid: ')):10d}\n")

    def test_marker_off_or_absent_keeps_the_kernel_answer(self):
        for marker in ('0', None):
            with self.subTest(marker=marker):
                root = self.sysroot(marker)
                result = self.run_probe(root)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout.split('\n', 1)[1], 'vinfo: Inappropriate ioctl for device\n')
                self.assertEqual((root / 'emu/fb-live').read_bytes(), b'\xff')
                self.assertEqual((root / 'emu/fb-flush').read_bytes(), b'')

    def test_only_the_device_paths_are_answered(self):
        """A regular file elsewhere, even with the same name, is still a plain file."""
        root = self.sysroot('1')
        (root / 'tmp').mkdir()
        (root / 'tmp/fb0').write_bytes(bytes(FB_BYTES))
        result = subprocess.run(['qemu-mipsel-static', '-L', str(root), str(self.probe), '/tmp/fb0'],
                                capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.split('\n', 1)[1]),
                         (2, 'vinfo: Inappropriate ioctl for device\n'))


if __name__ == '__main__':
    unittest.main()
