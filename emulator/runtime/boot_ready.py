#!/usr/bin/env python3
"""Wait for the guest's input devices and first framebuffer flush, without TCP probes."""
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


def ready(device, proc=Path('/proc')):
    # 15_controls.sh resets this marker before each boot: old pixels cannot count.
    try:
        if (device.root / 'emu/fb-live').read_bytes() not in (b'\x00', b'\x01'):
            return False
    except OSError:
        return False
    return all(holders(device, proc).values())


def wait_ready(device, timeout=60, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while not ready(device):
        if clock() >= deadline:
            raise TimeoutError('Guest input/framebuffer not ready; inspect mq_ui.log and mq_player.log')
        sleep(.2)


if __name__ == '__main__':
    wait_ready(Device(os.environ.get('ROOTFS', '/work/rootfs')))
    print('Guest input devices open and first framebuffer flush received', flush=True)
