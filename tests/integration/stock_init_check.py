"""Stock-init boot, power events and power-on keys on a disposable V2.57 guest.

Needs a guest prepared with USERDATA_MB (ci/integration.sh, CI_SCENARIO=stock-init).
Adds two generated init hooks and a static pin probe to the disposable rootfs
(the static device probe comes from setup); no firmware memory writes and no
stock file is edited.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from emulator.runtime import gpio, machine
from emulator.runtime.boot_ready import ready
from emulator.runtime.keys import Buttons, Device
from tests.integration.profile import version as firmware_version

ROOT = Path('/work/rootfs')
WORK = Path('/work')
SCRIPTS = '/repo/emulator/scripts'
LOG = ROOT / 'usr/data/emu-hooks.log'
EARLY = '''#!/bin/sh
case "$1" in
  start)
    mkdir -p /run/emu-check
    /emu/pinprobe > /run/emu-check/pins
    grep ' /usr/data ' /proc/mounts > /run/emu-check/userdata
    echo "$PATH" > /run/emu-check/path
    echo "S22 start" >> /usr/data/emu-hooks.log ;;
  stop) echo "S22 stop" >> /usr/data/emu-hooks.log ;;
esac
'''
LATE = '''#!/bin/sh
case "$1" in
  start)
    echo "S99 start" >> /usr/data/emu-hooks.log
    start-stop-daemon -S -b -m -p /run/emu-check/daemon.pid -x /bin/sleep -- 100000 ;;
  stop)
    start-stop-daemon -K -p /run/emu-check/daemon.pid -x /bin/sleep
    echo "S99 stop $?" >> /usr/data/emu-hooks.log ;;
esac
'''


def run(script, **environment):
    return subprocess.run(['bash', '-c', f'source {SCRIPTS}/lib.sh; {script}'], check=True, text=True,
                          capture_output=True, env={**os.environ, **environment}).stdout


def guest(command):
    return run('guest_run 20 /bin/sh -c "$COMMAND"', COMMAND=command)


def power(*args, **environment):
    subprocess.run(['bash', f'{SCRIPTS}/25_power.sh', *args], check=True,
                   env={**os.environ, 'BOOT_MODE': 'init', **environment})


def wait(read, predicate, label, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f'{label}: {value!r}')
        time.sleep(.25)


def stock(device):
    """Container PIDs of the stock pair, by the names the watch loop itself uses.

    While the watch loop replaces the pair, a dying and a starting process can carry
    the same name for a moment: that is "not settled" (an empty answer), not an error.
    """
    found = {}
    for pid in device.processes():
        try:
            name = Path(f'/proc/{pid}/comm').read_text().strip()
        except OSError:
            continue
        if name in ('mq_ui', 'mq_player'):
            if name in found:
                return {}
            found[name] = pid
    return found


def started(pid):
    return int(Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()[19])


def parent(pid):
    ppid = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()[1]
    return Path(f'/proc/{ppid}/comm').read_text().strip()


def card_mounted():
    wait(lambda: run('mountpoint -q "$ROOTFS/tmp/sdcard" && echo yes || echo no').strip(),
         lambda value: value == 'yes', 'card was not mounted for the restarted UI', 30)


def hooks():
    return LOG.read_text().split('\n')[:-1] if LOG.exists() else []


def prepare():
    subprocess.run(['mipsel-linux-gnu-gcc', '-static', '-nostdlib', '-msoft-float', '-mabi=32',
                    '-march=mips32r2', '-fno-pic', '-mno-abicalls', '-O1', '-o', str(ROOT / 'emu/pinprobe'),
                    '/repo/emulator/tests/guest/pinprobe.c'], check=True)
    for name, text in (('S22emu-check', EARLY), ('S99emu-check', LATE)):
        hook = ROOT / 'etc/init.d' / name
        hook.write_text(text)
        hook.chmod(0o755)


def check_pins_without_boot(device):
    """A static program has no preload shim: it must see the raw pin word."""
    assert guest('/emu/pinprobe').strip() == '0xF6EFE127'
    gpio.hold(ROOT, ['volume_down'])
    assert guest('/emu/pinprobe').strip() == '0xF6EFA127'
    gpio.release(ROOT)
    buttons = Buttons(ROOT, device, sleep=lambda _: None)
    device.running = lambda: True                       # only the pin level is under test here
    buttons.gesture('volume_up', 'hold')
    assert guest('/emu/pinprobe').strip() == '0xF6EFC127'
    buttons.gesture('volume_up', 'end')
    assert guest('/emu/pinprobe').strip() == '0xF6EFE127'
    del device.running


def check_boot(device):
    power('on', BOOT_KEYS='volume_up,play')
    state = machine.state(ROOT)
    assert state['state'] == 'running' and state['boots'] == 1, state
    # Keys were down before the first guest instruction and are let go once the UI is up.
    assert (ROOT / 'run/emu-check/pins').read_text().strip() == '0xF6EF4127'
    assert guest('/emu/pinprobe').strip() == '0xF6EFE127'
    # S21mount_ubifs ran before the S22 hook and mounted the size-limited image.
    assert (ROOT / 'run/emu-check/userdata').read_text().split()[:3] == ['/dev/ubi1_0', '/usr/data', 'ext4']
    # rcS sources /etc/profile, so hooks and fiio_init.sh search /sbin before /usr/bin.
    assert (ROOT / 'run/emu-check/path').read_text().strip() == '/bin:/sbin:/usr/bin:/usr/sbin'
    assert hooks() == ['S22 start', 'S99 start'], hooks()
    pair = stock(device)
    assert set(pair) == {'mq_ui', 'mq_player'}, pair
    assert started(pair['mq_ui']) < started(pair['mq_player'])
    # Started by stock's fiio_init.sh; its first shell exits once the watch loop runs.
    assert parent(pair['mq_ui']) in ('fiio_init.sh', 'init')
    wait(lambda: guest('pgrep -x fiio_init.sh | wc -l').strip(), lambda count: count == '1',
         'stock watch loop is not running', 20)
    view = guest('cat /proc/1/comm; hostname; pgrep -x mq_ui | wc -l; pgrep -x mq_player | wc -l; '
                 'grep -c "^tmpfs /run tmpfs" /proc/mounts; grep -c "^tmpfs /tmp tmpfs" /proc/mounts').split()
    assert view == ['init', 'ingenic', '1', '1', '1', '1'], view
    # The caller's argv[0] reaches the program (binfmt P flag): BusyBox picks its applet from it.
    assert guest('exec -a echo /bin/busybox argv0-kept').strip() == 'argv0-kept'
    assert Path(f'/proc/{pair["mq_ui"]}/cmdline').read_bytes().split(b'\0')[2] == b'mq_ui'   # as fiio_init.sh started it
    # /proc/<pid>/exe names the guest program: BusyBox start-stop-daemon -x works as on the player.
    daemon = guest('cat /run/emu-check/daemon.pid').strip()
    assert guest(f'readlink /proc/{daemon}/exe').strip() == '/bin/sleep'
    again = guest('start-stop-daemon -S -b -m -p /run/emu-check/daemon.pid -x /bin/sleep -- 100000; echo $?')
    assert again.split()[-1] == '1' and 'already running' in again, again
    assert guest('ps | grep -c "[s]leep 100000"').strip() == '1'
    return pair


def check_static_devices():
    """A static program loads no shim: the rebuilt qemu answers its device ioctls (#54)."""
    marker, live = ROOT / 'emu/qemu-devices', ROOT / 'emu/fb-live'
    assert marker.read_text() == '1'
    shown = live.read_bytes()
    lines = guest('/emu/devprobe').splitlines()
    assert lines[0] == 'fb: 360x360 virtual 360x1080 bpp 32 offsets r16 g8 b0 a24', lines
    assert lines[1] == 'fix: ingenicfb smem 1555200 line 1440 visual 2', lines
    assert 'pan: yoffset 360' in lines and 'touch name: cst816t' in lines and 'keys name: x2000_key' in lines, lines
    assert 'abs 0: 0..359' in lines and 'keys: 0x14a' in lines, lines
    assert live.read_bytes() == b'\x01'                 # the probe's pan reached the viewer's marker
    live.write_bytes(shown)
    marker.write_text('0')                              # QEMU_DEVICES=0: the kernel's answer, live
    try:
        failed = run('guest_run 20 /emu/devprobe || echo "rc=$?"')
        assert failed.splitlines() == ['vinfo: Inappropriate ioctl for device', 'rc=2'], failed
    finally:
        marker.write_text('1')


def check_watch_loop(device, pair):
    os.kill(pair['mq_ui'], signal.SIGKILL)
    killed = time.monotonic()
    fresh = wait(lambda: stock(device), lambda now: set(now) == {'mq_ui', 'mq_player'} and
                 not set(now.values()) & set(pair.values()), 'stock watch loop did not restart the pair', 20)
    print(f'Watch loop restarted both programs {time.monotonic() - killed:.1f}s after mq_ui died')
    assert started(fresh['mq_ui']) < started(fresh['mq_player'])
    assert parent(fresh['mq_ui']) == parent(fresh['mq_player']) == 'fiio_init.sh'
    assert 'mq_ui Restarting' in (ROOT / 'usr/data/fiio/log/process_failed.txt').read_text()
    subprocess.run(['bash', f'{SCRIPTS}/16_network.sh', 'wait'], check=True, env={**os.environ, 'NETWORK_WAIT': '60'})
    wait(lambda: ready(device), bool, 'restarted pair did not open its input devices', 60)
    card_mounted()


def uptime():
    return float(guest('cat /proc/uptime').split()[0])


def check_reboot():
    guest('echo ram > /run/emu-check/volatile; echo ram > /tmp/volatile; echo flash > /usr/data/kept; '
          'echo card > /tmp/sdcard/kept.txt')
    # The guest's clocks count from its power-on, not from the Docker VM's boot.
    before = uptime()
    assert before < 300, f'/proc/uptime is not this guest\'s: {before}'
    assert float(Path('/proc/uptime').read_text().split()[0]) > before + 60   # the container's is older
    started = time.monotonic()
    power('reboot')
    state = machine.state(ROOT)
    assert state['state'] == 'running' and state['boots'] == 2, state
    # rcK ran the hooks' stop in reverse order, then rcS started them again.
    assert hooks() == ['S22 start', 'S99 start', 'S99 stop 0', 'S22 stop', 'S22 start', 'S99 start'], hooks()
    assert not (ROOT / 'run/emu-check/volatile').exists() and not (ROOT / 'tmp/volatile').exists()
    assert (ROOT / 'usr/data/kept').read_text() == 'flash\n'
    card_mounted()
    assert (ROOT / 'tmp/sdcard/kept.txt').read_text() == 'card\n'
    assert guest('cat /proc/1/comm; pgrep -x mq_ui | wc -l').split() == ['init', '1']
    after = uptime()
    assert after < time.monotonic() - started + 5, f'uptime did not restart with the reboot: {before} -> {after}'


def check_power_cut(device):
    before = hooks()
    guest('echo durable > /usr/data/durable; sync; echo lost > /usr/data/volatile')
    power('cut', '--unsynced')
    state = machine.state(ROOT)
    assert state['state'] == 'off' and state['reason'] == 'power cut; unsynced data dropped', state
    assert not device.processes() and not machine.active(ROOT)
    run('userdata_mount')
    assert hooks() == before, 'a power cut must not run rcK'
    assert (ROOT / 'usr/data/durable').read_text() == 'durable\n'
    assert not (ROOT / 'usr/data/volatile').exists(), 'unsynced write survived the cut'
    power('on')                                          # cold start: same /usr/data and card
    assert machine.state(ROOT)['boots'] == 1
    assert hooks() == before + ['S22 start', 'S99 start']
    assert (ROOT / 'usr/data/kept').read_text() == 'flash\n'
    assert (ROOT / 'tmp/sdcard/kept.txt').read_text() == 'card\n'
    assert (ROOT / 'run/emu-check/pins').read_text().strip() == '0xF6EFE127'


def check_guest_poweroff(device):
    """Stock idle power-off is `poweroff -f`: served without a viewer, and without rcK."""
    before = hooks()
    assert guest('poweroff -f; echo requested').strip() == 'requested'   # the shared kernel never reboots
    wait(lambda: machine.state(ROOT), lambda value: value['state'] == 'off', 'guest poweroff -f was not served', 30)
    assert machine.state(ROOT)['reason'] == 'guest poweroff -f'
    wait(lambda: machine.active(ROOT), lambda value: not value, 'supervisor did not exit', 10)
    assert not device.processes()
    assert (ROOT / 'emu/power-request').read_bytes()[:1] == b'0'
    run('userdata_mount')
    assert hooks() == before


def check_foreign_ui(device):
    """A boot layer starts its ui package through /sbin/mq_ui: the stock name, another file."""
    run('userdata_mount')
    foreign = ROOT / 'usr/data/emu-ui/mq_ui'
    foreign.parent.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'usr/bin/mq_ui', foreign)
    foreign.chmod(0o755)
    wrapper = ROOT / 'sbin/mq_ui'                      # fiio_init.sh finds it first on its PATH
    wrapper.write_text('#!/bin/sh\nexec /usr/data/emu-ui/mq_ui "$@"\n')
    wrapper.chmod(0o755)
    try:
        power('on', BOOT_KEYS='play')                  # 20_boot.sh waits for readiness: this UI's
        pair = stock(device)
        assert Path(f'/proc/{pair["mq_ui"]}/cmdline').read_bytes().split(b'\0')[1] == b'/usr/data/emu-ui/mq_ui'
        assert guest('/emu/pinprobe').strip() == '0xF6EFE127', 'keys were not let go'
        card_mounted()
        # A restart in mid-run (stock's loop, a boot layer restarting its UI) is found the same way.
        os.kill(pair['mq_ui'], signal.SIGKILL)
        fresh = wait(lambda: stock(device), lambda now: set(now) == {'mq_ui', 'mq_player'} and
                     not set(now.values()) & set(pair.values()), 'the pair was not restarted', 20)
        assert Path(f'/proc/{fresh["mq_ui"]}/cmdline').read_bytes().split(b'\0')[1] == b'/usr/data/emu-ui/mq_ui'
        wait(lambda: ready(device), bool, 'restarted foreign UI never counted as ready', 60)
        card_mounted()
    finally:
        power('off')
        run('userdata_mount')
        wrapper.unlink()
        shutil.rmtree(foreign.parent)


