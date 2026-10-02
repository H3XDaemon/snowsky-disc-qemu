"""GPIO port B key levels: one state for the stock ioctl path and raw /dev/mem readers.

Static guest programs (no ld.so.preload shim) read the keys as the hardware pin
level: mmap of /dev/mem at the X2000 pinctrl base, port B PxPIN, active low.
The guest's /dev/mem is a sparse regular file holding only that word.
"""
import os
from pathlib import Path
import struct

PINCTRL_BASE = 0x10010000
PXPIN = 0x100                      # port B input level register
RELEASED = 0xF6EFE127              # device read with no key held (V2.40, 2026-08-13)
BITS = {'volume_up': 13, 'volume_down': 14, 'play_pause': 15}
MEM = 'dev/mem'
SIZE = PINCTRL_BASE + 0x1000       # one mappable page; the hole before it stays sparse
BUTTONS = 'emu/volume-buttons'     # fbshim: /dev/gpio pb13, pb14 as '0' (low) / '1'
HELD = 'emu/keys-held'             # levels kept low until released (power-on holds, CLI)
ARMED = 'emu/boot-keys'            # one-shot: held from the next power-on until boot ends


def word(held):
    """PxPIN value with the named keys pressed (their bits low)."""
    value = RELEASED
    for name in held:
        value &= ~(1 << BITS[name])
    return value


def parse(names):
    """Accept names or a comma/space separated string; 'play' is the Play/pause key."""
    if isinstance(names, str):
        names = names.replace(',', ' ').split()
    result = {'play_pause' if name == 'play' else name for name in names}
    unknown = result - set(BITS)
    if unknown:
        raise ValueError('Unknown key: ' + ', '.join(sorted(unknown)))
    return result


def _names(path):
    try:
        return parse(path.read_text())
    except (OSError, ValueError):
        return set()


def held(root):
    return _names(Path(root) / HELD)


def armed(root):
    return _names(Path(root) / ARMED)


def _save(path, names):
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(' '.join(sorted(names)) + '\n')
    temporary.replace(path)


def apply(root, extra=()):
    """Publish the levels of the persistent holds plus the caller's live holds."""
    root = Path(root)
    low = held(root) | set(extra)
    memory = root / MEM
    if not memory.exists():
        memory.touch()
    with memory.open('r+b') as device:
        if os.fstat(device.fileno()).st_size < SIZE:
            os.ftruncate(device.fileno(), SIZE)
        # Fixed-width overwrite: a reader never observes a truncated word.
        os.pwrite(device.fileno(), struct.pack('<I', word(low)), PINCTRL_BASE + PXPIN)
    levels = bytes(48 if name in low else 49 for name in ('volume_up', 'volume_down'))
    buttons = root / BUTTONS
    with buttons.open('r+b' if buttons.exists() else 'wb') as marker:
        marker.write(levels)
    return low


def read(root):
    """The raw word a static guest program would see, or None before setup."""
    try:
        with (Path(root) / MEM).open('rb') as device:
            data = os.pread(device.fileno(), 4, PINCTRL_BASE + PXPIN)
    except OSError:
        return None
    return struct.unpack('<I', data)[0] if len(data) == 4 else None


def hold(root, names):
    root = Path(root)
    _save(root / HELD, held(root) | parse(names))
    return apply(root)


def release(root, names=None):
    root = Path(root)
    _save(root / HELD, held(root) - parse(names) if names else set())
    return apply(root)


def arm(root, names):
    _save(Path(root) / ARMED, parse(names))


def power_on(root, names=()):
    """Start of a boot: armed keys (and the caller's) are down before any guest code runs."""
    root = Path(root)
    keys = armed(root) | parse(names)
    _save(root / ARMED, set())
    _save(root / HELD, keys)
    return apply(root)


def snapshot(root):
    value = read(root)
    return dict(word=None if value is None else f'0x{value:08X}',
                held=sorted(held(root)), armed=sorted(armed(root)))


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['reset', 'hold', 'release', 'arm', 'power-on', 'show'])
    parser.add_argument('keys', nargs='*', help='volume_up, volume_down, play_pause (or play)')
    args = parser.parse_args()
    target = os.environ.get('ROOTFS', '/work/rootfs')
    try:
        if args.action == 'reset':
            release(target)
        elif args.action == 'hold':
            hold(target, args.keys)
        elif args.action == 'release':
            release(target, args.keys)
        elif args.action == 'arm':
            arm(target, args.keys)
        elif args.action == 'power-on':
            power_on(target, args.keys)
    except ValueError as exc:
        parser.exit(2, f'{exc}\n')
    print(json.dumps(snapshot(target)))
