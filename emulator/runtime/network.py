"""Emulated network links of the guest: dummy interfaces, isolation and shaping.

  link NAME [--state up|down] [--addr CIDR|none] [--mac MAC] [--gateway IP]
        create or change a DUMMY interface the guest sees (wlan0, eth1 in an
        isolated guest ...) and its /sys/class/net mirror; never a real interface
  unlink NAME          remove a dummy interface created here
  isolate | share      give the guest its own empty network namespace, or the container's
  shape [--rate R] [--delay D] [--loss P] | shape off
        limit what the guest SENDS on the container's eth1 (tc tbf + netem)
  status               JSON

The guest reads interface state in two places: netlink/ioctl (real kernel
objects, hence the dummy interfaces) and /sys/class/net/<name>/ (stub files in
the rootfs, kept here). See emulator/docs/network.md.
"""
import json
import os
from pathlib import Path
import re
import subprocess

NAMESPACE = 'emu/netns'            # marker: name of the guest's own namespace, when isolated
NAME = re.compile(r'[a-z][a-z0-9]{1,13}')
RATE = re.compile(r'\d+(\.\d+)?(bit|kbit|mbit|gbit)')
DELAY = re.compile(r'\d+(\.\d+)?(ms|s)')
LOSS = re.compile(r'\d+(\.\d+)?%')
REAL = 'eth1'                      # the Docker interface of a shared guest: shaped, never edited


def namespace(root):
    """Name of the guest's own network namespace, or None when it shares the container's."""
    try:
        name = (Path(root) / NAMESPACE).read_text().strip()
    except OSError:
        return None
    return name if name and Path('/run/netns', name).exists() else None


def ip(root, *args, check=True, capture=False):
    scope = ['-n', namespace(root)] if namespace(root) else []
    return subprocess.run(['ip', *scope, *args], check=check, text=True,
                          capture_output=capture, timeout=10)


def links(root):
    return {item['ifname']: item for item in json.loads(ip(root, '-d', '-j', 'addr', 'show', capture=True).stdout)}


def is_dummy(item):
    return item.get('linkinfo', {}).get('info_kind') == 'dummy'


def mirror(root, name):
    """The rootfs' stub of /sys/class/net/<name>: what stock and services read."""
    directory = Path(root) / 'sys/class/net' / name
    item = links(root).get(name)
    if item is None:
        for attribute in ('address', 'operstate'):
            (directory / attribute).unlink(missing_ok=True)
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
        return
    directory.mkdir(parents=True, exist_ok=True)
    # A dummy link reports "unknown" when up; a radio reports "up". Publish the intent.
    state = 'up' if 'UP' in item['flags'] else 'down'
    (directory / 'address').write_text(item['address'] + '\n')
    (directory / 'operstate').write_text((item['operstate'].lower() if not is_dummy(item) else state) + '\n')


