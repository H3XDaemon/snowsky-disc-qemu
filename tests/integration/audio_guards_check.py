"""Output stream reporting and the FPU guard on a disposable V2.57 guest (CI_SCENARIO=audio-guards)."""
import json
import os
from pathlib import Path
import subprocess
import time

from controller.fiio_link import Client
from emulator.runtime import machine
from emulator.runtime.audio import STREAM, output_state
from emulator.runtime.keys import Buttons, Device
from emulator.runtime.peripherals import Peripherals
from research.diagnostics.player_memory import PlayerMemory
from tests.integration.profile import diagnostic, require_acceptance, version as firmware_version

ROOT = Path('/work/rootfs')
SCRIPTS = '/repo/emulator/scripts'
TRACK = 'Audio Check/Long tone.wav'
STATIC = ['mipsel-linux-gnu-gcc', '-static', '-nostdlib', '-mabi=32', '-march=mips32r2', '-fno-pic',
          '-mno-abicalls', '-O1']


def script(name, *args, **environment):
    subprocess.run(['bash', f'{SCRIPTS}/{name}', *args], check=True, env={**os.environ, **environment},
                   stdout=subprocess.DEVNULL)


def guest(command, **environment):
    return subprocess.run(['bash', '-c', f'source {SCRIPTS}/lib.sh; guest_run 20 {command}'], text=True,
                          capture_output=True, env={**os.environ, **environment})


def wait(read, predicate, label, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f'{label}: {value!r}')
        time.sleep(.25)


def check_output_stream(device):
    card = ROOT / 'tmp/sdcard'
    (card / TRACK).parent.mkdir(exist_ok=True)
    subprocess.run(['sox', '-n', '-r', '44100', '-b', '16', '-c', '2', str(card / TRACK),
                    'synth', '90', 'sine', '330', 'vol', '0.2'], check=True)
    os.sync()
    assert output_state(ROOT)['stream'] == 'closed'
    assert (ROOT / STREAM / 'status').read_text() == 'closed\n'
    buttons = Buttons(ROOT, device)
    with Client(timeout=8) as client:
        client.handshake()
        client.scan_library()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:                      # a60a/0005 ends a scan
            tag, payload = client.event(timeout=20)
            if tag == 'a60a' and bytes(payload)[-4:] == b'0005':
                break
        titles = wait(lambda: [item['title'] for item in client.tracks()['items']],
                      lambda found: 'Long tone.wav' in found, 'the long track was not indexed')
        client.play_index(titles.index('Long tone.wav'))
        state = wait(lambda: output_state(ROOT), lambda now: now['activity'] == 'samples', 'no samples reached the output')
        assert state == dict(stream='RUNNING', activity='samples', format='S32_LE', rate=44100, channels=2), state
        text = (ROOT / STREAM / 'hw_params').read_text()
        assert text.startswith('access: RW_INTERLEAVED\nformat: S32_LE\nsubformat: STD\nchannels: 2\n'
                               'rate: 44100 (44100/1)\nperiod_size: '), text
        owner = (ROOT / STREAM / 'status').read_text().split('owner_pid   : ')[1].strip()
        assert int(owner) == Peripherals(device)._pid(), owner       # direct boot: the container's PID
        # Pause: stock keeps the stream running and feeds it zeros.
        buttons.gesture('play_pause', 'single')
        paused = wait(lambda: output_state(ROOT), lambda now: now['activity'] == 'silence', 'pause still audible')
        assert paused['stream'] == 'RUNNING', paused
        print('Paused output:', json.dumps(paused), flush=True)
        buttons.gesture('play_pause', 'single')
        wait(lambda: output_state(ROOT), lambda now: now['activity'] == 'samples', 'resume not audible')
        buttons.gesture('play_pause', 'single')
        wait(lambda: output_state(ROOT), lambda now: now['activity'] == 'silence', 'second pause still audible')
    # Stopping the guest kills a player that never closes its stream: the report must not stay RUNNING.
    script('99_stop.sh')
    assert output_state(ROOT) == dict(stream='closed', activity='closed', format=None, rate=None, channels=None)


