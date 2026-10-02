"""Would this MIPS program hit the player's FPU delay-slot trap? (qemu-user never does.)

The player's Linux 4.4.94 emulates the delay slot of a taken floating-point
branch by writing instructions onto the user stack and jumping there
(mips_dsemul, replaced in Linux 4.8). That needs an executable stack. The stock
programs are hard-float and get one (glibc, no PT_GNU_STACK); a program built
today has a non-executable stack, and musl never gives threads an executable
one, so its first taken FP branch dies with a fault at its own stack address.
qemu-user executes FPU instructions itself and shows nothing.

So a hard-float program is refused when its stack is not executable
(PT_GNU_STACK without the execute flag) or when it is linked against musl.
The check reads the ELF headers only; it cannot see a static musl program built
with an executable main stack, whose threads would still trap. Soft-float is
the safe build.

  python3 -m emulator.runtime.abi check FILE...     exit 1 if any FILE would trap
  python3 -m emulator.runtime.abi check --root ROOTFS PATH...   PATH as the guest sees it
  python3 -m emulator.runtime.abi scan ROOTFS DIR... every executable program under DIR
"""
import os
from pathlib import Path
import struct
import sys

PT_DYNAMIC, PT_INTERP, PT_GNU_STACK, PT_MIPS_ABIFLAGS = 2, 3, 0x6474e551, 0x70000003
DT_FLAGS_1, DF_1_PIE = 0x6ffffffb, 0x08000000
FP_ABI = {0: 'any', 1: 'hard (double)', 2: 'hard (single)', 3: 'soft', 4: 'hard (old 64)',
          5: 'hard (fpxx)', 6: 'hard (fp64)', 7: 'hard (fp64a)'}
SOFT = 3


def inspect(path):
    """ELF facts of a 32-bit little-endian MIPS program, or None for anything else.

    A file that is cut short (an installer may still be writing it) yields the facts
    read so far; what is missing stays unknown. Never raises for file content.
    """
    try:
        with open(path, 'rb') as file:
            header = file.read(52)
            if len(header) < 52 or header[:6] != b'\x7fELF\x01\x01':
                return None
            kind, machine = struct.unpack_from('<HH', header, 16)
            if machine != 8 or kind not in (2, 3):
                return None
            offset, = struct.unpack_from('<I', header, 28)
            size, count = struct.unpack_from('<HH', header, 42)
            facts = dict(interpreter=None, stack_executable=True, fp_abi=None, library=False)
            pie = False
            for index in range(min(count, 64)):
                file.seek(offset + index * size)
                entry = file.read(32)
                if len(entry) < 32:
                    break
                segment, where, _, _, length, _, flags, _ = struct.unpack('<8I', entry)
                if segment == PT_INTERP and length < 256:
                    file.seek(where)
                    facts['interpreter'] = file.read(length).split(b'\0')[0].decode('ascii', 'replace')
                elif segment == PT_GNU_STACK:
                    facts['stack_executable'] = bool(flags & 1)
                elif segment == PT_MIPS_ABIFLAGS and length >= 8:
                    file.seek(where + 7)
                    value = file.read(1)
                    facts['fp_abi'] = value[0] if value else None
                elif segment == PT_DYNAMIC:
                    file.seek(where)
                    table = file.read(min(length, 8192))
                    for position in range(0, len(table) - 7, 8):
                        tag, item = struct.unpack_from('<II', table, position)
                        if tag == DT_FLAGS_1 and item & DF_1_PIE:
                            pie = True
            # ET_DYN without an interpreter is a shared library unless the linker marked it
            # as a (static) position-independent executable.
            facts['library'] = kind == 3 and not facts['interpreter'] and not pie
            return facts
    except (OSError, struct.error):
        return None


def resolve(root, program, limit=16):
    """The file a guest path names, following links INSIDE the guest root (as chroot does)."""
    root = Path(root)
    parts, done = [part for part in str(program).split('/') if part], []
    while parts:
        part = parts.pop(0)
        if part == '.':
            continue
        if part == '..':
            done = done[:-1]
            continue
        current = root.joinpath(*done, part)
        if current.is_symlink():
            limit -= 1
            if limit < 0:
                return current
            target = os.readlink(current)
            if target.startswith('/'):
                done = []
            parts = [piece for piece in target.split('/') if piece] + parts
            continue
        done.append(part)
    return root.joinpath(*done)


def verdict(facts):
    """'ok', 'trap' or 'unknown' (no ABI flags: built by a toolchain that does not say)."""
    if facts is None or facts['library']:
        return 'ok'                     # not a MIPS program: a script, data, a shared library
    if facts['fp_abi'] == SOFT:
        return 'ok'
    if facts['fp_abi'] is None:
        return 'unknown'
    musl = bool(facts['interpreter']) and 'musl' in facts['interpreter']
    return 'ok' if facts['fp_abi'] == 0 or (facts['stack_executable'] and not musl) else 'trap'


def describe(path, facts):
    return (f"{path}: FP ABI {FP_ABI.get(facts['fp_abi'], facts['fp_abi'])}, "
            f"{'dynamic ' + facts['interpreter'] if facts['interpreter'] else 'static'}, "
            f"{'executable' if facts['stack_executable'] else 'non-executable'} stack")


def check(paths):
    """[(path, verdict, description)] for the MIPS programs among the paths."""
    result = []
    for path in paths:
        facts = inspect(path)
        if facts is not None:
            result.append((str(path), verdict(facts), describe(path, facts)))
    return result


def scan(root, directories, limit=64 << 20):
    """Executable regular files under the guest directories (links and big media skipped)."""
    root = Path(root)
    for directory in directories:
        for folder, _, names in os.walk(root / directory.lstrip('/')):
            for name in names:
                path = Path(folder) / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if os.path.stat.S_ISREG(info.st_mode) and info.st_mode & 0o111 and info.st_size <= limit:
                    yield path


MESSAGE = ('would die on the player: Linux 4.4.94 emulates FPU branch delay slots on the stack, '
           'and this hard-float program has no executable stack (or is a musl program, whose threads '
           'never have one). Build it soft-float (-msoft-float).')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['check', 'scan'])
    parser.add_argument('paths', nargs='+')
    parser.add_argument('--root', help='check: resolve the paths inside this guest root')
    args = parser.parse_args()
    if args.action == 'scan':
        files = scan(args.paths[0], args.paths[1:])
    else:
        files = [resolve(args.root, path) for path in args.paths] if args.root else args.paths
    failed = False
    for name, outcome, text in check(files):
        if outcome == 'trap':
            failed = True
            print(f'[fpu-guard] {text}\n[fpu-guard] {MESSAGE}', file=sys.stderr)
        elif outcome == 'unknown':
            print(f'[fpu-guard] {text}: no MIPS ABI flags, cannot tell', file=sys.stderr)
    sys.exit(1 if failed else 0)