def check_clean_poweroff_and_direct_boot(device):
    power('on')
    before = hooks()
    power('off')
    assert machine.state(ROOT)['state'] == 'off' and not device.processes()
    run('userdata_mount')
    assert hooks() == before + ['S99 stop 0', 'S22 stop'], hooks()
    # The direct boot still works on the same volume, with the container's own /proc again.
    subprocess.run(['bash', f'{SCRIPTS}/20_boot.sh'], check=True, env={**os.environ, 'BOOT_MODE': 'direct'})
    assert (ROOT / 'proc/self/stat').exists() and not machine.active(ROOT)
    pair = stock(device)
    assert set(pair) == {'mq_ui', 'mq_player'}
    assert Path(f'/proc/{pair["mq_ui"]}/ns/pid').readlink() == Path('/proc/self/ns/pid').readlink()
    assert 'ext4' in run('findmnt -n -o FSTYPE "$ROOTFS/usr/data"')
    assert hooks() == before + ['S99 stop 0', 'S22 stop'], 'direct boot must not run init hooks'


def main():
    assert os.environ.get('CI_DISPOSABLE') == '1', 'disposable guest only'
    assert firmware_version() == '2.57'
    assert (WORK / 'userdata.img').stat().st_size == 83 << 20
    device = Device(ROOT)
    prepare()
    check_pins_without_boot(device)
    pair = check_boot(device)
    check_static_devices()
    check_watch_loop(device, pair)
    check_reboot()
    check_power_cut(device)
    check_guest_poweroff(device)
    check_foreign_ui(device)
    check_clean_poweroff_and_direct_boot(device)
    subprocess.run(['bash', f'{SCRIPTS}/99_stop.sh'], check=True)
    print(json.dumps({'stock_init': 'passed', 'machine': machine.state(ROOT)}))


if __name__ == '__main__':
    main()
