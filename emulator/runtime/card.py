"""The emulated SD card: its image, its loop device and the guest's block nodes.

Two layouts. The original **flat** image is one filesystem with no partition
table; the guest's /dev/mmcblk0 and /dev/mmcblk0p1 are then two names for one
device. A **partitioned** image is what a real card is: an MBR and one
partition, so the two nodes are different devices and stock's own `blkid`
enumeration finds the partition without help. The layout is read back from the
image, never from a side file.
"""
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import time

IMAGE = 'sdcard.img'
SECTOR = 512
START = 2048                                  # first partition at 1 MiB, as cards are sold
TYPES = {'vfat': 0x0c, 'exfat': 0x07}         # MBR partition type per filesystem
LABEL = 'SNOWSKY'
NODES = ('mmcblk0', 'mmcblk0p1')
SKIP = ('README.md', '.gitkeep')              # placeholders of the tracked media folder


def image(root):
    return Path(root).resolve().parent / IMAGE


def partitioned(path):
    """True for an image this module built with an MBR (a filesystem starts with a jump)."""
    with open(path, 'rb') as file:
        sector = file.read(SECTOR)
    return (len(sector) == SECTOR and sector[0] == 0 and sector[510:512] == b'\x55\xaa'
            and sector[450] in TYPES.values()
            and struct.unpack_from('<I', sector, 454)[0] == START)


def mbr(sectors, filesystem):
    """One primary partition from START to the end of the card."""
    table = bytearray(SECTOR)
    table[446:462] = struct.pack('<B3sB3sII', 0, b'\xfe\xff\xff', TYPES[filesystem], b'\xfe\xff\xff',
                                 START, sectors - START)
    table[510:512] = b'\x55\xaa'
    return bytes(table)


def loops(path):
    """Loop devices currently attached to this image."""
    if not Path(path).is_file():
        return []        # losetup -j would match other containers' loops by path text
    output = subprocess.run(['losetup', '-j', str(path)], capture_output=True, text=True).stdout
    return [line.split(':', 1)[0] for line in output.splitlines() if line]


def attach(path):
    """Attach the image; returns (loop path, whole-card device number, partition device number)."""
    split = partitioned(path)
    attached = loops(path)                    # still attached while a pulled card's file is open
    if attached:
        loop = attached[0]
    else:
        # The container's /dev is a snapshot: a loop device the VM creates now has no node here.
        loop = subprocess.check_output(['losetup', '--find'], text=True, timeout=10).strip()
        if not Path(loop).exists():
            os.mknod(loop, stat.S_IFBLK | 0o660, os.makedev(7, int(loop.rsplit('loop', 1)[1])))
        subprocess.run(['losetup'] + (['-P'] if split else []) + [loop, str(path)], check=True, timeout=10)
    info = Path(loop).stat()
    if not stat.S_ISBLK(info.st_mode) or os.major(info.st_rdev) != 7:
        raise ValueError('Expected a loop device for the SD image')
    if not split:
        return loop, info.st_rdev, info.st_rdev
    name = Path(loop).name
    entry = Path(f'/sys/block/{name}/{name}p1/dev')
    deadline = time.monotonic() + 5
    while not entry.exists():                 # the kernel scans the table asynchronously
        if time.monotonic() >= deadline:
            raise ValueError('The kernel did not find the card partition')
        time.sleep(.05)
    major, minor = (int(part) for part in entry.read_text().split(':'))
    return loop, info.st_rdev, os.makedev(major, minor)


def detach(path):
    for loop in loops(path):
        subprocess.run(['losetup', '-d', loop], check=False)


def devices(path):
    """Device numbers that belong to this image right now (whole card and partition)."""
    found = set()
    for loop in loops(path):
        found.add(Path(loop).stat().st_rdev)
        name = Path(loop).name
        try:
            major, minor = (int(part) for part in Path(f'/sys/block/{name}/{name}p1/dev').read_text().split(':'))
            found.add(os.makedev(major, minor))
        except OSError:
            pass
    return found


