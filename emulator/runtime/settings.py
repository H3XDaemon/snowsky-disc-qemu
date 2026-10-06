"""Named presets for the guest's SYSCONFIG row, applied while the guest is stopped.

Profiles are JSON files in emulator/settings/. A value may be "${NAME:-default}"
to take an integer from the environment. `--set COLUMN=INT` adds single values.
Only existing integer columns of the one SYSCONFIG row are written.

PLAYER_CHOICES are columns the user sets in the player's own Settings menu. A profile
writes them only to a database that setup has just primed (`apply --fresh`); later
setups (every `./emulator/run.sh boot`) keep what the player saved. One exception: a
LANGUAGE outside the menu's 0..9 (stock's initial 100, which opens the first-boot
wizard) is no choice yet, so the profile's language applies. `--set`/SETTINGS always
writes, because it names a column explicitly.

`primed` says whether the priming boot got as far as the SYSCONFIG table and its
row: mq_player creates the file first, so the file alone proves nothing. `priming`
also tells an unprimed database (safe to start over) from one setup cannot read.
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
# Settings > Cover Animation (1 Rotate, 0 Static) and the menu language.
PLAYER_CHOICES = ('LOCAL_IMG_ANIM', 'LANGUAGE')


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


def profile_values(name, fresh, current, environment=os.environ):
    """The profile's values for this apply. Without `fresh` the player's own choices in
    `current` (the row as it is) are left out, except a LANGUAGE the menu cannot set."""
    values = load(name, environment)
    if fresh:
        return values
    kept = {c for c in PLAYER_CHOICES if not (c == 'LANGUAGE' and current.get(c) not in range(10))}
    return {k: v for k, v in values.items() if k not in kept}


def overrides(text):
    values = {}
    for item in (text or '').replace(',', ' ').split():
        column, separator, value = item.partition('=')
        if not separator:
            raise ValueError(f'Expected COLUMN=INTEGER, got {item!r}')
        values[column] = value
    return values


def priming(root):
    """What the priming boot left in sysconfig.db: 'primed', 'unprimed', or an error.

    mq_player creates the empty file before the SYSCONFIG table: a priming cut short in
    between leaves a file without the table. 'unprimed' is only that: no file, an
    empty file, or no SYSCONFIG in sqlite_master — what setup may start over. A
    database it cannot read (locked, a WAL without its -shm, damaged) or one with
    other than one row is neither: ValueError says why, and setup stops rather than
    delete a guest's settings it could not look at.
    """
    database = Path(root) / DATABASE
    if not database.is_file() or database.stat().st_size == 0:
        return 'unprimed'
    try:
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=1) as db:
            if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='SYSCONFIG'").fetchone():
                return 'unprimed'
            rows = db.execute('SELECT COUNT(*) FROM SYSCONFIG').fetchone()[0]
    except sqlite3.Error as exc:
        raise ValueError(f'sysconfig.db could not be read: {exc}') from None
    if rows != 1:
        raise ValueError(f'sysconfig.db has {rows} SYSCONFIG rows, expected one')
    return 'primed'


def primed(root):
    """True once the SYSCONFIG table and its one row are there and readable; anything
    else, a refused read while the player still writes included, is "not yet"."""
    try:
        return priming(root) == 'primed'
    except ValueError:
        return False


def row(root):
    """The SYSCONFIG row as {column: value}."""
    with sqlite3.connect(f'file:{Path(root) / DATABASE}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return dict(db.execute('SELECT * FROM SYSCONFIG').fetchone())


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
        if not known:
            raise ValueError('sysconfig.db has no SYSCONFIG table: the priming boot was cut short '
                             '(setup primes again when the table is missing)')
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
    parser.add_argument('action', choices=['apply', 'list', 'show', 'primed', 'priming'],
                        help='primed: exit 0 once the SYSCONFIG table and its row exist; '
                             'priming: exit 0 primed, 1 unprimed (safe to start over), 2 unreadable or unexpected')
    parser.add_argument('--profile', default=os.environ.get('SETTINGS_PROFILE') or 'emulator')
    parser.add_argument('--set', default=os.environ.get('SETTINGS', ''), help='COLUMN=INT[,COLUMN=INT...]')
    parser.add_argument('--fresh', action='store_true',
                        help='the database was just primed: also preset ' + ', '.join(PLAYER_CHOICES))
    args = parser.parse_args()
    target = os.environ.get('ROOTFS', '/work/rootfs')
    try:
        if args.action == 'primed':
            parser.exit(0 if primed(target) else 1)
        elif args.action == 'priming':
            parser.exit(0 if priming(target) == 'primed' else 1)
        elif args.action == 'list':
            for name in profiles():
                print(f"{name}: {json.loads((PROFILES / (name + '.json')).read_text())['description']}")
        elif args.action == 'show':
            print(json.dumps(row(target)))
        else:
            from emulator.runtime.keys import Device
            if Device(target).processes():
                raise ValueError('Stop the guest first: the running player owns its settings')
            current = row(target) if primed(target) else {}     # apply() reports what is missing
            values = {**profile_values(args.profile, args.fresh, current), **overrides(args.set)}
            changed = apply(target, values)
            print(f'settings profile {args.profile}: ' +
                  (', '.join(f'{c} {old}->{new}' for c, (old, new) in changed.items()) or 'no change'))
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(2, f'{exc}\n')
