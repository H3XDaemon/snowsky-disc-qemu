"""Named presets for the guest's SYSCONFIG row, applied while the guest is stopped.

Profiles are JSON files in emulator/settings/. A value may be "${NAME:-default}"
to take an integer from the environment. `--set COLUMN=INT` adds single values.
Only existing integer columns of the one SYSCONFIG row are written.
"""
import json
import os
from pathlib import Path
import re
import sqlite3

PROFILES = Path(__file__).resolve().parents[1] / 'settings'
DATABASE = 'usr/data/fiio/db/sysconfig.db'
REFERENCE = re.compile(r'\$\{([A-Z_][A-Z0-9_]*):-(-?\d+)\}')
COLUMN = re.compile(r'[A-Z][A-Z0-9_]*')


def profiles():
    return sorted(path.stem for path in PROFILES.glob('*.json'))


def load(name, environment=os.environ):
    if name not in profiles():
        raise ValueError(f"Unknown settings profile {name!r}; available: {', '.join(profiles())}")
    values = {}
    for column, value in json.loads((PROFILES / f'{name}.json').read_text())['sysconfig'].items():
        if isinstance(value, str):
            match = REFERENCE.fullmatch(value)
            if not match:
                raise ValueError(f'{name}: {column} must be an integer or "${{NAME:-default}}"')
            value = environment.get(match[1]) or match[2]
        values[column] = value
    return values


def overrides(text):
    values = {}
    for item in (text or '').replace(',', ' ').split():
        column, separator, value = item.partition('=')
        if not separator:
            raise ValueError(f'Expected COLUMN=INTEGER, got {item!r}')
        values[column] = value
    return values


def apply(root, values):
    """Write the values; returns the columns that changed as {column: (before, after)}."""
    checked = {}
    for column, value in values.items():
        if not COLUMN.fullmatch(column) or column == 'ID':
            raise ValueError(f'Not a settings column: {column!r}')
        try:
            checked[column] = int(str(value))
        except ValueError:
            raise ValueError(f'{column} needs an integer, got {value!r}') from None
    database = Path(root) / DATABASE
    if not database.is_file():
        raise ValueError('sysconfig.db missing; run setup (it primes the database) first')
    with sqlite3.connect(f'file:{database}?mode=rw', uri=True) as db:
        known = {row[1] for row in db.execute('PRAGMA table_info(SYSCONFIG)')}
        unknown = sorted(set(checked) - known)
        if unknown:
            raise ValueError('Unknown SYSCONFIG column: ' + ', '.join(unknown))
        if db.execute('SELECT COUNT(*) FROM SYSCONFIG').fetchone() != (1,):
            raise ValueError('Expected exactly one SYSCONFIG row')
        if not checked:
            return {}
        columns = sorted(checked)
        before = db.execute(f"SELECT {', '.join(columns)} FROM SYSCONFIG").fetchone()
        db.execute(f"UPDATE SYSCONFIG SET {', '.join(c + '=?' for c in columns)}",
                   [checked[c] for c in columns])
    return {c: (old, checked[c]) for c, old in zip(columns, before) if old != checked[c]}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'list', 'show'])
    parser.add_argument('--profile', default=os.environ.get('SETTINGS_PROFILE') or 'emulator')
    parser.add_argument('--set', default=os.environ.get('SETTINGS', ''), help='COLUMN=INT[,COLUMN=INT...]')
    args = parser.parse_args()
    target = os.environ.get('ROOTFS', '/work/rootfs')
    try:
        if args.action == 'list':
            for name in profiles():
                print(f"{name}: {json.loads((PROFILES / (name + '.json')).read_text())['description']}")
        elif args.action == 'show':
            with sqlite3.connect(f'file:{Path(target) / DATABASE}?mode=ro', uri=True) as db:
                db.row_factory = sqlite3.Row
                print(json.dumps(dict(db.execute('SELECT * FROM SYSCONFIG').fetchone())))
        else:
            from emulator.runtime.keys import Device
            if Device(target).processes():
                raise ValueError('Stop the guest first: the running player owns its settings')
            values = {**load(args.profile), **overrides(args.set)}
            changed = apply(target, values)
            print(f'settings profile {args.profile}: ' +
                  (', '.join(f'{c} {old}->{new}' for c, (old, new) in changed.items()) or 'no change'))
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(2, f'{exc}\n')