def link(root, name, state=None, addr=None, mac=None, gateway=None):
    if not NAME.fullmatch(name) or name == 'lo':
        raise ValueError('Interface name must be like wlan0')
    current = links(root).get(name)
    if current is not None and not is_dummy(current):
        raise ValueError(f'{name} is a real interface; only emulated (dummy) links are changed here')
    if current is None:
        ip(root, 'link', 'add', name, 'type', 'dummy')
    if mac:
        if not re.fullmatch(r'([0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
            raise ValueError('MAC must look like d0:31:10:00:00:01')
        ip(root, 'link', 'set', name, 'address', mac)
    if addr is not None:
        ip(root, 'addr', 'flush', 'dev', name)
        if addr != 'none':
            ip(root, 'addr', 'add', addr, 'dev', name)
    if state is not None:
        ip(root, 'link', 'set', name, state)
    if gateway:
        ip(root, 'route', 'replace', 'default', 'via', gateway, 'dev', name)
    mirror(root, name)


def unlink(root, name):
    current = links(root).get(name)
    if current is not None:
        if not is_dummy(current):
            raise ValueError(f'{name} is a real interface')
        ip(root, 'link', 'del', name)
    mirror(root, name)


def isolate(root, name='disc-guest'):
    """A fresh namespace with only loopback: the guest has no network until a link is added."""
    root = Path(root)
    subprocess.run(['ip', 'netns', 'del', name], capture_output=True)
    subprocess.run(['ip', 'netns', 'add', name], check=True)
    subprocess.run(['ip', '-n', name, 'link', 'set', 'lo', 'up'], check=True)
    (root / NAMESPACE).write_text(name + '\n')
    for stale in (root / 'sys/class/net').glob('*'):     # no interface of the container is visible
        for attribute in ('address', 'operstate'):
            (stale / attribute).unlink(missing_ok=True)
        if not any(stale.iterdir()):
            stale.rmdir()


def share(root):
    root = Path(root)
    name = namespace(root)
    (root / NAMESPACE).unlink(missing_ok=True)
    if name:
        subprocess.run(['ip', 'netns', 'del', name], capture_output=True)


def shape(rate=None, delay=None, loss=None):
    """Egress of the container's interface = what a client downloads from the guest."""
    for value, pattern, label in ((rate, RATE, 'rate like 800kbit'), (delay, DELAY, 'delay like 80ms'),
                                  (loss, LOSS, 'loss like 1%')):
        if value is not None and not pattern.fullmatch(value):
            raise ValueError(f'Expected a {label}')
    subprocess.run(['tc', 'qdisc', 'del', 'dev', REAL, 'root'], capture_output=True)
    if not (rate or delay or loss):
        return
    parent = ['root', 'handle', '1:']
    if delay or loss:
        subprocess.run(['tc', 'qdisc', 'add', 'dev', REAL, *parent, 'netem'] +
                       (['delay', delay] if delay else []) + (['loss', loss] if loss else []), check=True)
        parent = ['parent', '1:1', 'handle', '10:']
    if rate:
        subprocess.run(['tc', 'qdisc', 'add', 'dev', REAL, *parent, 'tbf', 'rate', rate,
                        'burst', '32kbit', 'latency', '400ms'], check=True)


def status(root):
    result = dict(namespace=namespace(root), links={})
    for name, item in links(root).items():
        addresses = [a for a in item.get('addr_info', []) if a['family'] == 'inet']
        if name == 'lo' or not (is_dummy(item) or addresses):
            continue                 # the VM's idle tunnel devices are not the guest's links
        result['links'][name] = dict(
            emulated=is_dummy(item), up='UP' in item['flags'], mac=item.get('address'),
            addresses=[f"{a['local']}/{a['prefixlen']}" for a in item.get('addr_info', []) if a['family'] == 'inet'])
    shaping = subprocess.run(['tc', 'qdisc', 'show', 'dev', REAL], capture_output=True, text=True).stdout
    result['shaping'] = [line.strip() for line in shaping.splitlines() if 'tbf' in line or 'netem' in line]
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['link', 'unlink', 'isolate', 'share', 'shape', 'status'])
    parser.add_argument('name', nargs='?')
    parser.add_argument('--state', choices=['up', 'down'])
    parser.add_argument('--addr')
    parser.add_argument('--mac')
    parser.add_argument('--gateway')
    parser.add_argument('--rate')
    parser.add_argument('--delay')
    parser.add_argument('--loss')
    args = parser.parse_args()
    target = os.environ.get('ROOTFS', '/work/rootfs')
    try:
        if args.action == 'link':
            link(target, args.name or '', args.state, args.addr, args.mac, args.gateway)
        elif args.action == 'unlink':
            unlink(target, args.name or '')
        elif args.action == 'isolate':
            isolate(target)
        elif args.action == 'share':
            share(target)
        elif args.action == 'shape':
            shape(*(None, None, None) if args.name == 'off' else (args.rate, args.delay, args.loss))
        print(json.dumps(status(target)))
    except (ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'{exc}\n')
