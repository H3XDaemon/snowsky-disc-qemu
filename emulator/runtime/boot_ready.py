#!/usr/bin/env python3
"""Wait for the guest's input devices and the UI's first framebuffer flush, without TCP probes."""
import os
from pathlib import Path
import time

from emulator.runtime.keys import Device


PROGRAMS = {'mq_ui': 'event1', 'mq_player': 'event0'}   # name on the player -> input device it holds


def holders(device, proc=Path('/proc')):
    """PIDs of the stock-named programs that hold their input device: {'mq_ui': [...], 'mq_player': [...]}.

    The name is /proc/<pid>/comm, what stock's own `pgrep -x` matches: a UI started
    from another path (a boot layer's package) counts like stock's. A launcher or
    helper that carries the name without the device does not.
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