def jack_flags():
    with PlayerMemory(ROOT, firmware_version()) as memory:
        return memory.word(*diagnostic('output.single_ended')), memory.word(*diagnostic('output.balanced'))


def check_jack(device):
    """Stock's own detection: 3.5 mm on GPIO pb20, 4.4 mm on ADC channel 2; unplugging pauses."""
    controls = Peripherals(device)
    assert controls.jack() is None, 'the model must be off unless JACK is given'
    script('20_boot.sh', BOOT_MODE='direct', JACK='3.5')
    assert controls.jack() == '3.5'
    wait(jack_flags, lambda flags: flags == (1, 0), 'stock did not detect the 3.5 mm plug')
    with Client(timeout=8) as client:
        client.handshake()
        titles = [item['title'] for item in client.tracks()['items']]
        client.play_index(titles.index('Long tone.wav'))
        wait(lambda: output_state(ROOT), lambda now: now['activity'] == 'samples', 'no samples with a plug in')
        controls.set_jack('none')
        wait(jack_flags, lambda flags: flags == (0, 0), 'stock did not notice the unplug')
        wait(lambda: output_state(ROOT), lambda now: now['activity'] == 'silence', 'unplugging did not pause')
        assert client.now_playing()['state'] == 1                       # paused, by stock itself
        controls.set_jack('4.4')
        wait(jack_flags, lambda flags: flags == (0, 1), 'stock did not detect the 4.4 mm plug')
        seen = set()
        for _ in range(8):                                              # a plug does not resume
            seen.add(output_state(ROOT)['activity'])
            time.sleep(.25)
        assert 'samples' not in seen and client.now_playing()['state'] == 1, seen
        Buttons(ROOT, device).gesture('play_pause', 'single')
        wait(lambda: output_state(ROOT), lambda now: now['activity'] == 'samples', 'Play did not resume')
    for bad in ('2.5', None, 3.5):
        try:
            controls.set_jack(bad)
        except ValueError:
            continue
        raise AssertionError(f'jack {bad!r} accepted')
    controls.set_jack('off')
    assert controls.jack() is None


def check_fpu_guard(device):
    source = '/repo/emulator/tests/guest/pinprobe.c'
    subprocess.run(STATIC + ['-msoft-float', '-o', str(ROOT / 'usr/data/emu-soft'), source], check=True)
    subprocess.run(STATIC + ['-mhard-float', '-Wl,-z,noexecstack', '-o', str(ROOT / 'usr/data/emu-hard'), source],
                   check=True)
    assert guest('/usr/data/emu-soft').stdout.strip() == '0xF6EFE127'
    refused = guest('/usr/data/emu-hard')
    assert refused.returncode == 126 and '[fpu-guard]' in refused.stderr and refused.stdout == '', refused
    # qemu-user itself runs it without complaint: that is why the guard exists.
    warned = guest('/usr/data/emu-hard', FPU_GUARD='warn')
    assert warned.returncode == 0 and warned.stdout.strip() == '0xF6EFE127' and '[fpu-guard]' in warned.stderr
    assert guest('/bin/busybox true').returncode == 0                    # stock hard-float is fine
    # A stock-init guest starts image programs without guest_run: they are reported instead.
    script('20_boot.sh', BOOT_MODE='init')
    state = wait(lambda: machine.state(ROOT), lambda now: now.get('fpu_trap'), 'trapping program not reported', 30)
    assert state['fpu_trap'] == ['/usr/data/emu-hard'], state
    assert '[fpu-guard] /work/rootfs/usr/data/emu-hard' in (ROOT.parent / 'machine.log').read_text()
    assert device.running()


def main():
    require_acceptance('audio-guards')
    device = Device(ROOT)
    script('20_boot.sh', BOOT_MODE='direct')
    check_output_stream(device)
    check_jack(device)
    check_fpu_guard(device)
    script('99_stop.sh')
    print(json.dumps({'audio_guards': 'passed'}))


if __name__ == '__main__':
    main()
