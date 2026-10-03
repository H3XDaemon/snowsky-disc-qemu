"""FPU-trap guard and the qemu-user errno gap, on real cross-compiled programs."""
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import unittest.mock

from emulator.runtime import abi

GUEST = Path(__file__).resolve().parent / 'guest'
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
STATIC = ['mipsel-linux-gnu-gcc', '-static', '-nostdlib', '-mabi=32', '-march=mips32r2', '-fno-pic',
          '-mno-abicalls', '-O1']


def elf(fp_abi=None, interpreter=None, stack=None, machine=8, kind=2, pie=None):
    """A minimal ELF32 LE header with the program headers the guard reads."""
    segments, blob = [], b''
    base = 52 + 32 * 4
    if pie is not None:                               # PT_DYNAMIC with or without DF_1_PIE
        segments.append((2, base + len(blob), 16, 6))
        blob += struct.pack('<IIII', 0x6ffffffb, 0x08000000 if pie else 1, 0, 0)
    if interpreter:
        segments.append((3, base + len(blob), len(interpreter) + 1, 4))
        blob += interpreter.encode() + b'\0'
    if stack is not None:
        segments.append((0x6474e551, 0, 0, 6 | (1 if stack else 0)))
    if fp_abi is not None:
        segments.append((0x70000003, base + len(blob), 24, 4))
        blob += bytes([0, 0, 32, 2, 1, 0, 0, fp_abi]) + bytes(16)
    header = b'\x7fELF\x01\x01\x01' + bytes(9) + struct.pack('<HHIIIIIHHHHHH', kind, machine, 1, 0x400000, 52, 0, 0,
                                                             52, 32, len(segments), 40, 0, 0)
    table = b''.join(struct.pack('<8I', segment, offset, 0, 0, size, size, flags, 4)
                     for segment, offset, size, flags in segments).ljust(128, b'\0')
    return header + table + blob


class GuardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / 'rootfs'
        (self.root / 'emu').mkdir(parents=True)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755)
        return path

    def verdict(self, **shape):
        return abi.verdict(abi.inspect(self.write('probe', elf(**shape))))

    def test_only_soft_float_or_the_stock_shape_is_accepted(self):
        glibc = '/lib/ld-linux-mipsn8.so.1'
        self.assertEqual(self.verdict(fp_abi=3, stack=False), 'ok')                  # soft-float, any shape
        self.assertEqual(self.verdict(fp_abi=6, interpreter=glibc), 'ok')            # stock: no PT_GNU_STACK
        self.assertEqual(self.verdict(fp_abi=6, interpreter=glibc, stack=False), 'trap')
        self.assertEqual(self.verdict(fp_abi=5, stack=False), 'trap')                # static, modern toolchain
        self.assertEqual(self.verdict(fp_abi=1, interpreter='/lib/ld-musl-mipsel.so.1', stack=True), 'trap')
        self.assertEqual(self.verdict(interpreter=glibc), 'unknown')                 # no ABI flags at all
        self.assertEqual(self.verdict(fp_abi=0, stack=False), 'ok')                  # uses no FPU
        self.assertEqual(abi.verdict(abi.inspect(self.write('x86', elf(fp_abi=1, machine=62)))), 'ok')
        self.assertEqual(abi.verdict(abi.inspect(self.write('script', b'#!/bin/sh\n'))), 'ok')
        self.assertIsNone(abi.inspect(self.root / 'absent'))

    def test_truncated_files_never_raise_and_stay_unknown(self):
        whole = elf(fp_abi=5, interpreter='/lib/ld-linux-mipsn8.so.1', stack=False)
        for size in range(0, len(whole) + 1):                          # every prefix an installer may leave
            facts = abi.inspect(self.write('partial', whole[:size]))
            self.assertIn(abi.verdict(facts), ('ok', 'unknown', 'trap'))
        cut = abi.inspect(self.write('partial', whole[:-24]))          # ABI flags segment past the end
        self.assertEqual((cut['fp_abi'], abi.verdict(cut)), (None, 'unknown'))

    def test_shared_libraries_are_not_programs_but_static_pie_is(self):
        library = self.write('usr/data/lib/libx.so', elf(fp_abi=5, stack=False, kind=3, pie=False))
        static_pie = self.write('usr/data/bin/tool', elf(fp_abi=5, stack=False, kind=3, pie=True))
        self.assertTrue(abi.inspect(library)['library'])
        self.assertEqual(abi.verdict(abi.inspect(library)), 'ok')
        self.assertEqual(abi.verdict(abi.inspect(static_pie)), 'trap')
        found = sorted((Path(name).name, outcome) for name, outcome, _ in abi.check(abi.scan(self.root, ['/usr/data'])))
        self.assertEqual(found, [('libx.so', 'ok'), ('tool', 'trap')])

    def test_guest_links_are_followed_inside_the_guest_root(self):
        self.write('usr/data/real', elf(fp_abi=5, stack=False))
        (self.root / 'opt').mkdir()
        (self.root / 'opt/absolute').symlink_to('/usr/data/real')       # absolute: the GUEST's /usr/data
        (self.root / 'opt/relative').symlink_to('../usr/data/real')
        (self.root / 'opt/loop').symlink_to('/opt/loop')
        for name in ('/opt/absolute', '/opt/relative', '/opt/../usr/data/./real'):
            self.assertEqual(abi.resolve(self.root, name), self.root / 'usr/data/real')
        abi.resolve(self.root, '/opt/loop')                              # terminates
        self.assertEqual(self.guest_run('/opt/absolute').returncode, 126)
        self.assertEqual(self.guest_run('/emu/qemu-mipsel-static', '-0').returncode, 0)   # malformed: no hang

    def test_supervisor_scan_reports_traps_and_survives_bad_files(self):
        from emulator.runtime.machine import Machine
        self.write('usr/data/bin/tool', elf(fp_abi=5, stack=False))
        self.write('usr/data/lib/libx.so', elf(fp_abi=5, stack=False, kind=3, pie=False))
        self.write('opt/half', elf(fp_abi=5, stack=False)[:60])
        self.write('opt/soft', elf(fp_abi=3, stack=False))
        board = Machine(self.root)
        with unittest.mock.patch.object(board, 'publish') as publish, \
                unittest.mock.patch.dict(os.environ, {'FPU_GUARD': 'reject'}):
            board.fpu_scan()
        self.assertEqual(board.trapping, ['/usr/data/bin/tool'])
        publish.assert_called_once_with('running')
        with unittest.mock.patch('emulator.runtime.machine.abi.scan', side_effect=OSError('gone')):
            board.fpu_scan()                                             # logged, not raised

    def test_real_programs_from_the_cross_toolchain(self):
        soft, hard = self.root / 'emu/soft', self.root / 'emu/hard'
        subprocess.run(STATIC + ['-msoft-float', '-o', str(soft), str(GUEST / 'pinprobe.c')], check=True)
        subprocess.run(STATIC + ['-mhard-float', '-Wl,-z,noexecstack', '-o', str(hard), str(GUEST / 'pinprobe.c')],
                       check=True)
        self.assertEqual([outcome for _, outcome, _ in abi.check([soft, hard])], ['ok', 'trap'])
        self.assertEqual([path.name for path in abi.scan(self.root, ['/emu'])].count('hard'), 1)
        result = subprocess.run(['python3', '-B', '-m', 'emulator.runtime.abi', 'check', str(soft), str(hard)],
                                capture_output=True, text=True, cwd=SCRIPTS.parents[1])
        self.assertEqual(result.returncode, 1)
        self.assertIn('soft-float', result.stderr)
        self.assertIn('emu/hard: FP ABI hard', result.stderr)
        self.assertNotIn('emu/soft', result.stderr)

    def guest_run(self, *command, **environment):
        commands = self.base / 'commands'
        commands.mkdir(exist_ok=True)
        (commands / 'timeout').write_text('#!/bin/sh\necho started "$@"\n')
        (commands / 'timeout').chmod(0o755)
        env = dict(os.environ, PATH=f'{commands}:{os.environ["PATH"]}', ROOTFS=str(self.root), WORK=str(self.base),
                   REPO=str(SCRIPTS.parents[1]), FW_VERSION='2.57', **environment)
        env.pop('FPU_GUARD', None) if 'FPU_GUARD' not in environment else None
        return subprocess.run(['bash', '-c', f'source {SCRIPTS}/lib.sh; guest_run 5 "$@"', '-', *command],
                              env=env, capture_output=True, text=True)

    def test_guest_run_refuses_a_trapping_program_before_starting_it(self):
        self.write('usr/data/service', elf(fp_abi=5, stack=False))
        self.write('usr/bin/stock', elf(fp_abi=6, interpreter='/lib/ld-linux-mipsn8.so.1'))
        refused = self.guest_run('/usr/data/service', '--port', '1')
        self.assertEqual(refused.returncode, 126)
        self.assertNotIn('started', refused.stdout)
        self.assertIn('[fpu-guard]', refused.stderr)
        # The explicit interpreter form other projects use is checked too.
        explicit = self.guest_run('/emu/qemu-mipsel-static', '-0', 'disc-service', '/usr/data/service')
        self.assertEqual(explicit.returncode, 126)
        warned = self.guest_run('/usr/data/service', FPU_GUARD='warn')
        self.assertEqual(warned.returncode, 0)
        self.assertIn('started', warned.stdout)
        self.assertIn('[fpu-guard]', warned.stderr)
        silent = self.guest_run('/usr/data/service', FPU_GUARD='off')
        self.assertEqual((silent.returncode, silent.stderr), (0, ''))
        for command in (['/usr/bin/stock'], ['/bin/sh', '-c', 'true'], ['/absent']):
            with self.subTest(command=command):
                allowed = self.guest_run(*command)
                self.assertEqual((allowed.returncode, allowed.stderr), (0, ''))

    def test_rebuilt_qemu_returns_the_guest_errno_from_so_error(self):
        """Debian's qemu 7.2 returned the host's 111 here; the image's rebuilt interpreter
        (emulator/docker/qemu) translates SO_ERROR like the syscall errnos (emulator/docs/limits.md)."""
        probe = self.base / 'soerror'
        subprocess.run(['mipsel-linux-gnu-gcc', '-static', '-O1', '-o', str(probe), str(GUEST / 'soerror.c')],
                       check=True)
        output = subprocess.run(['qemu-mipsel-static', str(probe)], capture_output=True, text=True).stdout
        self.assertIn('blocking connect=-1 errno=146', output)       # the syscall's own errno
        self.assertIn('SO_ERROR=146 ECONNREFUSED=146 ok', output)    # and the socket option's value
        stock = subprocess.run(['/usr/bin/qemu-mipsel-static', str(probe)], capture_output=True, text=True).stdout
        self.assertIn('SO_ERROR=111 ECONNREFUSED=146', stock)        # the gap this fixes, kept visible


if __name__ == '__main__':
    unittest.main()
