"""SQLite snapshots and atomic publication, independent of device/search transports."""
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from library.artists import split_artists, artist_key


class StaleSnapshot(ValueError):
    pass


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'library.sqlite3'
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError(f'unsupported library database version {version}')
        if version == 0:
            self.db.executescript('''
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS snapshots (
                    generation TEXT PRIMARY KEY, device TEXT NOT NULL,
                    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    metadata TEXT NOT NULL, track_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS tracks (
                    id TEXT PRIMARY KEY, generation TEXT NOT NULL REFERENCES snapshots(generation),
                    ordinal INTEGER NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL,
                    album TEXT NOT NULL, source TEXT NOT NULL,
                    UNIQUE(generation, ordinal));
                CREATE TABLE IF NOT EXISTS heads (
                    device TEXT PRIMARY KEY, generation TEXT NOT NULL REFERENCES snapshots(generation),
                    collection TEXT, index_generation TEXT, index_signature TEXT);
                PRAGMA user_version=1;
                COMMIT;
            ''')

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def head(self, device):
        row = self.db.execute('''SELECT h.*, s.observed_at, s.track_count FROM heads h
            JOIN snapshots s USING(generation) WHERE h.device=?''', (device,)).fetchone()
        return dict(row) if row else {'device': device, 'generation': None, 'collection': None,
                                     'index_generation': None, 'index_signature': None, 'track_count': 0}

    def publish(self, device, tracks, metadata, *, expected_generation):
        generation = uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.head(device)['generation'] != expected_generation:
                raise StaleSnapshot('another import published first; retry sync')
            self.db.execute('INSERT INTO snapshots(generation,device,metadata,track_count) VALUES(?,?,?,?)',
                            (generation, device, json.dumps(metadata, ensure_ascii=False), len(tracks)))
            self.db.executemany('INSERT INTO tracks VALUES(?,?,?,?,?,?,?)', (
                (f'{generation}:{i}', generation, i, t.title, t.artist, t.album,
                 json.dumps({'category': 'album/song', 'album': t.album, 'position': t.position,
                             'row': t.raw}, ensure_ascii=False)) for i, t in enumerate(tracks)))
            # Retain old projection reference so lag is visible, never present it as current.
            self.db.execute('''INSERT INTO heads(device,generation) VALUES(?,?)
                ON CONFLICT(device) DO UPDATE SET generation=excluded.generation''', (device, generation))
        return self.head(device)

    def documents(self, generation):
        return [dict(row, artists=split_artists(row['artist']), artist_key=artist_key(row['artist'])) for row in self.db.execute(
            'SELECT id,generation,title,artist,album FROM tracks WHERE generation=? ORDER BY ordinal',
            (generation,))]

    def snapshot(self, device):
        """Read one published head and its immutable rows on the same connection."""
        from library.snapshot import Snapshot
        head = self.head(device)
        if not head['generation']:
            return head, None
        rows = [dict(row) for row in self.db.execute(
            'SELECT id,ordinal,title,artist,album FROM tracks WHERE generation=? ORDER BY ordinal',
            (head['generation'],))]
        metadata = json.loads(self.db.execute('SELECT metadata FROM snapshots WHERE generation=?',
                                              (head['generation'],)).fetchone()[0])
        return head, Snapshot(head['generation'], rows, genres=metadata.get('genres'))

    def matches_tracks(self, generation, tracks):
        """Exact snapshot content/order, including source rows; not identity reconciliation."""
        rows = self.db.execute('SELECT title,artist,album,source FROM tracks WHERE generation=? ORDER BY ordinal',
                               (generation,)).fetchall()
        return len(rows) == len(tracks) and all(
            (row['title'], row['artist'], row['album'], json.loads(row['source'])) ==
            (t.title, t.artist, t.album, {'category': 'album/song', 'album': t.album,
                                       'position': t.position, 'row': t.raw})
            for row, t in zip(rows, tracks))

    def publish_index(self, device, generation, collection, signature):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.head(device)['generation'] != generation:
                raise StaleSnapshot('catalog changed while indexing; rebuild the new snapshot')
            self.db.execute('''UPDATE heads SET collection=?, index_generation=?, index_signature=?
                WHERE device=?''', (collection, generation, signature, device))

    def verify_index(self, device, signature):
        head = self.head(device)
        if not head['generation']:
            raise ValueError('no catalog snapshot; run sync first')
        if (not head['collection'] or head['generation'] != head['index_generation']
                or head['index_signature'] != signature):
            raise StaleSnapshot('search index is missing, outdated or has different aliases/server; run index')
        return head
