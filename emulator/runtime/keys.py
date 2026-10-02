"""Physical gesture injection and guest-only power lifecycle (no firmware memory writes)."""
import os
from pathlib import Path
import signal
import struct
import subprocess
import threading
import time

from emulator.runtime import gpio, machine
from emulator.runtime.audio import reset_output

BRIGHTNESS = 'sys/bus/platform/drivers/pwm-backlight/backlight/backlight/backlight/brightness'
CODES = {
    'volume_up': {'single': 0xfb, 'double': 0x10a, 'hold': 0x107},
    'volume_down': {'single': 0xfc, 'double': 0x10b, 'hold': 0x106},
    'play_pause': {'single': 0xfa, 'double': 0x10d, 'hold': 0x10c},
    'power': {'single': 0x103},
}
SAFE_CODES = {v for gestures in CODES.values() for v in gestures.values()} | {0x109}


class Device:
    def __init__(self, rootfs, boot_script=None):
        self.root = Path(rootfs).resolve()
        self.boot_script = boot_script or Path(__file__).resolve().parents[1] / 'scripts/20_boot.sh'
        self.lock = threading.RLock()
        self.transition = None
        self.error = None

    def processes(self):
        """Only processes chrooted into THIS guest, never host/container processes."""
        result = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                if (entry / 'root').resolve(strict=True) != self.root:
                    continue
                if (entry / 'stat').read_text().split(') ', 1)[1][0] == 'Z':
                    continue
                result.append(int(entry.name))
            except (OSError, ValueError):
                continue
        return result

    def running(self):
        for pid in self.processes():
            try:
                args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                if b'/usr/bin/mq_player' in args:
                    return True
            except OSError:
                pass
        return False

    def screen_on(self):
        try:
            data = (self.root / BRIGHTNESS).read_bytes().split(b'\0', 1)[0].strip()
            return int(data) > 0
        except (OSError, ValueError):
            return True

    def status(self):
        running = self.running()
        return dict(running=running, screen_on=running and self.screen_on(),
                    transition=self.transition, error=self.error)

    def gains(self):
        result = []
        for channel in ('left', 'right'):
            try:
                attenuation = (self.root / f'emu/dac-{channel}').read_bytes()[0]
                result.append(0 if attenuation == 255 else 10 ** (-attenuation / 40))
            except (OSError, IndexError):
                result.append(1)
        return result

    def toggle_power(self):
        with self.lock:
            if self.transition:
                raise ValueError('Power transition already in progress')
            self.transition = 'stopping' if self.processes() else 'starting'
            self.error = None
            threading.Thread(target=self._power, daemon=True).start()

    def service_requests(self):
        """Honor stock idle-poweroff without allowing its reboot syscall to escape."""
        with self.lock:
            path = self.root / 'emu/power-request'
            try:
                # A stock-init guest's own PID 1 serves the request (guest_init.py).
                if self.transition or machine.active(self.root) or path.read_bytes()[:1] != b'1':
                    return
                with path.open('r+b') as marker:
                    marker.write(b'0')
            except FileNotFoundError:
                return
            if self.processes():
                self.transition = 'stopping'
                self.error = None
                threading.Thread(target=self._power, daemon=True).start()

    def _power(self):
        try:
            if self.transition == 'starting':
                log = self.root.parent / 'power-boot.log'
                with log.open('ab') as output:
                    subprocess.run(['bash', str(self.boot_script)], check=True,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   env={**os.environ, 'ROOTFS': str(self.root)}, timeout=180)
                if not self.running():
                    raise RuntimeError('Guest did not start; inspect power-boot.log')
            else:
                machine.cut(self.root)  # stock-init guest: power loss, then its mounts; else no-op
                # Recheck chroot membership immediately before every signal (PID reuse).
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    for pid in self.processes():
                        try:
                            if Path(f'/proc/{pid}/root').resolve(strict=True) == self.root:
                                os.kill(pid, sig)
                        except (OSError, ValueError):
                            pass
                    time.sleep(.5)
                if self.processes():
                    raise RuntimeError('Some guest processes could not be stopped')
                reset_output(self.root)     # a killed player never closed its stream
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.transition = None


class Buttons:
    def __init__(self, rootfs, device, sleep=time.sleep, clock=time.monotonic):
        self.root = Path(rootfs)
        self.device = device
        self.sleep, self.clock = sleep, clock
        self.lock = threading.RLock()
        self.holds = {}
        self._repeated = set()

    def reset(self):
        """Viewer restart must not leave a GPIO held by a vanished client."""
        with self.lock:
            self.holds.clear()
            self._repeated.clear()
            self._levels()

    def _levels(self):
        # Fixed-width overwrites: no empty-file interval while the guest reads GPIOs.
        # Power-on holds stay low underneath the viewer's own pointer holds.
        gpio.apply(self.root, self.holds)

    def _event(self, code, value):
        with (self.root / 'dev/input/event0').open('ab') as f:
            f.write(struct.pack('<iiHHi', 0, 0, 1, code, value)
                    + struct.pack('<iiHHi', 0, 0, 0, 0, 0))

    def pulse(self, code):
        if code not in SAFE_CODES:
            raise ValueError('Unsupported/unsafe key code')
        with self.lock:
            self._event(code, 1)
            self.sleep(.12)
            self._event(code, 0)

    def gesture(self, name, gesture):
        if name not in CODES or gesture not in ('single', 'double', 'hold', 'end', 'cancel'):
            raise ValueError('Unknown button or gesture')
        with self.lock:
            if gesture in ('end', 'cancel'):
                self._end(name)
                return
            if self.device.transition:
                raise ValueError('Wait for the power transition')
            if name == 'power' and (gesture == 'hold' or not self.device.running()):
                self.cancel()
                self.device.toggle_power()
                return
            if not self.device.running():
                raise ValueError('Player is off; press Power to start it')
            code = CODES[name].get(gesture)
            if code is None:
                raise ValueError('Gesture is not supported for this button')
            if gesture == 'hold' and name.startswith('volume_'):
                self.holds[name] = self.clock() + 1.5  # lost pointer/tab/network failsafe
                self._levels()
                self._event(code, 2 if name in self._repeated else 1)
                self._repeated.add(name)
            else:
                self.pulse(code)

    def _end(self, name):
        if name in self.holds:
            self._event(CODES[name]['hold'], 0)
            # Allow the reader to consume the preceding held event before GPIO goes high.
            self.sleep(.18)
            del self.holds[name]
            self._repeated.discard(name)
            self._levels()

    def cancel(self):
        with self.lock:
            for name in list(self.holds):
                self._end(name)

    def expire(self):
        with self.lock:
            for name, deadline in list(self.holds.items()):
                if self.clock() >= deadline:
                    self._end(name)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stop'])
    parser.parse_args()
    device = Device(os.environ.get('ROOTFS', '/work/rootfs'))
    device.transition = 'stopping'
    device._power()
    if device.error:
        parser.exit(1, device.error + '\n')
