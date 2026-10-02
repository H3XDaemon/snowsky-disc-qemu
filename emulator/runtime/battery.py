"""Fuel-gauge sysfs of the guest (cw221X-bat): selectable layout and runtime values.

Stock reads only `capacity` and `temp`. The `legacy` layout is the emulator's
original one; `device` has the attributes of a V2.57 player (type Mains, with
current_now and cycle_count, without status/online).
"""
import os
from pathlib import Path

DIRECTORY = 'sys/class/power_supply/cw221X-bat'
VALUES = {'capacity': 100, 'voltage_now': 4200000, 'temp': 250}   # percent, microvolts, 0.1 degC
RANGES = {'capacity': (0, 100), 'voltage_now': (0, 5000000), 'temp': (-400, 1000)}
PROFILES = {
    # Byte-for-byte what 10_setup_env.sh always wrote: no trailing newlines.
    'legacy': dict(newline='', fixed={'type': 'Battery', 'status': 'Full', 'health': 'Good', 'present': '1',
                                      'technology': 'Li-ion', 'online': '1'}, absent=()),
    'device': dict(newline='\n', fixed={'type': 'Mains', 'health': 'Good', 'present': '1',
                                        'technology': 'Li-ion', 'current_now': '0', 'cycle_count': '0'},
                   absent=('status', 'online')),
}


def _write(path, text):
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(text)
    temporary.replace(path)            # a reader never sees an empty attribute


def _check(values):
    for name, value in values.items():
        low, high = RANGES[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{name} must be an integer from {low} to {high}')


def profile_of(root):
    try:
        return 'device' if (Path(root) / DIRECTORY / 'type').read_text().strip() == 'Mains' else 'legacy'
    except OSError:
        return None


def prepare(root, profile='legacy', **values):
    """Create the attribute files of one layout; unnamed values get the full-battery defaults."""
    if profile not in PROFILES:
        raise ValueError('Unknown battery profile; use legacy or device')
    values = {**VALUES, **{name: value for name, value in values.items() if value is not None}}
    _check(values)
    layout = PROFILES[profile]
    directory = Path(root) / DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    for name in layout['absent']:
        (directory / name).unlink(missing_ok=True)
    for name, text in {**layout['fixed'], **{k: str(v) for k, v in values.items()}}.items():
        _write(directory / name, text + layout['newline'])


def update(root, **values):
    """Change values of a prepared gauge while the guest runs or is off."""
    values = {name: value for name, value in values.items() if value is not None}
    _check(values)
    profile = profile_of(root)
    if profile is None:
        raise ValueError('No battery gauge; run setup first')
    for name, value in values.items():
        _write(Path(root) / DIRECTORY / name, str(value) + PROFILES[profile]['newline'])


def snapshot(root):
    directory = Path(root) / DIRECTORY
    result = {'profile': profile_of(root)}
    for name in sorted(p.name for p in directory.iterdir()) if directory.is_dir() else ():
        result[name] = (directory / name).read_text().strip()
    return result


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'set', 'show'])
    parser.add_argument('--profile', default=os.environ.get('BATTERY_PROFILE') or 'legacy')
    parser.add_argument('--capacity', type=int, help='percent')
    parser.add_argument('--voltage', type=int, help='microvolts')
    parser.add_argument('--temp', type=int, help='tenths of a degree Celsius')
    args = parser.parse_args()
    target = os.environ.get('ROOTFS', '/work/rootfs')
    numbers = dict(capacity=args.capacity, voltage_now=args.voltage, temp=args.temp)
    try:
        if args.action == 'prepare':
            prepare(target, args.profile, **numbers)
        elif args.action == 'set':
            update(target, **numbers)
    except ValueError as exc:
        parser.exit(2, f'{exc}\n')
    print(json.dumps(snapshot(target)))
