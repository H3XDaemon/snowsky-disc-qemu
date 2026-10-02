"""Snapshot-scoped playback observations; never a permanent recording identity."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

MAX_COVER = 8 * 1024 * 1024
MAX_ARTWORK = 256 * 1024 * 1024


def image_type(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_COVER:
        return None
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n') and data.endswith(b'IEND\xaeB`\x82'):
        return 'image/png'
    return None


class Enrichment:
    """Separate optional database; opening it does not migrate the catalog store."""
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(directory / 'observations.sqlite3', timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS artwork (
                digest TEXT PRIMARY KEY, mime TEXT NOT NULL, body BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (
                device TEXT NOT NULL, generation TEXT NOT NULL, track TEXT NOT NULL,
                duration_ms INTEGER, artwork TEXT, provenance TEXT NOT NULL,
                observed_at TEXT NOT NULL, revision TEXT NOT NULL,
                PRIMARY KEY(device,generation,track));
        ''')
        # Additive migration keeps prior duration/artwork observations intact.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(observations)')}
            if 'metadata' not in columns:
                self.db.execute("ALTER TABLE observations ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def record_observation(self, device, generation, observation):
        if observation.ordinal is None:
            return False
        return self.record(device, generation, f'{generation}:{observation.ordinal}',
            duration_ms=observation.track.duration_ms, cover=observation.cover,
            provenance=observation.provenance, metadata=observation.track.metadata)

    def record(self, device, generation, track, *, duration_ms, cover, provenance, metadata=None):
        if type(duration_ms) is not int or not 0 < duration_ms <= 7 * 24 * 3600 * 1000:
            duration_ms = None
        metadata = metadata or {}
        mime = image_type(cover)
        if duration_ms is None and mime is None and not metadata:
            return False
        digest = hashlib.sha256(cover).hexdigest() if mime else None
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if digest and not self.db.execute('SELECT 1 FROM artwork WHERE digest=?', (digest,)).fetchone():
                size = self.db.execute('SELECT coalesce(sum(length(body)),0) FROM artwork').fetchone()[0]
                if size + len(cover) <= MAX_ARTWORK:
                    self.db.execute('INSERT INTO artwork VALUES(?,?,?)', (digest, mime, cover))
                else:
                    digest = None
            if duration_ms is None and digest is None and not metadata:
                return False
            # An absent current image must not resurrect a previous track's artwork.
            self.db.execute('''INSERT OR REPLACE INTO observations
                (device,generation,track,duration_ms,artwork,provenance,observed_at,revision,metadata)
                VALUES(?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?,?)''',
                (device, generation, track, duration_ms, digest,
                 json.dumps(provenance, ensure_ascii=False), uuid4().hex,
                 json.dumps(metadata, ensure_ascii=False)))
        return True

    def rows(self, device, generation):
        return {row['track']: dict(row, metadata=json.loads(row['metadata'])) for row in self.db.execute('''
            SELECT track,duration_ms,artwork,observed_at,revision,metadata FROM observations
            WHERE device=? AND generation=?''', (device, generation))}

    def state(self, device, generation):
        rows = self.rows(device, generation)
        revision = hashlib.sha256(''.join(sorted(r['revision'] for r in rows.values())).encode()).hexdigest()
        return {'count': len(rows), 'revision': revision,
                'artwork_count': sum(r['artwork'] is not None for r in rows.values()),
                'duration_count': sum(r['duration_ms'] is not None for r in rows.values())}

    def artwork(self, device, generation, digest):
        if not re.fullmatch('[0-9a-f]{64}', digest):
            return None
        row = self.db.execute('''SELECT a.mime,a.body FROM artwork a WHERE a.digest=?
            AND EXISTS (SELECT 1 FROM observations o WHERE o.artwork=a.digest
                AND o.device=? AND o.generation=?)''', (digest, device, generation)).fetchone()
        return (row['body'], row['mime']) if row else None
