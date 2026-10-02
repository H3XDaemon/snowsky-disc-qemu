"""Board-level lifecycle of a stock-init guest: power-on, reboot, power-off, power cut.

`run` is the supervisor outside the guest: every power-on starts
emulator.runtime.guest_init as PID 1 of fresh PID/IPC/UTS namespaces, replays what
the direct boot does around the stock programs (network announce, card remount,
key release), and restores the container's view when the guest is gone.
The other actions are clients of a running supervisor. See emulator/docs/stock-init.md.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from emulator.runtime import gpio
from emulator.runtime.guest_init import FORCED, REBOOT, mounted, unmount

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / 'emulator/scripts/lib.sh'
STATE = 'emu/machine.json'
INIT_PID = 'emu/init.pid'
REQUEST = 'emu/machine-request'
NETWORK_MARKER = b'Network detect thread started'
NAMESPACES = ['unshare', '--pid', '--ipc', '--uts', '--fork', '--kill-child']


def state(root):
    try:
        return json.loads((Path(root) / STATE).read_text())
    except (OSError, ValueError):
        return {'state': 'off', 'boots': 0, 'reason': None, 'pid': None}


def _alive(pid, module):
    try:
        return module.encode() in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    except (OSError, TypeError):
        return False


def supervisor_pid(root):
    pid = state(root).get('pid')
    return pid if pid and _alive(pid, 'emulator.runtime.machine') else None


def init_pid(root):
    """The guest's PID 1 as the container sees it, while that guest is alive."""
    try:
        pid = int((Path(root) / INIT_PID).read_text())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid, 'emulator.runtime.guest_init') else None


def active(root):
    return bool(supervisor_pid(root) or init_pid(root))


def shell(root, script, **options):
    # PROC_EXE: on the player /proc/<pid>/exe names the program; stock hooks rely on it.
    return subprocess.run(['bash', '-c', f'source {LIB}; {script}'],
                          env={'PROC_EXE': '1', **os.environ, 'ROOTFS': str(root)}, **options)


def restore_view(root):
    """Give the rootfs back to container-side tools: its proc and mqueue, no guest RAM."""
    root = Path(root)
    for name in ('tmp/sdcard', 'usr/data', 'tmp', 'run', 'dev/shm', 'dev/mqueue', 'proc/sys', 'proc'):
        unmount(root / name)
    subprocess.run(['mount', '-t', 'proc', 'proc', str(root / 'proc')], check=True)
    subprocess.run(['mount', '-t', 'mqueue', 'none', str(root / 'dev/mqueue')], check=True)
    (root / INIT_PID).unlink(missing_ok=True)


def guest_processes(root):
    from emulator.runtime.keys import Device
    return Device(root).processes()


def kill_guest_tree(root, timeout=10):
    """Power is gone: nothing in the guest gets to run another instruction."""
    pid = init_pid(root)
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)   # the kernel then kills the whole PID namespace
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = guest_processes(root)
        if not pids and not init_pid(root):
            return
        for pid in pids:                   # helpers started outside the namespace
            try:
                if Path(f'/proc/{pid}/root').resolve(strict=True) == Path(root).resolve():
                    os.kill(pid, signal.SIGKILL)
            except (OSError, ValueError):
                pass
        time.sleep(.1)
    raise RuntimeError('Some guest processes could not be stopped')


def drop_unsynced(root):
    """Keep only what had reached the /usr/data block device when power went away.

    Call right after the guest is killed and before anything is unmounted: dirty
    pages are then still only in memory, so the image file is the flash content.
    Returns a note for the state file, or None when /usr/data is not an image.
    """
    root = Path(root)
    image = root.parent / 'userdata.img'
    if not image.is_file() or not mounted(root / 'usr/data'):
        return None
    snapshot = image.with_suffix('.cut')
    subprocess.run(['cp', '--sparse=always', str(image), str(snapshot)], check=True)
    unmount(root / 'usr/data')
    # The copy is not atomic against kernel writeback. Replay its journal like the next
    # mount would; refuse a copy that needs more than that and keep the synced image.
    check = subprocess.run(['e2fsck', '-p', str(snapshot)], capture_output=True, text=True)
    if check.returncode >= 4:
        snapshot.unlink()
        return 'unsynced data kept: snapshot was inconsistent'
    shell(root, 'userdata_detach', check=True)
    snapshot.replace(image)
    shell(root, 'userdata_attach', check=True)
    return 'unsynced data dropped'


