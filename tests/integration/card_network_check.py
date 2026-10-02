"""A card like the player's, forced removal, emulated links and Reset all (V2.57).

CI_SCENARIO=card-network on a disposable volume. Runs its own setup: a 30.9 GiB
partitioned exFAT card (sparse), an 83 MiB /usr/data, an emulated wlan0, and a
stock-init boot. Reset all is the stock factory reset: disposable guests only.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from controller.fiio_link import Client
from emulator.runtime import card, machine, network
from emulator.runtime.boot_ready import ready
from emulator.runtime.keys import Device
from emulator.runtime.peripherals import Peripherals
from tests.integration.profile import require_acceptance

ROOT = Path('/work/rootfs')
WORK = Path('/work')
SCRIPTS = '/repo/emulator/scripts'
CARD = ROOT / 'tmp/sdcard'
CARD_MB = 31642                                     # 30.9 GiB, the player's card
TRACK = 'Card Check/Long tone.wav'


def script(name, *args, **environment):
    subprocess.run(['bash', f'{SCRIPTS}/{name}', *args], check=True, env={**os.environ, **environment},
                   stdout=subprocess.DEVNULL)


def shell(command):
    return subprocess.run(['bash', '-c', f'source {SCRIPTS}/lib.sh; {command}'], check=True, text=True,
                          capture_output=True).stdout


def wait(read, predicate, label, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f'{label}: {value!r}')
        time.sleep(.25)


def settle(controls, timeout=40):
    wait(lambda: controls.operation, lambda operation: operation is None, 'card operation did not finish', timeout)


def console():
    return (WORK / 'console.log').read_bytes()


def digests():
    return {str(path.relative_to(CARD)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(CARD.rglob('*')) if path.is_file()}


def held(controls):
    """Card files the player has open, as the container sees them."""
    result = []
    for descriptor in Path(f'/proc/{controls._pid()}/fd').iterdir():
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target.startswith(str(CARD) + '/'):
            result.append(target)
    return result


def send_local(message):
    """What the stock UI itself sends: one frame on the guest's `player` queue."""
    code = ('import ctypes, os, sys\n'
            'runtime = ctypes.CDLL("librt.so.1", use_errno=True)\n'
            'queue = runtime.mq_open(b"/player", os.O_WRONLY)\n'
            'frame = sys.argv[1].encode()\n'
            'sys.exit(0 if queue >= 0 and runtime.mq_send(queue, frame, len(frame), 0) == 0 else 1)\n')
    subprocess.run(['nsenter', '--target', str(machine.init_pid(ROOT)), '--ipc', 'python3', '-c', code,
                    message.decode()], check=True)


def check_card():
    assert card.image(ROOT).stat().st_size == CARD_MB << 20
    assert card.image(ROOT).stat().st_blocks * 512 < 256 << 20, 'the big card must stay sparse'
    assert card.partitioned(card.image(ROOT))
    whole, part = ((ROOT / 'dev' / name).stat().st_rdev for name in card.NODES)
    assert whole != part, 'whole card and partition must be different devices'
    assert shell('findmnt -n -o FSTYPE "$ROOTFS/tmp/sdcard"').strip() == 'exfat'
    size = os.statvfs(CARD)
    assert size.f_blocks * size.f_frsize > 30 << 30, size
    names = sorted(path.name for path in CARD.rglob('*.wav'))
    assert any('Проверка' in name for name in names), names       # UTF-8 long names survived
    # Stock's own enumeration (its LD_LIBRARY_PATH picks the older libblkid) names the partition
    # with an empty cache: nothing has to prime it.
    for cache in (ROOT / 'etc/blkid.tab', ROOT / 'run/blkid/blkid.tab'):
        cache.unlink(missing_ok=True)
    found = shell('guest_run 20 /bin/sh -c "LD_LIBRARY_PATH=/usr/lib:/usr/lib/pulseaudio/ blkid | '
                  'grep /dev/mmcblk0p1"')
    assert 'exfat' in found, found


