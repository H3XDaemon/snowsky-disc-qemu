"""PID 1 of a guest booted through the stock init scripts (BOOT_MODE=init).

Run only by emulator.runtime.machine inside fresh PID, IPC and UTS namespaces.
It stands in for BusyBox init and the inittab: prepares what the kernel and the
sysinit lines provide on the player, runs the real /etc/init.d/rcS, reaps
orphans, and answers the same signals (TERM reboot, USR1/USR2 halt/poweroff)
by running the real /etc/init.d/rcK. See emulator/docs/stock-init.md.
"""
import ctypes
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import time

# BusyBox init's environment for its children (init.c). rcS then sources /etc/profile.
ENVIRONMENT = {'HOME': '/', 'PATH': '/sbin:/usr/sbin:/bin:/usr/bin', 'SHELL': '/bin/sh',
               'USER': 'root', 'TERM': 'vt102'}
CONFINE = ['setpriv', '--bounding-set=-net_admin,-sys_time,-sys_boot,-sys_module,-sys_rawio',
           '--no-new-privs']
REBOOT = 3                          # exit status asking the machine for another power-on
FORCED = 4                          # guest `poweroff -f`: powered down without rcK
NODES = {'null': (1, 3), 'zero': (1, 5), 'full': (1, 7), 'random': (1, 8), 'urandom': (1, 9)}
TMPFS = (('tmp', 'mode=1777'), ('run', 'mode=0755,nosuid,nodev'), ('dev/shm', 'mode=0777'))


def log(message):
    print(f'[emu-init] {message}', flush=True)


def mounted(path):
    return subprocess.run(['mountpoint', '-q', str(path)]).returncode == 0


def unmount(path, lazy=False):
    while mounted(path):
        if subprocess.run(['umount'] + (['-l'] if lazy else []) + [str(path)]).returncode:
            if lazy:
                raise RuntimeError(f'Cannot unmount {path}')
            lazy = True


class Init:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.request = None

    def run(self, command, timeout):
        """One init action: wait for it while reaping every orphan, like init does."""
        child = subprocess.Popen(CONFINE + ['chroot', str(self.root)] + command, env=ENVIRONMENT,
                                 stdin=subprocess.DEVNULL, cwd='/')
        deadline = time.monotonic() + timeout
        while self.reap(child.pid) is None:
            if time.monotonic() >= deadline:
                log(f'{command[0]} did not finish in {timeout}s; continuing')
                return None
            time.sleep(.05)
        return child

    def reap(self, wanted=None):
        """Collect every exited child; return the wanted one's status if it was among them."""
        found = None
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            if pid == wanted:
                found = status
        return found

    def sysinit(self):
        root = self.root
        # A power cut leaves the previous boot's kernel mounts behind; RAM does not survive.
        for name in ('tmp/sdcard', 'usr/data', 'tmp', 'run', 'dev/shm', 'dev/mqueue', 'proc/sys', 'proc'):
            unmount(root / name)
        # inittab: mount proc, then `mount -a` (fstab: tmpfs /tmp, /run, /dev/shm). /dev stays the
        # emulator's device stubs instead of a fresh tmpfs + mdev; /sys stays the stub tree.
        subprocess.run(['mount', '-t', 'proc', 'proc', str(root / 'proc')], check=True)
        # Guest scripts write /proc/sys (printk, core_pattern): never the shared VM kernel's.
        subprocess.run(['mount', '--bind', str(root / 'proc/sys'), str(root / 'proc/sys')], check=True)
        subprocess.run(['mount', '-o', 'remount,ro,bind', str(root / 'proc/sys')], check=True)
        for name, options in TMPFS:
            (root / name).mkdir(parents=True, exist_ok=True)
            subprocess.run(['mount', '-t', 'tmpfs', '-o', options, 'tmpfs', str(root / name)], check=True)
        (root / 'dev/mqueue').mkdir(exist_ok=True)
        subprocess.run(['mount', '-t', 'mqueue', 'none', str(root / 'dev/mqueue')], check=True)
        for name, (major, minor) in NODES.items():   # inittab mknod /dev/null; mdev makes the rest
            node = root / 'dev' / name
            if not node.is_char_device():
                node.unlink(missing_ok=True)
                os.mknod(node, stat.S_IFCHR | 0o666, os.makedev(major, minor))
        console = root / 'dev/console'               # no tty: boot scripts write status lines here
        if console.is_symlink() or not console.is_file():
            console.unlink(missing_ok=True)
        console.write_bytes(b'')
        # inittab: hostname -F /etc/hostname, in this guest's own UTS namespace.
        socket.sethostname((root / 'etc/hostname').read_text().strip() or 'ingenic')

    def boot(self):
        self.sysinit()
        log('sysinit done; running /etc/init.d/rcS')
        child = self.run(['/etc/init.d/rcS'], timeout=300)
        log('rcS finished' if child else 'rcS still running')

    def shutdown(self, clean):
        if clean:
            log('running /etc/init.d/rcK')
            self.run(['/etc/init.d/rcK'], timeout=60)
        # BusyBox init: TERM everything, one second, then KILL; here PID 1 of the namespace.
        os.sync()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(-1, sig)
            except ProcessLookupError:
                break
            time.sleep(1)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.waitpid(-1, 0)
            except ChildProcessError:
                break
        # inittab: umount -a -r
        for name in ('tmp/sdcard', 'usr/data'):
            unmount(self.root / name)
        os.sync()

    def supervise(self):
        marker = self.root / 'emu/power-request'
        while self.request is None:
            self.reap()
            try:
                if marker.read_bytes()[:1] == b'1':
                    # Stock idle power-off is `poweroff -f`: sync and power down, no rcK.
                    with marker.open('r+b') as file:
                        file.write(b'0')
                    self.request = 'forced'
                    break
            except OSError:
                pass
            time.sleep(.2)
        return self.request


def main():
    if os.getpid() != 1:
        sys.exit('guest_init is PID 1 of a guest namespace; start it with emulator.runtime.machine')
    init = Init(os.environ.get('ROOTFS', '/work/rootfs'))
    ctypes.CDLL(None, use_errno=True).prctl(15, b'init', 0, 0, 0)  # PR_SET_NAME: comm as on the player
    # The container's /proc is still mounted at /proc: it names this process in the outer namespace.
    (init.root / 'emu/init.pid.new').write_text(os.readlink('/proc/self') + '\n')
    (init.root / 'emu/init.pid.new').replace(init.root / 'emu/init.pid')
    actions = {signal.SIGTERM: 'reboot', signal.SIGUSR1: 'poweroff', signal.SIGUSR2: 'poweroff'}
    for number, action in actions.items():
        signal.signal(number, lambda _n, _f, action=action: setattr(init, 'request', action))
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    init.boot()
    request = init.supervise()
    log(f'{request} requested')
    init.shutdown(clean=request != 'forced')
    log('power down' if request != 'reboot' else 'restarting')
    sys.exit({'reboot': REBOOT, 'forced': FORCED}.get(request, 0))


if __name__ == '__main__':
    main()