class Machine:
    def __init__(self, root, keys=(), ttl=0):
        self.root = Path(root).resolve()
        self.work = self.root.parent
        self.keys = gpio.parse(keys)
        self.ttl = ttl
        self.boots = 0
        self.child = None
        self.cut = False

    def publish(self, name, reason=None):
        data = dict(state=name, boots=self.boots, reason=reason, pid=os.getpid(),
                    init=init_pid(self.root))
        path = self.root / STATE
        temporary = path.with_name(path.name + '.new')
        temporary.write_text(json.dumps(data) + '\n')
        temporary.replace(path)

    def power_on(self, console):
        self.boots += 1
        shell(self.root, 'board_reset', check=True, stdout=console, stderr=subprocess.STDOUT)
        # Keys named for this run apply to its first power-on; armed keys to the next one, once.
        gpio.power_on(self.root, self.keys if self.boots == 1 else ())
        (self.root / INIT_PID).unlink(missing_ok=True)
        self.child = subprocess.Popen(
            NAMESPACES + [sys.executable, '-B', '-m', 'emulator.runtime.guest_init'],
            stdin=subprocess.DEVNULL, stdout=console, stderr=subprocess.STDOUT,
            env={**os.environ, 'ROOTFS': str(self.root)}, cwd='/')

    def watch(self, console_path, deadline):
        """Until this boot ends: do what hardware/hotplug does around the stock programs."""
        from emulator.runtime.boot_ready import ready
        from emulator.runtime.keys import Device
        device = Device(self.root)
        offset, tail, published, keys_down = 0, b'', False, True
        ui, waiting, settled = None, False, None
        let_go = time.monotonic() + 60          # nobody keeps a key down longer than this
        while self.child.poll() is None:
            if keys_down and time.monotonic() >= let_go:
                gpio.release(self.root)
                keys_down = False
            if self.cut:
                return
            if deadline and time.monotonic() >= deadline:
                self.cut = 'lifetime limit (GUEST_TTL)'
                return
            if not published and init_pid(self.root):
                self.publish('running')
                published = True
            # A fresh mq_player subscribes to address events but never asks for the
            # existing address: announce it once per start (also after the stock
            # watch loop restarts the pair).
            with console_path.open('rb') as log:
                log.seek(offset)
                data = tail + log.read()
                offset = log.tell()
            if NETWORK_MARKER in data:
                shell(self.root, f'bash {REPO}/emulator/scripts/16_network.sh reannounce')
            tail = data[-len(NETWORK_MARKER):] if NETWORK_MARKER not in data else b''
            # The stock pair unmounts the card while it starts and expects a hotplug
            # remount. Once THIS UI process has drawn a frame, keep the card mounted
            # until the start-up has settled.
            current = self.ui_pid(device)
            if current != ui:
                ui, waiting, settled = current, current is not None, None
                if waiting:
                    (self.root / 'emu/fb-live').write_bytes(b'\xff')
            elif waiting and ready(device):
                waiting, settled = False, time.monotonic() + 20
                if keys_down:
                    gpio.release(self.root)
                    keys_down = False
            if settled and (self.root / 'dev/mmcblk0p1').is_block_device() and \
                    not os.path.ismount(self.root / 'tmp/sdcard'):
                shell(self.root, 'sd_mount')
            if settled and time.monotonic() >= settled:
                settled = None
            time.sleep(.25)

    @staticmethod
    def ui_pid(device):
        for pid in device.processes():
            try:
                if Path(f'/proc/{pid}/comm').read_text().strip() == 'mq_ui':
                    return pid
            except OSError:
                pass
        return None

    def power_cut(self, reason, unsynced):
        self.child.kill()                  # --kill-child: takes the guest's PID 1 with it
        self.child.wait()
        kill_guest_tree(self.root)
        note = drop_unsynced(self.root) if unsynced else None
        return f'{reason}; {note}' if note else reason

    def run(self):
        signal.signal(signal.SIGUSR1, self.on_cut)
        signal.signal(signal.SIGTERM, self.on_cut)
        deadline = time.monotonic() + self.ttl if self.ttl else None
        console_path = self.work / 'console.log'
        reason = 'poweroff'
        with console_path.open('wb') as console:
            while True:
                self.publish('starting')
                self.power_on(console)
                self.watch(console_path, deadline)
                if self.cut:
                    reason = self.power_cut(*self.cut_request())
                    break
                if self.child.returncode != REBOOT:
                    if self.child.returncode == FORCED:
                        reason = 'guest poweroff -f'
                    elif self.child.returncode:
                        reason = f'init exited with status {self.child.returncode}'
                    break
                self.publish('rebooting')
        gpio.release(self.root)
        restore_view(self.root)
        self.publish('off', reason)

    def on_cut(self, number, _frame):
        self.cut = self.cut or ('power cut' if number == signal.SIGUSR1 else 'stopped')

    def cut_request(self):
        try:
            request = json.loads((self.root / REQUEST).read_text())
            (self.root / REQUEST).unlink()
        except (OSError, ValueError):
            request = {}
        return self.cut if isinstance(self.cut, str) else 'power cut', bool(request.get('unsynced'))