def check_native_mount():
    assert b'mount to /tmp/sdcard succeeded' in console(), 'stock did not mount the card at start-up'
    assert 'card not mounted by the stock start-up' not in (WORK / 'machine.log').read_text()


def check_forced_removal(device, controls):
    (CARD / TRACK).parent.mkdir()
    subprocess.run(['sox', '-n', '-r', '44100', '-b', '16', '-c', '2', str(CARD / TRACK),
                    'synth', '90', 'sine', '330', 'vol', '0.2'], check=True)
    os.sync()
    before = digests()
    with Client(timeout=8) as client:
        client.handshake()
        client.scan_library()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:                      # a60a/0005 ends a scan
            tag, payload = client.event(timeout=20)
            if tag == 'a60a' and bytes(payload)[-4:] == b'0005':
                break
        titles = wait(lambda: [item['title'] for item in client.tracks()['items']],
                      lambda found: 'Long tone.wav' in found, 'the long track was not indexed', 20)
        client.play_index(titles.index('Long tone.wav'))
        wait(lambda: held(controls), lambda files: files == [str(CARD / TRACK)], 'track is not open', 20)
        # An ordinary removal still refuses while the player holds a file.
        controls.set_sd(False)
        settle(controls)
        assert controls.error and 'busy' in controls.error and controls.snapshot()['sd_inserted']
        started = time.monotonic()
        controls.set_sd(False, force=True)
        settle(controls)
        assert controls.error is None, controls.error
        print(f'Forced removal took {time.monotonic() - started:.1f}s', flush=True)
        assert not controls.snapshot()['sd_inserted'] and not os.path.ismount(CARD)
        assert not os.path.ismount('/tmp/sdcard')
        # Stock reacts to the removal itself: it stops and lets the file go.
        wait(lambda: held(controls), lambda files: not files, 'player kept the pulled file open', 20)
    assert device.running() and ready(device), 'stock programs did not survive the removal'
    assert not CARD.exists() or not any(CARD.iterdir()), 'pulled card still visible to stock'
    controls.set_sd(True)
    settle(controls)
    assert controls.error is None and os.path.ismount(CARD), controls.snapshot()
    # Stock's add handler unmounts and mounts once more; read when the listing has settled.
    after = wait(digests, lambda now: all(now.get(name) == value for name, value in before.items()),
                 'card files changed across a forced removal', 20)
    print('Files stock added after the insertion:', sorted(set(after) - set(before)), flush=True)


def check_links():
    # S43wifi_bcm_init_config found wlan0 and wrote what it writes on the player.
    text = (ROOT / 'usr/data/wpa_supplicant.conf').read_text()
    assert 'ctrl_interface=/var/run/wpa_supplicant' in text and 'update_config=1' in text, text
    assert (ROOT / 'usr/data/macaddr.txt').read_text().strip().startswith('d0:31:10:')
    assert (ROOT / 'sys/class/net/wlan0/operstate').read_text() == 'down\n'
    network.link(ROOT, 'wlan0', state='up', addr='10.203.0.7/24')
    assert (ROOT / 'sys/class/net/wlan0/operstate').read_text() == 'up\n'
    assert (ROOT / 'sys/class/net/wlan0/address').read_text() == 'd0:31:10:a0:b1:c2\n'
    assert 'inet addr:10.203.0.7' in shell('guest_run 10 /bin/busybox ifconfig wlan0')
    network.link(ROOT, 'wlan0', state='down', addr='none')
    assert (ROOT / 'sys/class/net/wlan0/operstate').read_text() == 'down\n'
    for name in ('eth1', 'lo'):                       # the container's own interfaces are off limits
        try:
            network.link(ROOT, name, state='down')
        except ValueError:
            continue
        raise AssertionError(f'{name} must not be editable')
    network.shape(rate='800kbit', delay='60ms')
    assert len(network.status(ROOT)['shaping']) == 2
    network.shape()
    assert network.status(ROOT)['shaping'] == []


