#!/usr/bin/env python3
"""Wait for the guest's input devices and the UI's first framebuffer flush, without TCP probes."""
import os
from pathlib import Path
import time

from emulator.runtime.keys import Device


PROGRAMS = {'mq_ui': 'event1', 'mq_player': 'event0'}   # name on the player -> input device it holds


def argv0(pid, proc=Path('/proc')):
    """The argv[0] a guest program received, read from the container's view of its cmdline.

    The kernel builds a binfmt-started program's cmdline for the interpreter: qemu's
    path, the program's path, then the caller's argv[0] (binfmt flag P) and the
    arguments; an explicit `qemu -0 NAME PROGRAM` carries NAME after -0. None for a
    process that is not a guest (the native init, a helper) or a layout not known here.
    """
    try:
        fields = (proc / str(pid) / 'cmdline').read_bytes().split(b'\0')[:-1]
    except OSError:
        return None
    if len(fields) < 2 or not fields[0].rsplit(b'/', 1)[-1].startswith(b'qemu-mipsel'):
        return None
    if fields[1] == b'-0':
        return fields[2].decode('utf-8', 'replace') if len(fields) > 3 else None
    if fields[1].startswith(b'-'):
        return None
    try:
        auxv = (proc / str(pid) / 'auxv').read_bytes()
    except OSError:
        return None
    for offset in range(0, len(auxv) - 15, 16):          # 64-bit host: (type, value) pairs
        kind, value = int.from_bytes(auxv[offset:offset + 8], 'little'), int.from_bytes(auxv[offset + 8:offset + 16], 'little')
        if kind == 8:                                     # AT_FLAGS: bit 0 = AT_FLAGS_PRESERVE_ARGV0
            return fields[2 if value & 1 else 1].decode('utf-8', 'replace') if len(fields) > (2 if value & 1 else 1) else None
    return fields[1].decode('utf-8', 'replace')


def watched(name, pid, proc=Path('/proc')):
    """Would the player's `pgrep -x NAME` (BusyBox 1.31.1) find this guest process?

    BusyBox tries the pattern on argv[0] and falls back to the process name only when
    the pattern occurs nowhere in argv[0]; with -x the match must cover the whole
    string. So `exec /usr/bin/mq_ui` (argv[0] a path that contains the name) is
    invisible to stock's watch loop on the player, while `exec -a mq_ui ...` is found.
    The guest's own view of cmdline shows the same under PROC_EXE (emulation.md);
    this reads the container's view, so it holds either way.

    NAME is taken literally here; BusyBox compiles it as an extended regex, so for a
    name with `.` or other metacharacters (`fiio_init.sh`) the player matches more.
    """
    first = argv0(pid, proc)
    if first is None or name not in first:
        try:
            return (proc / str(pid) / 'comm').read_text().strip() == name
        except OSError:
            return False
    return first == name


def holders(device, proc=Path('/proc')):
    """PIDs of the stock-named programs that hold their input device: {'mq_ui': [...], 'mq_player': [...]}.

    The name is /proc/<pid>/comm, what `pidof`/`killall` accept (the name, or the
    basename of argv[0]): a UI started from another path (a boot layer's package)
    counts like stock's, and a launcher or helper that carries the name without the
    device does not. The player's `pgrep -x` is stricter: see watched().
    """
    found = {name: [] for name in PROGRAMS}
    for pid in sorted(device.processes()):          # live processes in this exact chroot only
        entry = proc / str(pid)
        try:
            name = (entry / 'comm').read_text().strip()
            if name in PROGRAMS and any(fd.resolve() == device.root / 'dev/input' / PROGRAMS[name]
                                        for fd in (entry / 'fd').iterdir()):
                found[name].append(pid)
        except OSError:
            continue                                # process/fd disappeared during the snapshot
    return found


def flusher(device):
    """PID, in its own namespace, of the process that last flushed a frame; None before the first.

    fbshim writes emu/fb-flush on a dynamic program's first copy into the framebuffer
    (and every buffer switch); the rebuilt qemu writes it on a static program's
    FBIOPAN_DISPLAY. Both write a fixed-width "%10d\\n" in place, so a poll never reads
    it empty or torn. 15_controls.sh empties it before each power-on.
    """
    try:
        return int((device.root / 'emu/fb-flush').read_text())
    except (OSError, ValueError):
        return None


def own_pid(pid, proc=Path('/proc')):
    """The PID a process has in its own namespace: the last NSpid entry (a stock-init
    guest lives in a PID namespace; a direct boot shares the container's)."""
    for line in (proc / str(pid) / 'status').read_text().splitlines():
        if line.startswith('NSpid:'):
            return int(line.split()[-1])
    return pid


def ready(device, proc=Path('/proc')):
    """Both input devices held, and a frame flushed by THIS UI process (not a predecessor's,
    not a probe's): old pixels cannot count, and a UI that flushed before anyone noticed it
    counts all the same."""
    found = holders(device, proc)
    if not all(found.values()):
        return False
    flushed = flusher(device)
    if flushed is None:
        return False
    for pid in found['mq_ui']:
        try:
            if own_pid(pid, proc) == flushed:
                return True
        except (OSError, ValueError):
            continue
    return False


def wait_ready(device, timeout=60, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while not ready(device):
        if clock() >= deadline:
            raise TimeoutError('Guest input/framebuffer not ready; inspect mq_ui.log and mq_player.log')
        sleep(.2)


if __name__ == '__main__':
    wait_ready(Device(os.environ.get('ROOTFS', '/work/rootfs')))
    print('Guest input devices open and first framebuffer flush received', flush=True)
