"""Guest environment presets on a disposable V2.57 guest (CI_SCENARIO=environment).

Starts from an extracted, not yet set up rootfs: the factory settings profile
must see the database exactly as stock created it.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

from emulator.runtime import battery, power_watch
from emulator.runtime.keys import Device
from emulator.runtime.peripherals import Peripherals
from research.diagnostics.player_memory import PlayerMemory
from tests.integration.profile import diagnostic, require_acceptance, version as firmware_version

ROOT = Path('/work/rootfs')
WORK = Path('/work')
SCRIPTS = '/repo/emulator/scripts'
SERIAL = '25090112345678'
PRESETS = ('BATTERY_PROFILE', 'BATTERY_CAPACITY', 'BATTERY_VOLTAGE_UV', 'BATTERY_TEMP', 'DEVICE_SN',
           'USB_POWER', 'SETTINGS_PROFILE', 'SETTINGS', 'POWER_WATCH', 'GUEST_TTL')


def script(name, **environment):
    clean = {key: value for key, value in os.environ.items() if key not in PRESETS}
    subprocess.run(['bash', f'{SCRIPTS}/{name}'], check=True, env={**clean, **environment},
                   stdout=subprocess.DEVNULL)


def settings():
    with sqlite3.connect(f'file:{ROOT}/usr/data/fiio/db/sysconfig.db?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return dict(db.execute('SELECT * FROM SYSCONFIG').fetchone())


def usb_detected():
    with PlayerMemory(ROOT, firmware_version()) as memory:
        return memory.word(*diagnostic('power.usb_detected'))


def wait(read, predicate, label, timeout):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f'{label}: {value!r}')
        time.sleep(.5)


def main():
    require_acceptance('environment')
    device = Device(ROOT)

    # 1. "factory": what a player holds after a firmware install; nothing is preset.
    script('10_setup_env.sh', SETTINGS_PROFILE='factory')
    stock = settings()
    assert stock['LANGUAGE'] == 100 and stock['LOCAL_IMG_ANIM'] == 1, stock
    print('Stock first-boot SYSCONFIG:', json.dumps(stock), flush=True)
    assert not (ROOT / 'usr/data/fiio/sn.txt').exists()
    assert battery.profile_of(ROOT) == 'legacy'

    # 2. Presets chosen at setup.
    script('10_setup_env.sh', BATTERY_PROFILE='device', BATTERY_CAPACITY='64', BATTERY_VOLTAGE_UV='3876000',
           BATTERY_TEMP='301', DEVICE_SN=SERIAL, USB_POWER='1', SETTINGS='MEMORY_PLAY=1')
    row = settings()
    assert (row['LANGUAGE'], row['LOCAL_IMG_ANIM'], row['BATTERY'], row['MEMORY_PLAY']) == (2, 0, 100, 1), row
    assert {k: v for k, v in row.items() if k not in ('LANGUAGE', 'LOCAL_IMG_ANIM', 'BATTERY', 'MEMORY_PLAY')} == \
        {k: v for k, v in stock.items() if k not in ('LANGUAGE', 'LOCAL_IMG_ANIM', 'BATTERY', 'MEMORY_PLAY')}
    gauge = battery.snapshot(ROOT)
    assert gauge == dict(profile='device', capacity='64', current_now='0', cycle_count='0', health='Good',
                         present='1', technology='Li-ion', temp='301', type='Mains', voltage_now='3876000'), gauge
    assert (ROOT / 'usr/data/fiio/sn.txt').read_text() == SERIAL + '\n'

    # 3. Unlimited lifetime, headless power service, cable present from the first instruction.
    script('20_boot.sh', GUEST_TTL='0', POWER_WATCH='1')
    limits = [Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[:2] for pid in device.processes()]
    assert [b'timeout', b'0'] in limits, limits
    wait(usb_detected, lambda value: value == 1, 'stock did not detect the preset cable', 30)
    log = (WORK / 'mq_player.log').read_bytes()
    assert b'sn_nb.c: 35> open file failed' not in log, 'stock could not read sn.txt'
    assert power_watch.running_pid(ROOT)

    # 4. The cable state is stored: a later boot without the preset keeps it.
    script('20_boot.sh', GUEST_TTL='0', POWER_WATCH='1')
    assert Peripherals(device).snapshot()['usb_connected']
    wait(usb_detected, lambda value: value == 1, 'stored cable state was lost', 30)

    # 5. Low battery, unplugged: stock counts down and powers off; the watcher serves it.
    Peripherals(device).set_usb(False)
    battery.update(ROOT, capacity=0)
    started = time.monotonic()
    wait(device.processes, lambda pids: not pids, 'guest did not power off on an empty battery', 150)
    print(f'Empty battery powered the guest off after {time.monotonic() - started:.0f}s', flush=True)
    assert b'reboot blocked; guest shutdown requested' in (ROOT / 'fbshim.log').read_bytes()
    wait(lambda: power_watch.read(ROOT).get('served'), lambda served: served == 1, 'request not recorded', 10)
    assert 'Power request: completed' in (WORK / 'power-watch.log').read_text()
    assert (ROOT / 'emu/power-request').read_bytes()[:1] == b'0'

    # 6. Charged again: an explicit boot brings it back; the watcher is replaced, not duplicated.
    battery.update(ROOT, capacity=80)
    script('20_boot.sh', GUEST_TTL='0', POWER_WATCH='1')
    assert device.running() and power_watch.running_pid(ROOT)
    script('99_stop.sh')
    assert not device.processes() and not power_watch.running_pid(ROOT)
    print(json.dumps({'environment': 'passed'}))


if __name__ == '__main__':
    main()
