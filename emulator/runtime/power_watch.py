"""Headless service of the guest's power-off request for the direct boot.

Stock idle power-off ends in BusyBox `poweroff -f`; fbshim turns that into
`emu/power-request`. The viewer serves it through Device.service_requests().
Without a viewer nothing did, and the stock pair stayed half shut down. This
watcher does the same job with no HTTP server and no lifetime of its own:
it runs until stopped. A stock-init guest needs none (its PID 1 serves the request).

  start   start a detached watcher for $ROOTFS (replaces a running one)
  stop    stop it
  status  JSON: running, pid, last served request
  run     foreground loop (what `start` launches)
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from emulator.runtime.keys import Device

PERIOD = .25


def paths(root):
    work = Path(root).resolve().parent
    return work / 'power-watch.json', work / 'power-watch.log'


def read(root):
    try:
        return json.loads(paths(root)[0].read_text())
    except (OSError, ValueError):
        return {}


def running_pid(root):
    pid = read(root).get('pid')
    try:
        args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    except (OSError, TypeError):
        return None
    return pid if b'emulator.runtime.power_watch' in args and b'run' in args else None


def publish(root, **fields):
    path = paths(root)[0]
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(json.dumps({**read(root), **fields}) + '\n')
    temporary.replace(path)


def run(root, sleep=time.sleep, rounds=None):
    device = Device(root)
    publish(root, pid=os.getpid(), rootfs=str(device.root), served=read(root).get('served', 0))
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    previous = None
    while not stopping and rounds != 0:
        device.service_requests()
        current = device.transition
        if current != previous:
            # Same wording as the viewer-free adapters this replaces: logs stay comparable.
            print('Power request: ' + (current or (f'failed: {device.error}' if device.error else 'completed')),
                  flush=True)
            if previous and not current and not device.error:
                publish(root, served=read(root).get('served', 0) + 1, last=time.time())
            previous = current
        sleep(PERIOD)
        rounds = None if rounds is None else rounds - 1
    deadline = time.monotonic() + 5
    while device.transition and time.monotonic() < deadline:   # let a stop in progress finish
        sleep(.1)


def stop(root, timeout=10):
    pid = running_pid(root)
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while running_pid(root) and time.monotonic() < deadline:
        time.sleep(.1)
    if running_pid(root):
        os.kill(pid, signal.SIGKILL)
    return True


def start(root):
    stop(root)
    with paths(root)[1].open('ab') as output:
        subprocess.Popen([sys.executable, '-B', '-m', 'emulator.runtime.power_watch', 'run'],
                         stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                         env={**os.environ, 'ROOTFS': str(root)}, start_new_session=True, cwd='/')
    deadline = time.monotonic() + 10
    while not running_pid(root):
        if time.monotonic() >= deadline:
            raise RuntimeError('Power watcher did not start; inspect power-watch.log')
        time.sleep(.05)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['start', 'stop', 'status', 'run'])
    action = parser.parse_args().action
    target = os.environ.get('ROOTFS', '/work/rootfs')
    try:
        if action == 'run':
            run(target)
        elif action == 'start':
            start(target)
        elif action == 'stop':
            stop(target)
        if action != 'run':
            print(json.dumps({**read(target), 'running': bool(running_pid(target))}))
    except RuntimeError as exc:
        parser.exit(1, f'{exc}\n')
