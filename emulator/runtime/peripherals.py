"""Viewer settings and scoped emulated peripherals; no firmware memory writes."""
import os
from pathlib import Path
import socket
import stat
import subprocess
import threading
import time

from emulator.runtime import card, gpio
from emulator.runtime.keys import BRIGHTNESS
from firmware.profile import identify_player


class Peripherals:
    def __init__(self, device):
        self.device = device
        self.root = device.root
        self.lock = threading.RLock()
        self.operation = None
        self.error = None
        self.profile_key = None
        self.profile = None

    def _profile(self):
        binary = self.root / 'usr/bin/mq_player'
        info = binary.stat()
        key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if key != self.profile_key:
            self.profile = identify_player(binary.read_bytes())
            self.profile_key = key
        return self.profile

    def _pid(self):
        self._profile()
        pids = []
        for pid in self.device.processes():
            try:
                if Path(f'/proc/{pid}/comm').read_text().strip() == 'mq_player' and \
                        b'/usr/bin/mq_player' in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0'):
                    pids.append(pid)
            except FileNotFoundError:
                continue
        if len(pids) != 1:
            raise ValueError('Player is not ready')
        return pids[0]

    def snapshot(self):
        try:
            brightness = int((self.root / BRIGHTNESS).read_bytes().split(b'\0', 1)[0])
        except (OSError, ValueError):
            brightness = None
        active = self.root / 'dev/mmcblk0p1'
        saved = self.root / 'emu/sd-mmcblk0p1'
        return dict(brightness=brightness, sd_available=active.is_block_device() or saved.is_block_device(),
                    sd_inserted=active.is_block_device(),
                    usb_connected=self._usb_connected(), jack=self.jack(),
                    boot_keys=sorted(gpio.armed(self.root)),
                    peripheral_transition=self.operation,
                    peripheral_error=self.error)

    def _usb_connected(self):
        try:
            return (self.root / 'emu/usb-connected').read_text().strip() == '1'
        except FileNotFoundError:
            return False

    def set_usb(self, connected):
        if type(connected) is not bool:
            raise ValueError('Expected connected boolean')
        with self.device.lock, self.lock:
            if self.device.transition or self.operation:
                raise ValueError('Wait for the current operation')
            path = self.root / 'emu/usb-connected'
            path.parent.mkdir(parents=True, exist_ok=True)
            # The ADC shim polls this byte. Avoid a transient empty file between
            # truncate/write being interpreted as a cable removal.
            with path.open('r+b' if path.exists() else 'wb') as marker:
                marker.write(b'1' if connected else b'0')
            # V2.57's shim reports sink-role/ADC power detection from this byte;
            # only guest sysfs, never host USB gadget/role-switch events.
            battery = self.root / 'sys/class/power_supply/cw221X-bat/status'
            if battery.is_file():
                battery.write_text('Charging\n' if connected else 'Discharging\n')
            self.error = None

    JACKS = {'3.5': b'3', '4.4': b'4', 'none': b'n'}

    def jack(self):
        """What is plugged into the analog outputs, or None while the model is off."""
        try:
            value = (self.root / 'emu/jack').read_bytes()[:1]
        except OSError:
            return None
        return next((name for name, mark in self.JACKS.items() if mark == value), None)

    def set_jack(self, state):
        """'3.5', '4.4', 'none', or 'off' to remove the model.

        Stock polls three times a second and debounces about a second."""
        path = self.root / 'emu/jack'
        if state == 'off':
            path.unlink(missing_ok=True)
            return
        if state not in self.JACKS:
            raise ValueError('Expected jack 3.5, 4.4, none or off')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('r+b' if path.exists() else 'wb') as marker:     # no empty-file interval
            marker.write(self.JACKS[state])

    def set_boot_keys(self, keys):
        """Keys held from the next power-on until that boot ends (one boot only)."""
        if not isinstance(keys, list) or any(type(key) is not str for key in keys):
            raise ValueError('Expected a list of key names')
        gpio.arm(self.root, keys)

    def _listener(self):
        """Netlink port of the player's uevent socket: its PID in its OWN PID namespace."""
        pid = port = self._pid()
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('NSpid:'):
                port = int(line.split()[-1])     # differs from pid in a stock-init guest
        if not any(row.split()[1:3] == ['15', str(port)] for row in
                   Path('/proc/net/netlink').read_text().splitlines()[1:]):
            raise ValueError('SD listener is not ready')
        return port

    def _event(self, action):
        pid = self._listener()
        payload = (f'{action}@/devices/platform/mmc/mmcblk0\0ACTION={action}\0'
                   'SUBSYSTEM=block\0DEVNAME=mmcblk0\0').encode()
        with socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 15) as channel:
            channel.bind((0, 0))
            channel.sendto(payload, (pid, 0))

    def _mounted(self, path):
        return subprocess.run(['mountpoint', '-q', str(path)]).returncode == 0

    def set_sd(self, inserted, force=False):
        """force (removal only): pull the card even while a track is open, as a hand would."""
        if type(inserted) is not bool or type(force) is not bool:
            raise ValueError('Expected inserted boolean')
        with self.device.lock, self.lock:
            if self.device.transition or self.operation:
                raise ValueError('Wait for the current operation')
            self._profile()
            if self.snapshot()['sd_inserted'] == inserted:
                return
            if not self.snapshot()['sd_available']:
                raise ValueError('No emulated SD card')
            self.operation = 'Inserting SD card…' if inserted else 'Ejecting SD card…'
            self.error = None
            threading.Thread(target=self._sd, args=(inserted, force), daemon=True).start()

    def _sd(self, inserted, force=False):
        try:
            # Power transitions use this same lock at request time. The operation
            # marker also blocks HTTP buttons until the card state has settled.
            with self.device.lock:
                active = [self.root / ('dev/' + n) for n in card.NODES]
                saved = [self.root / ('emu/sd-' + p.name) for p in active]
                self.root.joinpath('emu').mkdir(exist_ok=True)
                source, target = (saved, active) if inserted else (active, saved)
                identities = set()
                for old, new in zip(source, target):
                    info = old.lstat()
                    if not stat.S_ISBLK(info.st_mode):
                        raise ValueError('SD node does not belong to an emulated block device')
                    if new.exists() or new.is_symlink():
                        raise ValueError('SD target node already exists')
                    identities.add(info.st_rdev)
                card_image = card.image(self.root)
                if inserted:
                    # mount/umount can mark a loop AUTOCLEAR. Once the last
                    # mount disappears, its number can be reused by another
                    # container. Reattach THIS image and recreate its aliases;
                    # never operate on the device numbers stored at ejection.
                    _, whole, part = card.attach(card_image)
                    card.make_nodes(self.root / 'emu', whole, part, names=[node.name for node in saved])
                elif not identities <= card.devices(card_image):
                    raise ValueError('SD node does not belong to this emulated image')
                if self.device.running():
                    self._listener()
                if inserted:
                    # The stock add handler owns the first mount. Pre-mounting
                    # here races its cleanup of the mountpoint directory.
                    self._move_nodes(saved, active)
                    subprocess.run(['bash', '-lc', 'source /repo/emulator/scripts/lib.sh; sd_probe'],
                                   env={**os.environ, 'ROOTFS': str(self.root)}, check=True, timeout=15)
                    if self.device.running():
                        self._event('add')
                        self._wait_mount(True)
                    self._mount_sd()
                else:
                    # Stock cleanup uses rm -rf even after a failed umount.
                    # First unmount our image WITHOUT force/lazy flags; if busy,
                    # fail before notifying stock firmware. Never expose mounted
                    # media to that cleanup path. A forced removal detaches a busy
                    # mount instead (see _unmount_sd): the path is empty for stock.
                    self._unmount_sd(identities, force)
                    if self.device.running():
                        self._event('remove')
                    self._move_nodes(active, saved)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.error = str(exc)
        finally:
            self.operation = None

    def _mount_sd(self):
        subprocess.run(['bash', '-lc', 'source /repo/emulator/scripts/lib.sh; sd_mount'],
                       env={**os.environ, 'ROOTFS': str(self.root)}, check=True, timeout=30)

    def _unmount_sd(self, identities, force=False):
        for mount in (self.root / 'tmp/sdcard', Path('/tmp/sdcard')):
            if self._mounted(mount):
                if mount.stat().st_dev not in identities:
                    raise ValueError('Mount does not belong to this emulated SD card')
                try:
                    subprocess.run(['umount', str(mount)], check=True, timeout=5, capture_output=True)
                except subprocess.CalledProcessError as exc:
                    if not force:
                        raise ValueError('SD card is busy; stop playback and retry') from exc
                    # A pulled card: the mount leaves the namespace at once, so stock's
                    # cleanup only finds an empty directory. A file the player still holds
                    # stays readable until it closes it; real hardware returns I/O errors.
                    subprocess.run(['umount', '-l', str(mount)], check=True, timeout=5, capture_output=True)

    def _wait_mount(self, mounted):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._mounted(self.root / 'tmp/sdcard') == mounted:
                return
            time.sleep(.1)
        raise ValueError('Player did not finish mounting' if mounted else 'SD card is busy; stop playback and retry')

    @staticmethod
    def _move_nodes(source, target):
        moved = []
        try:
            for old, new in zip(source, target):
                old.rename(new)
                moved.append((old, new))
        except OSError:
            for old, new in reversed(moved):
                new.rename(old)
            raise