def make_nodes(directory, whole, part, names=NODES):
    """Real block nodes (the chrooted guest cannot follow a link to the container's /dev)."""
    for name, device in zip(names, (whole, part)):
        node = Path(directory) / name
        replacement = node.with_name(node.name + '.new')
        replacement.unlink(missing_ok=True)
        os.mknod(replacement, stat.S_IFBLK | 0o644, device)
        replacement.replace(node)


def build(root, source, size_mb=None, filesystem='vfat', partition=False):
    """A new card image holding the files of `source`."""
    if filesystem not in TYPES:
        raise ValueError('SDCARD_FS must be vfat or exfat')
    if filesystem == 'exfat' and not shutil.which('mkfs.exfat'):
        raise ValueError('mkfs.exfat missing: rebuild the image from emulator/docker (exfatprogs)')
    source = Path(source)
    if size_mb is None:
        used = int(subprocess.check_output(['du', '-sm', str(source)], text=True).split()[0])
        size_mb = used + 32
    if type(size_mb) is not int or not 16 <= size_mb <= 262144:
        raise ValueError('SDCARD_MB must be 16..262144 (MiB)')
    path = image(root)
    path.unlink(missing_ok=True)
    with path.open('wb') as file:
        file.truncate(size_mb << 20)          # sparse: a 31 GiB card costs what it holds
        if partition:
            file.write(mbr((size_mb << 20) // SECTOR, filesystem))
    loop, _, part = attach(path)
    workspace = Path(tempfile.mkdtemp())
    node = workspace / 'card'
    try:
        os.mknod(node, stat.S_IFBLK | 0o600, part)
        maker = ['mkfs.vfat', '-n', LABEL] if filesystem == 'vfat' else ['mkfs.exfat', '-L', LABEL]
        subprocess.run(maker + [str(node)], check=True, capture_output=True)
        mount = workspace / 'mount'
        mount.mkdir()
        # The guest mounts with iocharset=utf8: write long names the same way, or a host
        # default of iso8859-1 corrupts UTF-8 paths before the guest sees them.
        subprocess.run(['mount', '-t', filesystem, '-o', 'iocharset=utf8', str(node), str(mount)], check=True)
        try:
            subprocess.run(['cp', '-r', f'{source}/.', f'{mount}/'], check=False, capture_output=True)
            for name in SKIP:
                (mount / name).unlink(missing_ok=True)
            os.sync()
        finally:
            subprocess.run(['umount', str(mount)], check=True)
    finally:
        node.unlink(missing_ok=True)
        shutil.rmtree(workspace, ignore_errors=True)
        subprocess.run(['losetup', '-d', loop], check=False)
    return dict(size_mb=size_mb, filesystem=filesystem, partitioned=partition)


def insert(root, directory='dev'):
    """Attach the image and publish its nodes in the guest; returns the loop path."""
    root = Path(root)
    loop, whole, part = attach(image(root))
    make_nodes(root / directory, whole, part)
    return loop


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['build', 'insert', 'detach', 'show'])
    parser.add_argument('--source', default='/sdcard')
    parser.add_argument('--mb', type=int, help='card size in MiB (default: content + 32)')
    parser.add_argument('--fs', default='vfat', choices=sorted(TYPES))
    parser.add_argument('--partition', action='store_true', help='MBR with one partition, like a real card')
    args = parser.parse_args()
    target = os.environ.get('ROOTFS', '/work/rootfs')
    try:
        if args.action == 'build':
            print(json.dumps(build(target, args.source, args.mb, args.fs, args.partition)))
        elif args.action == 'insert':
            print(insert(target))
        elif args.action == 'detach':
            detach(image(target))
        else:
            path = image(target)
            print(json.dumps(dict(image=str(path), bytes=path.stat().st_size, partitioned=partitioned(path),
                                  loops=loops(path)) if path.exists() else dict(image=None)))
    except (ValueError, subprocess.SubprocessError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
