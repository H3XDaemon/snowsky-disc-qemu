"""Exercise the actual shell encoding consumed by Linux binfmt_misc."""
from pathlib import Path
import re
import subprocess
import unittest


class BinfmtTests(unittest.TestCase):
    def test_registration_preserves_escapes_and_selects_only_mipsel(self):
        source = (Path(__file__).resolve().parents[2] / 'emulator/scripts/10_setup_env.sh').read_text()
        assignments = '\n'.join(re.findall(r'^(?:MAGIC|MASK)=.*$', source, re.M))
        command = next(line.strip().split(' > ')[0] for line in source.splitlines()
                       if 'printf' in line and ':qemu-mipsel:M:' in line)
        encoded = subprocess.check_output(['bash', '-c', assignments + '\nQEMU_INTERPRETER=/lib/qemu-x/qemu\n' + command])
        self.assertNotIn(b'\0', encoded)  # Raw NUL truncated the old registration at byte 6.
        fields = encoded.decode().split(':')
        self.assertEqual(fields[-1], 'FP')      # P: the caller's argv[0] reaches the program
        self.assertEqual(fields[-2], '/lib/qemu-x/qemu')   # the build-named file, not the stable link
        magic, mask = (bytes.fromhex(value.replace('\\x', '')) for value in fields[4:6])
        self.assertEqual(len(magic), 20)
        self.assertEqual(len(mask), 20)

        def matches(machine, bits=1, endian=1, kind=2, abi=0):
            elf = bytearray(magic)
            elf[4:6] = bytes([bits, endian])
            elf[7] = abi
            elf[16:20] = kind.to_bytes(2, 'little') + machine.to_bytes(2, 'little')
            return all((a & m) == (b & m) for a, b, m in zip(elf, magic, mask))

        self.assertTrue(matches(8))
        self.assertTrue(matches(8, kind=3, abi=3))  # PIE + nonzero OS ABI.
        for machine in (3, 40, 62, 183):  # i386, ARM, x86-64, AArch64.
            self.assertFalse(matches(machine))
        self.assertFalse(matches(8, bits=2))
        self.assertFalse(matches(8, endian=2))
