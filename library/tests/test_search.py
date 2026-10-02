import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

from library.search.typesense import Search
from library.store import Store, StaleSnapshot
from library.tests.helpers import TRACKS, ALIASES


class SearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.close)
        self.head = self.store.publish('test', TRACKS, {}, expected_generation=None)
        self.collection = Mock()
        self.collection.documents.import_ = AsyncMock(return_value=[{'success': True}] * len(TRACKS))
        self.collection.retrieve = AsyncMock(return_value={'num_documents': len(TRACKS)})
        self.collection.delete = AsyncMock()
        self.client = Mock()
        self.client.collections = Mock()
        self.client.collections.__getitem__ = Mock(return_value=self.collection)
        self.client.collections.create = AsyncMock()
        self.search = Search(self.client, ALIASES, ['http', 'localhost', 8108])

    async def test_projection_and_publish_after_success(self):
        head = await self.search.build(self.store, 'test')
        docs = self.collection.documents.import_.call_args.args[0]
        self.assertEqual(docs[0]['artist_aliases'], ['линкин парк'])
        self.assertEqual(docs[0]['title'], 'Numb')
        self.assertEqual(docs[4]['title_aliases'], ['tishina'])
        self.assertEqual(docs[4]['artist_aliases'], ['artist e'])
        self.assertEqual(docs[4]['album_aliases'], ['albom'])
        self.assertEqual(head['generation'], head['index_generation'])
        self.collection.delete.assert_not_called()

    async def test_artist_filter_is_applied_before_top_k_without_raw_query_syntax(self):
        from library.artists import artist_key
        await self.search.build(self.store, 'test')
        self.collection.documents.search = AsyncMock(return_value={'found': 0, 'hits': []})
        credit = 'Name`],other:=true || artist:[anything'
        await self.search.search(self.store, 'test', 'Song', artist_scope=[credit], split_join='fallback')
        params = self.collection.documents.search.call_args.args[0]
        self.assertEqual(params['filter_by'], 'artist_key:=[' + artist_key(credit) + ']')
        self.assertEqual(params['split_join_tokens'], 'fallback')
        self.assertNotIn(credit, params['filter_by'])
        with self.assertRaises(ValueError):
            await self.search.search(self.store, 'test', 'Song', artist_scope=[])

    async def test_empty_snapshot_is_indexed_without_document_import(self):
        self.store.publish('test', [], {}, expected_generation=self.head['generation'])
        self.collection.retrieve.return_value = {'num_documents': 0}
        head = await self.search.build(self.store, 'test')
        self.assertEqual(head['track_count'], 0)
        self.assertEqual(head['generation'], head['index_generation'])
        self.collection.documents.import_.assert_not_called()

    async def test_later_batch_failure_does_not_publish_partial_collection(self):
        self.store.publish('test', TRACKS * 30, {}, expected_generation=self.head['generation'])
        self.collection.documents.import_.side_effect = [
            [{'success': True}] * 200, [{'success': False}] * 10]
        with self.assertRaises(ValueError):
            await self.search.build(self.store, 'test')
        self.assertEqual([len(c.args[0]) for c in self.collection.documents.import_.call_args_list], [200, 10])
        self.assertIsNone(self.store.head('test')['collection'])

    async def test_partial_import_retains_old_projection(self):
        old = await self.search.build(self.store, 'test')
        self.collection.documents.import_.return_value = [{'success': False}] * len(TRACKS)
        with self.assertRaises(ValueError):
            await self.search.build(self.store, 'test')
        self.assertEqual(self.store.head('test'), old)
        self.collection.delete.assert_awaited_once()

    async def test_transport_failure_and_count_mismatch_do_not_publish(self):
        for kind in ('transport', 'count'):
            with self.subTest(kind=kind):
                self.collection.documents.import_.side_effect = OSError('offline') if kind == 'transport' else None
                self.collection.retrieve.return_value = {'num_documents': 1}
                with self.assertRaises((OSError, ValueError)):
                    await self.search.build(self.store, 'test')
                self.assertIsNone(self.store.head('test')['collection'])

    async def test_catalog_changes_during_indexing(self):
        async def changed():
            self.store.publish('test', [], {}, expected_generation=self.head['generation'])
            return {'num_documents': len(TRACKS)}
        self.collection.retrieve.side_effect = changed
        with self.assertRaises(StaleSnapshot):
            await self.search.build(self.store, 'test')
        self.assertIsNone(self.store.head('test')['collection'])

    async def test_search_checks_generation_evidence_and_policy(self):
        await self.search.build(self.store, 'test')
        doc = self.store.documents(self.head['generation'])[0]
        self.collection.documents.search = AsyncMock(return_value={'found': 1, 'hits': [{
            'document': doc, 'text_match': 123, 'highlights': [
                {'field': 'artist_aliases', 'matched_tokens': [['линкин', 'парк']]}]}]})
        result = await self.search.search(self.store, 'test', 'линкин парк')
        self.assertEqual(result['candidates'][0]['match'][0]['field'], 'artist_aliases')
        self.assertEqual(result['selection'], 'candidates_only')
        self.assertEqual(self.collection.documents.search.call_args.args[0]['drop_tokens_threshold'], 0)
        doc['generation'] = 'obsolete'
        with self.assertRaises(StaleSnapshot):
            await self.search.search(self.store, 'test', 'Numb')

    async def test_alias_changes_and_index_lag_block_search_before_network(self):
        await self.search.build(self.store, 'test')
        with self.assertRaises(StaleSnapshot):
            await Search(self.client, {}, ['http', 'localhost', 8108]).search(self.store, 'test', 'Numb')
        self.store.publish('test', [], {}, expected_generation=self.head['generation'])
        with self.assertRaises(StaleSnapshot):
            await self.search.search(self.store, 'test', 'Numb')
        self.collection.documents.search.assert_not_called()

    async def test_replaced_snapshot_during_query_is_not_returned(self):
        await self.search.build(self.store, 'test')
        async def replaced(_):
            self.store.publish('test', [], {}, expected_generation=self.head['generation'])
            return {'found': 0, 'hits': []}
        self.collection.documents.search = AsyncMock(side_effect=replaced)
        with self.assertRaises(StaleSnapshot):
            await self.search.search(self.store, 'test', 'Numb')

    async def test_blank_or_excessive_query_rejected(self):
        for query in ('', '   ', 'x' * 1001):
            with self.assertRaises(ValueError):
                await self.search.search(self.store, 'test', query)

    async def test_member_projection_aliases_and_tamper_rejection(self):
        from library.catalog import Track
        tracks = [Track('Stan', 'Eminem;Dido', 'Album', 0, {})]
        self.head = self.store.publish('test', tracks, {}, expected_generation=self.head['generation'])
        self.search = Search(self.client, {'artists': {'Dido': ['дайдо']}}, ['http', 'localhost', 8108])
        self.collection.documents.import_.return_value = [{'success': True}]
        self.collection.retrieve.return_value = {'num_documents': 1}
        await self.search.build(self.store, 'test')
        doc = self.collection.documents.import_.call_args.args[0][0]
        self.assertEqual(doc['artist'], 'Eminem;Dido')
        self.assertEqual(doc['artists'], ['Eminem', 'Dido'])
        self.assertIn('дайдо', doc['artist_aliases'])
        self.assertIn('daydo', doc['artist_aliases'])
        schema = self.client.collections.create.call_args.args[0]['fields']
        self.assertIn({'name': 'artists', 'type': 'string[]'}, schema)
        self.collection.documents.search = AsyncMock(return_value={'found': 1, 'hits': [{'document': doc}]})
        self.assertEqual((await self.search.search(self.store, 'test', 'Dido'))['candidates'][0]['artists'],
                         ['Eminem', 'Dido'])
        doc['artists'] = ['Wrong']
        with self.assertRaises(StaleSnapshot):
            await self.search.search(self.store, 'test', 'Dido')

    async def test_old_projection_signature_requires_reindex(self):
        from unittest.mock import patch
        from library.search.typesense import signature
        with patch('library.search.typesense.SCHEMA_VERSION', 2):
            old = signature(ALIASES, ['http', 'localhost', 8108])
        self.store.publish_index('test', self.head['generation'], 'old-index', old)
        with self.assertRaises(StaleSnapshot):
            await self.search.search(self.store, 'test', 'Dido')
        self.collection.documents.search.assert_not_called()
