from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from library.store import Store, StaleSnapshot
from library.tests.helpers import TRACKS


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.close)

    def publish(self, tracks=TRACKS):
        return self.store.publish('test', tracks, {}, expected_generation=self.store.head('test')['generation'])

    def test_persistence_and_separate_duplicate_identities(self):
        head = self.publish()
        documents = self.store.documents(head['generation'])
        self.assertEqual(len({r['id'] for r in documents}), len(TRACKS))
        with Store(self.tmp.name) as reopened:
            self.assertEqual(reopened.documents(head['generation']), documents)
            self.assertIsNone(reopened.head('other-device')['generation'])

    def test_failed_publish_rolls_back_all_rows(self):
        head = self.publish()
        broken = TRACKS + [replace(TRACKS[0], raw={'not_json': object()})]
        with self.assertRaises(TypeError):
            self.publish(broken)
        self.assertEqual(self.store.head('test'), head)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 1)
        self.assertEqual(len(self.store.documents(head['generation'])), len(TRACKS))

    def test_concurrent_import_cannot_overwrite_completed_import(self):
        self.publish()
        with self.assertRaises(StaleSnapshot):
            self.store.publish('test', [], {}, expected_generation=None)
        self.assertEqual(self.store.head('test')['track_count'], len(TRACKS))

    def test_empty_snapshot_and_index_lag(self):
        head = self.publish()
        self.store.publish_index('test', head['generation'], 'old', 'sig')
        empty = self.publish([])
        self.assertEqual(empty['track_count'], 0)
        self.assertEqual(empty['collection'], 'old')
        with self.assertRaises(StaleSnapshot):
            self.store.verify_index('test', 'sig')
        with self.assertRaises(StaleSnapshot):
            self.store.publish_index('test', head['generation'], 'obsolete', 'sig')

    def test_unknown_schema_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with sqlite3.connect(Path(directory) / 'library.sqlite3') as db:
                db.execute('PRAGMA user_version=999')
            with self.assertRaisesRegex(ValueError, 'version 999'):
                Store(directory)