def settings():
    with sqlite3.connect(f'file:{ROOT}/usr/data/fiio/db/sysconfig.db?mode=ro', uri=True) as db:
        return db.execute('SELECT LANGUAGE, LOCAL_IMG_ANIM, VOLUME, POWER_SAVE FROM SYSCONFIG').fetchone()


def check_reset_all():
    """Stock factory reset (local 0800): no MCU involved, it needs wpa_supplicant.conf to exist."""
    assert settings()[:2] == (2, 0)
    (ROOT / 'usr/data/fiio/wifi/emu-marker').write_text('removed by Reset all\n')
    boots = machine.state(ROOT)['boots']
    send_local(b'0800000C0003')
    # It ends in stock `reboot`: rcK, then a new power-on.
    wait(lambda: machine.state(ROOT), lambda state: state['boots'] == boots + 1 and state['state'] == 'running',
         'Reset all did not reboot the guest', 90)
    assert b'open /usr/data/wpa_supplicant.conf failed' not in console()
    wait(lambda: (ROOT / 'usr/data/fiio/db/sysconfig.db').exists(), bool, '/usr/data was not mounted again', 30)
    assert settings() == (100, 1, 40, 300), settings()             # stock factory values
    assert 'country=NZL' in (ROOT / 'usr/data/wpa_supplicant.conf').read_text()
    assert not (ROOT / 'usr/data/fiio/wifi/emu-marker').exists()
    wait(lambda: (ROOT / 'usr/data/fiio/db/song.db').exists(), bool, 'stock did not recreate song.db', 60)


def check_isolated(device):
    script('25_power.sh', 'off')
    shell('userdata_mount; ROOTFS="$ROOTFS" python3 -B -m emulator.runtime.settings apply')
    script('25_power.sh', 'on', BOOT_MODE='init', NETWORK='isolated')
    assert network.namespace(ROOT) == 'disc-guest'
    listeners = lambda scope: subprocess.run(  # noqa: E731
        scope + ['ss', '-H', '-lnt'], capture_output=True, text=True).stdout.count(':1210')
    assert listeners([]) == 0, 'an isolated guest must not listen in the container'
    assert shell('guest_run 10 /bin/ls /sys/class/net').split() == []
    # Wi-Fi comes up later: the emulated wlan0 is the guest's only link, and stock serves on it.
    network.link(ROOT, 'wlan0', state='up', addr='192.0.2.2/24', gateway='192.0.2.1', mac='d0:31:10:a0:b1:c2')
    inside = ['ip', 'netns', 'exec', 'disc-guest']
    wait(console, lambda log: b'Interface wlan0: IP Address added' in log, 'stock did not see wlan0 come up', 15)
    wait(lambda: listeners(inside), lambda count: count == 2, 'stock did not bind after the link came up', 40)
    probe = subprocess.run(inside + ['python3', '-B', '-c', 'from controller.fiio_link import Client\n'
                                     'with Client(host="192.0.2.2", timeout=8) as c:\n    c.handshake()'],
                           capture_output=True, text=True, cwd='/repo')
    assert probe.returncode == 0, probe.stderr
    script('25_power.sh', 'off')
    script('20_boot.sh', BOOT_MODE='direct', NETWORK='shared')     # back to the container's network
    assert network.namespace(ROOT) is None and device.running()
    assert listeners([]) == 2


def main():
    require_acceptance('card-network')
    script('10_setup_env.sh', SDCARD_MB=str(CARD_MB), SDCARD_FS='exfat', SDCARD_PARTITION='1', USERDATA_MB='83')
    check_card()
    device = Device(ROOT)
    controls = Peripherals(device)
    script('20_boot.sh', BOOT_MODE='init', WLAN0='1', WLAN0_MAC='d0:31:10:a0:b1:c2')
    check_native_mount()
    check_forced_removal(device, controls)
    check_links()
    check_reset_all()
    check_isolated(device)
    script('99_stop.sh')
    print(json.dumps({'card_network': 'passed'}))


if __name__ == '__main__':
    main()