def wait_for(predicate, timeout, message):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError(message)
        time.sleep(.1)


def start(root, keys=(), ttl=0):
    root = Path(root)
    if active(root):
        raise RuntimeError('Guest machine is already running; cut or power it off first')
    (root / STATE).write_text(json.dumps(dict(state='starting', boots=0, reason=None, pid=None)) + '\n')
    with (root.parent / 'machine.log').open('ab') as output:
        subprocess.Popen([sys.executable, '-B', '-m', 'emulator.runtime.machine', 'run',
                          '--ttl', str(ttl), '--keys', ' '.join(sorted(gpio.parse(keys)))],
                         stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                         env={**os.environ, 'ROOTFS': str(root)}, start_new_session=True, cwd='/')
    wait_for(lambda: state(root)['state'] in ('running', 'off'), 30, 'Guest init did not start')
    if state(root)['state'] == 'off':
        raise RuntimeError('Guest machine stopped at once; inspect machine.log and console.log')


def cut(root, unsynced=False, timeout=30):
    """Hard power loss. Safe to call when nothing runs; cleans up a stale guest view."""
    root = Path(root)
    supervisor = supervisor_pid(root)
    if supervisor:
        request = root / REQUEST
        request.with_name(request.name + '.new').write_text(json.dumps({'unsynced': unsynced}))
        request.with_name(request.name + '.new').replace(request)
        os.kill(supervisor, signal.SIGUSR1)
        wait_for(lambda: not supervisor_pid(root), timeout, 'Machine supervisor did not stop')
    elif init_pid(root) or (root / INIT_PID).exists():
        kill_guest_tree(root)              # supervisor died first: finish its job
        restore_view(root)


def signal_init(root, number, expect, timeout):
    pid, before = init_pid(root), state(root)
    if not pid:
        raise RuntimeError('No stock-init guest is running')
    os.kill(pid, number)
    wait_for(lambda: expect(before, state(root)), timeout, 'Guest did not complete the transition')


def reboot(root, timeout=180):
    """Clean restart: rcK, then a new power-on through rcS."""
    signal_init(root, signal.SIGTERM,
                lambda old, new: new['boots'] > old['boots'] and new['state'] == 'running', timeout)


def poweroff(root, timeout=120):
    """Clean shutdown through rcK; the machine stays off."""
    signal_init(root, signal.SIGUSR2, lambda _old, new: new['state'] == 'off', timeout)
    wait_for(lambda: not supervisor_pid(root), 10, 'Machine supervisor did not stop')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'start', 'status', 'reboot', 'poweroff', 'cut'])
    parser.add_argument('--keys', default='', help='keys held from this power-on until boot ends')
    parser.add_argument('--ttl', type=int, default=0, help='seconds before a forced stop; 0 = none')
    parser.add_argument('--unsynced', action='store_true',
                        help='cut: also lose /usr/data writes that were not yet on the image')
    args = parser.parse_args()
    target = os.environ.get('ROOTFS', '/work/rootfs')
    try:
        if args.action == 'run':
            Machine(target, args.keys, args.ttl).run()
        elif args.action == 'start':
            start(target, args.keys, args.ttl)
        elif args.action == 'reboot':
            reboot(target)
        elif args.action == 'poweroff':
            poweroff(target)
        elif args.action == 'cut':
            cut(target, args.unsynced)
        if args.action != 'run':
            print(json.dumps({**state(target), 'active': active(target)}))
    except (RuntimeError, TimeoutError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
